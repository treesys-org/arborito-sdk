"""NIP-44 v2 encrypt/decrypt (encrypt-to-self), parity with Arborito nostr-tools."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import os
from typing import Union

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

BytesLike = Union[bytes, bytearray, memoryview]

_MIN_PLAIN = 1
_MAX_PLAIN = 65535


def _hkdf_extract(ikm: bytes, salt: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def conversation_key(priv_hex: str, pub_hex: str) -> bytes:
    """ECDH shared X + HKDF-Extract(salt=nip44-v2), same as nostr-tools getConversationKey.

    Uses ``cryptography`` secp256k1 ECDH with the even-Y (``02``) lift of the
    x-only pubkey — same convention as nostr-tools / noble-secp256k1.
    """
    from cryptography.hazmat.primitives.asymmetric import ec

    priv_raw = bytes.fromhex(str(priv_hex).strip().lower())
    pub_x = str(pub_hex).strip().lower()
    if len(priv_raw) != 32 or len(pub_x) != 64:
        raise ValueError("NIP-44 expects 32-byte priv and 32-byte x-only pub hex")
    sk = ec.derive_private_key(int.from_bytes(priv_raw, "big"), ec.SECP256K1())
    peer = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256K1(),
        bytes.fromhex("02" + pub_x),
    )
    shared_x = sk.exchange(ec.ECDH(), peer)
    if len(shared_x) != 32:
        raise RuntimeError("NIP-44 ECDH did not return 32-byte shared X")
    return _hkdf_extract(shared_x, b"nip44-v2")


def _message_keys(conversation: bytes, nonce: bytes) -> tuple[bytes, bytes, bytes]:
    keys = HKDFExpand(algorithm=SHA256(), length=76, info=nonce).derive(conversation)
    return keys[:32], keys[32:44], keys[44:76]


def _calc_padded_len(length: int) -> int:
    if not isinstance(length, int) or length < 1:
        raise ValueError("expected positive integer")
    if length <= 32:
        return 32
    next_power = 1 << (math.floor(math.log2(length - 1)) + 1)
    chunk = 32 if next_power <= 256 else next_power // 8
    return chunk * (((length - 1) // chunk) + 1)


def _pad(plaintext: str) -> bytes:
    unpadded = plaintext.encode("utf-8")
    n = len(unpadded)
    if n < _MIN_PLAIN or n > _MAX_PLAIN:
        raise ValueError("invalid plaintext size: must be between 1 and 65535 bytes")
    prefix = n.to_bytes(2, "big")
    suffix = bytes(_calc_padded_len(n) - n)
    return prefix + unpadded + suffix


def _unpad(padded: bytes) -> str:
    if len(padded) < 2:
        raise ValueError("invalid padding")
    unpadded_len = int.from_bytes(padded[:2], "big")
    unpadded = padded[2 : 2 + unpadded_len]
    if (
        unpadded_len < _MIN_PLAIN
        or unpadded_len > _MAX_PLAIN
        or len(unpadded) != unpadded_len
        or len(padded) != 2 + _calc_padded_len(unpadded_len)
    ):
        raise ValueError("invalid padding")
    return unpadded.decode("utf-8")


def _hmac_aad(key: bytes, message: bytes, aad: bytes) -> bytes:
    if len(aad) != 32:
        raise ValueError("AAD associated data must be 32 bytes")
    return hmac.new(key, aad + message, hashlib.sha256).digest()


def _chacha20(key: bytes, nonce12: bytes, data: bytes) -> bytes:
    # cryptography ChaCha20 wants 16 bytes: 4-byte little-endian counter + 12-byte nonce.
    if len(nonce12) != 12:
        raise ValueError("ChaCha20 nonce must be 12 bytes")
    nonce16 = (0).to_bytes(4, "little") + nonce12
    cipher = Cipher(algorithms.ChaCha20(key, nonce16), mode=None)
    enc = cipher.encryptor()
    return enc.update(data) + enc.finalize()


def encrypt(plaintext: str, conversation: bytes, *, nonce: bytes | None = None) -> str:
    nonce = nonce if nonce is not None else os.urandom(32)
    if len(nonce) != 32:
        raise ValueError("nonce must be 32 bytes")
    chacha_key, chacha_nonce, hmac_key = _message_keys(conversation, nonce)
    ciphertext = _chacha20(chacha_key, chacha_nonce, _pad(plaintext))
    mac = _hmac_aad(hmac_key, ciphertext, nonce)
    payload = bytes([2]) + nonce + ciphertext + mac
    return base64.b64encode(payload).decode("ascii")


def decrypt(payload: str, conversation: bytes) -> str:
    raw = str(payload or "")
    if not raw or raw[0] == "#":
        raise ValueError("invalid NIP-44 payload")
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("invalid base64") from exc
    if len(data) < 99 or len(data) > 65603:
        raise ValueError("invalid data length")
    if data[0] != 2:
        raise ValueError(f"unknown encryption version {data[0]}")
    nonce = data[1:33]
    ciphertext = data[33:-32]
    mac = data[-32:]
    chacha_key, chacha_nonce, hmac_key = _message_keys(conversation, nonce)
    calculated = _hmac_aad(hmac_key, ciphertext, nonce)
    if not hmac.compare_digest(calculated, mac):
        raise ValueError("invalid MAC")
    return _unpad(_chacha20(chacha_key, chacha_nonce, ciphertext))


def encrypt_for_self(pair: dict[str, str], data: object) -> str:
    import json

    key = conversation_key(pair["priv"], pair["pub"])
    return encrypt(json.dumps(data, ensure_ascii=False, separators=(",", ":")), key)


def decrypt_for_self(pair: dict[str, str], encrypted: str) -> object:
    import json

    key = conversation_key(pair["priv"], pair["pub"])
    return json.loads(decrypt(str(encrypted), key))


def pack_for_sync(pair: dict[str, str], data: object, *, max_plain: int = 10000) -> dict[str, object]:
    """Slice + NIP-44 encrypt (parity with packPrivateTreeForSync)."""
    import json

    from .bundle_publish import split_utf8_chunks

    key = conversation_key(pair["priv"], pair["pub"])
    plain = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    slices = split_utf8_chunks(plain, max_plain)
    parts = [encrypt(slice_, key) for slice_ in slices]
    manifest = json.dumps({"v": 2, "n": len(parts)}, separators=(",", ":"))
    return {"manifestCiphertext": encrypt(manifest, key), "partCiphertexts": parts}


def unpack_from_sync(
    pair: dict[str, str],
    manifest_ciphertext: str,
    part_ciphertexts: list[str],
) -> object:
    import json

    key = conversation_key(pair["priv"], pair["pub"])
    parts = list(part_ciphertexts or [])
    if not manifest_ciphertext or not parts:
        raise ValueError("Missing private tree sync payload.")
    # Manifest is encrypted for integrity; n is taken from parts length when assembling.
    decrypt(str(manifest_ciphertext), key)
    json_body = "".join(decrypt(str(ct), key) for ct in parts)
    return json.loads(json_body)
