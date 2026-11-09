#!/usr/bin/env bash
# setup_host.sh — Fase 0: prepara o host Linux Mint (gateway do Sentinela).
#
# Uso (no host Mint, de dentro do repositório):
#     sudo ./setup_host.sh
#
# O que faz:
#   1. Atualiza o sistema.
#   2. Instala os pacotes de infraestrutura (VirtualBox, AP, DHCP/DNS, firewall,
#      banco, varredura, Python, Git).
#   3. Deixa hostapd e dnsmasq PARADOS e DESABILITADOS — eles só sobem na Fase 1,
#      já configurados para a br0 (evita conflito do dnsmasq com a porta 53 do
#      systemd-resolved).
#   4. Cria o .venv do projeto e instala o requirements.txt como o usuário comum.
#   5. Verifica se a placa Wi-Fi suporta modo AP (pré-requisito da Fase 1).
#
# É idempotente: rodar de novo só reinstala o que faltar.
set -euo pipefail

PACOTES=(
    virtualbox      # hipervisor da VM Windows Server (Fase 2) e da Kali/Parrot (Fase 6)
    hostapd         # Access Point Wi-Fi (Fase 1)
    dnsmasq         # DHCP + DNS do segmento (Fase 1)
    nftables        # firewall: whitelist, NAT e redirect do portal (Fases 1 e 1.5)
    iw              # inspeção da placa Wi-Fi (suporte a modo AP)
    mysql-server    # banco vigia_de_rede (Fase 3)
    nmap            # varredura de portas do Sentinela (Fase 5)
    arp-scan        # descoberta de dispositivos por ARP (Fase 5)
    python3
    python3-venv
    python3-pip
    git
    rsync           # implantação em /opt/sentinela (instalar.sh)
    wireguard-tools # VPN de acesso remoto (Fase 6)
    qrencode        # QR code da config do WireGuard para o celular (Fase 6)
)

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USUARIO="${SUDO_USER:-}"

info() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
erro() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; }

# --- pré-checagens -----------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    erro "Rode com sudo: sudo $0"
    exit 1
fi

if [[ -z "$USUARIO" || "$USUARIO" == "root" ]]; then
    erro "Rode via 'sudo' a partir do seu usuário comum (o .venv não deve pertencer ao root)."
    exit 1
fi

if ! grep -qiE 'linuxmint|ubuntu|debian' /etc/os-release; then
    warn "Distribuição não reconhecida como Mint/Ubuntu/Debian — prosseguindo mesmo assim."
fi

# --- 1 e 2: atualização e pacotes -------------------------------------------
info "Atualizando o sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade

info "Instalando pacotes: ${PACOTES[*]}"
apt-get install -y "${PACOTES[@]}"

# --- 3: serviços de rede ficam desligados até a Fase 1 -----------------------
info "Desabilitando hostapd e dnsmasq até a configuração da Fase 1"
for svc in hostapd dnsmasq; do
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
    ok "$svc parado e desabilitado"
done

# Usuário comum no grupo vboxusers (necessário para VBoxManage/USB na Fase 2)
if ! id -nG "$USUARIO" | grep -qw vboxusers; then
    usermod -aG vboxusers "$USUARIO"
    warn "$USUARIO adicionado ao grupo vboxusers — faça logout/login para valer."
fi

# --- 4: ambiente Python do projeto ------------------------------------------
info "Criando .venv e instalando requirements.txt (como $USUARIO)"
sudo -u "$USUARIO" bash -c "
    set -euo pipefail
    cd '$REPO_DIR'
    [[ -d .venv ]] || python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
"
ok ".venv pronto em $REPO_DIR/.venv"

# --- 5: verificação ----------------------------------------------------------
info "Verificando ferramentas instaladas"
for cmd in VBoxManage hostapd dnsmasq nft iw mysql nmap arp-scan python3 git; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd -> $(command -v "$cmd")"
    else
        erro "$cmd não encontrado"
    fi
done

info "Verificando suporte a modo AP na placa Wi-Fi (pré-requisito da Fase 1)"
if iw list 2>/dev/null | sed -n '/Supported interface modes/,/^\s*[A-Z].*:$/p' | grep -qE '^\s*\* AP$'; then
    ok "A placa Wi-Fi suporta modo AP."
else
    warn "Não encontrei modo AP em 'iw list'. Sem isso o hostapd não sobe — confira a placa (ou use um adaptador USB que suporte AP) antes da Fase 1."
fi

info "Fase 0 concluída no host. Próximo passo: Fase 1 (rede controlada)."
