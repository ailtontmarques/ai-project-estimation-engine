"""Bootstrap do domínio do Motor de Estimativa no UNE AI SSO (idempotente).

Passos (na ordem; scripts/sso_setup_dev.sh executa 1 a 3 de uma vez):
  1. domain             cria o domínio SSO_DOMAIN_SLUG (POST /domains não exige autenticação no SSO).
  2. register           registra o primeiro usuário no domínio (ou recupera o id, se já existir).
  3. first-admin-sql    gera o SQL que cria as roles admin, tech_leader e product_owner e atribui
                        admin ao primeiro usuário. Deve ser executado no banco do SSO: o SSO não tem
                        seed e criar/atribuir roles via API exige uma role com domain.roles.write /
                        user.roles.write no próprio domínio, que ainda não existe.
  4. check              faz login e mostra as roles do usuário e do domínio.
  Depois do passo 3, a API do SSO passa a servir para o dia a dia:
     roles              cria (se faltarem) as roles tech_leader e product_owner.
     assign             atribui uma role a um usuário do domínio.

A senha nunca vai em argumento de linha de comando por padrão: é lida de SSO_BOOTSTRAP_PASSWORD
ou pedida no terminal. Lê SSO_BASE_URL e SSO_DOMAIN_SLUG do .env do projeto.
"""
from __future__ import annotations
import argparse
import getpass
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("SSO_BASE_URL", "http://localhost:4000")
SLUG = os.environ.get("SSO_DOMAIN_SLUG", "motor-estimativa")

# Permissões do próprio SSO necessárias para o admin do domínio gerenciar roles e atribuições.
SSO_ADMIN_PERMISSIONS = ["domain.roles.read", "domain.roles.write", "user.roles.read", "user.roles.write", "rbac.read"]
ADMIN_DESCRIPTION = "Administrador do Motor de Estimativa (parâmetros, aprovação e gestão de roles)"
APP_ROLES = {
    "tech_leader": "Tech Leader: revisa e aprova estimativas técnicas",
    "product_owner": "Product Owner: cadastra projetos e solicita estimativas",
}
# Mesma política do SSO (PasswordService.validatePasswordStrength): 12+ caracteres e ao menos uma
# minúscula, uma maiúscula, um número e um especial entre @$!%*?& (outros caracteres são permitidos).
PASSWORD_RULE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{12,}$")


def fail(response: httpx.Response, action: str) -> None:
    hint = ""
    if response.status_code >= 500:
        hint = ("\nDica: veja o log do SSO (docker logs une-ai-sso-service). Se aparecer 'relation ... does not exist', "
                "as migrações do SSO não foram aplicadas: docker exec une-ai-sso-service npm run migration:run")
    sys.exit(f"Falha ao {action}: HTTP {response.status_code} {response.text[:300]}{hint}")


def read_password(args) -> str:
    password = getattr(args, "password", None) or os.environ.get("SSO_BOOTSTRAP_PASSWORD") or getpass.getpass("Senha: ")
    return password


def get_domain(http: httpx.Client) -> dict | None:
    response = http.get(f"/domains/slug/{SLUG}", headers={"x-domain-slug": SLUG})
    return response.json() if response.status_code == 200 else None


def require_domain(http: httpx.Client) -> dict:
    domain = get_domain(http)
    if domain is None:
        sys.exit(f"Domínio '{SLUG}' não encontrado; execute o passo 'domain' primeiro.")
    return domain


def login(http: httpx.Client, domain_id: str, email: str, password: str) -> dict[str, str]:
    response = http.post("/auth/login", json={"email": email, "password": password}, headers={"x-domain-id": domain_id})
    if not response.is_success or "access_token" not in response.json():
        fail(response, "autenticar (MFA não é suportado por este script)")
    return {"Authorization": f"Bearer {response.json()['access_token']}", "x-domain-id": domain_id}


def get_me(http: httpx.Client, headers: dict[str, str]) -> dict:
    response = http.get("/users/me", headers=headers)
    if not response.is_success:
        fail(response, "consultar /users/me")
    return response.json()


def list_roles(http: httpx.Client, domain_id: str, headers: dict[str, str]) -> dict[str, dict]:
    response = http.get(f"/domains/{domain_id}/roles", params={"limit": 100}, headers=headers)
    if not response.is_success:
        fail(response, "listar as roles do domínio")
    return {role["name"]: role for role in response.json()["data"]}  # paginado: {data, total, page, limit}


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def cmd_domain(http: httpx.Client, args) -> None:
    domain = get_domain(http)
    if domain is None:
        response = http.post("/domains", json={"name": args.name, "slug": SLUG,
                                               "description": "Estimativa de esforço e custos com IA"})
        if response.status_code != 409 and not response.is_success:
            fail(response, "criar o domínio")
        domain = require_domain(http)
    print(f"domínio  {domain['id']}  {domain['slug']}  ativo={domain.get('is_active')}")


def cmd_register(http: httpx.Client, args) -> None:
    domain = require_domain(http)
    password = read_password(args)
    if not PASSWORD_RULE.match(password):
        sys.exit("Senha recusada pela política do SSO: mínimo de 12 caracteres, com ao menos uma maiúscula, "
                 "uma minúscula, um número e um caractere especial entre @$!%*?&.")
    response = http.post("/auth/register", headers={"x-domain-id": domain["id"]},
                         json={"email": args.email, "password": password, "full_name": args.full_name})
    if response.status_code == 409:
        # Já registrado: recupera o id autenticando com a mesma senha.
        user = get_me(http, login(http, domain["id"], args.email, password))
        print(f"usuário  {user['id']}  {user['email']} (já existia)")
        return
    if not response.is_success:
        fail(response, "registrar o usuário (o SSO limita o registro a 3 por hora)")
    user = response.json()
    print(f"usuário  {user['id']}  {user['email']} (registrado)")


def cmd_first_admin_sql(http: httpx.Client, args) -> None:
    domain = require_domain(http)
    d, u = sql_literal(domain["id"]), sql_literal(args.user_id)
    admin_permissions = ", ".join(sql_literal(p) for p in SSO_ADMIN_PERMISSIONS)
    rows = [f"    ('admin', {sql_literal(ADMIN_DESCRIPTION)}, ARRAY[{admin_permissions}]::text[])"]
    rows += [f"    ({sql_literal(name)}, {sql_literal(desc)}, ARRAY[]::text[])" for name, desc in APP_ROLES.items()]
    values = ",\n".join(rows)
    sql = f"""-- Bootstrap do domínio {SLUG} no UNE AI SSO (idempotente). Executar no banco do SSO.
BEGIN;

-- Roles do app: admin (com permissões de gestão do próprio SSO), tech_leader e product_owner.
INSERT INTO domain_roles (domain_id, name, description, permissions)
SELECT {d}, v.name, v.description, v.permissions
FROM (VALUES
{values}
) AS v(name, description, permissions)
ON CONFLICT (domain_id, name) DO NOTHING;

-- Primeiro administrador (user_roles não tem chave única no banco; por isso o NOT EXISTS).
INSERT INTO user_roles (user_id, role_id)
SELECT {u}, r.id FROM domain_roles r
WHERE r.domain_id = {d} AND r.name = 'admin'
  AND NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = {u} AND ur.role_id = r.id);

COMMIT;
"""
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(sql, encoding="utf-8")
        print(f"sql      {args.output}")
    else:
        print(sql)


def cmd_check(http: httpx.Client, args) -> None:
    domain = require_domain(http)
    headers = login(http, domain["id"], args.email, read_password(args))
    me = get_me(http, headers)
    print(f"usuário  {me['id']}  {me['email']}  roles={me.get('roles')}")
    if "admin" in (me.get("roles") or []):
        print(f"domínio  roles={sorted(list_roles(http, domain['id'], headers))}")


def cmd_roles(http: httpx.Client, args) -> None:
    domain = require_domain(http)
    headers = login(http, domain["id"], args.email, read_password(args))
    existing = list_roles(http, domain["id"], headers)
    for name, description in APP_ROLES.items():
        if name in existing:
            print(f"role     {existing[name]['id']}  {name} (já existia)")
            continue
        response = http.post(f"/domains/{domain['id']}/roles", headers=headers,
                             json={"name": name, "description": description, "permissions": []})
        if not response.is_success:
            fail(response, f"criar a role {name}")
        print(f"role     {response.json().get('id')}  {name} (criada)")


def cmd_assign(http: httpx.Client, args) -> None:
    domain = require_domain(http)
    headers = login(http, domain["id"], args.email, read_password(args))
    roles = list_roles(http, domain["id"], headers)
    if args.role not in roles:
        sys.exit(f"Role '{args.role}' não existe no domínio; execute o passo 'roles'.")
    response = http.post(f"/users/{args.user_id}/roles", headers=headers, json={"domainRoleId": roles[args.role]["id"]})
    if response.status_code != 409 and not response.is_success:
        fail(response, "atribuir a role")
    print(f"usuário  {args.user_id}  role {args.role}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap do domínio do Motor de Estimativa no UNE AI SSO")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("domain", help="cria o domínio")
    p.add_argument("--name", default="Motor de Estimativa")

    p = sub.add_parser("register", help="registra o primeiro usuário")
    p.add_argument("--email", required=True)
    p.add_argument("--full-name", default=None)

    p = sub.add_parser("first-admin-sql", help="gera o SQL das roles e do primeiro admin")
    p.add_argument("--user-id", required=True)
    p.add_argument("--output", help="grava o SQL neste arquivo em vez de imprimir")

    for name in ("check", "roles", "assign"):
        p = sub.add_parser(name)
        p.add_argument("--email", required=True)
        if name == "assign":
            p.add_argument("--user-id", required=True)
            p.add_argument("--role", required=True, choices=["admin", *APP_ROLES])

    args = parser.parse_args()
    commands = {"domain": cmd_domain, "register": cmd_register, "first-admin-sql": cmd_first_admin_sql,
                "check": cmd_check, "roles": cmd_roles, "assign": cmd_assign}
    with httpx.Client(base_url=BASE_URL, timeout=10) as http:
        commands[args.command](http, args)


if __name__ == "__main__":
    main()
