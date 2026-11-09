"""Fixtures compartilhadas dos testes do Sentinela.

Variáveis de ambiente usadas (ver .github/workflows/ci.yml):
    MYSQL_HOST, MYSQL_PORT                -> servidor MySQL
    MYSQL_ADMIN_USER, MYSQL_ADMIN_PASSWORD -> usuário administrativo (recria o banco)
    MYSQL_USER, MYSQL_PASSWORD            -> usuário 'sentinela' usado pelo código
    CI                                    -> no GitHub Actions, infraestrutura
                                             ausente FALHA o teste em vez de pulá-lo
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCHEMA = RAIZ / "sql" / "schema.sql"
FIREWALL = RAIZ / "captive" / "firewall.nft"
NOME_BANCO = "vigia_de_rede"
TABELAS = {"TB_DISPOSITIVOS", "TB_VARREDURAS", "TB_PRESENCAS", "TB_PORTAS", "TB_ALERTAS"}


def indisponivel(motivo: str):
    """Fora do CI pula (ex.: no WSL sem MySQL); no CI falha — o pipeline
    não pode ficar verde só porque a infraestrutura não subiu."""
    if os.environ.get("CI"):
        pytest.fail(motivo, pytrace=False)
    pytest.skip(motivo)


# --- MySQL -------------------------------------------------------------------

def _admin():
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_ADMIN_USER", "root"),
        "password": os.environ.get("MYSQL_ADMIN_PASSWORD", ""),
    }


def conectar_admin(database: str | None = None):
    import mysql.connector
    try:
        return mysql.connector.connect(**_admin(), database=database, autocommit=True)
    except mysql.connector.Error as e:
        indisponivel(f"MySQL indisponível: {e}")


def aplicar_schema() -> subprocess.CompletedProcess:
    """Aplica sql/schema.sql com o cliente `mysql`, do jeito que se faz no host."""
    if not shutil.which("mysql"):
        indisponivel("cliente 'mysql' não instalado")
    a = _admin()
    with open(SCHEMA, encoding="utf-8") as f:
        return subprocess.run(
            ["mysql", f"--host={a['host']}", f"--port={a['port']}", f"--user={a['user']}"],
            stdin=f, capture_output=True, text=True,
            env={**os.environ, "MYSQL_PWD": a["password"]},
        )


def resetar_banco():
    """Apaga o banco, reaplica o schema e devolve uma conexão admin nele."""
    cx = conectar_admin()
    cx.cursor().execute(f"DROP DATABASE IF EXISTS {NOME_BANCO}")
    cx.close()
    r = aplicar_schema()
    assert r.returncode == 0, f"schema.sql falhou:\n{r.stderr}"
    return conectar_admin(NOME_BANCO)


@pytest.fixture
def banco():
    """Banco vazio, com o schema recém-aplicado."""
    cx = resetar_banco()
    yield cx
    cx.close()


def inserir_dispositivo(cx, mac: str, nome: str = "teste", autorizado: bool = False) -> int:
    cur = cx.cursor()
    cur.execute(
        "INSERT INTO TB_DISPOSITIVOS (endereco_mac, nome_dispositivo, autorizado) "
        "VALUES (%s, %s, %s)", (mac, nome, autorizado))
    return cur.lastrowid


# --- nftables ----------------------------------------------------------------

def nft(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["sudo", "-n", "nft", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"nft {' '.join(args)} falhou: {r.stderr}")
    return r


@pytest.fixture
def ruleset():
    """Carrega captive/firewall.nft limpo e remove a tabela ao final."""
    if not shutil.which("nft") and not Path("/usr/sbin/nft").exists():
        indisponivel("nft não instalado")
    if subprocess.run(["sudo", "-n", "nft", "list", "tables"],
                      capture_output=True).returncode != 0:
        indisponivel("sem permissão para rodar 'sudo nft'")
    nft("delete", "table", "inet", "portal", check=False)
    nft("-f", str(FIREWALL))
    yield
    nft("delete", "table", "inet", "portal", check=False)
