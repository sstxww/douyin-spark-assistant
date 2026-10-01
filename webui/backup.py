"""Password-protected backup. Cookies and deduplication keys never leave in plaintext."""
from __future__ import annotations
import base64
import json
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from spark.core import SafeError
from spark.web_config import validate_workspace

AAD = b"spark-web-backup-v2"


def key(password: str, salt: bytes) -> bytes:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise SafeError("BACKUP")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def encrypt(workspace: dict, password: str) -> dict:
    ws = validate_workspace(workspace)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    ciphertext = AESGCM(key(password, salt)).encrypt(
        nonce, json.dumps(ws, ensure_ascii=False).encode(), AAD)
    return {"format": "spark-backup-v2", "salt": base64.b64encode(salt).decode(),
            "nonce": base64.b64encode(nonce).decode(), "data": base64.b64encode(ciphertext).decode()}


def decrypt(backup: dict, password: str) -> dict:
    try:
        if backup.get("format") != "spark-backup-v2" or len(backup["data"]) > 4_000_000:
            raise SafeError("BACKUP")
        salt, nonce = (base64.b64decode(backup[n], validate=True) for n in ("salt", "nonce"))
        if len(salt) != 16 or len(nonce) != 12:
            raise SafeError("BACKUP")
        raw = AESGCM(key(password, salt)).decrypt(nonce, base64.b64decode(backup["data"], validate=True), AAD)
        ws = validate_workspace(json.loads(raw))
        ws["published"] = False  # Must republish/check after restoring.
        return ws
    except Exception:
        raise SafeError("BACKUP") from None
