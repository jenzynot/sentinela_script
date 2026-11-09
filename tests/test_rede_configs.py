"""Unidade — Fase 1: geração das configs de rede e leitura do .env."""
import os

import pytest

import gerar_configs
from sentinela.config import carregar_env, ler_env

pytestmark = pytest.mark.unidade

ENV_BASE = {
    "WIFI_IF": "wlp2s0",
    "WIFI_SSID": "Sentinela",
    "WIFI_SENHA": "senha-forte-123",
    "REDE_SEGMENTO": "192.168.50.0/24",
    "REDE_GATEWAY": "192.168.50.1",
    "VM_MAC": "08:00:27:5E:00:10",
    "VM_IP": "192.168.50.10",
}


def gerar(**trocas):
    env = {**ENV_BASE, **trocas}
    return gerar_configs.gerar(gerar_configs.ler_config(env))


def linhas(texto):
    return {l for l in texto.splitlines() if l and not l.startswith("#")}


def test_hostapd_pendura_a_placa_na_br0_com_wpa2():
    hostapd = linhas(gerar()["hostapd.conf"])

    assert {"interface=wlp2s0", "bridge=br0", "ssid=Sentinela", "wpa=2",
            "wpa_key_mgmt=WPA-PSK", "rsn_pairwise=CCMP",
            "wpa_passphrase=senha-forte-123", "ap_isolate=1"} <= hostapd


def test_senha_vazia_gera_rede_aberta():
    hostapd = gerar(WIFI_SENHA="")["hostapd.conf"]

    assert "wpa=" not in hostapd and "wpa_passphrase" not in hostapd


def test_dnsmasq_so_na_br0_com_host_como_gateway_e_dns():
    dnsmasq = linhas(gerar()["dnsmasq.conf"])

    assert {"interface=br0", "bind-interfaces", "except-interface=lo", "no-resolv",
            "dhcp-range=192.168.50.100,192.168.50.200,255.255.255.0,12h",
            "dhcp-option=option:router,192.168.50.1",
            "dhcp-option=option:dns-server,192.168.50.1",
            "server=1.1.1.1", "server=9.9.9.9"} <= dnsmasq


def test_vm_ganha_ip_fixo_por_mac():
    dnsmasq = linhas(gerar()["dnsmasq.conf"])

    assert "dhcp-host=08:00:27:5e:00:10,192.168.50.10,servidor-casa" in dnsmasq


def test_sem_vm_configurada_nao_ha_reserva():
    assert "dhcp-host" not in gerar(VM_MAC="", VM_IP="")["dnsmasq.conf"]


def test_networkmanager_larga_a_placa_e_a_bridge():
    nm = gerar()["nm-sentinela.conf"]

    assert "unmanaged-devices=interface-name:wlp2s0;interface-name:br0" in nm


def test_segmento_e_faixa_dhcp_configuraveis():
    dnsmasq = gerar(REDE_SEGMENTO="10.20.0.0/24", REDE_GATEWAY="10.20.0.1",
                    DHCP_INICIO="10.20.0.50", DHCP_FIM="10.20.0.60",
                    VM_IP="10.20.0.10")["dnsmasq.conf"]

    assert "dhcp-range=10.20.0.50,10.20.0.60,255.255.255.0,12h" in dnsmasq


@pytest.mark.parametrize("trocas, trecho", [
    ({"WIFI_IF": ""}, "WIFI_IF"),
    ({"WIFI_SENHA": "curta"}, "8 a 63"),
    ({"WIFI_SSID": "x" * 33}, "32 bytes"),
    ({"WIFI_SSID": "rede\nwpa=0"}, "quebra de linha"),       # injeção no hostapd.conf
    ({"REDE_GATEWAY": "10.0.0.1"}, "fora de REDE_SEGMENTO"),
    ({"DHCP_INICIO": "192.168.50.1"}, "gateway"),
    ({"VM_IP": "10.0.0.10"}, "VM_IP"),
])
def test_config_invalida_e_recusada_com_mensagem_clara(trocas, trecho):
    with pytest.raises(ValueError, match=trecho):
        gerar(**trocas)


def test_main_escreve_arquivos_e_protege_a_senha(tmp_path):
    env = tmp_path / "sentinela.env"
    env.write_text("\n".join(f"{k}={v}" for k, v in ENV_BASE.items()))

    assert gerar_configs.main(["--env", str(env), "--saida", str(tmp_path / "etc")]) == 0

    hostapd = tmp_path / "etc" / "hostapd.conf"
    assert hostapd.exists()
    assert oct(hostapd.stat().st_mode & 0o777) == "0o600"


def test_ler_env_ignora_comentarios_e_tira_aspas(tmp_path):
    arq = tmp_path / ".env"
    arq.write_text('# comentário\n\nA=1\nB="com espaço"\nC=\'x=y\'\nlixo\n')

    assert ler_env(arq) == {"A": "1", "B": "com espaço", "C": "x=y"}


def test_carregar_env_nao_sobrescreve_o_ambiente(tmp_path, monkeypatch):
    arq = tmp_path / ".env"
    arq.write_text("SENTINELA_TESTE_A=do_arquivo\nSENTINELA_TESTE_B=do_arquivo\n")
    monkeypatch.setenv("SENTINELA_TESTE_A", "do_ambiente")
    monkeypatch.delenv("SENTINELA_TESTE_B", raising=False)

    carregar_env([tmp_path / "nao-existe.env", arq])

    assert os.environ["SENTINELA_TESTE_A"] == "do_ambiente"
    assert os.environ["SENTINELA_TESTE_B"] == "do_arquivo"
    monkeypatch.delenv("SENTINELA_TESTE_B")
