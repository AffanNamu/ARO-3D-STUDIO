"""Supabase access-token verification (server side, on every request).

Accepted: an access token signed by the project, with audience ``authenticated``, a valid ``exp``, a UUID ``sub`` and role
``authenticated``. Rejected: ``alg: none`` and any algorithm that does not match the configured key type (so a public key can never be
used as an HMAC secret), anon/service tokens, expired tokens, wrong audience or issuer.

Asymmetric projects publish their keys at ``<supabase url>/auth/v1/.well-known/jwks.json``; legacy projects share an HS256 secret.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from aro_cloud.errors import Unauthorized

log = logging.getLogger("aro_cloud.auth")
ASYMMETRIC = ("ES256", "RS256", "EdDSA")


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    email: str | None = None


class JwtVerifier:
    def __init__(
        self,
        *,
        audience: str = "authenticated",
        issuer: str | None = None,
        secret: str | None = None,
        jwks_url: str | None = None,
        jwks_fetch: Callable[[], dict[str, Any]] | None = None,
        leeway_s: int = 10,
        jwks_ttl_s: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not (secret or jwks_url or jwks_fetch):
            raise ValueError("configure a JWT secret or a JWKS URL")
        self.audience, self.issuer, self.secret, self.leeway = audience, issuer, secret, leeway_s
        self._jwks_enabled = bool(jwks_url or jwks_fetch)
        self._fetch: Callable[[], dict[str, Any]] = jwks_fetch or (lambda: self._http_jwks(jwks_url or ""))
        self._keys: dict[str, Any] = {}
        self._loaded_at = -1e9
        self._ttl = jwks_ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._last_refresh_try = -1e9

    @staticmethod
    def _http_jwks(url: str) -> dict[str, Any]:
        r = httpx.get(url, timeout=5.0)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise ValueError("JWKS is not an object")
        return data

    def _refresh(self, *, force: bool) -> None:
        now = self._clock()
        with self._lock:
            if not force and now - self._loaded_at < self._ttl:
                return
            if (
                now - self._last_refresh_try < 30.0 and self._keys
            ):  # an unknown kid must not make every request hit the network
                return
            self._last_refresh_try = now
            try:
                keys = {}
                for jwk in self._fetch().get("keys", []):
                    if jwk.get("kid"):
                        keys[jwk["kid"]] = jwt.PyJWK(jwk)
                if keys:
                    self._keys, self._loaded_at = keys, now
            except Exception as e:  # noqa: BLE001 - keep serving the cached keys; verification still fails closed for unknown ones
                log.warning("could not refresh the signing keys (%s)", type(e).__name__)

    def _key_for(self, kid: str | None) -> Any:
        if not kid:
            raise Unauthorized("The access token has no key id.")
        self._refresh(force=False)
        if kid not in self._keys:
            self._refresh(force=True)
        k = self._keys.get(kid)
        if k is None:
            raise Unauthorized("The access token was signed with an unknown key.")
        return k.key

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise Unauthorized("The access token is malformed.") from None
        alg = header.get("alg")
        if alg == "HS256" and self.secret:
            key: Any = self.secret
        elif (
            alg in ASYMMETRIC and self._jwks_enabled
        ):  # the algorithm must match the key TYPE we hold: never HMAC with a public key
            key = self._key_for(header.get("kid"))
        else:
            raise Unauthorized("The access token uses an unsupported signing algorithm.")
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[alg],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "sub", "aud"], "verify_iss": self.issuer is not None},
            )
        except jwt.ExpiredSignatureError:
            raise Unauthorized("The access token has expired.", recommended_action="Sign in again.") from None
        except jwt.PyJWTError:
            raise Unauthorized("The access token is not valid.") from None
        if claims.get("role") != "authenticated":
            raise Unauthorized("Only signed-in users may use this API.")
        try:
            uid = uuid.UUID(str(claims["sub"]))
        except ValueError:
            raise Unauthorized("The access token has an invalid subject.") from None
        email = claims.get("email")
        return Principal(uid, email if isinstance(email, str) else None)
