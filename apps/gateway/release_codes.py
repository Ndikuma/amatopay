"""Authenticated encryption for payer delivery codes on RTP collections."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _configured_keys():
    if settings.RELEASE_CODE_ENCRYPTION_KEYS:
        return settings.RELEASE_CODE_ENCRYPTION_KEYS
    # Development/test fallback. Production settings reject a missing key at startup.
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return [base64.urlsafe_b64encode(digest).decode()]


def _cipher():
    try:
        return MultiFernet(
            [Fernet(key.encode()) for key in _configured_keys()]
        )
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            "RELEASE_CODE_ENCRYPTION_KEYS contains an invalid Fernet key."
        ) from exc


def encrypt_release_code(code):
    return _cipher().encrypt(code.encode("ascii")).decode("ascii")


def decrypt_release_code(ciphertext):
    if not ciphertext:
        raise ValueError("This RTP collection has no available delivery code.")
    try:
        return _cipher().decrypt(ciphertext.encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        raise ValueError("The stored RTP delivery code cannot be decrypted.") from exc


if __name__ == "__main__":
    print(Fernet.generate_key().decode("ascii"))
