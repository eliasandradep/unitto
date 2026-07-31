"""Criptografia (Fernet) para credenciais de terceiros salvas no banco, ex.: tokens de acesso da Meta."""
import os

from cryptography.fernet import Fernet


def _fernet():
    key = os.getenv('META_TOKEN_ENCRYPTION_KEY', '').strip()
    if not key:
        raise RuntimeError('META_TOKEN_ENCRYPTION_KEY não configurada.')
    return Fernet(key.encode())


def encrypt_token(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
