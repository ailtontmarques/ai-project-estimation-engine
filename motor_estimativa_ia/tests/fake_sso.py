"""SSO falso em memória que imita o contrato do UNE AI SSO (rotas, cabeçalhos de domínio, tokens).

É ligado ao SSOClient real por httpx.MockTransport, então os testes exercitam também o cliente.
Os tokens têm o formato JWT com as mesmas claims do SSO real, mas assinatura fictícia.
"""
from __future__ import annotations
import base64
import itertools
import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass

import httpx

from sso import SSOClient

DOMAIN_ID = "6f0c2a4e-1d1b-4c56-9a2b-000000000001"
OTHER_DOMAIN_ID = "6f0c2a4e-1d1b-4c56-9a2b-000000000002"
SLUG = "motor-estimativa"
ACCESS_LIFETIME = 3600
REFRESH_LIFETIME = 7 * 24 * 3600


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


@dataclass
class FakeUser:
    id: uuid.UUID
    email: str
    full_name: str | None
    password: str
    roles: list[str]
    is_active: bool = True
    mfa: bool = False
    token: str = ""  # access token pronto para uso nos testes


class FakeSSO:
    def __init__(self):
        self.users: dict[str, FakeUser] = {}
        self.access: dict[str, FakeUser] = {}
        self.refresh: dict[str, FakeUser] = {}
        self.calls: Counter[str] = Counter()
        self.requests: list[httpx.Request] = []
        self.fail_with: int | None = None  # força este status em todas as respostas
        self._serial = itertools.count(1)

    def client(self, **kwargs) -> SSOClient:
        return SSOClient(base_url="http://sso.test", domain_slug=SLUG, transport=httpx.MockTransport(self.handle), **kwargs)

    def add_user(self, email: str, roles: list[str], full_name: str | None = None, password: str = "senha-forte",
                 mfa: bool = False) -> FakeUser:
        user = FakeUser(id=uuid.uuid4(), email=email, full_name=full_name, password=password, roles=roles, mfa=mfa)
        self.users[email] = user
        user.token = self.issue(user)
        return user

    def issue(self, user: FakeUser, lifetime: int = ACCESS_LIFETIME, domain_id: str = DOMAIN_ID,
              exp_offset: int | None = None, kind: str = "access") -> str:
        now = int(time.time())
        exp = now + (lifetime if exp_offset is None else exp_offset)
        payload = {"sub": str(user.id), "email": user.email, "domain_id": domain_id, "domain_slug": SLUG,
                   "iat": now, "exp": exp}
        token = f"{_b64({'alg': 'HS256', 'typ': 'JWT'})}.{_b64(payload)}.fake{next(self._serial)}"
        (self.access if kind == "access" else self.refresh)[token] = user
        return token

    # Servidor

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = f"{request.method} {request.url.path}"
        self.calls[route] += 1
        if self.fail_with is not None:
            return httpx.Response(self.fail_with, json={"message": "falha simulada"})
        if request.method == "GET" and request.url.path.startswith("/domains/slug/"):
            slug = request.url.path.rsplit("/", 1)[-1]
            if request.headers.get("x-domain-slug") != slug or slug != SLUG:
                return httpx.Response(500, json={"statusCode": 500, "message": "Internal server error"})
            return httpx.Response(200, json={"id": DOMAIN_ID, "slug": SLUG, "name": "Motor", "is_active": True})
        if request.headers.get("x-domain-id") != DOMAIN_ID:
            return httpx.Response(400, json={"message": "Domain context is required"})
        body = json.loads(request.content) if request.content else {}
        if route == "POST /auth/login":
            user = self.users.get(body.get("email"))
            if user is None or user.password != body.get("password"):
                return httpx.Response(401, json={"message": "Invalid credentials"})
            if user.mfa:
                return httpx.Response(200, json={"mfa_required": True, "mfa_token": self.issue(user),
                                                 "available_methods": ["totp"]})
            return httpx.Response(200, json=self._pair(user))
        if route == "POST /auth/refresh":
            user = self.refresh.pop(body.get("refresh_token"), None)
            if user is None:
                return httpx.Response(401, json={"message": "Invalid refresh token"})
            return httpx.Response(200, json=self._pair(user))
        user = self._bearer(request)
        if user is None:
            return httpx.Response(401, json={"message": "Unauthorized"})
        if route == "POST /auth/logout":
            for token in [t for t, u in self.refresh.items() if u is user and body.get("refresh_token") in (None, t)]:
                del self.refresh[token]
            return httpx.Response(200, json={"message": "Logout successful"})
        if route == "GET /users/me":
            return httpx.Response(200, json={
                "id": str(user.id), "email": user.email, "full_name": user.full_name, "is_active": user.is_active,
                "is_verified": True, "mfa_enabled": user.mfa, "roles": user.roles, "permissions": []})
        return httpx.Response(404, json={"message": "Not found"})

    def _pair(self, user: FakeUser) -> dict:
        return {"access_token": self.issue(user), "refresh_token": self.issue(user, REFRESH_LIFETIME, kind="refresh"),
                "expires_in": ACCESS_LIFETIME, "token_type": "Bearer", "mfa_required": False}

    def _bearer(self, request: httpx.Request) -> FakeUser | None:
        # Como o SSO real: valida assinatura/expiração; refresh token também passa como Bearer.
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        user = self.access.get(token) or self.refresh.get(token)
        if user is None:
            return None
        segment = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        return user if payload["exp"] > time.time() and payload["domain_id"] == request.headers.get("x-domain-id") else None
