#!/usr/bin/env bash
# security/wireguard.sh — Fase 6: VPN de acesso remoto terminando no host.
#
# Uso:
#   sudo security/wireguard.sh servidor        # chaves + wg0.conf + serviço (idempotente)
#   sudo security/wireguard.sh peer <nome>     # novo cliente: .conf + QR code no terminal
#   sudo security/wireguard.sh listar
#
# Túnel dividido: o cliente só manda pela VPN o tráfego da rede da casa
# (segmento + rede da VPN); a internet dele continua saindo pelo próprio 4G/Wi-Fi.
# O firewall.nft já libera 51820/udp na entrada e wg0 -> br0 no forward.
set -euo pipefail

WG_DIR=/etc/wireguard
CONF=$WG_DIR/wg0.conf
CLIENTES=$WG_DIR/clientes
REDE_VPN=10.8.0
PORTA=51820
ENV_FILE="${SENTINELA_ENV:-/etc/sentinela/sentinela.env}"

ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
erro() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; exit 1; }

valor() {
    local v=""
    [[ -r "$ENV_FILE" ]] && v=$(grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d "\"'" || true)
    echo "${v:-$2}"
}

[[ $EUID -eq 0 ]] || erro "rode com sudo"
command -v wg >/dev/null || erro "wireguard-tools não instalado (setup_host.sh)"
umask 077    # chaves privadas: só root lê

servidor() {
    install -d -m 700 "$WG_DIR" "$CLIENTES"
    if [[ ! -f $WG_DIR/servidor.key ]]; then
        wg genkey > "$WG_DIR/servidor.key"
        wg pubkey < "$WG_DIR/servidor.key" > "$WG_DIR/servidor.pub"
        ok "chaves do servidor geradas"
    fi
    if [[ ! -f $CONF ]]; then
        cat > "$CONF" <<EOF
# Gerado por security/wireguard.sh — peers são acrescentados no fim.
[Interface]
Address = $REDE_VPN.1/24
ListenPort = $PORTA
PrivateKey = $(cat "$WG_DIR/servidor.key")
EOF
        ok "$CONF criado"
    fi
    systemctl enable -q --now wg-quick@wg0
    ok "wg0 ativo na porta $PORTA/udp"
    [[ -n "$(valor VPN_ENDPOINT "")" ]] \
        || warn "defina VPN_ENDPOINT no .env (IP público ou DDNS da casa) antes de criar peers"
}

peer() {
    local nome="${1:-}"
    [[ "$nome" =~ ^[A-Za-z0-9_-]{1,32}$ ]] || erro "nome do peer: letras, números, _ ou - (ex.: celular-ana)"
    [[ -f $CONF ]] || servidor
    [[ ! -f "$CLIENTES/$nome.conf" ]] || erro "peer '$nome' já existe ($CLIENTES/$nome.conf)"

    local ultimo proximo
    ultimo=$(grep -oE "AllowedIPs = $REDE_VPN\.[0-9]+" "$CONF" | awk -F. '{print $4}' | sort -n | tail -n1)
    proximo=$(( ${ultimo:-1} + 1 ))
    (( proximo <= 254 )) || erro "rede da VPN cheia"

    local priv pub psk endpoint
    priv=$(wg genkey)
    pub=$(wg pubkey <<< "$priv")
    psk=$(wg genpsk)        # chave pré-compartilhada: camada extra (pós-quântica)
    endpoint=$(valor VPN_ENDPOINT "SEU_IP_PUBLICO_OU_DDNS")

    cat >> "$CONF" <<EOF

[Peer]
# $nome
PublicKey = $pub
PresharedKey = $psk
AllowedIPs = $REDE_VPN.$proximo/32
EOF

    cat > "$CLIENTES/$nome.conf" <<EOF
[Interface]
PrivateKey = $priv
Address = $REDE_VPN.$proximo/32

[Peer]
PublicKey = $(cat "$WG_DIR/servidor.pub")
PresharedKey = $psk
Endpoint = $endpoint:$PORTA
AllowedIPs = $(valor REDE_SEGMENTO 192.168.50.0/24), $REDE_VPN.0/24
PersistentKeepalive = 25
EOF

    if systemctl is-active -q wg-quick@wg0; then
        wg syncconf wg0 <(wg-quick strip wg0)    # aplica sem derrubar quem está conectado
    fi
    ok "peer '$nome' = $REDE_VPN.$proximo — config em $CLIENTES/$nome.conf"
    echo "No app WireGuard do celular: + > Ler código QR"
    if command -v qrencode >/dev/null; then
        qrencode -t ansiutf8 < "$CLIENTES/$nome.conf"
    else
        warn "qrencode ausente: importe o arquivo $CLIENTES/$nome.conf"
    fi
}

listar() {
    wg show wg0 2>/dev/null || echo "wg0 não está ativo"
    echo; echo "Clientes:"; ls -1 "$CLIENTES" 2>/dev/null || echo "  (nenhum)"
}

case "${1:-}" in
    servidor) servidor ;;
    peer)     peer "${2:-}" ;;
    listar)   listar ;;
    *) sed -n '/^# Uso/,/^# Túnel/p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
