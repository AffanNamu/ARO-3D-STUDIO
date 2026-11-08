"""Token verification: what the API accepts, and the specific attacks it must refuse."""

from __future__ import annotations

import base64
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from aro_cloud.auth import JwtVerifier
from aro_cloud.errors import Unauthorized

SECRET = "s" * 48
USER = str(uuid.uuid4())
ISS = "https://proj.supabase.co/auth/v1"


def claims(**over):
    c = {
        "sub": USER,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": ISS,
        "exp": int(time.time()) + 600,
        "email": "a@example.test",
    }
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def hs(**over):
    return jwt.encode(claims(**over), SECRET, algorithm="HS256")


def verifier(**kw):
    return JwtVerifier(issuer=ISS, secret=SECRET, **kw)


def test_a_valid_token_yields_the_user():
    p = verifier().verify(hs())
    assert str(p.user_id) == USER and p.email == "a@example.test"


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-jwt",
        jwt.encode(claims(), "wrong-secret-wrong-secret-wrong-secret-1", algorithm="HS256"),
        jwt.encode(claims(exp=int(time.time()) - 3600), SECRET, algorithm="HS256"),
        jwt.encode(claims(aud="other"), SECRET, algorithm="HS256"),
        jwt.encode(claims(iss="https://evil.example/auth/v1"), SECRET, algorithm="HS256"),
        jwt.encode(claims(role="anon"), SECRET, algorithm="HS256"),
        jwt.encode(claims(role="service_role"), SECRET, algorithm="HS256"),
        jwt.encode(claims(sub="not-a-uuid"), SECRET, algorithm="HS256"),
        jwt.encode(claims(sub=None), SECRET, algorithm="HS256"),
        jwt.encode(claims(exp=None), SECRET, algorithm="HS256"),
    ],
)
def test_bad_tokens_are_refused(token):
    with pytest.raises(Unauthorized):
        verifier().verify(token)


def test_alg_none_is_refused():
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    token = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims())}."
    with pytest.raises(Unauthorized):
        verifier().verify(token)


# ----------------------------------------------------------------------------------------------------- asymmetric (JWKS)
def make_es256():
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="k1", alg="ES256", use="sig")
    return key, jwk


def test_es256_token_is_verified_with_the_published_key():
    key, jwk = make_es256()
    v = JwtVerifier(issuer=ISS, jwks_fetch=lambda: {"keys": [jwk]})
    token = jwt.encode(claims(), key, algorithm="ES256", headers={"kid": "k1"})
    assert str(v.verify(token).user_id) == USER


def test_a_token_signed_by_another_key_with_the_same_kid_is_refused():
    _, jwk = make_es256()
    other, _ = make_es256()
    v = JwtVerifier(issuer=ISS, jwks_fetch=lambda: {"keys": [jwk]})
    with pytest.raises(Unauthorized):
        v.verify(jwt.encode(claims(), other, algorithm="ES256", headers={"kid": "k1"}))


def test_algorithm_confusion_public_key_as_hmac_secret_is_refused():
    key, jwk = make_es256()
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    forged = (
        jwt.encode(claims(), pem, algorithm="HS256", headers={"kid": "k1"}) if False else None
    )  # PyJWT refuses to sign HS256 with a PEM
    assert forged is None

    # build it by hand, the way an attacker would
    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    import hashlib
    import hmac

    signing = (
        f"{b64(json.dumps({'alg': 'HS256', 'typ': 'JWT', 'kid': 'k1'}).encode())}.{b64(json.dumps(claims()).encode())}"
    )
    sig = b64(hmac.new(pem, signing.encode(), hashlib.sha256).digest())
    v = JwtVerifier(issuer=ISS, jwks_fetch=lambda: {"keys": [jwk]})  # JWKS only: HS256 must not be accepted at all
    with pytest.raises(Unauthorized):
        v.verify(f"{signing}.{sig}")


def test_hs256_is_refused_when_only_asymmetric_keys_are_configured_and_vice_versa():
    _, jwk = make_es256()
    only_jwks = JwtVerifier(issuer=ISS, jwks_fetch=lambda: {"keys": [jwk]})
    with pytest.raises(Unauthorized):
        only_jwks.verify(hs())
    key, _ = make_es256()
    only_secret = verifier()
    with pytest.raises(Unauthorized):
        only_secret.verify(jwt.encode(claims(), key, algorithm="ES256", headers={"kid": "k1"}))


def test_unknown_kid_does_not_hammer_the_key_endpoint():
    key, jwk = make_es256()
    calls = []
    now = [0.0]

    def fetch():
        calls.append(1)
        return {"keys": [jwk]}

    v = JwtVerifier(issuer=ISS, jwks_fetch=fetch, clock=lambda: now[0])
    stranger = jwt.encode(claims(), key, algorithm="ES256", headers={"kid": "unknown"})
    for _ in range(20):
        with pytest.raises(Unauthorized):
            v.verify(stranger)
    assert len(calls) <= 2
    now[0] += 60
    with pytest.raises(Unauthorized):
        v.verify(stranger)
    assert len(calls) <= 3


def test_a_verifier_needs_some_key_material():
    with pytest.raises(ValueError):
        JwtVerifier()
