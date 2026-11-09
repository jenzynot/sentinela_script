#!/usr/bin/env bash
# security/backup.sh — Fase 6: backup local do banco vigia_de_rede, com retenção.
#
# Agendado pelo cron (instalar.sh seguranca): todo dia às 02:00, como root.
# No host conecta pelo socket (root do MySQL sem senha); no CI usa
# MYSQL_HOST / MYSQL_PWD / MYSQL_ADMIN_USER.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/sentinela}"
RETENCAO_DIAS="${RETENCAO_DIAS:-7}"
# milissegundos: o backup de segurança do restore.sh nunca pode ter o mesmo
# nome (e sobrescrever) o arquivo que está sendo restaurado
STAMP=$(date +%Y-%m-%d_%H-%M-%S_%3N)
ARQUIVO="$BACKUP_DIR/vigia_de_rede_$STAMP.sql.gz"

if [[ -z "${MYSQL_HOST:-}" && $EUID -ne 0 ]]; then
    echo "rode como root (o root do MySQL autentica pelo socket)" >&2
    exit 1
fi

umask 077                       # backup contém a whitelist inteira: só o dono lê
mkdir -p "$BACKUP_DIR"

# --single-transaction: dump consistente sem travar o InnoDB (o agente segue gravando)
# --databases: o arquivo recria o banco sozinho no restore
mysqldump --user="${MYSQL_ADMIN_USER:-root}" --single-transaction --no-tablespaces \
    --routines --triggers --databases vigia_de_rede | gzip > "$ARQUIVO.tmp"
gzip -t "$ARQUIVO.tmp"          # arquivo corrompido não substitui nada
mv "$ARQUIVO.tmp" "$ARQUIVO"

# Política de retenção: apaga backups com mais de RETENCAO_DIAS dias
find "$BACKUP_DIR" -name "vigia_de_rede_*.sql.gz" -mtime +"$RETENCAO_DIAS" -delete

echo "$(date '+%F %T') backup concluído: $ARQUIVO ($(du -h "$ARQUIVO" | cut -f1))"
