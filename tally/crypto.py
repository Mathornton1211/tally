"""Plaid access tokens at rest. HANDOFF invariant 5.

The key lives in the environment, never in the database, so a DB dump alone
cannot be used to pull transactions.
"""
from cryptography.fernet import Fernet


class TokenBox:
    def __init__(self, key: str):
        self._f = Fernet(key.encode())

    def seal(self, token: str) -> bytes:
        return self._f.encrypt(token.encode())

    def open(self, blob: bytes, ttl: int | None = None) -> str:
        """`ttl` in seconds rejects a token older than that. Fernet stamps every
        token with its creation time, so session expiry needs nothing else."""
        return self._f.decrypt(bytes(blob), ttl=ttl).decode()


def new_key() -> str:
    return Fernet.generate_key().decode()
