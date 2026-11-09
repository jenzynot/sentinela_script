"""Job 1 — Banco de dados: schema + queries (planejamento_testes.md §2)."""
import os
import subprocess
from datetime import datetime

import mysql.connector
import pytest

from conftest import NOME_BANCO, RAIZ, TABELAS, _admin, aplicar_schema, inserir_dispositivo

pytestmark = pytest.mark.banco

ER_DUP_ENTRY = 1062
ER_NO_REFERENCED_ROW_2 = 1452


def test_schema_idempotente(banco):
    """Dado   o schema já aplicado
    Quando  aplico schema.sql de novo
    Então   não há erro e nenhuma tabela é recriada (os dados continuam lá)"""
    inserir_dispositivo(banco, "02:00:00:00:00:01")

    r = aplicar_schema()

    assert r.returncode == 0, r.stderr
    cur = banco.cursor()
    cur.execute("SELECT COUNT(*) FROM TB_DISPOSITIVOS")
    assert cur.fetchone()[0] == 1


def test_todas_as_tabelas_sao_innodb(banco):
    """Dado   o schema aplicado
    Quando  consulto SHOW TABLE STATUS
    Então   as cinco tabelas existem e todas usam InnoDB"""
    cur = banco.cursor(dictionary=True)
    cur.execute(f"SHOW TABLE STATUS FROM {NOME_BANCO}")
    engines = {linha["Name"]: linha["Engine"] for linha in cur.fetchall()}

    assert set(engines) == TABELAS
    assert set(engines.values()) == {"InnoDB"}


def test_fk_rejeita_presenca_de_varredura_inexistente(banco):
    """Dado   um dispositivo cadastrado e nenhuma varredura
    Quando  insiro uma presença referenciando a varredura 9999
    Então   o MySQL rejeita (a FK não é decorativa)"""
    id_disp = inserir_dispositivo(banco, "02:00:00:00:00:01")

    with pytest.raises(mysql.connector.IntegrityError) as erro:
        banco.cursor().execute(
            "INSERT INTO TB_PRESENCAS (id_varredura, id_dispositivo, endereco_ip) "
            "VALUES (9999, %s, '192.168.50.10')", (id_disp,))

    assert erro.value.errno == ER_NO_REFERENCED_ROW_2


def test_mac_duplicado_e_rejeitado(banco):
    """Dado   um dispositivo com MAC X
    Quando  insiro outro dispositivo com o mesmo MAC X
    Então   o MySQL rejeita (endereco_mac é UNIQUE)"""
    inserir_dispositivo(banco, "02:00:00:00:00:01")

    with pytest.raises(mysql.connector.IntegrityError) as erro:
        inserir_dispositivo(banco, "02:00:00:00:00:01")

    assert erro.value.errno == ER_DUP_ENTRY


def test_upsert_do_portal_atualiza_sem_duplicar(banco):
    """Dado   um MAC já visto pelo agente, ainda não autorizado
    Quando  o portal registra esse MAC duas vezes
    Então   continua existindo uma linha só, autorizada e com o nome mais recente"""
    from dados import registrar_autorizado

    inserir_dispositivo(banco, "02:00:00:00:00:01", nome="desconhecido", autorizado=False)

    registrar_autorizado("02:00:00:00:00:01", "Celular do João")
    registrar_autorizado("02:00:00:00:00:01", "Celular de teste")

    cur = banco.cursor(dictionary=True)
    cur.execute("SELECT * FROM TB_DISPOSITIVOS WHERE endereco_mac = '02:00:00:00:00:01'")
    linhas = cur.fetchall()
    assert len(linhas) == 1
    assert linhas[0]["autorizado"] == 1
    assert linhas[0]["nome_dispositivo"] == "Celular de teste"


def test_ciclo_completo_e_joins_do_relatorio(banco):
    """Dado   um banco vazio
    Quando  gravo varredura → presença → porta → alerta
    Então   o JOIN do relatório devolve tudo amarrado ao dispositivo certo"""
    agora = datetime.now().replace(microsecond=0)
    cur = banco.cursor()
    id_disp = inserir_dispositivo(banco, "02:00:00:00:00:99", nome="intruso")
    cur.execute("INSERT INTO TB_VARREDURAS (data_varredura, quantidade_dispositivos, "
                "total_portas, total_alertas, resultado_geral) VALUES (%s, 1, 1, 1, 'alerta')",
                (agora,))
    id_varr = cur.lastrowid
    cur.execute("INSERT INTO TB_PRESENCAS (id_varredura, id_dispositivo, endereco_ip) "
                "VALUES (%s, %s, '192.168.50.99')", (id_varr, id_disp))
    id_pres = cur.lastrowid
    cur.execute("INSERT INTO TB_PORTAS (id_presenca, numero_porta, protocolo, servico, "
                "status_porta) VALUES (%s, 3389, 'tcp', 'ms-wbt-server', 'open')", (id_pres,))
    cur.execute("INSERT INTO TB_ALERTAS (id_varredura, id_dispositivo, tipo_alerta, "
                "descricao, nivel_risco, data_alerta) VALUES (%s, %s, "
                "'dispositivo_nao_autorizado', 'MAC fora da whitelist', 'alto', %s)",
                (id_varr, id_disp, agora))

    # Portas abertas por dispositivo em cada varredura
    cur.execute("""
        SELECT d.endereco_mac, p.endereco_ip, po.numero_porta, po.protocolo, v.data_varredura
        FROM TB_PORTAS po
        JOIN TB_PRESENCAS p    ON p.id_presenca    = po.id_presenca
        JOIN TB_DISPOSITIVOS d ON d.id_dispositivo = p.id_dispositivo
        JOIN TB_VARREDURAS v   ON v.id_varredura   = p.id_varredura
    """)
    assert cur.fetchall() == [("02:00:00:00:00:99", "192.168.50.99", 3389, "tcp", agora)]

    # Alertas com o dispositivo e a varredura que os geraram
    cur.execute("""
        SELECT a.tipo_alerta, a.nivel_risco, d.nome_dispositivo, v.id_varredura
        FROM TB_ALERTAS a
        JOIN TB_DISPOSITIVOS d ON d.id_dispositivo = a.id_dispositivo
        JOIN TB_VARREDURAS v   ON v.id_varredura   = a.id_varredura
    """)
    assert cur.fetchall() == [("dispositivo_nao_autorizado", "alto", "intruso", id_varr)]


# --- Fase 3: sql/setup_banco.sh ---------------------------------------------

ER_TABLEACCESS_DENIED = 1142
USUARIO_SETUP = "sentinela_setup"
SENHA_SETUP = "senha-do-setup-com-'aspas'-e-\barra"


def rodar_setup(env_file):
    a = _admin()
    return subprocess.run(
        ["bash", str(RAIZ / "sql" / "setup_banco.sh"), str(env_file)],
        capture_output=True, text=True,
        env={**os.environ, "MYSQL_HOST": a["host"], "MYSQL_TCP_PORT": str(a["port"]),
             "MYSQL_ADMIN_USER": a["user"], "MYSQL_PWD": a["password"],
             "HOSTS_SENTINELA": "%", "MANTER_ROOT_REMOTO": "1"})


@pytest.fixture
def env_setup(tmp_path, banco):
    arq = tmp_path / "sentinela.env"
    # a senha tem aspas e barra invertida de propósito: testa o escape do SQL
    arq.write_text(f"MYSQL_USER={USUARIO_SETUP}\nMYSQL_PASSWORD={SENHA_SETUP}\n"
                   "MYSQL_DATABASE=vigia_de_rede\n")
    yield arq
    banco.cursor().execute(f"DROP USER IF EXISTS '{USUARIO_SETUP}'@'%'")


def test_setup_banco_e_idempotente_e_da_so_dml(env_setup):
    """Dado   um MySQL com o banco já criado
    Quando  rodo setup_banco.sh duas vezes
    Então   as duas terminam bem, e o usuário criado consegue ler/gravar no
            vigia_de_rede mas não consegue apagar tabela nem ler mysql.user"""
    for _ in range(2):
        r = rodar_setup(env_setup)
        assert r.returncode == 0, r.stdout + r.stderr

    a = _admin()
    cx = mysql.connector.connect(host=a["host"], port=a["port"], user=USUARIO_SETUP,
                                 password=SENHA_SETUP, database=NOME_BANCO, autocommit=True)
    cur = cx.cursor()
    cur.execute("INSERT INTO TB_DISPOSITIVOS (endereco_mac) VALUES ('02:00:00:00:00:77')")
    cur.execute("SELECT COUNT(*) FROM TB_DISPOSITIVOS")
    assert cur.fetchone()[0] == 1

    with pytest.raises(mysql.connector.ProgrammingError) as erro:
        cur.execute("DROP TABLE TB_ALERTAS")
    assert erro.value.errno == ER_TABLEACCESS_DENIED
    with pytest.raises(mysql.connector.ProgrammingError):
        cur.execute("SELECT * FROM mysql.user")
    cx.close()


@pytest.mark.parametrize("conteudo, trecho", [
    ("MYSQL_USER=root\nMYSQL_PASSWORD=uma-senha-bem-longa\n", "root"),
    ("MYSQL_USER=sentinela\nMYSQL_PASSWORD=curta\n", "12 caracteres"),
    ("MYSQL_USER=sentinela\nMYSQL_PASSWORD=troque-esta-senha\n", "troque"),
    ("MYSQL_USER=a';DROP\nMYSQL_PASSWORD=uma-senha-bem-longa\n", "inválido"),
])
def test_setup_banco_recusa_config_perigosa(tmp_path, banco, conteudo, trecho):
    arq = tmp_path / "sentinela.env"
    arq.write_text(conteudo)

    r = rodar_setup(arq)

    assert r.returncode != 0
    assert trecho in r.stderr
