"""Who is calling. The Next.js app signs the user in with Google and mints a 5-minute HS256 token
for this API (Auth.js's own session cookie is encrypted and is not read here). The token's `sub`
is the user id, `google:<google sub>`; no email or name is ever stored.

Anonymous visitors (no Authorization header) may read the sample documents and ask questions.
A header that is present but invalid is a 401, never a silent downgrade to anonymous."""

import hashlib
import hmac
import ipaddress
import re
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request

from app.config import Settings, get_settings

SAMPLES = "samples"  # owner of the shared, read-only sample documents
ALGORITHM = "HS256"
_ID = re.compile(r"^[A-Za-z0-9._-]{1,255}$")


@dataclass(frozen=True)
class Identity:
    user_id: str | None  # None: an anonymous visitor
    counter_key: str  # who the daily limits count: a salted hash, never an IP or a user id

    @property
    def signed_in(self) -> bool:
        return self.user_id is not None

    @property
    def owners(self) -> list[str]:
        """Whose documents this caller may see: the samples plus their own."""
        return [SAMPLES, self.user_id] if self.user_id else [SAMPLES]


def _hash(s: Settings, value: str) -> str:
    return hmac.new(s.salt.encode(), value.encode(), hashlib.sha256).hexdigest()[:16]


def verify_token(token: str, s: Settings) -> str:
    """The user id in a valid token, or raises jwt.PyJWTError. The algorithm is pinned (a token
    cannot pick `none` or an RSA key), and subject, expiry, issuer and audience are required."""
    if not s.api_token_secret:
        raise jwt.InvalidTokenError("sign-in is not configured")
    claims = jwt.decode(
        token,
        s.api_token_secret,
        algorithms=[ALGORITHM],
        audience=s.auth_audience,
        issuer=s.auth_issuer,
        options={"require": ["sub", "exp", "iss", "aud"]},
        leeway=10,
    )
    sub = claims["sub"]
    # Users are "google:<id>"; the frontend's test login is "dev:<id>", accepted only when enabled.
    providers = ("google", "dev") if s.allow_dev_users else ("google",)
    provider, _, ident = sub.partition(":") if isinstance(sub, str) else ("", "", "")
    if provider not in providers or not _ID.match(ident):
        raise jwt.InvalidTokenError("bad subject")
    return sub


def visitor_address(ip: str) -> str:
    """What identifies a visitor behind this address. An IPv6 customer is given a whole /64 and can
    switch to any address inside it, so counting single addresses would hand them a fresh daily
    allowance per request; the /64 is the unit that is one connection. IPv4, and anything that is
    not an address, is kept as it came (so existing counters carry over)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:  # ::ffff:1.2.3.4 is the IPv4 client 1.2.3.4
            return str(addr.ipv4_mapped)
        return str(ipaddress.IPv6Address(int(addr) >> 64 << 64))
    return ip


def _client_ip_key(request: Request, s: Settings) -> str:
    """Behind a proxy that sets X-Forwarded-For itself, its last entry is the real client;
    trusting the header anywhere else would let a visitor pick their own identity."""
    ip = request.client.host if request.client else "unknown"
    if s.trust_forwarded_for and (fwd := request.headers.get("x-forwarded-for", "").strip()):
        ip = fwd.split(",")[-1].strip()
    return _hash(s, visitor_address(ip))


def identity(request: Request) -> Identity:
    s = get_settings()
    header = request.headers.get("authorization")
    if header is None:
        return Identity(None, _client_ip_key(request, s))
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Sign in again.", headers={"WWW-Authenticate": "Bearer"})
    try:
        user = verify_token(token.strip(), s)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            401, "Your sign-in has expired or is invalid. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return Identity(user, _hash(s, user))


def require_user(who: Annotated[Identity, Depends(identity)]) -> Identity:
    if not who.signed_in:
        raise HTTPException(401, "Sign in to do this.", headers={"WWW-Authenticate": "Bearer"})
    return who


Who = Annotated[Identity, Depends(identity)]
User = Annotated[Identity, Depends(require_user)]
