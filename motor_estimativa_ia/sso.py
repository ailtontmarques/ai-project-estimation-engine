"""Integração com o UNE AI SSO: proxy de login/refresh/logout e validação do token de acesso.

O token é validado por introspecção (GET /users/me no SSO), com cache curto. O app não verifica
a assinatura do JWT: isso exigiria guardar o segredo HS256 do SSO e perderia, ainda, desativação
de usuários e troca de roles feitas no SSO. O payload só é decodificado para pré-checagens baratas.

O SSO é multi-tenant: toda chamada leva o cabeçalho x-domain-id do domínio do app (SSO_DOMAIN_SLUG).
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

# Perfil do app por nome de role no domínio do SSO; com várias roles vale a de maior precedência.
ROLE_TO_PROFILE = {"admin": "admin", "tech_leader": "tech_leader", "product_owner": "product_owner"}
PROFILE_PRECEDENCE = ("admin", "tech_leader", "product_owner")


class SSOError(Exception):
    status_code = 502

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidCredentials(SSOError):
    status_code = 401


class InvalidToken(SSOError):
    status_code = 401


class AccessDenied(SSOError):
    status_code = 403


class SSOUnavailable(SSOError):
    status_code = 503


@dataclass(frozen=True)
class Identity:
    """Usuário autenticado; é o "actor" recebido pelos serviços."""
    id: uuid.UUID
    email: str
    name: str
    roles: tuple[str, ...]
    profile: str


def profile_for(roles: tuple[str, ...]) -> str:
    profiles = {ROLE_TO_PROFILE[r] for r in roles if r in ROLE_TO_PROFILE}
    for profile in PROFILE_PRECEDENCE:
        if profile in profiles:
            return profile
    raise AccessDenied("Usuário sem role de acesso ao Motor de Estimativa (admin, tech_leader ou product_owner).")


def decode_payload(token: str) -> dict[str, Any]:
    """Decodifica o payload do JWT sem verificar a assinatura."""
    try:
        segment = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except (IndexError, ValueError):
        raise InvalidToken("Token malformado.") from None
    if not isinstance(payload, dict):
        raise InvalidToken("Token malformado.")
    return payload


class TokenCache:
    """Identidades já validadas, por hash do token; nunca além do exp do próprio token."""

    def __init__(self, ttl_seconds: float):
        self.ttl = ttl_seconds
        self._items: dict[str, tuple[float, Identity]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token: str) -> Identity | None:
        key = self._key(token)
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            if item[0] <= time.time():
                del self._items[key]
                return None
            return item[1]

    def put(self, token: str, identity: Identity, token_exp: float) -> None:
        if self.ttl <= 0:
            return
        with self._lock:
            self._items[self._key(token)] = (min(time.time() + self.ttl, token_exp), identity)

    def discard(self, token: str) -> None:
        with self._lock:
            self._items.pop(self._key(token), None)


class SSOClient:
    def __init__(self, base_url: str, domain_slug: str, timeout: float = 5.0, cache_ttl: float = 30.0,
                 max_token_lifetime: float = 3660.0, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        self.domain_slug = domain_slug
        self.max_token_lifetime = max_token_lifetime
        self.cache = TokenCache(cache_ttl)
        self._domain_id: str | None = None

    @classmethod
    def from_env(cls) -> SSOClient:
        return cls(
            base_url=os.environ.get("SSO_BASE_URL", "http://localhost:4000"),
            domain_slug=os.environ.get("SSO_DOMAIN_SLUG", "motor-estimativa"),
            timeout=float(os.environ.get("SSO_TIMEOUT_SECONDS", "5")),
            cache_ttl=float(os.environ.get("SSO_CACHE_TTL_SECONDS", "30")),
            max_token_lifetime=float(os.environ.get("SSO_MAX_TOKEN_LIFETIME_SECONDS", "3660")),
        )

    # Transporte

    def _send(self, method: str, path: str, *, headers: dict[str, str], token: str | None = None,
              body: dict | None = None) -> httpx.Response:
        if token:
            headers = {**headers, "Authorization": f"Bearer {token}"}
        try:
            response = self.http.request(method, path, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise SSOUnavailable(f"SSO indisponível: {exc.__class__.__name__}.") from exc
        if response.status_code == 429:
            raise SSOUnavailable("SSO recusou por limite de requisições (429); tente novamente em instantes.")
        if response.status_code >= 500:
            raise SSOUnavailable(f"SSO respondeu com erro {response.status_code}.")
        return response

    def domain_id(self) -> str:
        """ID do domínio do app no SSO, resolvido pelo slug na primeira chamada."""
        if self._domain_id is None:
            try:
                response = self._send("GET", f"/domains/slug/{self.domain_slug}",
                                      headers={"x-domain-slug": self.domain_slug})
            except SSOUnavailable as exc:
                # O SSO responde 500 (e não 404) para slug inexistente.
                raise SSOUnavailable(f"Domínio '{self.domain_slug}' não encontrado ou SSO indisponível; "
                                     "confira SSO_DOMAIN_SLUG e o bootstrap do domínio.") from exc
            if response.status_code != 200:
                raise SSOUnavailable(f"Domínio '{self.domain_slug}' não encontrado no SSO.")
            self._domain_id = str(response.json()["id"])
        return self._domain_id

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        return self._send(method, path, headers={"x-domain-id": self.domain_id()}, **kwargs)

    @staticmethod
    def _tokens(data: dict[str, Any], previous_refresh: str | None = None) -> dict[str, Any]:
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token") or previous_refresh,
            "expires_in": int(data.get("expires_in") or 3600),
            "token_type": data.get("token_type") or "Bearer",
        }

    # Sessão (proxy)

    def login(self, email: str, password: str) -> dict[str, Any]:
        response = self._request("POST", "/auth/login", body={"email": email, "password": password})
        if not response.is_success:
            raise InvalidCredentials("E-mail ou senha inválidos.")
        data = response.json()
        if data.get("mfa_required") or data.get("setup_required"):
            raise AccessDenied("Conta com MFA ativo; o login com MFA ainda não é suportado pelo Motor de Estimativa.")
        return self._tokens(data)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        response = self._request("POST", "/auth/refresh", body={"refresh_token": refresh_token})
        if not response.is_success:
            raise InvalidToken("Refresh token inválido, expirado ou revogado.")
        return self._tokens(response.json(), previous_refresh=refresh_token)

    def logout(self, access_token: str, refresh_token: str | None = None) -> None:
        """Best-effort: o cache local é sempre descartado, mesmo se o SSO falhar."""
        self.cache.discard(access_token)
        try:
            self._request("POST", "/auth/logout", token=access_token,
                          body={"refresh_token": refresh_token} if refresh_token else None)
        except SSOUnavailable:
            pass

    # Validação do token de acesso

    def precheck(self, token: str) -> dict[str, Any]:
        """Rejeita sem chamar o SSO tokens malformados, vencidos, de outro domínio ou de longa duração."""
        payload = decode_payload(token)
        try:
            exp, iat = float(payload["exp"]), float(payload["iat"])
            uuid.UUID(str(payload["sub"]))
            domain_id = str(payload["domain_id"])
        except (KeyError, TypeError, ValueError):
            raise InvalidToken("Token sem as claims esperadas.") from None
        if exp <= time.time():
            raise InvalidToken("Token expirado.")
        if domain_id != self.domain_id():
            raise InvalidToken("Token emitido para outro domínio do SSO.")
        # O SSO emite refresh e access tokens com as mesmas claims; só o tempo de vida os distingue.
        if exp - iat > self.max_token_lifetime:
            raise InvalidToken("Use o access token; refresh token não é aceito como Bearer.")
        return payload

    def authenticate(self, token: str, on_new: Callable[[Identity], None] | None = None) -> Identity:
        """Identidade do token. on_new roda quando a identidade não estava no cache (ex.: espelhar o usuário)."""
        cached = self.cache.get(token)
        if cached is not None:
            return cached
        payload = self.precheck(token)
        response = self._request("GET", "/users/me", token=token)
        if response.status_code in (401, 403):
            raise InvalidToken("Token inválido, expirado ou revogado.")
        if not response.is_success:
            raise SSOUnavailable(f"SSO respondeu {response.status_code} em /users/me.")
        data = response.json()
        if str(data.get("id")) != str(payload["sub"]):
            raise InvalidToken("Token não corresponde ao usuário retornado pelo SSO.")
        if data.get("is_active") is False:
            raise AccessDenied("Usuário desativado no SSO.")
        roles = tuple(data.get("roles") or ())
        identity = Identity(id=uuid.UUID(str(data["id"])), email=data["email"],
                            name=data.get("full_name") or data["email"], roles=roles, profile=profile_for(roles))
        if on_new is not None:
            on_new(identity)
        self.cache.put(token, identity, float(payload["exp"]))
        return identity


@lru_cache
def get_sso_client() -> SSOClient:
    """Dependência FastAPI: cliente único por processo (mantém o cache e o domain_id)."""
    return SSOClient.from_env()
