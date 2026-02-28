"""Fernet encryption/decryption for credentials."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet


def _key_path() -> Path:
    return Path.home() / ".job-agent" / "fernet.key"


def generate_key() -> bytes:
    """Generate a new Fernet key and save it securely."""
    key = Fernet.generate_key()
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


def load_key() -> bytes:
    """Load the Fernet key, generating one if it doesn't exist."""
    path = _key_path()
    if not path.exists():
        return generate_key()
    return path.read_bytes()


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return the base64-encoded ciphertext."""
    f = Fernet(load_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext string."""
    f = Fernet(load_key())
    return f.decrypt(ciphertext.encode()).decode()
