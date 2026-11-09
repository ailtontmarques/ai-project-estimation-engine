"""SSOClient isolado (sem banco): requisições enviadas ao SSO, mapeamento de erros e cache."""
import os
import time
import unittest

try:
    import httpx
    import sso
    from fake_sso import DOMAIN_ID, SLUG, FakeSSO
    DEPENDENCIES = True
except ImportError:
    DEPENDENCIES = False


@unittest.skipUnless(DEPENDENCIES, "dependências da API não instaladas (pip install -r requirements.txt)")
class SSOClientTests(unittest.TestCase):
    def setUp(self):
        self.sso = FakeSSO()
        self.client = self.sso.client()
        self.user = self.sso.add_user("po@teste", ["product_owner"], full_name="PO")

    def test_domain_is_resolved_once_by_slug_and_sent_as_id(self):
        self.client.authenticate(self.user.token)
        self.client.login("po@teste", "senha-forte")
        resolve, *calls = self.sso.requests
        self.assertEqual(resolve.url.path, f"/domains/slug/{SLUG}")
        self.assertEqual(resolve.headers["x-domain-slug"], SLUG)
        self.assertTrue(all(r.headers["x-domain-id"] == DOMAIN_ID for r in calls))

    def test_users_me_receives_bearer(self):
        self.client.authenticate(self.user.token)
        me = next(r for r in self.sso.requests if r.url.path == "/users/me")
        self.assertEqual(me.headers["authorization"], f"Bearer {self.user.token}")

    def test_unknown_domain_slug_is_reported(self):
        client = sso.SSOClient(base_url="http://sso.test", domain_slug="inexistente",
                               transport=httpx.MockTransport(self.sso.handle))
        with self.assertRaises(sso.SSOUnavailable) as ctx:
            client.domain_id()
        self.assertIn("SSO_DOMAIN_SLUG", ctx.exception.message)

    def test_network_error_is_unavailable(self):
        def broken(request):
            raise httpx.ConnectError("recusado", request=request)
        client = sso.SSOClient(base_url="http://sso.test", domain_slug=SLUG, transport=httpx.MockTransport(broken))
        with self.assertRaises(sso.SSOUnavailable):
            client.authenticate(self.user.token)

    def test_on_new_runs_only_on_cache_miss(self):
        seen = []
        for _ in range(2):
            self.client.authenticate(self.user.token, on_new=seen.append)
        self.assertEqual([i.email for i in seen], ["po@teste"])

    def test_cache_disabled_with_zero_ttl(self):
        client = self.sso.client(cache_ttl=0)
        client.authenticate(self.user.token)
        client.authenticate(self.user.token)
        self.assertEqual(self.sso.calls["GET /users/me"], 2)

    def test_cache_never_outlives_token(self):
        token = self.sso.issue(self.user, exp_offset=2)
        self.client.authenticate(token)
        cached_until = self.client.cache._items[self.client.cache._key(token)][0]
        self.assertLessEqual(cached_until, time.time() + 2)

    def test_logout_is_best_effort(self):
        self.client.domain_id()
        self.sso.fail_with = 503
        self.client.logout(self.user.token)  # não levanta

    def test_from_env_reads_configuration(self):
        names = ("SSO_BASE_URL", "SSO_DOMAIN_SLUG", "SSO_CACHE_TTL_SECONDS", "SSO_MAX_TOKEN_LIFETIME_SECONDS")
        saved = {k: os.environ.get(k) for k in names}
        try:
            os.environ.update({"SSO_BASE_URL": "http://sso.local:9999", "SSO_DOMAIN_SLUG": "outro",
                               "SSO_CACHE_TTL_SECONDS": "5", "SSO_MAX_TOKEN_LIFETIME_SECONDS": "100"})
            client = sso.SSOClient.from_env()
            self.assertEqual(str(client.http.base_url), "http://sso.local:9999")
            self.assertEqual((client.domain_slug, client.cache.ttl, client.max_token_lifetime), ("outro", 5.0, 100.0))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


@unittest.skipUnless(DEPENDENCIES and os.environ.get("SSO_IT_EMAIL") and os.environ.get("SSO_IT_PASSWORD"),
                     "integração com o SSO real: defina SSO_IT_EMAIL e SSO_IT_PASSWORD")
class RealSSOIntegrationTests(unittest.TestCase):
    """Contra o SSO configurado no .env; o usuário precisa ter uma role do app no domínio."""

    def test_login_and_authenticate(self):
        client = sso.SSOClient.from_env()
        tokens = client.login(os.environ["SSO_IT_EMAIL"], os.environ["SSO_IT_PASSWORD"])
        identity = client.authenticate(tokens["access_token"])
        self.assertEqual(identity.email.lower(), os.environ["SSO_IT_EMAIL"].lower())
        client.logout(tokens["access_token"], tokens["refresh_token"])

if __name__ == "__main__":
    unittest.main()
