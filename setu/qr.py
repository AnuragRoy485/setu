"""Minimal QR code encoder (byte mode, error levels L and M, versions 1-20).

Pure standard library, written for Setu so QR codes work anywhere Python does.
Output helpers: terminal text, SVG and PNG.
"""
from __future__ import annotations

import struct
import zlib
from typing import List, Tuple

# (blocks, total codewords per block, data codewords per block) per group, versions 1..20
_BLOCKS = {
    "L": [((1, 26, 19),), ((1, 44, 34),), ((1, 70, 55),), ((1, 100, 80),), ((1, 134, 108),),
          ((2, 86, 68),), ((2, 98, 78),), ((2, 121, 97),), ((2, 146, 116),),
          ((2, 86, 68), (2, 87, 69)), ((4, 101, 81),), ((2, 116, 92), (2, 117, 93)),
          ((4, 133, 107),), ((3, 145, 115), (1, 146, 116)), ((5, 109, 87), (1, 110, 88)),
          ((5, 122, 98), (1, 123, 99)), ((1, 135, 107), (5, 136, 108)),
          ((5, 150, 120), (1, 151, 121)), ((3, 141, 113), (4, 142, 114)),
          ((3, 135, 107), (5, 136, 108))],
    "M": [((1, 26, 16),), ((1, 44, 28),), ((1, 70, 44),), ((2, 50, 32),), ((2, 67, 43),),
          ((4, 43, 27),), ((4, 49, 31),), ((2, 60, 38), (2, 61, 39)),
          ((3, 58, 36), (2, 59, 37)), ((4, 69, 43), (1, 70, 44)),
          ((1, 80, 50), (4, 81, 51)), ((6, 58, 36), (2, 59, 37)),
          ((8, 59, 37), (1, 60, 38)), ((4, 64, 40), (5, 65, 41)),
          ((5, 65, 41), (5, 66, 42)), ((7, 73, 45), (3, 74, 46)),
          ((10, 74, 46), (1, 75, 47)), ((9, 69, 43), (4, 70, 44)),
          ((3, 70, 44), (11, 71, 45)), ((3, 67, 41), (13, 68, 42))],
}
_FORMAT_BITS = {"L": 1, "M": 0}

# --- Reed-Solomon over GF(256), polynomial 0x11d ---------------------------------
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> List[int]:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _gmul(c, _EXP[i])
        poly = nxt
    return poly


def _rs_remainder(data: List[int], degree: int) -> List[int]:
    gen = _rs_generator(degree)
    rem = [0] * degree
    for b in data:
        factor = b ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(degree):
            rem[i] ^= _gmul(gen[i + 1], factor)
    return rem


# --- Encoding --------------------------------------------------------------------
def _data_capacity(version: int, ec: str) -> int:
    return sum(n * d for n, _t, d in _BLOCKS[ec][version - 1])


def _make_codewords(data: bytes, version: int, ec: str) -> List[int]:
    cc_bits = 8 if version < 10 else 16
    bits: List[int] = []

    def put(val: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            bits.append((val >> i) & 1)

    put(0b0100, 4)
    put(len(data), cc_bits)
    for b in data:
        put(b, 8)
    cap = _data_capacity(version, ec) * 8
    put(0, min(4, cap - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    cw = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(cw) < cap // 8:
        cw.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC
    # split into blocks and add error correction
    blocks, eccs = [], []
    pos = 0
    ecc_len = 0
    for n, total, nd in _BLOCKS[ec][version - 1]:
        ecc_len = total - nd
        for _ in range(n):
            blk = cw[pos:pos + nd]
            pos += nd
            blocks.append(blk)
            eccs.append(_rs_remainder(blk, ecc_len))
    out: List[int] = []
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ecc_len):
        for e in eccs:
            out.append(e[i])
    return out


def _align_positions(version: int) -> List[int]:
    if version == 1:
        return []
    size = 17 + 4 * version
    n = version // 7 + 2
    step = 26 if version == 32 else (version * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    res = [size - 7 - i * step for i in range(n - 1)] + [6]
    return list(reversed(res))


_MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


class _Builder:
    def __init__(self, version: int, ec: str):
        self.v, self.ec = version, ec
        self.n = 17 + 4 * version
        self.m = [[False] * self.n for _ in range(self.n)]
        self.fn = [[False] * self.n for _ in range(self.n)]
        self._patterns()

    def _set(self, x: int, y: int, dark: bool) -> None:
        self.m[y][x] = dark
        self.fn[y][x] = True

    def _patterns(self) -> None:
        n = self.n
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        d = max(abs(dx), abs(dy))
                        self._set(x, y, d not in (2, 4))
        pos = _align_positions(self.v)
        for i, cy in enumerate(pos):
            for j, cx in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self._format(0)  # reserve
        if self.v >= 7:
            rem = self.v
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.v << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self._set(a, b, bit)
                self._set(b, a, bit)

    def _format(self, mask: int) -> None:
        n = self.n
        data = _FORMAT_BITS[self.ec] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        g = lambda i: (bits >> i) & 1 == 1  # noqa: E731
        for i in range(0, 6):
            self._set(8, i, g(i))
        self._set(8, 7, g(6))
        self._set(8, 8, g(7))
        self._set(7, 8, g(8))
        for i in range(9, 15):
            self._set(14 - i, 8, g(i))
        for i in range(0, 8):
            self._set(n - 1 - i, 8, g(i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, g(i))
        self._set(8, n - 8, True)

    def place(self, codewords: List[int]) -> None:
        n = self.n
        bits = [(cw >> (7 - i)) & 1 for cw in codewords for i in range(8)]
        k = 0
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and k < len(bits):
                        self.m[y][x] = bits[k] == 1
                        k += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        f = _MASKS[mask]
        for y in range(self.n):
            for x in range(self.n):
                if not self.fn[y][x] and f(x, y):
                    self.m[y][x] = not self.m[y][x]

    def penalty(self) -> int:
        n, m = self.n, self.m
        score = 0
        for grid in (m, [list(r) for r in zip(*m)]):
            for row in grid:
                run, prev = 1, row[0]
                for c in row[1:]:
                    if c == prev:
                        run += 1
                    else:
                        if run >= 5:
                            score += run - 2
                        run, prev = 1, c
                if run >= 5:
                    score += run - 2
                s = "".join("1" if c else "0" for c in row)
                for pat in ("10111010000", "00001011101"):
                    i = s.find(pat)
                    while i != -1:
                        score += 40
                        i = s.find(pat, i + 1)
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(c for r in m for c in r)
        k = abs(dark * 20 - n * n * 10) // (n * n)
        return score + k * 10


def make(data, ec: str = "L") -> List[List[bool]]:
    """Return the QR matrix (list of rows, True = dark) for text or bytes."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if ec not in _BLOCKS:
        raise ValueError("ec must be 'L' or 'M'")
    for version in range(1, 21):
        cc = 8 if version < 10 else 16
        if 4 + cc + 8 * len(data) <= _data_capacity(version, ec) * 8:
            break
    else:
        raise ValueError("data too long for QR versions 1-20 (%d bytes)" % len(data))
    cw = _make_codewords(data, version, ec)
    best: Tuple[int, int, List[List[bool]]] = (10 ** 9, 0, [])
    for mask in range(8):
        b = _Builder(version, ec)
        b.place(cw)
        b.apply_mask(mask)
        b._format(mask)
        p = b.penalty()
        if p < best[0]:
            best = (p, mask, [row[:] for row in b.m])
    return best[2]


# --- Renderers -------------------------------------------------------------------
def to_terminal(matrix: List[List[bool]], border: int = 2) -> str:
    """Black-on-white half-block rendering that scans on dark and light terminals."""
    n = len(matrix)
    size = n + 2 * border

    def dark(x: int, y: int) -> bool:
        x -= border
        y -= border
        return 0 <= x < n and 0 <= y < n and matrix[y][x]

    lines = []
    for y in range(0, size, 2):
        row = []
        for x in range(size):
            t, b = dark(x, y), dark(x, y + 1)
            row.append("█" if t and b else "▀" if t else "▄" if b else " ")
        lines.append("\x1b[30;47m" + "".join(row) + "\x1b[0m")
    return "\n".join(lines)


def to_svg(matrix: List[List[bool]], border: int = 4, scale: int = 1) -> str:
    n = len(matrix)
    size = n + 2 * border
    path = []
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            if row[x]:
                s = x
                while x < n and row[x]:
                    x += 1
                path.append("M%d,%dh%dv1h-%dz" % (s + border, y + border, x - s, x - s))
            else:
                x += 1
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
            'shape-rendering="crispEdges"><rect width="100%%" height="100%%" fill="#fff"/>'
            '<path d="%s" fill="#000"/></svg>' % (size, size, size * scale, size * scale, "".join(path)))


def to_png(matrix: List[List[bool]], scale: int = 8, border: int = 4) -> bytes:
    n = len(matrix)
    size = (n + 2 * border) * scale
    rows = []
    for py in range(size):
        y = py // scale - border
        line = bytearray([0])
        for px in range(size):
            x = px // scale - border
            d = 0 <= x < n and 0 <= y < n and matrix[y][x]
            line.append(0 if d else 255)
        rows.append(bytes(line))
    raw = b"".join(rows)

    def chunk(tag: bytes, body: bytes) -> bytes:
        c = struct.pack(">I", len(body)) + tag + body
        return c + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
