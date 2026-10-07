# SPDX-License-Identifier: MIT
# Vendored from sambanks/octabam 36a056c5 tools/ghidra/depack.py (MIT, Copyright (c) 2026 Sam Banks). Unchanged below.
"""Unpack a GKA3 stream: the inverse of tools/remix/pack.pack.

The lint reads a built image on its own, and the DRAM runtimes it jumps
into travel packed in the appended payloads. This decoder follows the bit
layout `pack` writes:
- tag bits are read MSB first, a byte at a time;
- the data bytes follow the tag byte whose bit they belong to;
- tag bit 1 is a literal;
- tag bit 0 is a match. Its gamma offset-high value is 2 for "the last
  offset again"; otherwise a low byte follows;
- gamma 0x01000002 ends the stream.
"""

MAGIC = b"GKA3"
END = 0x01000002
MAX_OFFSET_FOR_LEN2 = 0x0D00


def depack(stream: bytes) -> bytes:
    """`stream` = MAGIC + u32 BE raw length + the packed bits."""
    if stream[:4] != MAGIC:
        raise ValueError("not a GKA3 stream")
    want = int.from_bytes(stream[4:8], "big")
    s, pos = stream, 8
    tag, left = 0, 0
    out = bytearray()

    def bit():
        nonlocal tag, left, pos
        if not left:
            tag, left = s[pos], 8
            pos += 1
        left -= 1
        return (tag >> left) & 1

    def byte():
        nonlocal pos
        pos += 1
        return s[pos - 1]

    def gamma():
        v = 1
        while True:
            v = (v << 1) | bit()
            if bit():
                return v

    last = None
    while True:
        if bit():
            out.append(byte())
            continue
        g = gamma()
        if g == 2:
            if last is None:
                raise ValueError("offset reuse before any match")
            off = last
        else:
            low = byte()
            if g == END and low == 0xFF:
                break
            off = g * 0x100 + low - 0x300 + 1
        b1, b2 = bit(), bit()
        n = {(0, 1): 1, (1, 0): 2, (1, 1): 3}.get((b1, b2))
        if n is None:
            n = gamma() + 2
        n += 2 if off > MAX_OFFSET_FOR_LEN2 else 1
        if off > len(out):
            raise ValueError(f"match offset {off} before the start of the output")
        for _ in range(n):
            out.append(out[-off])
        last = off
    if len(out) != want:
        raise ValueError(f"unpacked {len(out)} bytes, the header says {want}")
    return bytes(out)
