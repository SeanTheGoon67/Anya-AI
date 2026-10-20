#!/usr/bin/env python
"""
qr.py — a tiny, dependency-free QR Code encoder (standard library only).

Anya uses this to show a scannable link for phone access without pulling in a
third-party package. It supports byte mode, all 40 versions, all four error
correction levels, automatic version + mask selection, and renders straight to a
PNG (8-bit greyscale, no external libraries).

    import qr
    png_bytes = qr.png("http://192.168.1.5:8091/?k=abc", scale=6)

The algorithm follows the public QR Code specification (ISO/IEC 18004).
"""
from __future__ import annotations

import struct
import zlib

# --- error correction levels, indexed the way the spec's tables are ----------
# order used everywhere below: 0=Low, 1=Medium, 2=Quartile, 3=High
ECL_ORDER = {"L": 0, "M": 1, "Q": 2, "H": 3}
# the 3-bit value that goes into the format information (note: L=1, M=0, Q=3, H=2)
ECL_FORMAT_BITS = {0: 1, 1: 0, 2: 3, 3: 2}

# ECC codewords per block, [ecl][version] (version 0 is a pad slot)
_ECC_PER_BLOCK = [
    [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28,
     28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26,
     26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26,
     30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26,
     28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
]
# number of error correction blocks, [ecl][version]
_NUM_BLOCKS = [
    [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7,
     8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14,
     16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21,
     20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    [-1, 1, 1, 2, 4, 4, 4, 5, 5, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25,
     25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81],
]
# how many bits of "character count" the byte-mode header carries, per version
_CHAR_COUNT_BITS = [8] * 10 + [16] * 31   # index by version (1..40)


def _num_raw_data_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        numalign = ver // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if ver >= 7:
            result -= 36
    return result


def _num_data_codewords(ver: int, ecl: int) -> int:
    return _num_raw_data_modules(ver) // 8 - _ECC_PER_BLOCK[ecl][ver] * _NUM_BLOCKS[ecl][ver]


def _alignment_positions(ver: int) -> list:
    if ver == 1:
        return []
    numalign = ver // 7 + 2
    step = 26 if ver == 32 else (ver * 4 + numalign * 2 + 1) // (numalign * 2 - 2) * 2
    result = [6]
    pos = ver * 4 + 10
    for _ in range(numalign - 1):
        result.insert(1, pos)
        pos -= step
    return result


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree: int) -> list:
    result = [0] * degree
    result[degree - 1] = 1
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list, divisor: list) -> list:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _get_bit(x: int, i: int) -> bool:
    return ((x >> i) & 1) != 0


class _QR:
    def __init__(self, ver: int, ecl: int):
        self.ver = ver
        self.ecl = ecl
        self.size = ver * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.isfunc = [[False] * self.size for _ in range(self.size)]

    def _set_func(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self.isfunc[y][x] = True

    # -- function patterns -------------------------------------------------
    def _draw_finder(self, x: int, y: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                dist = max(abs(dx), abs(dy))
                xx, yy = x + dx, y + dy
                if 0 <= xx < self.size and 0 <= yy < self.size:
                    self._set_func(xx, yy, dist != 2 and dist != 4)

    def _draw_alignment(self, x: int, y: int) -> None:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self._set_func(x + dx, y + dy, max(abs(dx), abs(dy)) != 1)

    def _draw_format_bits(self, mask: int) -> None:
        data = ECL_FORMAT_BITS[self.ecl] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        for i in range(0, 6):
            self._set_func(8, i, _get_bit(bits, i))
        self._set_func(8, 7, _get_bit(bits, 6))
        self._set_func(8, 8, _get_bit(bits, 7))
        self._set_func(7, 8, _get_bit(bits, 8))
        for i in range(9, 15):
            self._set_func(14 - i, 8, _get_bit(bits, i))
        for i in range(0, 8):
            self._set_func(self.size - 1 - i, 8, _get_bit(bits, i))
        for i in range(8, 15):
            self._set_func(8, self.size - 15 + i, _get_bit(bits, i))
        self._set_func(8, self.size - 8, True)   # the always-dark module

    def _draw_function_patterns(self) -> None:
        for i in range(self.size):
            self._set_func(6, i, i % 2 == 0)
            self._set_func(i, 6, i % 2 == 0)
        self._draw_finder(3, 3)
        self._draw_finder(self.size - 4, 3)
        self._draw_finder(3, self.size - 4)
        align = _alignment_positions(self.ver)
        n = len(align)
        for i in range(n):
            for j in range(n):
                if (i == 0 and j == 0) or (i == 0 and j == n - 1) or (i == n - 1 and j == 0):
                    continue
                self._draw_alignment(align[i], align[j])
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = _get_bit(bits, i)
                a, b = self.size - 11 + i % 3, i // 3
                self._set_func(a, b, bit)
                self._set_func(b, a, bit)
        self._draw_format_bits(0)   # reserves those cells; redrawn per mask

    # -- data --------------------------------------------------------------
    def _draw_codewords(self, data: list) -> None:
        i = 0
        n = len(data) * 8
        for right in range(self.size - 1, 0, -2):
            if right <= 6:
                right -= 1      # skip the vertical timing column (x == 6)
            for vert in range(self.size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = (self.size - 1 - vert) if upward else vert
                    if not self.isfunc[y][x] and i < n:
                        self.modules[y][x] = _get_bit(data[i >> 3], 7 - (i & 7))
                        i += 1

    def _apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.isfunc[y][x]:
                    continue
                invert = False
                if mask == 0:
                    invert = (x + y) % 2 == 0
                elif mask == 1:
                    invert = y % 2 == 0
                elif mask == 2:
                    invert = x % 3 == 0
                elif mask == 3:
                    invert = (x + y) % 3 == 0
                elif mask == 4:
                    invert = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    invert = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    invert = (x * y % 2 + x * y % 3) % 2 == 0
                elif mask == 7:
                    invert = ((x + y) % 2 + x * y % 3) % 2 == 0
                if invert:
                    self.modules[y][x] = not self.modules[y][x]

    def _penalty(self) -> int:
        size = self.size
        result = 0
        # rule 1: runs of five or more like modules in a row/column
        for y in range(size):
            run = 0
            runcolor = False
            for x in range(size):
                if x == 0 or self.modules[y][x] != runcolor:
                    runcolor = self.modules[y][x]
                    run = 1
                else:
                    run += 1
                    if run == 5:
                        result += 3
                    elif run > 5:
                        result += 1
        for x in range(size):
            run = 0
            runcolor = False
            for y in range(size):
                if y == 0 or self.modules[y][x] != runcolor:
                    runcolor = self.modules[y][x]
                    run = 1
                else:
                    run += 1
                    if run == 5:
                        result += 3
                    elif run > 5:
                        result += 1
        # rule 2: 2x2 blocks of the same colour
        for y in range(size - 1):
            for x in range(size - 1):
                c = self.modules[y][x]
                if c == self.modules[y][x + 1] == self.modules[y + 1][x] == self.modules[y + 1][x + 1]:
                    result += 3
        # rule 3: finder-like patterns 1:1:3:1:1 with 4 light modules beside them
        for y in range(size):
            for x in range(size):
                if x + 6 < size:
                    pat = [self.modules[y][x + k] for k in range(7)]
                    light_before = (x >= 4 and all(not self.modules[y][x - 1 - k] for k in range(4))) \
                        or (x + 10 < size and all(not self.modules[y][x + 7 + k] for k in range(4)))
                    if pat == [True, False, True, True, True, False, True] and light_before:
                        result += 40
                if y + 6 < size:
                    pat = [self.modules[y + k][x] for k in range(7)]
                    light_before = (y >= 4 and all(not self.modules[y - 1 - k][x] for k in range(4))) \
                        or (y + 10 < size and all(not self.modules[y + 7 + k][x] for k in range(4)))
                    if pat == [True, False, True, True, True, False, True] and light_before:
                        result += 40
        # rule 4: balance of dark/light modules
        dark = sum(1 for row in self.modules for c in row if c)
        total = size * size
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        result += k * 10
        return result


def _encode_data(text: bytes, ver: int, ecl: int) -> list:
    """Return the full codeword sequence (data + ecc) for byte mode."""
    capacity = _num_data_codewords(ver, ecl)
    # 4-bit mode indicator (0100) + character count + payload
    bits = [0, 1, 0, 0]
    cc = _CHAR_COUNT_BITS[ver]
    n = len(text)
    for i in range(cc - 1, -1, -1):
        bits.append((n >> i) & 1)
    for b in text:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    # terminator (up to 4 zero bits) then pad to a whole codeword
    for _ in range(min(4, capacity * 8 - len(bits))):
        bits.append(0)
    while len(bits) % 8 != 0:
        bits.append(0)
    # pad codewords 0xEC / 0x11
    pad = (0xEC, 0x11)
    i = 0
    while len(bits) < capacity * 8:
        byte = pad[i % 2]
        for j in range(7, -1, -1):
            bits.append((byte >> j) & 1)
        i += 1
    datawords = [int("".join(str(b) for b in bits[k:k + 8]), 2) for k in range(0, len(bits), 8)]
    return _add_ecc(datawords, ver, ecl)


def _add_ecc(data: list, ver: int, ecl: int) -> list:
    numblocks = _NUM_BLOCKS[ecl][ver]
    blockecclen = _ECC_PER_BLOCK[ecl][ver]
    rawcodewords = _num_raw_data_modules(ver) // 8
    numshortblocks = numblocks - rawcodewords % numblocks
    shortblocklen = rawcodewords // numblocks
    divisor = _rs_divisor(blockecclen)
    blocks: list = []
    k = 0
    for i in range(numblocks):
        datlen = shortblocklen - blockecclen + (0 if i < numshortblocks else 1)
        dat = list(data[k:k + datlen])
        k += datlen
        ecc = _rs_remainder(dat, divisor)
        if i < numshortblocks:
            dat.append(0)
        blocks.append(dat + ecc)
    result: list = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortblocklen - blockecclen or j >= numshortblocks:
                result.append(blk[i])
    return result


def matrix(text: str, ecl: str = "M", mask: int | None = None) -> list:
    """Encode `text` and return a size x size list of 0/1 rows (1 = dark)."""
    data = text.encode("utf-8")
    level = ECL_ORDER.get(str(ecl).upper(), 1)
    # reject payloads too big for QR's biggest version
    ver = 1
    while ver <= 40 and len(data) > _num_data_codewords(ver, level) - _byte_header_words(ver):
        ver += 1
    if ver > 40:
        raise ValueError("text too long for a QR code")
    codewords = _encode_data(data, ver, level)

    best_mask = 0
    best_penalty = None
    best_modules = None
    for m in range(8):
        q = _QR(ver, level)
        q._draw_function_patterns()
        q._draw_codewords(codewords)
        q._apply_mask(m)
        q._draw_format_bits(m)
        if mask is not None and m != mask:
            continue
        p = q._penalty()
        if best_penalty is None or p < best_penalty:
            best_penalty = p
            best_mask = m
            best_modules = [row[:] for row in q.modules]
        if mask is not None:
            break
    if best_modules is None:
        raise ValueError("no mask produced (mask out of range)")
    return [[1 if c else 0 for c in row] for row in best_modules]


def _byte_header_words(ver: int) -> int:
    """Codewords consumed by the 4-bit mode + character-count header."""
    return (4 + _CHAR_COUNT_BITS[ver] + 7) // 8


def png(text: str, scale: int = 6, border: int = 4, ecl: str = "M") -> bytes:
    """Render `text` as a QR code PNG (greyscale, no dependencies)."""
    m = matrix(text, ecl=ecl)
    n = len(m)
    dim = (n + border * 2) * scale
    # build raw scanlines, each prefixed with filter type 0
    rows = bytearray()
    white = 255
    black = 0
    for py in range(dim):
        my = py // scale - border
        rows.append(0)
        for px in range(dim):
            mx = px // scale - border
            if 0 <= mx < n and 0 <= my < n and m[my][mx]:
                rows.append(black)
            else:
                rows.append(white)
    return _png_grey8(dim, dim, bytes(rows))


def _png_grey8(width: int, height: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":       # tiny manual check:  python qr.py "text"
    import sys
    out = png(sys.argv[1] if len(sys.argv) > 1 else "https://example.com")
    with open("qr_check.png", "wb") as fh:
        fh.write(out)
    print(f"wrote qr_check.png ({len(out)} bytes)")
