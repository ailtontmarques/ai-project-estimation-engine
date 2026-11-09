"""Autenticação via SSO, pela API: proxy de sessão, validação do Bearer, perfis e espelho local."""
import unittest

from support import DATABASE, DatabaseTestCase

if DATABASE:
    from sqlalchemy import text
    from fake_sso import OTHER_DOMAIN_ID, REFRESH_LIFETIME


class SessionProxyTests(DatabaseTestCase):
    def login(self, email="po@teste", password="senha-forte"):
        return self.client.post("/auth/login", json={"email": email, "password": password})

    def test_login_returns_sso_tokens_usable_as_bearer(self):
        response = self.login()
        self.assertEqual(response.status_code, 200, response.text)
        tokens = response.json()
        self.assertEqual(tokens["token_type"], "Bearer")
        self.assertEqual(tokens["expires_in"], 3600)
        me = self.client.get("/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        self.assertEqual(me.json()["email"], "po@teste")

    def test_login_sends_app_domain_to_sso(self):
        self.login()
        request = next(r for r in self.sso.requests if r.url.path == "/auth/login")
        self.assertEqual(request.headers["x-domain-id"], self.sso_client.domain_id())

    def test_invalid_credentials_return_401(self):
        response = self.login(password="errada")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "E-mail ou senha inválidos.")

    def test_mfa_account_is_refused_with_clear_message(self):
        self.sso.add_user("mfa@teste", ["product_owner"], mfa=True)
        response = self.login("mfa@teste")
        self.assertEqual(response.status_code, 403)
        self.assertIn("MFA", response.json()["detail"])

    def test_refresh_rotates_tokens(self):
        tokens = self.login().json()
        response = self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["refresh_token"], tokens["refresh_token"])
        reused = self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assertEqual(reused.status_code, 401)

    def test_logout_revokes_refresh_and_clears_cache(self):
        tokens = self.login().json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        self.client.get("/users/me", headers=headers)
        response = self.client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers)
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(self.sso_client.cache.get(tokens["access_token"]))
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code, 401)

    def test_logout_requires_bearer(self):
        self.assertEqual(self.client.post("/auth/logout").status_code, 401)


class BearerValidationTests(DatabaseTestCase):
    PUBLIC_ROUTES = {("GET", "/health"), ("POST", "/auth/login"), ("POST", "/auth/refresh")}

    def get_me(self, token):
        return self.client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    def test_every_non_public_route_requires_bearer(self):
        from fastapi.routing import APIRoute
        from api import app
        any_id = "00000000-0000-0000-0000-000000000000"
        checked = 0
        for route in (r for r in app.routes if isinstance(r, APIRoute)):
            for method in route.methods:
                if (method, route.path) in self.PUBLIC_ROUTES:
                    continue
                path = route.path.replace("{project_id}", any_id).replace("{estimate_id}", any_id)
                with self.subTest(f"{method} {route.path}"):
                    self.assertEqual(self.client.request(method, path, json={}).status_code, 401)
                checked += 1
        self.assertGreaterEqual(checked, 15)
        self.assertEqual(self.sso.calls["GET /users/me"], 0)

    def test_missing_or_malformed_token_is_rejected(self):
        response = self.client.get("/users/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(self.get_me("nao-e-um-jwt").status_code, 401)

    def test_prechecks_reject_without_calling_sso(self):
        cases = {
            "expirado": self.sso.issue(self.po, exp_offset=-10),
            "outro domínio": self.sso.issue(self.po, domain_id=OTHER_DOMAIN_ID),
            "refresh como Bearer": self.sso.issue(self.po, REFRESH_LIFETIME, kind="refresh"),
        }
        for label, token in cases.items():
            with self.subTest(label):
                self.assertEqual(self.get_me(token).status_code, 401)
        self.assertEqual(self.sso.calls["GET /users/me"], 0)

    def test_token_unknown_to_sso_is_rejected(self):
        forged = self.po.token.rsplit(".", 1)[0] + ".assinatura-falsa"
        self.assertEqual(self.get_me(forged).status_code, 401)

    def test_sso_unavailable_fails_closed(self):
        self.sso.fail_with = 503
        response = self.get_me(self.po.token)
        self.assertEqual(response.status_code, 503)
        self.sso.fail_with = 429
        self.assertEqual(self.get_me(self.tl.token).status_code, 503)

    def test_validated_identity_is_cached(self):
        for _ in range(3):
            self.assertEqual(self.get_me(self.po.token).status_code, 200)
        self.assertEqual(self.sso.calls["GET /users/me"], 1)
        self.assertEqual(self.sso.calls["GET /domains/slug/motor-estimativa"], 1)

    def test_deactivated_user_is_denied(self):
        self.po.is_active = False
        self.assertEqual(self.get_me(self.po.token).status_code, 403)


class ProfileMappingTests(DatabaseTestCase):
    def profile_of(self, user):
        response = self.client.get("/users/me", headers=self.as_user(user))
        return response.status_code, response.json().get("profile")

    def test_profile_comes_from_role_names(self):
        self.assertEqual(self.profile_of(self.tl), (200, "tech_leader"))
        self.assertEqual(self.profile_of(self.admin), (200, "admin"))

    def test_highest_profile_wins_and_unknown_roles_are_ignored(self):
        user = self.sso.add_user("multi@teste", ["product_owner", "editor", "tech_leader"])
        self.assertEqual(self.profile_of(user), (200, "tech_leader"))

    def test_user_without_app_role_is_forbidden(self):
        user = self.sso.add_user("sem-role@teste", ["editor"])
        status, _ = self.profile_of(user)
        self.assertEqual(status, 403)

    def test_profile_drives_permissions(self):
        estimate = self.create_estimate(self.create_project()["id"])
        self.assertEqual(self.client.post(f"/estimates/{estimate['id']}/approve", headers=self.as_user(self.po)).status_code, 403)
        self.assertEqual(self.client.post(f"/estimates/{estimate['id']}/approve", headers=self.as_user(self.tl)).status_code, 200)


class LocalMirrorTests(DatabaseTestCase):
    def local_user(self, user):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT name, email FROM users WHERE id = :id"), {"id": user.id}).first()

    def test_first_access_creates_local_user_used_in_audit(self):
        self.assertIsNone(self.local_user(self.po))
        project = self.client.post("/projects", json={"name": "Do PO"}, headers=self.as_user(self.po)).json()
        self.assertEqual(tuple(self.local_user(self.po)), ("PO", "po@teste"))
        self.assertEqual(project["created_by"], str(self.po.id))

    def test_new_validation_updates_name_and_email(self):
        self.client.get("/users/me", headers=self.as_user(self.po))
        self.po.full_name, self.po.email = "PO Renomeado", "novo-email@teste"
        new_token = self.sso.issue(self.po)  # novo token = nova validação no SSO
        self.client.get("/users/me", headers={"Authorization": f"Bearer {new_token}"})
        self.assertEqual(tuple(self.local_user(self.po)), ("PO Renomeado", "novo-email@teste"))

    def test_name_falls_back_to_email(self):
        user = self.sso.add_user("sem-nome@teste", ["product_owner"])
        self.assertEqual(self.client.get("/users/me", headers=self.as_user(user)).json()["name"], "sem-nome@teste")

if __name__ == "__main__":
    unittest.main()
