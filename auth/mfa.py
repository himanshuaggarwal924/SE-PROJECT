"""
auth/mfa.py - Optional TOTP multi-factor authentication (Phase 7).

Fully local: the secret is generated here, shown once as a QR code to scan
with any authenticator app (Google Authenticator, Microsoft Authenticator,
Aegis...), and stored in auth/users.yaml (git-ignored). No email, no SMS.
"""

import io

import pyotp
import qrcode

ISSUER = "FinReq Agents"


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def qr_png(uri: str) -> bytes:
    image = qrcode.make(uri)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def verify(secret: str, code: str) -> bool:
    """True if the 6-digit code is valid now (±30 s for clock drift)."""
    code = (code or "").strip().replace(" ", "")
    return bool(secret) and code.isdigit() and pyotp.TOTP(secret).verify(code, valid_window=1)
