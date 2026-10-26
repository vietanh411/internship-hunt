"""Encryption of sensitive personal data at rest (Fernet / AES-128-CBC + HMAC)."""
from __future__ import annotations

import json
import logging

from cryptography.fernet import Fernet, InvalidToken

from hunt.config import get_settings

log = logging.getLogger(__name__)

PLAINTEXT_PREFIX = "plain:"


def generate_key() -> str:
    return Fernet.generate_key().decode()


def encryption_enabled() -> bool:
    return bool(get_settings().secret_key)


def _fernet() -> Fernet | None:
    key = get_settings().secret_key
    return Fernet(key.encode()) if key else None


def encrypt_json(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True)
    f = _fernet()
    if f is None:
        return PLAINTEXT_PREFIX + raw
    return f.encrypt(raw.encode()).decode()


def decrypt_json(blob: str | None) -> dict:
    if not blob:
        return {}
    if blob.startswith(PLAINTEXT_PREFIX):
        return json.loads(blob[len(PLAINTEXT_PREFIX):])
    f = _fernet()
    if f is None:
        log.error("Encrypted profile data present but HUNT_SECRET_KEY is not set")
        return {}
    try:
        return json.loads(f.decrypt(blob.encode()))
    except InvalidToken:
        log.error("HUNT_SECRET_KEY does not match the key used to encrypt profile data")
        return {}
