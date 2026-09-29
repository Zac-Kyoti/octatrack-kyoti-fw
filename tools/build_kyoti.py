#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
KYOTI V1.0 -- every FINAL feature in one image.

    MUTE MODE (OT / OTFX / OTFX-T / DT-T)      QUANTIZE LIVE REC toggle
    SIDE-CHAIN COMPRESSOR (cross-core)         TRIGLESS-LOCK AUTO-REMOVE
    RELOAD FROM PROJECT (RELOAD3 chords)       DIRECT JUMP V7.0.1
    REPITCH KYOTI (rev 16)                     the bug fixes: PLAYSFREEFIX,
                                               PATTERN LED, PARTREAPPLY

Boot splash and SYSTEM STATUS -> OS VERSION read VERSTR below.

Method -- compose the finished builds, never re-implement them.
Each feature's own builder is run in a SANDBOX copy of the tree (so nothing it
writes lands in out/), with its caves moved to the addresses this build allocates
(tools/kyoti_place.py -- with no override every builder is byte-for-byte its
standalone self).  Its image is diffed against the base it was built from, and
the composite is that base plus the union of every delta.  Nothing about a
feature is re-derived here: SIDE-CHAIN's DSP payloads and descriptors, MUTE
MODE's menu surgery and REPITCH's DSP engine all come through untouched.

Why the caves move, and where to (reference/MERGE.md, reference/kb/caves.md):
the finished caves need ~9.6 KB and the classic cave holds 5.9 KB.  Zones, by the
evidence behind them:

  proven   0x400d6500..0x400d7c3c  this project's cave, hardware-proven for months.
           NOT from 0x400d64da: that is a runtime record table (base 0x400d64ca,
           24-byte records, fields +0x10/+0x14 written by 0x40001732, empty-slot
           finder 0x4000176c) -- the word at 0x400d64e2 is its terminator.
  midisc   midisc 1.40MIDISC8.2 ships code in each of these (tools/midisc/
           memory_map.py).  Ends are trimmed below any word stock references.
  reclaim  stock data this very image makes unreachable:
           SPRING REVERB's ColdFire descriptor -- both SIDE-CHAIN and REPITCH
             remove SPRING, and the only references to it are the two id2e
             entries they both redirect to NONE;
           the three stock PERSONALIZE pointer arrays -- MUTE MODE relocates
             them (17 entries) and repoints all five references.
           The builders see these zeroed (a PREPARED base); the composite is
           checked to hold no reference into them from anything but our caves.

Code on the engine/frame/ISR paths stays in the proven zone and SAFE_CAVE;
the thinner zones carry key-handler / page-draw code and REPITCH's glyph data.

Merge blockers (reference/MERGE.md), resolved here:
  B1  MUTE MODE widens the ANDY restore over 0x800000d8.  DIRECT JUMP is built
      with DJ_MODE_IN_CAVE: its on/off word lives in its cave, re-loaded from
      flash every boot -> OFF at power-on by construction.  Asserted.
  B2  DIRECT JUMP writes the [PTN]-overlay YES record; RELOAD3's standalone
      builder asserts that record stock.  Asserted here instead: every record
      RELOAD3 depends on is stock, and DIRECT JUMP's write is the only overlay
      change.

Verification, every run: every builder reports success in its sandbox; every
piece lies inside its zone and no two pieces overlap; feature deltas are
pairwise DISJOINT except SPRING's removal, which SIDE-CHAIN and REPITCH write
with identical bytes; every byte that differs from stock has an owner; each
feature's delta, outside its caves, equals its standalone delta (a relocation
may move caves and the pointers into them, nothing else); no branch lands
inside any displaced span; B1, B2 and the reclaim invariants.

Usage:  python3 tools/build_kyoti.py
Outputs (out/KYOTI/): OCTATRACK_OS1.40C_KYOTI_V1.0.syx (MIDI), OCTATRACK_KYOTI_V1.0.bin
(CF card), mainos_kyoti_v1.0.bin, kyoti_v1.0_map.json (every placement + symbol).
"""
import hashlib, json, os, pathlib, shutil, struct, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kyoti_status import status, PREVIEW

status(PREVIEW, "KYOTI V1.0 (combined image)", """
Every FINAL feature, composed from their own builders.  Each feature is
hardware-confirmed on its own; this combined image is NOT yet flashed, and it
places code in zones this project has not used before (see the docstring).
""")

VERSTR = "KYOTI V1.0"
TAG = "KYOTI_V1.0"
BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUTDIR = ROOT / "out/KYOTI"
SANDBOX = OUTDIR / "_sandbox"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
ALIGN = 4

o = lambda a: a - BASE

# --- zones: name -> (lo, hi exclusive, class, why) -----------------------------------
ZONES = {
    "CAVE":  (0x400d6500, 0x400d7c3c, "proven",
              "this project's cave (from 0x400d6500 as every flashed build; 0xff from 0x400d7c3c)"),
    "SAFE":  (0x400d24d0, 0x400d2cdc, "midisc", "SAFE_CAVE; stock references 0x400d2cdc"),
    "ENC":   (0x400c45b0, 0x400c4700, "midisc", "ENC_UNLOCK_CAVE"),
    "CAVE2": (0x400d2ee8, 0x400d301c, "midisc", "CAVE2; stock references 0x400d301c (6x)"),
    "RELD":  (0x400d359c, 0x400d3664, "midisc", "RELOAD_CAVE; stock references 0x400d3664 (4x)"),
    "SEAM":  (0x400d46e4, 0x400d47aa, "midisc", "SEAM_CAVE; stock references 0x400d47aa (8x)"),
    "PASTE": (0x400d3da4, 0x400d3e38, "midisc", "SCENE_PASTE_CAVE"),
    "FILT":  (0x400d3480, 0x400d34cf, "midisc", "FILT_PERSIST_LOAD_CAVE"),
    "SPRING": (0x400d5728, 0x400d58b8, "reclaim",
               "SPRING REVERB's CF descriptor 0x400d5726..; dead once SIDE-CHAIN/REPITCH remove SPRING"),
    "PERS1": (0x400b2a34, 0x400b2ab4, "reclaim",
              "stock PERSONALIZE labels+getters; dead once MUTE MODE relocates them"),
    "PERS2": (0x400b2ac0, 0x400b2b00, "reclaim",
              "stock PERSONALIZE setters; dead once MUTE MODE relocates them"),
}
# What each reclaim zone's deadness depends on, and the stock words that referenced it.
RECLAIM_WHOLE = {"SPRING": (0x400d5726, 0x400d58b8), "PERS1": (0x400b2a34, 0x400b2ab4),
                 "PERS2": (0x400b2ac0, 0x400b2b00)}

# --- the placement plan: zone -> pieces, packed in this order --------------------------
#   engine / ISR / tick-path code: CAVE and SAFE only.
PLAN = {
    # Session 116: MUTE MODE's SIDE-CHAIN KEY exemption grew patch_softmute by 124 B, which
    # the classic cave does not have. PLAYSFREEFIX moved into RELD beside patch_sidechain,
    # and the PERSONALIZE labels array into CAVE2. MUTE MODE is built on TRUE stock, where
    # PERS1/PERS2 still hold the stock arrays it relocates, so no MUTE MODE piece can go
    # there: REPITCH's glyph data 3 (68 B) moved from CAVE2 into PERS1 to make the room, and
    # four glyph records (20 B, pure data) out of PERS1 into PERS2 / SPRING / ENC.
    "CAVE":  ["patch_reload3", "patch_directjump_v7", "patch_softmute", "patch_partreapply",
              "patch_mutemode", "patch_pattern_led"],
    "SAFE":  ["rpk_logic", "personalize_getters", "personalize_setters"],
    "SPRING": ["rpk_widget7", "rpk_glyph_rec2"],
    "ENC":   ["patch_triglock",                    # LIVE-erase key path only
              "rpk_glyph_rec3", "rpk_glyph_rec4"],
    "RELD":  ["patch_sidechain",                   # COMPRESSOR page formatters
              "patch_trigscale"],
    "SEAM":  ["patch_qlrec"],                      # [PLAY]/[REC] key handlers
    "CAVE2": ["rpk_glyph_data0", "rpk_glyph_data1", "rpk_glyph_data2", "personalize_labels"],
    "PASTE": ["rpk_glyph_data4", "rpk_glyph_data5"],
    "FILT":  ["rpk_glyph_data6"],
    "PERS1": ["rpk_glyph_tab", "rpk_glyph_data3", "rpk_glyph_rec0"],
    "PERS2": ["rpk_glyph_rec1", "rpk_glyph_rec5", "rpk_glyph_rec6"],
}

# --- the features: name -> (builder, image, base, placement keys, standalone blob files) --
#   base "stock": built on true stock (MUTE MODE reads the stock PERSONALIZE arrays it
#   relocates); "prep": built on the prepared base (reclaim zones zeroed).
FEATURES = {
    "PLAYSFREEFIX": ("build_trigscale_only.py", "mainos_trigscale_only.bin", "prep",
                     {"patch_trigscale": "patch_trigscale.bin"}),
    "PATTERNLED": ("build_pattern_led.py", "mainos_patternled.bin", "prep",
                   {"patch_pattern_led": "patch_pattern_led.bin"}),
    "PARTREAPPLY": ("build_partreapply.py", "mainos_partreapply.bin", "prep",
                    {"patch_partreapply": "patch_partreapply.bin"}),
    "TRIGLOCK": ("build_triglock.py", "mainos_triglock.bin", "prep",
                 {"patch_triglock": "patch_triglock.bin"}),
    "QLREC": ("build_qlrec.py", "mainos_qlrec.bin", "prep", {"patch_qlrec": "patch_qlrec.bin"}),
    "MUTEMODE_DT": ("build_mutemode_dt.py", "mainos_mutemode_dt.bin", "stock",
                    {"patch_softmute": "patch_softmute_dt.bin",
                     "patch_mutemode": "patch_mutemode_dt.bin",
                     "personalize_labels": 68, "personalize_getters": 68,
                     "personalize_setters": 68}),
    "SIDECHAIN3_CROSS": ("build_sidechain3.py", "mainos_sidechain3_cross.bin", "prep",
                         {"patch_sidechain": "patch_sidechain.bin"}),
    "RELOAD3": ("build_reload3.py", "mainos_reload3.bin", "prep",
                {"patch_reload3": "patch_reload3.bin"}),
    "DIRECTJUMP_V7": ("build_directjump_v7.py", "mainos_directjump_v7.bin", "prep",
                      {"patch_directjump_v7": "patch_directjump_v7.bin"}),
    "REPITCH_KYOTI": ("build_repitch_kyoti.py", "mainos_repitch_kyoti.bin", "prep",
                      dict({"rpk_logic": "patch_repitch_kyoti.bin", "rpk_widget7": 0x174,
                            "rpk_glyph_tab": 28},
                           **{f"rpk_glyph_rec{k}": 20 for k in range(7)},
                           **{f"rpk_glyph_data{k}": 68 for k in range(7)})),
}
# builder flags that are not addresses
FLAGS = {"DIRECTJUMP_V7": {"dj_mode_in_cave": True}}


def flags_for(feat):
    """FLAGS, plus the ones that depend on what else is in the image.  MUTE MODE's SIDE-CHAIN
    KEY exemption (Session 116: a muted KEY track keeps feeding the key and MON, whatever
    MUTE MODE says) only exists when SIDE-CHAIN does -- a --without SIDECHAIN3_CROSS image
    drops it too."""
    f = dict(FLAGS.get(feat, {}))
    if feat == "MUTEMODE_DT" and "SIDECHAIN3_CROSS" in FEATURES:
        f["mutemode_sc_key"] = True
    return f
# bytes two features may both write, with identical values (SPRING REVERB's removal)
SHARED_OK = {frozenset(("SIDECHAIN3_CROSS", "REPITCH_KYOTI"))}

PROBLEMS = []


def flag(msg):
    PROBLEMS.append(msg)
    print(f"  !! {msg}")


# ------------------------------------------------------------------------------------
def make_sandbox(name, section):
    """A copy of the tree the builders can write into freely: sources copied, the
    large read-only inputs (refs/, vendor/, downloads/) linked, out/raw/ holding
    `section` as the stock MAIN OS."""
    sb = SANDBOX / name
    if sb.exists():
        shutil.rmtree(sb)
    sb.mkdir(parents=True)
    for p in ROOT.iterdir():
        if p.name in (".git", "out", "ghidra_project", "ghidra_project.bak_pre_fullanalysis_s70"):
            continue
        if p.name.endswith(".md"):
            continue
        if p.is_symlink():
            os.symlink(os.readlink(p), sb / p.name)
        elif p.is_dir():
            shutil.copytree(p, sb / p.name, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(p, sb / p.name)
    (sb / "out/raw").mkdir(parents=True)
    (sb / "out/raw/section_3_MAIN_OS.bin").write_bytes(section)
    return sb


def run_builder(sb, feat, place):
    builder = FEATURES[feat][0]
    env = dict(os.environ, KYOTI_PLACE=json.dumps(place))
    env.pop("KYOTI_ALLOW_WIP", None)
    r = subprocess.run([sys.executable, f"tools/{builder}"], cwd=sb, env=env,
                       capture_output=True, text=True)
    (OUTDIR / "_logs").mkdir(parents=True, exist_ok=True)
    (OUTDIR / "_logs" / f"{feat}.log").write_text(r.stdout + r.stderr)
    if r.returncode != 0:
        sys.exit(f"{feat}: {builder} failed in the sandbox (log out/KYOTI/_logs/{feat}.log):\n"
                 + (r.stdout + r.stderr)[-2000:])
    return (sb / "out" / FEATURES[feat][1]).read_bytes()


def nm(elf):
    out = subprocess.run(["m68k-elf-nm", str(elf)], capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in out.splitlines()) if len(p) == 3}


def delta(a, b):
    return {i: b[i] for i in range(len(a)) if a[i] != b[i]}


def runs(offsets):
    """Sorted offsets -> [(start, end_exclusive)] of contiguous runs."""
    out = []
    for i in sorted(offsets):
        if out and i == out[-1][1]:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return [tuple(r) for r in out]


def is_branch_insn(src):
    """Is `src` really the start of a branch instruction in stock?  The byte scan below
    reads any 0x6xxx word as a branch, operands included (a `movea.l 0x800062a4` holds
    `62a4`), so each hit is confirmed by disassembling from two different points before
    it and requiring both sweeps to decode a branch AT `src`."""
    for back in (0x100, 0xc2):
        lst = subprocess.run(["m68k-elf-objdump", "-D", "-b", "binary", "-m", "m68k:cfv4e", "-EB",
                              f"--adjust-vma=0x{BASE:x}", f"--start-address=0x{src - back:x}",
                              f"--stop-address=0x{src + 8:x}", str(STOCK_SECT)],
                             capture_output=True, text=True).stdout
        hit = [l for l in lst.splitlines() if l.strip().startswith(f"{src:x}:")]
        if not hit or not hit[0].split("\t")[-1].strip().startswith("b"):
            return False
    return True


def assert_no_branch_into(img, site, n, window=0x600):
    """Refuse a patched span that a branch lands strictly inside (build_triglock.py's guard,
    with each hit confirmed as a real instruction -- see is_branch_insn)."""
    lo, hi = o(site) - window, o(site) + window
    a = max(lo, 0)
    while a < min(hi, len(img) - 8):
        op = int.from_bytes(img[a:a + 2], "big")
        if 0x6000 <= op <= 0x6FFF:
            d8 = op & 0xFF
            if d8 == 0x00:
                disp = int.from_bytes(img[a + 2:a + 4], "big", signed=True)
            elif d8 == 0xFF:
                disp = int.from_bytes(img[a + 2:a + 6], "big", signed=True)
            else:
                disp = d8 - 0x100 if d8 & 0x80 else d8
            tgt = BASE + a + 2 + disp
            if site < tgt < site + n and is_branch_insn(BASE + a):
                return BASE + a, tgt
        a += 2
    return None


def refs_into(img, lo, hi):
    """Every byte-aligned 32-bit value in `img` that points into [lo, hi)."""
    out = []
    for i in range(len(img) - 3):
        v = (img[i] << 24) | (img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]
        if lo <= v < hi:
            out.append((i + BASE, v))
    return out


# ------------------------------------------------------------------------------------
def apply_without(argv):
    """--without NAME[,NAME]: a BISECTION image -- KYOTI V1.0 minus those features, built
    by the same method.  It gets its own OS VERSION ("KV1-NO-" + a short code per removed
    feature, e.g. KV1-NO-RPK) and its own directory out/KYOTI_BISECT/<tag>/, so it can never be
    mistaken for, or overwrite, the real image."""
    global VERSTR, TAG, OUTDIR, SANDBOX
    if "--without" not in argv:
        return
    drop = argv[argv.index("--without") + 1].upper().split(",")
    bad = [d for d in drop if d not in FEATURES]
    if bad:
        sys.exit(f"--without: unknown feature(s) {bad}; choose from {sorted(FEATURES)}")
    for d in drop:
        del FEATURES[d]
    if not ({"SIDECHAIN3_CROSS", "REPITCH_KYOTI"} & set(FEATURES)):
        del RECLAIM_WHOLE["SPRING"]          # nothing removes SPRING any more: not dead
    if "MUTEMODE_DT" not in FEATURES:
        del RECLAIM_WHOLE["PERS1"], RECLAIM_WHOLE["PERS2"]
    short = {"MUTEMODE_DT": "MM", "QLREC": "QL", "SIDECHAIN3_CROSS": "SC", "TRIGLOCK": "TL",
             "RELOAD3": "RL", "DIRECTJUMP_V7": "DJ", "REPITCH_KYOTI": "RPK",
             "PLAYSFREEFIX": "PF", "PATTERNLED": "PL", "PARTREAPPLY": "PR"}
    VERSTR = ("KV1-NO-" + "".join(short[d] for d in drop))[:10]
    TAG = "KYOTI_V1.0_WITHOUT_" + "_".join(drop)
    OUTDIR = ROOT / "out/KYOTI_BISECT" / TAG
    SANDBOX = OUTDIR / "_sandbox"
    print(f"  BISECTION IMAGE: without {', '.join(drop)}  ->  OS VERSION {VERSTR!r}, "
          f"{OUTDIR.relative_to(ROOT)}\n")


def main():
    apply_without(sys.argv)
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    if len(VERSTR) > 10:
        sys.exit(f"VERSTR {VERSTR!r} is {len(VERSTR)} chars; the ELEK field holds 10")
    stock = STOCK_SECT.read_bytes()
    OUTDIR.mkdir(parents=True, exist_ok=True)

    # zone sanity against TRUE stock: midisc/proven zones must be zero, every zone's
    # bytes unreferenced by stock except where the reclaim reasoning covers it
    print("=== zones ===")
    for z, (lo, hi, cls, why) in ZONES.items():
        if lo % ALIGN:
            sys.exit(f"zone {z} starts unaligned")
        if cls != "reclaim" and any(stock[o(lo):o(hi)]):
            sys.exit(f"zone {z} 0x{lo:08x}..0x{hi:08x} is not all-zero in stock")
        if cls != "reclaim":
            r = refs_into(stock, lo, hi)
            if r:
                sys.exit(f"zone {z}: stock references into it: "
                         + ", ".join(f"0x{a:08x}->0x{v:08x}" for a, v in r[:6]))
        print(f"  {z:7s} 0x{lo:08x}..0x{hi:08x} {hi-lo:5d} B  {cls:7s} {why}")

    # the prepared base: stock with the reclaim zones zeroed
    prep = bytearray(stock)
    for lo, hi in RECLAIM_WHOLE.values():
        prep[o(lo):o(hi)] = bytes(hi - lo)
    prep = bytes(prep)

    # --- pass 1: sizes, from each builder at its standalone placement ------------------
    print("\n=== pass 1: sizes (each builder at its standalone addresses) ===")
    sb1 = make_sandbox("sizes", stock)
    size = {}
    for feat, (builder, _img, _base, keys) in FEATURES.items():
        run_builder(sb1, feat, flags_for(feat) or {"_sizing": True})
        for key, src in keys.items():
            size[key] = src if isinstance(src, int) else len((sb1 / "out" / src).read_bytes())
    for key in size:
        if not any(key in v for v in PLAN.values()):
            sys.exit(f"{key} has no zone in PLAN")

    # --- allocate ------------------------------------------------------------------------
    print("\n=== allocation ===")
    place, zone_of = {}, {}
    for z, keys in PLAN.items():
        lo, hi, cls, _ = ZONES[z]
        at = lo
        for key in keys:
            if key not in size:                  # its feature is left out (--without)
                continue
            at = (at + ALIGN - 1) & ~(ALIGN - 1)
            if at + size[key] > hi:
                sys.exit(f"zone {z}: {key} ({size[key]} B) does not fit at 0x{at:08x} "
                         f"(zone ends 0x{hi:08x})")
            place[key], zone_of[key] = at, z
            at += size[key]
        print(f"  {z:7s} {cls:7s} " + ", ".join(f"{k} {size[k]}@{place[k]:08x}" for k in keys if k in size)
              + f"   [{hi - at} B left]")
    spans = sorted((place[k], place[k] + size[k], k) for k in place)
    for (a1, e1, k1), (a2, e2, k2) in zip(spans, spans[1:]):
        if e1 > a2:
            sys.exit(f"pieces overlap: {k1} 0x{a1:08x}..0x{e1:08x} / {k2} 0x{a2:08x}")

    # --- pass 2: every feature at its allocated addresses ---------------------------------
    print("\n=== pass 2: builders at the allocated addresses ===")
    sbs = {"stock": make_sandbox("stock", stock), "prep": make_sandbox("prep", prep)}
    base_of = {"stock": stock, "prep": prep}
    deltas, syms = {}, {}
    for feat, (builder, _img, base, keys) in FEATURES.items():
        p = {k: place[k] for k in keys if not k.startswith("rpk_glyph_rec")
             and not k.startswith("rpk_glyph_data")}
        if feat == "REPITCH_KYOTI":
            p["rpk_glyph_recs"] = [place[f"rpk_glyph_rec{k}"] for k in range(7)]
            p["rpk_glyph_data"] = [place[f"rpk_glyph_data{k}"] for k in range(7)]
        p.update(flags_for(feat))
        img = run_builder(sbs[base], feat, p)
        deltas[feat] = delta(base_of[base], img)
        for src in keys.values():                    # each linked blob's .elf sits beside it
            if isinstance(src, str):
                stem = src[:-len(".bin")]
                syms[stem] = nm(sbs[base] / "out" / f"{stem}.elf")
        print(f"  {feat:17s} {builder:26s} base={base:5s} {len(deltas[feat]):5d} B changed")
        # a feature built on true stock must not touch a reclaim zone
        if base == "stock":
            for z, (lo, hi) in RECLAIM_WHOLE.items():
                if any(lo <= i + BASE < hi for i in deltas[feat]):
                    sys.exit(f"{feat} writes into reclaim zone {z}")

    # --- relocation changed only caves and pointers into them -------------------------
    print("\n=== each feature vs its standalone build ===")
    for feat, (builder, _img, base, keys) in FEATURES.items():
        alone = delta(stock, (sb1 / "out" / FEATURES[feat][1]).read_bytes())
        mine = deltas[feat]
        caves_now = [(place[k], place[k] + size[k]) for k in keys]
        caves_then = []                       # the standalone caves: any changed byte in
        for a, e in runs(alone):              # the free zones, plus zero gaps inside them
            if 0x400d6500 <= a + BASE < 0x400d7c3c:
                caves_then.append((a + BASE, e + BASE))
        def in_caves(i, cs):
            return any(lo <= i + BASE < hi for lo, hi in cs)
        outside_now = {i: v for i, v in mine.items() if not in_caves(i, caves_now)}
        outside_then = {i: v for i, v in alone.items() if not in_caves(i, caves_then)}
        # Outside the caves the SAME sites must change; only a cave address written at a
        # site (jmp/jsr target, descriptor pointer) may differ.  A moved address can
        # happen to equal stock in a byte or two, so any difference must sit within a
        # longword of a site the standalone build writes.
        then_i = sorted(outside_then)
        def near_site(i):
            import bisect
            k = bisect.bisect_left(then_i, i - 3)
            return k < len(then_i) and then_i[k] <= i + 3
        diff = [i for i in set(outside_now) | set(outside_then)
                if outside_now.get(i, stock[i]) != outside_then.get(i, stock[i])]
        wild = sorted(i for i in diff if not near_site(i))
        if wild:
            flag(f"{feat}: {len(wild)} byte(s) outside its caves differ from its standalone "
                 f"build away from any site it writes, first 0x{wild[0] + BASE:08x}")
        moved = len(diff)
        print(f"  {feat:17s} {len(outside_now):5d} B outside its caves; {moved} B differ from "
              f"standalone, all within a pointer of its own sites")

    # --- compose -------------------------------------------------------------------------
    print("\n=== compose ===")
    comp = bytearray(prep)
    owner = {}
    names = list(FEATURES)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both = set(deltas[a]) & set(deltas[b])
            if not both:
                continue
            same = all(deltas[a][k] == deltas[b][k] for k in both)
            if frozenset((a, b)) in SHARED_OK and same:
                print(f"  {a} and {b} share {len(both)} identical byte(s) "
                      f"(SPRING REVERB's removal: FX chooser, id2e, DSP dispatch stubs)")
            else:
                flag(f"{a} x {b}: {len(both)} byte(s) claimed by both "
                     f"({'identical' if same else 'DIFFERENT'} values), first 0x{min(both)+BASE:08x}")
    for feat in names:
        for i, v in deltas[feat].items():
            comp[i] = v
            owner.setdefault(i, []).append(feat)
    reclaimed = {i for lo, hi in RECLAIM_WHOLE.values() for i in range(o(lo), o(hi))}
    stray = [i for i in range(len(comp)) if comp[i] != stock[i] and i not in owner
             and i not in reclaimed]
    if stray:
        flag(f"{len(stray)} changed byte(s) with no owner, first 0x{stray[0]+BASE:08x}")
    for feat in names:                                      # every delta survived intact
        lost = [i for i, v in deltas[feat].items() if comp[i] != v]
        if lost:
            flag(f"{feat}: {len(lost)} of its bytes did not survive the composition")
    changed = sum(1 for a, b in zip(stock, comp) if a != b)
    print(f"  composite: {changed} B changed vs stock, "
          f"{sum(len(d) for d in deltas.values())} B of feature deltas, "
          f"{len(reclaimed)} B of reclaimed stock data")

    # --- invariants ------------------------------------------------------------------------
    print("\n=== invariants ===")
    # no branch into any patched span outside the zones (the detour sites)
    zone_ranges = [(lo, hi) for lo, hi, _, _ in ZONES.values()]
    code_runs = [(a + BASE, e - a) for a, e in runs(owner)
                 if a + BASE < 0x400b0000
                 and not any(lo <= a + BASE < hi for lo, hi in zone_ranges)]
    bad = [(s, n, assert_no_branch_into(stock, s, n)) for s, n in code_runs]
    bad = [b for b in bad if b[2]]
    for s, n, (src, tgt) in bad:
        flag(f"branch 0x{src:08x} -> 0x{tgt:08x} lands inside the patched span 0x{s:08x}+{n}")
    print(f"  {len(code_runs)} patched code spans: no branch lands inside any" if not bad else "")

    if "DIRECTJUMP_V7" in FEATURES:
        # B1: DJ_MODE in the DJ cave; MUTE MODE's widened restore therefore cannot reach it
        dj = syms.get("patch_directjump_v7", {})
        djm, djlo, djhi = dj.get("DJ_MODE"), place["patch_directjump_v7"], \
            place["patch_directjump_v7"] + size["patch_directjump_v7"]
        widened = all(comp[o(s) + 3] == 0x70 for s in (0x4001f322, 0x4001f3be, 0x4001fb24))
        dj_blob = bytes(comp[o(djlo):o(djhi)])
        raw_ref = any(struct.unpack(">I", dj_blob[i:i + 4])[0] == 0x800000D8
                      for i in range(0, len(dj_blob) - 3, 2))
        if djm is None or not (djlo <= djm < djhi) or raw_ref:
            flag(f"B1: DJ_MODE is not in DIRECT JUMP's cave (sym {djm}, raw ref {raw_ref})")
        elif comp[o(djm):o(djm) + 4] != b"\x00\x00\x00\x00":
            flag("B1: DJ_MODE's image word is not 0")
        else:
            print(f"  B1: DJ_MODE at 0x{djm:08x} in DIRECT JUMP's cave, image value 0 "
                  f"(ANDY restore widened by MUTE MODE: {widened}; 0x800000d8 unreferenced by DJ)")

        # B2: the keymap overlays -- DJ's YES press field is the only change
        ptn_yes = 0x400bf0be
        for addr, what in ((0x400d00ee, "[BANK]-layer YES record"), (0x400d00d4, "[BANK]-layer NO record"),
                           (0x4005a044, "[PTN] key handler"), (0x400bf0a4, "[PTN]-layer NO record"),
                           (0x4007af80, "[BANK] key handler")):
            if comp[o(addr):o(addr) + 8] != stock[o(addr):o(addr) + 8]:
                flag(f"B2: {what} 0x{addr:08x} is not stock")
        for i in range(8):
            rec = 0x400bf122 + i * 26
            if int.from_bytes(comp[o(rec) + 2:o(rec) + 6], "big") != 0x40083dc4:
                flag(f"B2: [PTN]-overlay TRACK slot {i} no longer points at 0x40083dc4")
        ov = [i for i in range(o(0x400bf000), o(0x400bf300)) if comp[i] != stock[i]]
        if any(not (o(ptn_yes) + 2 <= i < o(ptn_yes) + 6) for i in ov):
            flag("B2: the [PTN] overlay changed outside the YES record's press field")
        press = int.from_bytes(comp[o(ptn_yes) + 2:o(ptn_yes) + 6], "big")
        if not (djlo <= press < djhi):
            flag(f"B2: [PTN]-overlay YES press field 0x{press:08x} is not in DIRECT JUMP's cave")
        else:
            print(f"  B2: [PTN]+[YES] -> 0x{press:08x} (DIRECT JUMP); RELOAD3's records, handlers and "
                  f"8 TRACK slots stock")

    # reclaim: nothing but our own pieces may point into a reclaimed zone
    ours = [(place[k], place[k] + size[k]) for k in place]
    for z, (lo, hi) in RECLAIM_WHOLE.items():
        # a reference is ours if we wrote it: inside a placed piece, or a longword
        # some feature changed (REPITCH's descriptor pokes aim at its widget clone)
        foreign = [(a, v) for a, v in refs_into(comp, lo, hi)
                   if not any(p <= a < e for p, e in ours)
                   and comp[o(a):o(a) + 4] == stock[o(a):o(a) + 4]]
        if foreign:
            flag(f"reclaim {z}: still referenced from outside our caves: "
                 + ", ".join(f"0x{a:08x}->0x{v:08x}" for a, v in foreign[:6]))
    fx = {"FX1": 0x400d5f58, "FX2": 0x400d5fdc} if "SPRING" in RECLAIM_WHOLE else {}
    for bus, id2e in fx.items():
        if int.from_bytes(comp[o(id2e) + 0x15 * 4:o(id2e) + 0x15 * 4 + 4], "big") != 0x400d45e0 + 0x38:
            flag(f"reclaim SPRING: {bus} id2e[0x15] does not point at NONE")
    print("  reclaim: SPRING's descriptor and the stock PERSONALIZE arrays are unreferenced "
          "except by our own caves; both id2e[SPRING] -> NONE" if not any(
              "reclaim" in p for p in PROBLEMS) else "")

    # the classic cave floor: the runtime record table below 0x400d6500 stays stock
    if comp[o(0x400d64ca):o(0x400d6500)] != stock[o(0x400d64ca):o(0x400d6500)]:
        flag("the runtime record table 0x400d64ca..0x400d6500 was modified")
    else:
        print("  0x400d64ca..0x400d6500 (runtime record table + terminator) untouched")

    # --- write + wrap -----------------------------------------------------------------------
    mainos = OUTDIR / f"mainos_{TAG.lower()}.bin"
    mainos.write_bytes(bytes(comp))
    cmap = {"verstr": VERSTR, "zones": {z: [hex(lo), hex(hi), cls] for z, (lo, hi, cls, _) in ZONES.items()},
            "pieces": {k: {"zone": zone_of[k], "at": hex(place[k]), "size": size[k]} for k in place},
            "symbols": {e: {s: hex(a) for s, a in sorted(t.items())} for e, t in syms.items()}}
    (OUTDIR / f"{TAG.lower()}_map.json").write_text(json.dumps(cmap, indent=1))

    if PROBLEMS:
        print(f"\n{len(PROBLEMS)} problem(s) -- NOT wrapping:")
        for p in PROBLEMS:
            print(f"  - {p}")
        sys.exit(1)

    elek = OUTDIR / f"elek_{TAG.lower()}.bin"
    syx = OUTDIR / f"OCTATRACK_OS1.40C_{TAG}.syx"
    binf = OUTDIR / f"OCTATRACK_{TAG}.bin"
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(elek))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(mainos), "-V", VERSTR,
                        "-o", str(syx)], capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode != 0 or "version               : set to" not in r.stdout:
        sys.exit(f"EFT wrap failed:\n{r.stdout}\n{r.stderr}")
    subprocess.run([sys.executable, "tools/make_bin.py", str(elek), "-o", str(binf)],
                   check=True, cwd=ROOT, capture_output=True)
    chk = subprocess.run([str(EFT), str(syx)], capture_output=True, text=True, cwd=ROOT)
    field = elek.read_bytes()[0x08:0x12]           # the 10-char ELEK version field
    if chk.returncode != 0 or "checksums : ok" not in chk.stdout or field != VERSTR.encode().ljust(10):
        sys.exit(f".syx does not re-parse, or its version field is {field!r}:\n{chk.stdout}\n{chk.stderr}")
    print("\n=== wrapped ===")
    for f in (mainos, syx, binf):
        print(f"  {f.relative_to(ROOT)}  sha256 {hashlib.sha256(f.read_bytes()).hexdigest()}")
    print(f"  OS VERSION / boot splash: {VERSTR!r}   (round-trip OK)")
    shutil.rmtree(SANDBOX, ignore_errors=True)


if __name__ == "__main__":
    main()
