"""BIP-340 Schnorr (secp256k1) — NIP-01 signing without native ``secp256k1`` / ``coincurve``.

Adapted from the BIP-340 reference implementation (bitcoin/bips), trimmed to
keygen + sign + verify used by Arborito Nostr publish / Care sync.
"""

from __future__ import annotations

import hashlib
from typing import Optional, Tuple

p = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)

Point = Tuple[int, int]


def tagged_hash(tag: str, msg: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(tag_hash + tag_hash + msg).digest()


def _is_infinite(P: Optional[Point]) -> bool:
    return P is None


def _x(P: Point) -> int:
    return P[0]


def _y(P: Point) -> int:
    return P[1]


def _point_add(P1: Optional[Point], P2: Optional[Point]) -> Optional[Point]:
    if P1 is None:
        return P2
    if P2 is None:
        return P1
    if (_x(P1) == _x(P2)) and (_y(P1) != _y(P2)):
        return None
    if P1 == P2:
        lam = (3 * _x(P1) * _x(P1) * pow(2 * _y(P1), p - 2, p)) % p
    else:
        lam = ((_y(P2) - _y(P1)) * pow(_x(P2) - _x(P1), p - 2, p)) % p
    x3 = (lam * lam - _x(P1) - _x(P2)) % p
    return (x3, (lam * (_x(P1) - x3) - _y(P1)) % p)


def _point_mul(P: Optional[Point], scalar: int) -> Optional[Point]:
    R: Optional[Point] = None
    for i in range(256):
        if (scalar >> i) & 1:
            R = _point_add(R, P)
        P = _point_add(P, P)
    return R


def _bytes_from_int(x: int) -> bytes:
    return x.to_bytes(32, byteorder="big")


def _bytes_from_point(P: Point) -> bytes:
    return _bytes_from_int(_x(P))


def _xor_bytes(b0: bytes, b1: bytes) -> bytes:
    return bytes(x ^ y for (x, y) in zip(b0, b1))


def _lift_x(x: int) -> Optional[Point]:
    if x >= p:
        return None
    y_sq = (pow(x, 3, p) + 7) % p
    y = pow(y_sq, (p + 1) // 4, p)
    if pow(y, 2, p) != y_sq:
        return None
    return (x, y if y & 1 == 0 else p - y)


def _int_from_bytes(b: bytes) -> int:
    return int.from_bytes(b, byteorder="big")


def _has_even_y(P: Point) -> bool:
    return _y(P) % 2 == 0


def pubkey_gen(seckey: bytes) -> bytes:
    d0 = _int_from_bytes(seckey)
    if not (1 <= d0 <= n - 1):
        raise ValueError("The secret key must be an integer in the range 1..n-1.")
    P = _point_mul(G, d0)
    assert P is not None
    return _bytes_from_point(P)


def schnorr_sign(msg: bytes, seckey: bytes, aux_rand: bytes) -> bytes:
    d0 = _int_from_bytes(seckey)
    if not (1 <= d0 <= n - 1):
        raise ValueError("The secret key must be an integer in the range 1..n-1.")
    if len(aux_rand) != 32:
        raise ValueError(f"aux_rand must be 32 bytes instead of {len(aux_rand)}.")
    P = _point_mul(G, d0)
    assert P is not None
    d = d0 if _has_even_y(P) else n - d0
    t = _xor_bytes(_bytes_from_int(d), tagged_hash("BIP0340/aux", aux_rand))
    k0 = _int_from_bytes(tagged_hash("BIP0340/nonce", t + _bytes_from_point(P) + msg)) % n
    if k0 == 0:
        raise RuntimeError("Failure. This happens only with negligible probability.")
    R = _point_mul(G, k0)
    assert R is not None
    k = n - k0 if not _has_even_y(R) else k0
    e = (
        _int_from_bytes(
            tagged_hash("BIP0340/challenge", _bytes_from_point(R) + _bytes_from_point(P) + msg)
        )
        % n
    )
    sig = _bytes_from_point(R) + _bytes_from_int((k + e * d) % n)
    if not schnorr_verify(msg, _bytes_from_point(P), sig):
        raise RuntimeError("The created signature does not pass verification.")
    return sig


def schnorr_verify(msg: bytes, pubkey: bytes, sig: bytes) -> bool:
    if len(pubkey) != 32:
        raise ValueError("The public key must be a 32-byte array.")
    if len(sig) != 64:
        raise ValueError("The signature must be a 64-byte array.")
    P = _lift_x(_int_from_bytes(pubkey))
    r = _int_from_bytes(sig[0:32])
    s = _int_from_bytes(sig[32:64])
    if (P is None) or (r >= p) or (s >= n):
        return False
    e = _int_from_bytes(tagged_hash("BIP0340/challenge", sig[0:32] + pubkey + msg)) % n
    R = _point_add(_point_mul(G, s), _point_mul(P, n - e))
    if (R is None) or (not _has_even_y(R)) or (_x(R) != r):
        return False
    return True
