import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _derive_fernet_key(raw_key: str) -> bytes:
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(plain_text: str, encryption_key: str) -> str:
    fernet = Fernet(_derive_fernet_key(encryption_key))
    return fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_value(cipher_text: str, encryption_key: str) -> str:
    fernet = Fernet(_derive_fernet_key(encryption_key))
    try:
        return fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt stored secret") from exc
