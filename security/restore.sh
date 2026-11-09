#!/usr/bin/env bash
# security/restore.sh — Fase 6: restaura o banco a partir de um backup.
#
# Uso:  sudo security/restore.sh <arquivo.sql.gz> [--sim]
#       --sim  pula a confirmação interativa (ensaio automatizado / CI)
#
# Antes de sobrescrever, tira um backup de segurança do estado atual:
# um restore errado também tem volta.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/sentinela}"

if [[ $# -lt 1 ]]; then
    echo "Uso: $0 <arquivo_de_backup.sql.gz> [--sim]"
    echo "Disponíveis em $BACKUP_DIR:"
    ls -1t "$BACKUP_DIR" 2>/dev/null || echo "  (nenhum)"
    exit 1
fi

ARQUIVO="$1"
CONFIRMADO="${2:-}"
[[ -f "$ARQUIVO" ]] || { echo "Arquivo não encontrado: $ARQUIVO" >&2; exit 1; }
gzip -t "$ARQUIVO" || { echo "Backup corrompido: $ARQUIVO" >&2; exit 1; }

if [[ "$CONFIRMADO" != "--sim" ]]; then
    echo "ATENÇÃO: isso vai sobrescrever o banco vigia_de_rede com '$ARQUIVO'."
    read -r -p "Confirmar? (digite SIM): " confirma
    [[ "$confirma" == "SIM" ]] || { echo "Cancelado."; exit 0; }
fi

echo "Backup de segurança do estado atual:"
BACKUP_DIR="$BACKUP_DIR" bash "$DIR/backup.sh"

CONEXAO=(--user="${MYSQL_ADMIN_USER:-root}")
[[ -n "${MYSQL_HOST:-}" ]] && CONEXAO+=(--host="$MYSQL_HOST" --port="${MYSQL_TCP_PORT:-3306}")
gunzip < "$ARQUIVO" | mysql "${CONEXAO[@]}"
echo "$(date '+%F %T') restore concluído a partir de: $ARQUIVO"
echo "Lembrete: o firewall espelha o banco — rode 'sudo systemctl restart sentinela-ressync'."
