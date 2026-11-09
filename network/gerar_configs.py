#!/usr/bin/env python3
"""network/gerar_configs.py — Fase 1: gera as configs da rede a partir do .env.

Saída (no diretório indicado, por padrão /etc/sentinela):
    hostapd.conf      AP Wi-Fi pendurado na br0 (modo 600: contém a senha)
    dnsmasq.conf      DHCP + DNS do segmento, só na br0
    nm-sentinela.conf drop-in do NetworkManager: não mexer na placa Wi-Fi nem na br0

Uso:
    sudo python3 network/gerar_configs.py [--env /etc/sentinela/sentinela.env] [--saida /etc/sentinela]

Só biblioteca padrão: roda com o python3 do sistema, antes de existir .venv.
"""
import argparse
import ipaddress
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Template

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sentinela.config import ler_env  # noqa: E402

BRIDGE = "br0"


@dataclass
class ConfigRede:
    wifi_if: str
    ssid: str
    senha: str            # vazia = rede aberta (controle de acesso só pelo portal)
    canal: int
    pais: str
    segmento: ipaddress.IPv4Network
    gateway: ipaddress.IPv4Address
    dhcp_inicio: ipaddress.IPv4Address
    dhcp_fim: ipaddress.IPv4Address
    dns_upstream: list[str]
    dominio: str
    vm_mac: str
    vm_ip: str


def _sem_quebra(nome: str, valor: str) -> str:
    if any(c in valor for c in "\r\n\0"):
        raise ValueError(f"{nome} não pode conter quebra de linha")
    return valor


def ler_config(env: dict) -> ConfigRede:
    """Valida o .env e devolve a configuração da rede. Erro claro > config quebrada."""
    wifi_if = _sem_quebra("WIFI_IF", env.get("WIFI_IF", "").strip())
    if not wifi_if:
        raise ValueError("WIFI_IF não definido (nome da placa Wi-Fi, ex.: wlp2s0 — veja `iw dev`)")

    ssid = _sem_quebra("WIFI_SSID", env.get("WIFI_SSID", "Sentinela"))
    if not 1 <= len(ssid.encode()) <= 32:
        raise ValueError("WIFI_SSID precisa ter de 1 a 32 bytes")

    senha = _sem_quebra("WIFI_SENHA", env.get("WIFI_SENHA", ""))
    if senha and not 8 <= len(senha) <= 63:
        raise ValueError("WIFI_SENHA precisa ter de 8 a 63 caracteres (ou ficar vazia = rede aberta)")

    segmento = ipaddress.ip_network(env.get("REDE_SEGMENTO", "192.168.50.0/24"))
    gateway = ipaddress.ip_address(env.get("REDE_GATEWAY", "192.168.50.1"))
    if gateway not in segmento:
        raise ValueError(f"REDE_GATEWAY {gateway} fora de REDE_SEGMENTO {segmento}")

    base = segmento.network_address
    inicio = ipaddress.ip_address(env.get("DHCP_INICIO") or base + 100)
    fim = ipaddress.ip_address(env.get("DHCP_FIM") or base + 200)
    if not (inicio in segmento and fim in segmento and inicio <= fim):
        raise ValueError("faixa DHCP (DHCP_INICIO..DHCP_FIM) inválida para o segmento")
    if inicio <= gateway <= fim:
        raise ValueError("o gateway não pode estar dentro da faixa DHCP")

    dns = [ipaddress.ip_address(s.strip()).compressed
           for s in env.get("DNS_UPSTREAM", "1.1.1.1,9.9.9.9").split(",") if s.strip()]

    vm_mac = env.get("VM_MAC", "").strip().lower()
    vm_ip = env.get("VM_IP", "").strip()
    if vm_ip and ipaddress.ip_address(vm_ip) not in segmento:
        raise ValueError(f"VM_IP {vm_ip} fora do segmento {segmento}")

    return ConfigRede(
        wifi_if=wifi_if, ssid=ssid, senha=senha,
        canal=int(env.get("WIFI_CANAL", "6")), pais=env.get("WIFI_PAIS", "BR").upper(),
        segmento=segmento, gateway=gateway, dhcp_inicio=inicio, dhcp_fim=fim,
        dns_upstream=dns, dominio=env.get("REDE_DOMINIO", "casa.lan"),
        vm_mac=vm_mac, vm_ip=vm_ip,
    )


HOSTAPD = Template("""\
# Gerado por network/gerar_configs.py — edite o .env, não este arquivo.
interface=$wifi_if
bridge=$bridge
driver=nl80211
ssid=$ssid
utf8_ssid=1
country_code=$pais
ieee80211d=1
hw_mode=g
channel=$canal
ieee80211n=1
wmm_enabled=1
# Clientes Wi-Fi não conversam direto entre si: tudo passa pela br0 (e pelo host).
ap_isolate=1
auth_algs=1
ignore_broadcast_ssid=0
$seguranca
""")

DNSMASQ = Template("""\
# Gerado por network/gerar_configs.py — edite o .env, não este arquivo.
# Só atende na br0: não briga com o systemd-resolved (127.0.0.53).
interface=$bridge
bind-interfaces
except-interface=lo

# DNS: encaminha para os servidores escolhidos, ignora o resolv.conf do host
no-resolv
domain-needed
bogus-priv
$servidores
domain=$dominio
local=/$dominio/
address=/portal.$dominio/$gateway

# DHCP: o próprio host é gateway e DNS do segmento
dhcp-authoritative
dhcp-range=$inicio,$fim,$mascara,12h
dhcp-option=option:router,$gateway
dhcp-option=option:dns-server,$gateway
$reserva_vm
log-dhcp
""")

NM = Template("""\
# Gerado por network/gerar_configs.py
# O NetworkManager não deve gerenciar a placa do AP nem a bridge: quem cuida
# delas é o hostapd e o network/rede.sh.
[keyfile]
unmanaged-devices=interface-name:$wifi_if;interface-name:$bridge
""")


def gerar(cfg: ConfigRede) -> dict[str, str]:
    if cfg.senha:
        seguranca = ("wpa=2\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n"
                     f"wpa_passphrase={cfg.senha}")
    else:
        seguranca = "# Rede aberta: o controle de acesso é o portal cativo + whitelist."

    reserva_vm = ""
    if cfg.vm_mac and cfg.vm_ip:
        reserva_vm = f"# Servidor da casa (VM) sempre no mesmo IP — alvo do RDP\n" \
                     f"dhcp-host={cfg.vm_mac},{cfg.vm_ip},servidor-casa"

    return {
        "hostapd.conf": HOSTAPD.substitute(
            wifi_if=cfg.wifi_if, bridge=BRIDGE, ssid=cfg.ssid, pais=cfg.pais,
            canal=cfg.canal, seguranca=seguranca),
        "dnsmasq.conf": DNSMASQ.substitute(
            bridge=BRIDGE, servidores="\n".join(f"server={s}" for s in cfg.dns_upstream),
            dominio=cfg.dominio, gateway=cfg.gateway, inicio=cfg.dhcp_inicio,
            fim=cfg.dhcp_fim, mascara=cfg.segmento.netmask, reserva_vm=reserva_vm),
        "nm-sentinela.conf": NM.substitute(wifi_if=cfg.wifi_if, bridge=BRIDGE),
    }


def escrever(arquivos: dict[str, str], saida: Path) -> None:
    saida.mkdir(parents=True, exist_ok=True)
    for nome, conteudo in arquivos.items():
        destino = saida / nome
        destino.write_text(conteudo, encoding="utf-8")
        os.chmod(destino, 0o600 if nome == "hostapd.conf" else 0o644)
        print(f"gerado: {destino}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--env", default="/etc/sentinela/sentinela.env")
    p.add_argument("--saida", default="/etc/sentinela")
    args = p.parse_args(argv)
    try:
        cfg = ler_config(ler_env(args.env))
    except (OSError, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    escrever(gerar(cfg), Path(args.saida))
    return 0


if __name__ == "__main__":
    sys.exit(main())
