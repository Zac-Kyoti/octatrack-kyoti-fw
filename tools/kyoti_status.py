#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
The build gate: everything is WORK IN PROGRESS until the author promotes it.

A WIP build refuses to run unless KYOTI_ALLOW_WIP=1 is set, so nobody flashes an
unfinished image by accident.  A builder is FINAL only while it still builds exactly the
image that was promoted: FINAL below pins each promoted builder to the sha256 of that
image (the patched MAIN OS section, before it is wrapped into a .syx).  Change the
builder or anything it assembles and the image changes, so the build is WIP again until
the author promotes the new one -- which then replaces the old.  A diagnostic variant of
a final builder builds a different image, so it is WIP too.

Two calls in every builder:

    gate(__file__)           first thing: a builder not on the FINAL list is WIP
    seal(__file__, image)    after writing the image, before wrapping it: a FINAL
                             builder whose image no longer matches is WIP

PROMOTION happens only on the author's explicit instruction: build it, put the sha256
that seal() prints into FINAL, and give the feature its entry in README.md.  When the
promoted build is a new builder rather than an update in place, it takes the old one's
FINAL entry and the old builder is deleted.

FEATURE IMAGES (the author, 2026-11-15): every feature ships WITH the three bug fixes. A feature
builder run on its own hands off from gate() to tools/feature_image.py, which builds the feature
as a UNIT (KYOTI_UNIT=1: the feature alone, pinned under its builder, never wrapped for flashing)
and composes the fixes onto it (pinned under "feature_image.py"). build_kyoti.py runs units with
KYOTI_PLACE set, which also means unit.

The gate is a courtesy, not a lock -- this is a public repo.  Read FLASHING.md before you
flash anything, whatever the gate says.
"""
import hashlib
import os
import sys

ALLOW_ENV = "KYOTI_ALLOW_WIP"

# builder -> sha256 of the image it built when the author promoted it.  A builder that
# writes several images maps to {image file name: sha256}, one per promoted image.
FINAL = {
    "build_mute_modes.py":                 "7d48737df97465df74bebad88e2b92592b96beed1c1e066b597c840c03cbb137",
    "build_direct_jump_kyoti.py":          "7b48fdd6b6144f78e4f4966c8e6ef8c6912b3d83f0fd5f1f01730c1a9f4cd093",
    "build_sidechain_compressor.py":       "44465569a6118a9a7936c83d0f728a5f8c81122c42433a7cdaf267206e99f2fc",
    "build_reload_from_project.py":        "fc25a9943a7aa1c5e1a6d2e08733ce3a67d366d49b8f4dcc5da1d9a27051880b",
    "build_quantize_live_rec_toggle.py":   "2012abd83f75336ddc73925f0a3ebb8de16ed3ea24b4c28d226e35ef99c2a6f4",
    "build_erase_empty_trigless_locks.py": "3d60c73153771bbab8920bc0be0a31bbd72286eca5e7293c2859d1436fc4b740",
    "build_midi_plays_free_fix.py":        "672158c18630703cc1aadc635d45aeb68549a3237830d5c4a0aeb2d113afad35",
    "build_empty_pattern_led_fix.py":      "074315c20d4c1c2073fc9ee324cf31dcd92f6c639a664d661cf88e542ef5e1a5",
    "build_rec_trig_mute.py":              "60e97fb35e255f2a1f19eac84dd463058788b7fcdb481110459aa8b9f8f1cffc",
    "feature_image.py": {                         # each feature + the three bug fixes (out/<FEATURE>/)
        "mainos_mute_modes.bin":                             "316f01f713cf048f2fdd32464845c7c1493211be95abb76ae5a2e9344064e1b2",
        "mainos_quantize_live_rec_toggle.bin":               "9b51ad03846acd3f3be2d286ce6f33eea948b2e37dd6c037dbe3bdda6466fa57",
        "mainos_sidechain_compressor.bin":                   "2d5a401692894c50996201db525a177f19bb4f19d4a9f258a79ce52c6db604c2",
        "mainos_erase_empty_trigless_locks.bin":               "0f9f1f6f1b34b87ecf7f5fba74c23af2b734932540d968b1095554dc8eb61d4a",
        "mainos_reload_from_project.bin":                    "38f2f7de9c88561bfd9bd2027d7276819aed085eb9873424d02caf16548ef4b6",
        "mainos_direct_jump_kyoti.bin":                      "79b422fdb3bcf62c42395c7fab775d95e81113bd64fb6c65ff0ea44e3475f872",
        "mainos_rec_trig_mute.bin":                          "f8ee2d55ac6d253699b5c4bc2a35a02c587badc3fb43353d17bfc605f47d1c10",
        "mainos_blackpyramids_303.bin":                      "4f2b2ec94cdf98b67e012079a26ade692ceaabf0576e6bda518803737f584989",
        "mainos_varispeed.bin":                              "fe4e7f50fb6386e1ee717b54896f615fd946c74e7b9f1d2a061098c729388566",
        "mainos_varispeed_emus.bin":                         "f3b08c791b888f1683f13a57b14f7f44f3f331d79f383b588a161803bf1a4123",
        "mainos_batch_bugfixes.bin":                         "fa374dd80125aea37d2f2ab858b94af7f618e75b080718dfb4f9f23d9c95c1ca",
    },
    "build_kyoti.py": {
        "mainos_kyoti_v1.8.bin":                             "02e30123328b8aeca3959804f68cf91c571ec386f282d981201e79c1de9f8810",
        "mainos_kyoti_v1.8c.bin":                            "94fe94c29baea5cc8d9ed9e5793991b698c3aa05da7cf58db5b18b8f7b44fc33",
        "mainos_clyps.bin":                                  "eb3cc85bd2666efe3994a482539e5948d33cabff2017e0bd5334c2d7974afcd3",
        "mainos_kyoti_v1.8bc.bin":                           "0a8aad47407fe12a8144ada288156ccec38011ac6603f51397da5cd7e9e7ce95",
    },
    "build_blackpyramids_303.py":          "2a0b990118dc6cffa5ef8a7b8849e0831346d35fcb6b77b8fef5872868aa2b4e",
    "build_part_change_carryover_fix.py":  "dd2a7e2ba3328364caa560e431195fd248cbb5d83dce1759de1e7e3effc5febd",
    "build_varispeed.py":                  "2e365957f13495c5c6aa8d21e9c75b8954b41104efa7968302140d8ee8b73d54",
    "build_varispeed_emus.py":             "b54e72464dfb5f3ffbefae98e93198c6c1f76ef8237484e44e06967ee22532bc",
}

_RULE = "  " + "-" * 72


def _allowed():
    return os.environ.get(ALLOW_ENV) == "1"


def _banner(lines, out):
    print(_RULE, file=out)
    for line in lines:
        print(f"  {line}", file=out)
    print(_RULE, file=out)
    out.flush()   # a builder's child processes write straight to the terminal; without
                  # this, a piped run prints the banner after their output instead of first


def _refuse(why, builder):
    print(f"\n  Refusing to build: {why}.\n"
          f"  If you meant it, set {ALLOW_ENV}=1:\n\n"
          f"      {ALLOW_ENV}=1 python3 {os.path.relpath(builder)}\n", file=sys.stderr)
    sys.exit(2)


def unit_mode():
    """True when a composer (feature_image.py, build_kyoti.py) drives this builder."""
    return os.environ.get("KYOTI_UNIT") == "1" or "KYOTI_PLACE" in os.environ


def gate(builder, note=""):
    """Say whether `builder` is FINAL or WIP; refuse a WIP build without the opt-in.

    `note` is free text shown with a WIP banner -- what is unfinished, specifically.
    Call it at the top of a builder, before it reads the stock image or writes anything.
    A feature builder run on its own hands off here to its feature image (feature_image.py).
    """
    name = os.path.basename(builder)
    if not unit_mode():
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import feature_image
        if name in feature_image.BUILDERS or name in feature_image.ELSEWHERE:
            feature_image.standalone(name)          # exits
    if name in FINAL:
        _banner([f"{name}  --  FINAL"], sys.stdout)
        print()
        return
    out = sys.stdout if _allowed() else sys.stderr
    _banner([f"{name}  --  WIP, not promoted to final"]
            + [l.strip() for l in note.strip().splitlines()], out)
    if not _allowed():
        _refuse("this build is work in progress, and an image built from it is not\n"
                "  something to flash", builder)
    print()


# On-chip SRAM that stock code owns at runtime: a patch must not keep state there, however
# quiet a static scan says it is. 0x80006924..0x80007873 is the stock timestretch task's
# (prio 1, entry 0x40098a5c): per-track splice results at 0x80006924, then the splice
# search's windows and the transient detector's samples, refilled with audio on every
# grain whenever a track plays. It explains the "0x80006a40+ is overwritten on hardware"
# losses of Sessions 95 and 98, and MUTE_MODES' SHADOW lived there until 2026-10-25.
STOCK_SRAM = ((0x80006924, 0x80007874, "the stock timestretch task's work area"),)
STOCK_SRAM_ENV = "KYOTI_ALLOW_STOCK_SRAM"
_STOCK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "out", "raw", "section_3_MAIN_OS.bin")


_IMG_BASE = 0x40000400
_LOADER_AT = 0x4010FDF0            # tools/dram/dram.py: the append starts at the byte after the stock image
_ARENA_BASE = 0x40A955E0           # ... and every DRAM runtime is linked there
_PACKED = b"OCTA" + b"GKA3"        # dram.SIGNATURE + pack.PACKED_MAGIC


def packed_payloads(img):
    """The DRAM payloads tools/dram/ appends after the stock image: [(start, end, runtime)] -- the image
    offsets of each packed blob ('OCTA' + GKA3 stream) and the runtime it depacks to (linked at the
    arena base). Its length comes from the loader's own payload table (blob address, blob length), so
    a coincidental 'OCTAGKA3' is not taken for one. [] for an image with no append."""
    if len(img) <= _LOADER_AT - _IMG_BASE:
        return []
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "dram"))
    import depack
    out, i = [], _LOADER_AT - _IMG_BASE
    while True:
        p = img.find(_PACKED, i)
        if p < 0:
            return out
        t = img.find((_IMG_BASE + p).to_bytes(4, "big"), _LOADER_AT - _IMG_BASE, p)
        n = int.from_bytes(img[t + 4:t + 8], "big") if t >= 0 else 0
        if t < 0 or t % 2 or not 8 < n <= len(img) - p:
            i = p + 1
            continue
        out.append((p, p + n, depack.depack(img[p + 4:p + n])))
        i = p + n


def stock_sram_refs(img):
    """Every 32-bit word the build changed or appended (vs stock) that points into
    STOCK_SRAM: [(address, value, what)]. Stock's own references are left alone.

    A DRAM payload travels packed: its bytes are a compressed bit stream, not code, so a match
    there is a coincidence (KYOTI V1.8BC, 2026-11-19: 0x800076cd at 0x40119664, inside the packed
    stream). The scan skips each packed blob and reads the runtime it depacks to instead (the
    code that actually runs, at its DRAM address) -- stricter than before, not looser: the
    packed bytes used to hide whatever the runtime held."""
    import re
    with open(_STOCK, "rb") as f:
        stock = f.read()
    blobs = packed_payloads(img)

    def scan(buf, base, ref, skip=()):
        for m in re.finditer(rb"\x80\x00[\x69-\x78]", buf):
            i = m.start()
            if i % 2 or i + 4 > len(buf) or any(a - 3 <= i < b for a, b in skip):
                continue
            v = int.from_bytes(buf[i:i + 4], "big")
            for lo, hi, what in STOCK_SRAM:
                if lo <= v < hi and buf[i:i + 4] != ref[i:i + 4]:
                    hits.append((base + i, v, what))
    hits = []
    scan(img, _IMG_BASE, stock, [(a, b) for a, b, _ in blobs])
    for _, _, raw in blobs:
        scan(raw, _ARENA_BASE, b"")
    return hits


def _check_stock_sram(builder, image):
    if not os.path.exists(_STOCK):
        print(f"  (stock SRAM check skipped: {os.path.relpath(_STOCK)} missing)")
        return
    with open(image, "rb") as f:
        hits = stock_sram_refs(f.read())
    if not hits:
        return
    lines = [f"0x{a:08x}: 0x{v:08x}  ({what})" for a, v, what in hits[:12]]
    out = sys.stdout if os.environ.get(STOCK_SRAM_ENV) == "1" else sys.stderr
    _banner([f"{os.path.basename(builder)}  --  points into stock-owned SRAM"] + lines, out)
    if os.environ.get(STOCK_SRAM_ENV) != "1":
        print(f"\n  Refusing to build: patch code references SRAM that stock code overwrites at\n"
              f"  runtime (CLAUDE.md, the scratch-RAM rule). Keep the state in the patch's own\n"
              f"  unit (cave or DRAM .data). If a hit is only a coincidental byte pattern, set\n"
              f"  {STOCK_SRAM_ENV}=1.\n", file=sys.stderr)
        sys.exit(2)


# Stock data that LOOKS free and is read at runtime: an image may not change a byte of it.
#   0x400d24d0..0x400d2ce0 = entries 508..1023 of the stock DELAY's one-pole coefficient table at
#   0x400d1ce0 (FX2 DELAY, 0x400031a0: LP pole = table[(BASE+WDTH)>>6], HP = table[BASE>>6]); stock 0 =
#   filter open. KYOTI V1.1-V1.6 kept ~2 KB of code there ("SAFE"): every DELAY with BASE+WDTH >= 127
#   (the default included) read a code word as its LP pole -> darker repeats (NOTES 2026-11-01,
#   reference/kb/caves.md §5).
STOCK_TABLES = [(0x400d24d0, 0x400d2ce0, "DELAY's coefficient table, entries 508..1023 (0x400d1ce0)")]


def _check_stock_tables(builder, image):
    if not os.path.exists(_STOCK):
        print(f"  (stock table check skipped: {os.path.relpath(_STOCK)} missing)")
        return
    with open(_STOCK, "rb") as f:
        stock = f.read()
    with open(image, "rb") as f:
        img = f.read()
    for lo, hi, what in STOCK_TABLES:
        a, b = lo - 0x40000400, hi - 0x40000400
        if img[a:b] != stock[a:b]:
            first = next(i for i in range(a, b) if img[i] != stock[i])
            _banner([f"{os.path.basename(builder)}  --  writes into a live stock table",
                     f"0x{lo:08x}..0x{hi:08x}: {what}",
                     f"first changed byte 0x{0x40000400 + first:08x}"], sys.stderr)
            print("\n  Refusing to build: that range looks free but stock reads it at runtime.\n",
                  file=sys.stderr)
            sys.exit(2)


def seal(builder, image):
    """After a builder writes its image: refuse references into stock-owned SRAM and changes
    to live stock tables (every builder), then, for a FINAL builder, is it still the promoted one?

    A build placed at other addresses for the combined image (KYOTI_PLACE set, see
    tools/kyoti_place.py) cannot match its standalone promotion, so it is not checked
    here; the combined builder is gated on its own.
    """
    _check_stock_sram(builder, image)
    _check_stock_tables(builder, image)
    name = os.path.basename(builder)
    if name not in FINAL or os.environ.get("KYOTI_PLACE"):
        return
    with open(image, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    want = FINAL[name]
    if isinstance(want, dict):
        want = want.get(os.path.basename(image), "(not one of the promoted images)")
    if sha == want:
        print(f"  image matches the promoted FINAL build (sha256 {sha[:16]}...)")
        return
    out = sys.stdout if _allowed() else sys.stderr
    _banner([f"{name}  --  WIP: this is not the promoted build",
             "The builder, or something it assembles, has changed since it was",
             "promoted. It stays WIP until the author promotes it.",
             f"  this build  {sha}",
             f"  promoted    {want}"], out)
    if not _allowed():
        _refuse("the build no longer matches its promoted image", builder)
