#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
seal()'s stock-SRAM check and the packed DRAM payload (tools/kyoti_status.py, 2026-11-19).

The check refuses any changed or appended word pointing into the stock timestretch task's SRAM
(0x80006924..0x80007873). KYOTI V1.8BC tripped it by coincidence: 0x800076cd at 0x40119664, inside the
COMPRESSED DRAM stream tools/dram/ appends -- bit-stream bytes, not code. The check now skips each packed
blob and scans the runtime it depacks to. Three synthetic images (stock + a loader-style table + one blob):

  1. a stream that holds 80 00 70 cd (two literals, a match's offset byte, a literal) while its runtime
     does not: the old scan (every even offset of the image) hits it, the new one does not;
  2. a runtime that holds 0x80006a40: the new scan reports it at its DRAM address (the old one saw
     only packed bytes);
  3. the same runtime without the table entry: an 'OCTAGKA3' the loader does not list is not taken
     for a payload (the bytes are scanned as they are).

Then, for every image path given on the command line, the old and the new verdict side by side.

    python3 tools/kyoti_status_sram_test.py [out/KYOTI/mainos_kyoti_v1.8bc.bin ...]
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "dram"))
import kyoti_status as ks          # noqa: E402
import pack, depack                # noqa: E402

with open(ks._STOCK, "rb") as f:
    STOCK = f.read()
LOADER_OFF = ks._LOADER_AT - ks._IMG_BASE
fails = []


def check(ok, what):
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        fails.append(what)


def old_refs(img):
    """The check as it was until 2026-11-19: every even offset of the whole image, packed bytes included."""
    hits = []
    for m in re.finditer(rb"\x80\x00[\x69-\x78]", img):
        i = m.start()
        if i % 2 or i + 4 > len(img):
            continue
        v = int.from_bytes(img[i:i + 4], "big")
        for lo, hi, what in ks.STOCK_SRAM:
            if lo <= v < hi and img[i:i + 4] != STOCK[i:i + 4]:
                hits.append((ks._IMG_BASE + i, v, what))
    return hits


def stream_of(ops):
    """A GKA3 stream for a chosen parse (literal ints, (offset, length) matches), through pack's own emitter."""
    keep = pack._greedy_parse
    pack._greedy_parse = lambda data, mc: ops
    try:
        bits = pack._pack(b"", 0)
    finally:
        pack._greedy_parse = keep
    raw = bytearray()
    for op in ops:
        if isinstance(op, int):
            raw.append(op)
        else:
            off, n = op
            for _ in range(n):
                raw.append(raw[-off])
    return pack.PACKED_MAGIC + len(raw).to_bytes(4, "big") + bits, bytes(raw)


def image(stream, table=True, parity=0):
    """stock + an append: [pad] .long 1, blob address, blob length, 0 x5 ; 'OCTA' + stream.
    `parity` places the blob so that its stream bytes sit at even (0) or odd (1) image offsets."""
    blob = b"OCTA" + stream
    head = bytearray(32)
    p = LOADER_OFF + len(head)
    if p % 2 != parity:
        head = bytearray(33)
        p += 1
    head[0:4] = (1).to_bytes(4, "big")
    if table:
        head[4:8] = (ks._IMG_BASE + p).to_bytes(4, "big")
        head[8:12] = len(blob).to_bytes(4, "big")
    return bytes(STOCK[:LOADER_OFF]) + bytes(head) + blob, p


def main(paths):
    # 1. 120 literals (bits 0..119), then in one tag group: literal 0x80, literal 0x00, a match at offset
    #    0x71 (its offset byte (0x70 + 0x300) % 0x100 = 0x70), length 2, literal 0xcd -- the four emissions
    #    follow that group's tag byte back to back: 80 00 70 cd in the stream; the runtime holds 80 00 then
    #    the two bytes 0x71 back.
    ops = [0x11 + (k % 0x40) for k in range(120)] + [0x80, 0x00, (0x71, 2), 0xCD]
    stream, raw = stream_of(ops)
    check(depack.depack(stream) == raw, "case 1: the hand-made stream depacks to its runtime")
    at = stream.find(bytes.fromhex("800070cd"))
    check(at > 0 and b"\x80\x00\x70" not in raw, "case 1: 80 00 70 cd in the stream, not in the runtime")
    for parity in (0, 1):
        img, p = image(stream, parity=parity)
        if (p + 4 + at) % 2:
            continue
        o, n = old_refs(img), ks.stock_sram_refs(img)
        check(any(v == 0x800070CD for _, v, _ in o), f"case 1: the old scan hits 0x800070cd ({o[:2]})")
        check(n == [], f"case 1: the new scan does not ({n[:2]})")
        blobs = ks.packed_payloads(img)
        check(len(blobs) == 1 and blobs[0][2] == raw and blobs[0][:2] == (p, p + 4 + len(stream)),
              "case 1: packed_payloads finds the blob, its extent and its runtime")

    # 2. a runtime that DOES point into the timestretch work area, packed by the real packer
    raw2 = bytes(range(64)) * 8 + (0x80006A40).to_bytes(4, "big") + bytes(range(64, 128)) * 4
    off2 = raw2.find(b"\x80\x00\x6a\x40")
    stream2 = pack.PACKED_MAGIC + len(raw2).to_bytes(4, "big") + pack.pack(raw2, 4096)
    img2, _ = image(stream2)
    n2 = ks.stock_sram_refs(img2)
    check(n2 == [(ks._ARENA_BASE + off2, 0x80006A40, ks.STOCK_SRAM[0][2])],
          f"case 2: the runtime's 0x80006a40 reported at its DRAM address 0x{ks._ARENA_BASE + off2:08x} ({n2[:2]})")

    # 3. no table entry: not a payload, its bytes scanned as they stand
    img3, _ = image(stream, table=False)
    check(ks.packed_payloads(img3) == [], "case 3: an unlisted 'OCTAGKA3' is not taken for a payload")
    check(ks.stock_sram_refs(img3) == old_refs(img3), "case 3: ... and is scanned like any appended bytes")

    for path in paths:
        with open(path, "rb") as f:
            img = f.read()
        blobs = ks.packed_payloads(img)
        o, n = old_refs(img), ks.stock_sram_refs(img)
        print(f"  {path}: {len(blobs)} packed payload(s) "
              f"({', '.join(f'{b - a:,} B -> {len(r):,} B' for a, b, r in blobs) or '-'}); "
              f"old scan {[(hex(a), hex(v)) for a, v, _ in o] or 'clean'}; "
              f"new scan {[(hex(a), hex(v)) for a, v, _ in n] or 'clean'}")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
