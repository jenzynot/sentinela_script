"""Job 4 — Lógica do portal cativo (planejamento_testes.md §2).

Rotas Flask isoladas: mac_do_ip() e liberar_mac() são substituídos por
dublês; o banco é o MySQL real do job.
"""
import pytest

import portal

pytestmark = pytest.mark.portal

MAC = "02:00:00:00:00:42"
IP_CLIENTE = "192.168.50.42"
SENHA = "senha-de-teste"


@pytest.fixture
def cliente(monkeypatch, banco):
    liberados = []
    monkeypatch.setattr(portal, "SENHA_REDE", SENHA)
    monkeypatch.setattr(portal, "mac_do_ip", lambda ip: MAC if ip == IP_CLIENTE else None)
    monkeypatch.setattr(portal, "liberar_mac", liberados.append)
    portal.app.config["TESTING"] = True
    c = portal.app.test_client()
    c.environ_base["REMOTE_ADDR"] = IP_CLIENTE
    c.liberados = liberados
    return c


def dispositivos(banco):
    cur = banco.cursor(dictionary=True)
    cur.execute("SELECT endereco_mac, nome_dispositivo, autorizado FROM TB_DISPOSITIVOS")
    return cur.fetchall()


def test_pagina_mostra_o_mac_do_cliente(cliente):
    r = cliente.get("/")

    assert r.status_code == 200
    assert MAC in r.get_data(as_text=True)


@pytest.mark.parametrize("caminho", [
    "/generate_204",            # Android
    "/hotspot-detect.html",     # iOS / macOS
    "/connecttest.txt",         # Windows
    "/qualquer/outra/coisa",
])
def test_deteccao_de_portal_cai_na_pagina_de_registro(cliente, caminho):
    """Dado   um aparelho não autorizado testando a conexão por HTTP
    Quando  o firewall redireciona o teste para o portal
    Então   ele recebe a página de registro (e não o 204/'Success' esperado),
            o que faz o sistema operacional abrir a tela do portal"""
    r = cliente.get(caminho)

    assert r.status_code == 200
    assert MAC in r.get_data(as_text=True)


def test_nome_muito_longo_e_cortado_no_tamanho_da_coluna(cliente, banco):
    r = cliente.post("/registrar", data={"nome": "x" * 300, "senha": SENHA})

    assert r.status_code == 200
    assert dispositivos(banco)[0]["nome_dispositivo"] == "x" * 100


def test_senha_errada_retorna_403_e_nao_grava_nem_libera(cliente, banco):
    """Dado   um cliente identificado
    Quando  envia /registrar com a senha errada
    Então   recebe 403, nada é gravado no banco e o firewall não é chamado"""
    r = cliente.post("/registrar", data={"nome": "celular", "senha": "errada"})

    assert r.status_code == 403
    assert dispositivos(banco) == []
    assert cliente.liberados == []


def test_senha_certa_grava_autorizado_e_libera(cliente, banco):
    """Dado   um cliente identificado
    Quando  envia /registrar com a senha certa
    Então   o dispositivo é gravado com autorizado = TRUE e o MAC é liberado"""
    r = cliente.post("/registrar", data={"nome": "Celular de teste", "senha": SENHA})

    assert r.status_code == 200
    assert dispositivos(banco) == [
        {"endereco_mac": MAC, "nome_dispositivo": "Celular de teste", "autorizado": 1}]
    assert cliente.liberados == [MAC]


def test_sem_senha_configurada_ninguem_se_registra(cliente, banco, monkeypatch):
    """Dado   o portal sem PORTAL_SENHA configurada
    Quando  alguém envia /registrar com senha vazia
    Então   é recusado (falha fechada, não aberta)"""
    monkeypatch.setattr(portal, "SENHA_REDE", None)

    r = cliente.post("/registrar", data={"nome": "x", "senha": ""})

    assert r.status_code == 403
    assert dispositivos(banco) == []
    assert cliente.liberados == []


@pytest.mark.parametrize("metodo, rota", [("get", "/"), ("post", "/registrar")])
def test_mac_nao_identificado_retorna_400_e_nao_grava(cliente, banco, metodo, rota):
    """Dado   um cliente cujo IP não aparece na tabela ARP
    Quando  acessa o portal
    Então   recebe 400, nada é gravado e o firewall não é chamado"""
    cliente.environ_base["REMOTE_ADDR"] = "192.168.50.200"

    r = getattr(cliente, metodo)(rota, data={"nome": "x", "senha": SENHA})

    assert r.status_code == 400
    assert dispositivos(banco) == []
    assert cliente.liberados == []
