#!/usr/bin/env bash
# sql/setup_banco.sh — Fases 3 e 4: protege o MySQL, aplica o schema e cria o
# usuário dedicado do Sentinela (nunca root no agente/portal).
#
# Uso:  sudo sql/setup_banco.sh [/etc/sentinela/sentinela.env]
#
# No host, conecta como root pelo socket (auth_socket do Ubuntu/Mint: sem senha
# em lugar nenhum). Idempotente: rodar de novo só sincroniza senha e permissões.
#
# Variáveis opcionais (usadas pelo CI, que fala com um MySQL em container):
#   MYSQL_HOST / MYSQL_PWD / MYSQL_ADMIN_USER  conexão administrativa por TCP
#   HOSTS_SENTINELA="localhost 127.0.0.1"      de onde o usuário pode logar
#   MANTER_ROOT_REMOTO=1                       não remove root@'%' (container)
set -euo pipefail

ENV_FILE="${1:-/etc/sentinela/sentinela.env}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
erro() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; exit 1; }

valor() {   # lê uma chave do .env sem executar o arquivo
    local v
    v=$(grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    echo "${v:-$2}"
}

sql_str() {   # literal SQL seguro: escapa \ e '
    local s=${1//\\/\\\\}
    s=${s//\'/\'\'}
    printf "'%s'" "$s"
}

[[ -r "$ENV_FILE" ]] || erro "não consigo ler $ENV_FILE"
if [[ -z "${MYSQL_HOST:-}" && $EUID -ne 0 ]]; then
    erro "rode com sudo (o root do MySQL autentica pelo socket)"
fi

USUARIO=$(valor MYSQL_USER sentinela)
SENHA=$(valor MYSQL_PASSWORD "")
BANCO=$(valor MYSQL_DATABASE vigia_de_rede)
read -r -a HOSTS <<< "${HOSTS_SENTINELA:-localhost 127.0.0.1}"

[[ "$USUARIO" =~ ^[A-Za-z0-9_]{1,32}$ ]] || erro "MYSQL_USER inválido: $USUARIO"
[[ "$USUARIO" != root ]] || erro "MYSQL_USER não pode ser root"
[[ "$BANCO" == vigia_de_rede ]] || erro "o schema cria 'vigia_de_rede'; MYSQL_DATABASE=$BANCO não bate"
[[ ${#SENHA} -ge 12 ]] || erro "MYSQL_PASSWORD precisa de pelo menos 12 caracteres"
[[ "$SENHA" != troque-esta-senha ]] || erro "troque a MYSQL_PASSWORD do .env"

MYSQL=(mysql --user="${MYSQL_ADMIN_USER:-root}")

if [[ -z "${MYSQL_HOST:-}" ]]; then
    systemctl enable -q --now mysql
fi

# --- 1. equivalente ao mysql_secure_installation ----------------------------
FILTRO_ROOT="(User='root' AND Host NOT IN ('localhost','127.0.0.1','::1'))"
[[ "${MANTER_ROOT_REMOTO:-0}" == 1 ]] && FILTRO_ROOT="FALSE"
"${MYSQL[@]}" -N -e "SELECT CONCAT('DROP USER IF EXISTS ', QUOTE(User), '@', QUOTE(Host), ';')
                     FROM mysql.user WHERE User = '' OR $FILTRO_ROOT" | "${MYSQL[@]}"
"${MYSQL[@]}" -e "DROP DATABASE IF EXISTS test;
                  DELETE FROM mysql.db WHERE Db = 'test' OR Db = 'test\\_%';
                  FLUSH PRIVILEGES;"
ok "usuários anônimos, root remoto e banco 'test' removidos"

BIND=$("${MYSQL[@]}" -N -e "SELECT @@bind_address")
if [[ -z "${MYSQL_HOST:-}" && "$BIND" != 127.0.0.1 && "$BIND" != localhost ]]; then
    warn "MySQL ouvindo em '$BIND' — o padrão seguro é 127.0.0.1 (só o host acessa)"
fi

# --- 2. schema (Fase 4) -----------------------------------------------------
"${MYSQL[@]}" < "$DIR/schema.sql"
ok "schema aplicado ($DIR/schema.sql)"

# --- 3. usuário dedicado: só DML no banco do Sentinela -----------------------
{
    for h in "${HOSTS[@]}"; do
        u="$(sql_str "$USUARIO")@$(sql_str "$h")"
        echo "CREATE USER IF NOT EXISTS $u IDENTIFIED BY $(sql_str "$SENHA");"
        echo "ALTER USER $u IDENTIFIED BY $(sql_str "$SENHA");"
        echo "GRANT SELECT, INSERT, UPDATE, DELETE ON vigia_de_rede.* TO $u;"
    done
    echo "FLUSH PRIVILEGES;"
} | "${MYSQL[@]}"      # via stdin: a senha não aparece no `ps`
ok "usuário '$USUARIO' com SELECT/INSERT/UPDATE/DELETE em vigia_de_rede (hosts: ${HOSTS[*]})"

# --- 4. conferência ---------------------------------------------------------
NAO_INNODB=$("${MYSQL[@]}" -N -e "SELECT COUNT(*) FROM information_schema.tables
                                  WHERE table_schema = 'vigia_de_rede' AND engine <> 'InnoDB'")
[[ "$NAO_INNODB" == 0 ]] || erro "há tabelas fora do InnoDB (FKs seriam decorativas)"
ok "todas as tabelas em InnoDB"
