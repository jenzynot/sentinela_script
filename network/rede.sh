#!/usr/bin/env bash
# network/rede.sh — Fase 1: sobe/derruba a bridge br0 do segmento da casa.
#
# Uso: sudo network/rede.sh subir|descer|status
#
# O hostapd coloca a placa Wi-Fi dentro da br0 sozinho (bridge=br0 no
# hostapd.conf); a VM entra na br0 pelo adaptador "bridged" do VirtualBox.
# Normalmente quem chama este script é o sentinela-bridge.service.
set -euo pipefail

BRIDGE=br0
ENV_FILE="${SENTINELA_ENV:-/etc/sentinela/sentinela.env}"

valor() {   # valor CHAVE PADRAO — lê uma chave do .env sem executar o arquivo
    local v=""
    [[ -r "$ENV_FILE" ]] && v=$(grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d "\"'" || true)
    echo "${v:-$2}"
}

GATEWAY=$(valor REDE_GATEWAY 192.168.50.1)
SEGMENTO=$(valor REDE_SEGMENTO 192.168.50.0/24)
PREFIXO=${SEGMENTO#*/}
WIFI_IF=$(valor WIFI_IF "")

subir() {
    if ! ip link show "$BRIDGE" >/dev/null 2>&1; then
        ip link add "$BRIDGE" type bridge stp_state 0
    fi
    ip addr replace "$GATEWAY/$PREFIXO" dev "$BRIDGE"
    ip link set "$BRIDGE" up

    # O host passa a rotear: segmento <-> internet (NAT no firewall.nft)
    sysctl -q -w net.ipv4.ip_forward=1

    # Rádio desbloqueado e longe do NetworkManager (o hostapd assume a placa)
    if [[ -n "$WIFI_IF" ]]; then
        rfkill unblock wlan 2>/dev/null || true
        nmcli device set "$WIFI_IF" managed no 2>/dev/null || true
    fi
    echo "br0 no ar: $GATEWAY/$PREFIXO"
}

descer() {
    ip link del "$BRIDGE" 2>/dev/null || true
    echo "br0 removida"
}

status() {
    ip -br addr show "$BRIDGE" 2>/dev/null || echo "br0 não existe"
    bridge link show 2>/dev/null | grep "master $BRIDGE" || echo "(nenhuma porta na br0)"
    echo "ip_forward=$(sysctl -n net.ipv4.ip_forward)"
}

case "${1:-}" in
    subir)  subir ;;
    descer) descer ;;
    status) status ;;
    *) echo "uso: $0 subir|descer|status" >&2; exit 2 ;;
esac
