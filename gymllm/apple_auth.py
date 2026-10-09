"""Checking the identity token Sign in with Apple hands the iOS app: a JWT signed by
one of Apple's published keys, issued by Apple, for this app, and not expired. Done
by hand with `cryptography` (google-auth already brings it) to save a dependency."""

from __future__ import annotations

import base64
import binascii
import json
import time

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ISSUER = "https://appleid.apple.com"
KEYS_URL = "https://appleid.apple.com/auth/keys"
KEYS_KEPT = 60 * 60  # seconds; Apple rotates its keys rarely
LEEWAY = 60  # seconds a clock may be off

_keys: dict[str, dict] = {}
_keys_at = 0.0


def _b64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def fetch_keys() -> dict[str, dict]:
    """Apple's signing keys by key id. Raises requests' errors when Apple is out of reach."""
    resp = requests.get(KEYS_URL, timeout=5)
    resp.raise_for_status()
    return {k["kid"]: k for k in resp.json()["keys"]}


def _key(kid: str) -> dict | None:
    """The key `kid`, asking Apple again when it is unknown or the copy is old."""
    global _keys, _keys_at
    if kid not in _keys or time.time() - _keys_at > KEYS_KEPT:
        _keys, _keys_at = fetch_keys(), time.time()
    return _keys.get(kid)


def verify_identity_token(token: str, audience: str) -> dict:
    """The token's claims if Apple signed it for our app; ValueError if not."""
    try:
        head, body, signature = token.split(".")
        header = json.loads(_b64(head))
        claims = json.loads(_b64(body))
        signed = _b64(signature)
    except (ValueError, binascii.Error):
        raise ValueError("not a JWT") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("not a JWT")
    if header.get("alg") != "RS256":
        raise ValueError("unexpected algorithm")
    jwk = _key(str(header.get("kid")))
    if jwk is None or jwk.get("kty") != "RSA":
        raise ValueError("unknown signing key")
    public = rsa.RSAPublicNumbers(
        int.from_bytes(_b64(jwk["e"]), "big"), int.from_bytes(_b64(jwk["n"]), "big")
    ).public_key()
    try:
        public.verify(signed, f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise ValueError("bad signature") from None
    if claims.get("iss") != ISSUER:
        raise ValueError("wrong issuer")
    aud = claims.get("aud")
    if audience not in (aud if isinstance(aud, list) else [aud]):
        raise ValueError("wrong audience")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time() - LEEWAY:
        raise ValueError("expired")
    return claims
