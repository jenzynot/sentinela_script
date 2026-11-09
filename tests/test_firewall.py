"""Job 2 — Firewall / whitelist com nftables (planejamento_testes.md §2).

Roda no runner com `sudo nft`, exatamente como o portal roda no host.
"""
import re

import pytest

import firewall_ctl
from conftest import FIREWALL, inserir_dispositivo, nft

pytestmark = pytest.mark.firewall

MAC_A = "02:00:00:00:00:0a"
MAC_B = "02:00:00:00:00:0b"


def test_ruleset_carrega_com_conjunto_vazio(ruleset):
    """Dado   o firewall.nft
    Quando  ele é carregado
    Então   a tabela inet portal existe e o conjunto 'autorizados' nasce vazio"""
    assert "table inet portal" in nft("list", "tables").stdout
    assert firewall_ctl.macs_autorizados() == set()


def test_recarregar_ruleset_nao_duplica_regras(ruleset):
    """Dado   o firewall.nft já carregado
    Quando  carrego o arquivo de novo
    Então   não dá erro e a chain forward continua com as mesmas regras"""
    antes = nft("list", "chain", "inet", "portal", "forward").stdout

    nft("-f", str(FIREWALL))

    assert nft("list", "chain", "inet", "portal", "forward").stdout == antes


def test_input_fecha_o_host_e_so_abre_o_necessario(ruleset):
    """Dado   o firewall carregado
    Quando  leio a chain input
    Então   a política é drop e só DHCP/DNS/portal (na br0) e WireGuard estão abertos"""
    entrada = nft("list", "chain", "inet", "portal", "input").stdout

    assert "policy drop" in entrada
    assert 'iifname "br0" udp dport { 53, 67 } accept' in entrada
    assert 'iifname "br0" tcp dport { 53, 8080 } accept' in entrada
    assert "udp dport 51820 accept" in entrada
    assert "3306" not in entrada and "dport 22 " not in entrada


def test_vpn_alcanca_a_rede_da_casa_e_nat_so_para_o_segmento(ruleset):
    forward = nft("list", "chain", "inet", "portal", "forward").stdout
    post = nft("list", "chain", "inet", "portal", "postrouting").stdout

    assert 'iifname "wg0" oifname "br0" accept' in forward
    # o nft pode listar os elementos do conjunto em qualquer ordem
    assert re.search(r'iifname "br0" oifname != \{ ("br0", "wg0"|"wg0", "br0") \} masquerade', post)


def test_liberar_coloca_mac_no_conjunto(ruleset):
    """Dado   o conjunto vazio
    Quando  libero um MAC
    Então   o conjunto contém esse MAC"""
    firewall_ctl.liberar_mac(MAC_A)

    assert firewall_ctl.macs_autorizados() == {MAC_A}


def test_liberar_aceita_mac_em_maiusculas(ruleset):
    firewall_ctl.liberar_mac(MAC_A.upper())

    assert firewall_ctl.macs_autorizados() == {MAC_A}


def test_revogar_tira_mac_do_conjunto(ruleset):
    """Dado   dois MACs liberados
    Quando  revogo um deles
    Então   só o outro continua no conjunto"""
    firewall_ctl.liberar_mac(MAC_A)
    firewall_ctl.liberar_mac(MAC_B)

    firewall_ctl.revogar_mac(MAC_A)

    assert firewall_ctl.macs_autorizados() == {MAC_B}


def test_liberar_mac_ja_presente_nao_falha(ruleset):
    firewall_ctl.liberar_mac(MAC_A)
    firewall_ctl.liberar_mac(MAC_A)

    assert firewall_ctl.macs_autorizados() == {MAC_A}


def test_revogar_mac_ausente_nao_falha(ruleset):
    firewall_ctl.revogar_mac(MAC_A)

    assert firewall_ctl.macs_autorizados() == set()


@pytest.mark.parametrize("mac", [
    "nao-e-mac",
    "02:00:00:00:00",                          # curto
    "02:00:00:00:00:0a, 02:00:00:00:00:0b",    # tentativa de liberar dois de uma vez
    "02:00:00:00:00:0a } ; flush ruleset ; {",  # tentativa de injetar sintaxe nft
])
def test_mac_invalido_e_recusado_sem_tocar_no_firewall(ruleset, mac):
    with pytest.raises(ValueError):
        firewall_ctl.liberar_mac(mac)

    assert firewall_ctl.macs_autorizados() == set()


def test_ressync_espelha_exatamente_os_autorizados_do_banco(ruleset, banco):
    """Dado   3 dispositivos autorizados e 1 não autorizado no banco,
            e um MAC 'fantasma' sobrando no conjunto
    Quando  rodo o ressync.py
    Então   o conjunto tem os 3 autorizados — e só eles"""
    import ressync

    autorizados = {"02:00:00:00:00:01", "02:00:00:00:00:02", "02:00:00:00:00:03"}
    for mac in autorizados:
        inserir_dispositivo(banco, mac, autorizado=True)
    inserir_dispositivo(banco, "02:00:00:00:00:04", autorizado=False)
    firewall_ctl.liberar_mac("02:00:00:00:00:ff")   # não está no banco

    ressync.main()

    assert firewall_ctl.macs_autorizados() == autorizados


def test_ressync_com_banco_vazio_esvazia_o_conjunto(ruleset, banco):
    import ressync

    firewall_ctl.liberar_mac(MAC_A)

    ressync.main()

    assert firewall_ctl.macs_autorizados() == set()
