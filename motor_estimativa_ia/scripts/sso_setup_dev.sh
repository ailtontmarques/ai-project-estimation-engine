#!/usr/bin/env bash
# Prepara o domínio do Motor de Estimativa no UNE AI SSO local e o primeiro administrador.
#
#   1. cria o domínio SSO_DOMAIN_SLUG (.env)
#   2. registra o primeiro usuário (ou recupera o id, se já existir)
#   3. gera scripts/out/sso_first_admin.sql: roles admin, tech_leader e product_owner + admin ao usuário
#   4. aplica o SQL no Postgres do SSO, se SSO_DB_USER e SSO_DB_NAME estiverem definidos
#   5. confere as roles fazendo login
#
# Uso:
#   SSO_BOOTSTRAP_PASSWORD='<senha forte>' scripts/sso_setup_dev.sh [email] [nome completo]
#   (sem SSO_BOOTSTRAP_PASSWORD a senha é pedida no terminal)
#
# Para aplicar o SQL automaticamente (passo 4), informe as credenciais do banco do SSO:
#   SSO_DB_USER=<usuário> SSO_DB_NAME=<banco> [SSO_DB_CONTAINER=une-ai-sso-postgres] scripts/sso_setup_dev.sh
set -euo pipefail
cd "$(dirname "$0")/.."

EMAIL="${1:-ailton.marques@une.cx}"
FULL_NAME="${2:-}"
PY=".venv/bin/python"
BOOTSTRAP="scripts/sso_bootstrap.py"
SQL_FILE="scripts/out/sso_first_admin.sql"
SSO_DB_CONTAINER="${SSO_DB_CONTAINER:-une-ai-sso-postgres}"

if [[ -z "${SSO_BOOTSTRAP_PASSWORD:-}" ]]; then
  read -rsp "Senha para ${EMAIL}: " SSO_BOOTSTRAP_PASSWORD
  echo
fi
export SSO_BOOTSTRAP_PASSWORD

echo "== 1. Domínio"
"$PY" "$BOOTSTRAP" domain

echo "== 2. Primeiro usuário"
register_args=(register --email "$EMAIL")
[[ -n "$FULL_NAME" ]] && register_args+=(--full-name "$FULL_NAME")
REGISTER_OUT="$("$PY" "$BOOTSTRAP" "${register_args[@]}")"
echo "$REGISTER_OUT"
USER_ID="$(awk '/^usuário/ {print $2}' <<<"$REGISTER_OUT")"

echo "== 3. SQL das roles e do primeiro admin"
"$PY" "$BOOTSTRAP" first-admin-sql --user-id "$USER_ID" --output "$SQL_FILE"

echo "== 4. Aplicar no banco do SSO"
if [[ -n "${SSO_DB_USER:-}" && -n "${SSO_DB_NAME:-}" ]]; then
  docker exec -i "$SSO_DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$SSO_DB_USER" -d "$SSO_DB_NAME" < "$SQL_FILE"
else
  echo "SSO_DB_USER/SSO_DB_NAME não definidos; aplique manualmente e rode o passo 5:"
  echo "  docker exec -i $SSO_DB_CONTAINER psql -v ON_ERROR_STOP=1 -U <usuário> -d <banco> < $SQL_FILE"
  echo "  $PY $BOOTSTRAP check --email $EMAIL"
  exit 0
fi

echo "== 5. Conferência"
"$PY" "$BOOTSTRAP" check --email "$EMAIL"
