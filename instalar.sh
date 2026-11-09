#!/usr/bin/env bash
# instalar.sh — implanta o Sentinela no host Mint, uma etapa por fase.
#
# Uso (do repositório, depois do setup_host.sh e com o .env preenchido):
#     sudo ./instalar.sh rede        # Fase 1:   br0 + hostapd + dnsmasq + firewall/NAT
#     sudo ./instalar.sh portal      # Fase 1.5: portal cativo + ressync (precisa do banco)
#     sudo ./instalar.sh verificar   # mostra o estado de tudo
#
# Cada etapa é idempotente: depois de um `git pull`, rode de novo.
#
# Layout no host:
#     /opt/sentinela                 cópia do código (root:root) + .venv
#     /etc/sentinela/sentinela.env   cópia do .env (640 root:sentinela)
#     /etc/sentinela/*.conf          configs geradas (hostapd, dnsmasq)
#     /etc/systemd/system/sentinela-*  units (agrupadas em sentinela.target)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIXO=/opt/sentinela
ETC=/etc/sentinela
ENV_FILE=$ETC/sentinela.env
USUARIO_SVC=sentinela

info() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
erro() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; exit 1; }

# --- comum a todas as etapas -------------------------------------------------

preparar_base() {
    [[ $EUID -eq 0 ]] || erro "rode com sudo: sudo $0 ${ETAPA:-}"

    if ! id "$USUARIO_SVC" >/dev/null 2>&1; then
        useradd --system --no-create-home --shell /usr/sbin/nologin "$USUARIO_SVC"
        ok "usuário de serviço '$USUARIO_SVC' criado"
    fi

    install -d -m 755 "$ETC"
    if [[ -f "$REPO_DIR/.env" ]]; then
        install -m 640 -o root -g "$USUARIO_SVC" "$REPO_DIR/.env" "$ENV_FILE"
        ok ".env copiado para $ENV_FILE"
    elif [[ ! -f "$ENV_FILE" ]]; then
        erro "não achei $REPO_DIR/.env — copie o .env.example e preencha"
    fi

    info "Implantando o código em $PREFIXO"
    install -d -m 755 "$PREFIXO"
    rsync -a --delete \
        --exclude .git --exclude .venv --exclude .env --exclude tests \
        --exclude __pycache__ --exclude .pytest_cache --exclude .github \
        "$REPO_DIR/" "$PREFIXO/"
    chown -R root:root "$PREFIXO"
    [[ -x $PREFIXO/.venv/bin/python ]] || python3 -m venv "$PREFIXO/.venv"
    "$PREFIXO/.venv/bin/pip" install -q --upgrade pip
    "$PREFIXO/.venv/bin/pip" install -q -r "$PREFIXO/requirements.txt"
    ok "código e .venv prontos"
}

instalar_units() {   # instalar_units unit1 unit2 ...
    for unit in "$@"; do
        install -m 644 "$PREFIXO/systemd/$unit" "/etc/systemd/system/$unit"
    done
    systemctl daemon-reload
}

ativar() {   # ativar unit1 unit2 ... — habilita no boot e (re)inicia agora
    systemctl enable -q "$@"
    systemctl restart "$@"
    for unit in "$@"; do
        if systemctl is-active -q "$unit"; then ok "$unit ativo"
        else warn "$unit NÃO subiu — veja: journalctl -u $unit -n 50"; fi
    done
}

# --- Fase 1: rede controlada -------------------------------------------------

etapa_rede() {
    info "Fase 1 — gerando configs da rede a partir do .env"
    python3 "$PREFIXO/network/gerar_configs.py" --env "$ENV_FILE" --saida "$ETC"

    install -m 644 "$ETC/nm-sentinela.conf" /etc/NetworkManager/conf.d/90-sentinela.conf
    systemctl reload NetworkManager 2>/dev/null || true
    ok "NetworkManager não gerencia mais a placa do AP nem a br0"

    instalar_units sentinela.target sentinela-bridge.service sentinela-firewall.service \
                   sentinela-ap.service sentinela-dhcp.service
    systemctl enable -q sentinela.target
    ativar sentinela-bridge.service sentinela-firewall.service \
           sentinela-ap.service sentinela-dhcp.service

    cat <<EOF

Pronto quando (Fase 1): o celular conecta no SSID e pega IP.
  - Acompanhe as concessões DHCP:  journalctl -fu sentinela-dhcp
  - Associações Wi-Fi:              journalctl -fu sentinela-ap
  - No celular, use MAC "fixo/do dispositivo" para esta rede (ver docs/fase1_rede.md).
  - Sem portal (Fase 1.5) o celular ainda NÃO navega: a whitelist começa vazia.
EOF
}

# --- Fase 1.5: portal cativo -------------------------------------------------

banco_acessivel() {   # o usuário de serviço consegue logar no MySQL com o .env?
    runuser -u "$USUARIO_SVC" -- "$PREFIXO/.venv/bin/python" -c "
import sys; sys.path.insert(0, '$PREFIXO')
from sentinela.config import carregar_env, mysql_params
carregar_env()
import mysql.connector
mysql.connector.connect(**mysql_params()).close()" 2>/dev/null
}

etapa_portal() {
    info "Fase 1.5 — portal cativo"
    visudo -cf "$PREFIXO/captive/sudoers.sentinela" >/dev/null || erro "sudoers inválido"
    install -m 440 -o root -g root "$PREFIXO/captive/sudoers.sentinela" /etc/sudoers.d/sentinela
    ok "sudoers: '$USUARIO_SVC' só pode rodar /usr/sbin/nft como root"

    banco_acessivel || erro "o portal não consegue acessar o banco — rode antes: sudo $0 banco"

    instalar_units sentinela-ressync.service sentinela-portal.service
    ativar sentinela-ressync.service sentinela-portal.service

    cat <<EOF

Pronto quando (Fase 1.5): o celular conecta, a tela do portal abre sozinha,
o registro com a PORTAL_SENHA libera a navegação.
  - Logs do portal:  journalctl -fu sentinela-portal
  - Whitelist viva:  sudo nft list set inet portal autorizados
EOF
}

# --- verificação -------------------------------------------------------------

etapa_verificar() {
    info "Serviços"
    for unit in sentinela-bridge sentinela-firewall sentinela-ap sentinela-dhcp \
                sentinela-ressync sentinela-portal sentinela-agente; do
        printf '  %-22s %s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || true)"
    done
    info "Bridge"
    "$PREFIXO/network/rede.sh" status || true
    info "Whitelist no firewall"
    nft list set inet portal autorizados 2>/dev/null | grep -E 'elements|type' || echo "  (tabela inet portal não carregada)"
    info "Concessões DHCP"
    cat /var/lib/misc/dnsmasq.leases 2>/dev/null || echo "  (nenhuma)"
}

ETAPA="${1:-}"
case "$ETAPA" in
    rede)      preparar_base; etapa_rede ;;
    portal)    preparar_base; etapa_portal ;;
    verificar) etapa_verificar ;;
    *)
        sed -n '/^# Uso/,/^# Cada etapa/p' "$0" | sed 's/^# \{0,1\}//'
        exit 2 ;;
esac
