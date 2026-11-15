"""WireGuard key handling in pure Python (X25519 per RFC 7748).

Lets Setu create keys on any machine, with or without wireguard-tools installed.
"""
from __future__ import annotations

import base64
import os

_P = 2 ** 255 - 19
_A24 = 121665


def x25519(k: bytes, u: bytes) -> bytes:
    """Scalar multiplication on Curve25519 (RFC 7748, section 5)."""
    kb = bytearray(k)
    kb[0] &= 248
    kb[31] &= 127
    kb[31] |= 64
    scalar = int.from_bytes(kb, "little")
    x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in reversed(range(255)):
        kt = (scalar >> t) & 1
        swap ^= kt
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = pow(da + cb, 2, _P)
        z3 = x1 * pow(da - cb, 2, _P) % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


_BASE = (9).to_bytes(32, "little")


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text.strip(), validate=True)


def genkey() -> str:
    """New private key, clamped like `wg genkey`."""
    k = bytearray(os.urandom(32))
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return b64(bytes(k))


def pubkey(private_b64: str) -> str:
    return b64(x25519(unb64(private_b64), _BASE))


def genpsk() -> str:
    return b64(os.urandom(32))


def valid_key(text: str) -> bool:
    try:
        return len(unb64(text)) == 32
    except Exception:
        return False
