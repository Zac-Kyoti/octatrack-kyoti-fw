#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Every feature build is the feature WITH the three BATCH_BUGFIXES (the author, 2026-11-15): there is no
standalone image without them any more, and no separate "Bugbuild". This module composes them.

    python3 tools/build_<feature>.py     ->  out/<FEATURE>/OCTATRACK_OS1.40C_<FEATURE>.syx (+ .bin)

kyoti_status.gate() sends a feature builder run on its own here (standalone()). The composer runs
that builder again as a UNIT (KYOTI_UNIT=1: the feature alone, out/mainos_<feature>.bin, which the
emulator harnesses and build_kyoti.py use; the flashable files a unit run wraps are deleted), then
links the bug-fix caves into free space in that image and applies their detours. The three fix
builders (and build_batch_bugfixes.py) give BATCH_BUGFIXES: the three fixes on stock. build_clyps.py
gives the standalone CLYPS image, which build_kyoti.py composes (CLYPS needs DIRECT JUMP).

    MUTE_MODES  QUANTIZE_LIVE_REC_TOGGLE  SIDECHAIN_COMPRESSOR  ERASE_EMPTY_TRIGLESS_LOCKS
    RELOAD_FROM_PROJECT  DIRECT_JUMP_KYOTI  REC_TRIG_MUTE  BLACKPYRAMIDS_303  VARISPEED  VARISPEED_EMUS
    BATCH_BUGFIXES (MIDI_PLAYS_FREE_FIX + EMPTY_PATTERN_LED_FIX + PART_CHANGE_CARRYOVER_FIX)

Promotion: kyoti_status.FINAL pins each unit under its builder (as before) and each composed image
under "feature_image.py" (mainos_<feature>.bin in out/<FEATURE>/). Both seal; a WIP unit or image
refuses without KYOTI_ALLOW_WIP=1, which a run passes through to the unit.

Method -- compose onto the finished feature image, do not re-implement it. SIDE-CHAIN in particular
is never re-derived: its DSP payloads, COMPRESSOR descriptor and FX2 chooser edits come through
untouched, and its cave stays at its own address so the descriptor's formatter pointers stay valid.
VARISPEED_EMUS's DSP payload edits come through the same way.

Cave layout, where each fix is placed if that space is free in the base (it is in all but
RELOAD_FROM_PROJECT, whose own cave starts at 0x400d6500, so the allocator moves the two fixes up):
    patch_partreapply   0x400d6500   402 B
    patch_pattern_led   0x400d6694   158 B
    (never below 0x400d6500 -- 0x400d64ca.. is a runtime record table, kb/caves.md 2b)
    patch_trigscale     0x400d7b00    62 B

Verification (every image, every run):
  * each cave region is all-zero in the base before it is written, and never covers a byte a
    feature writes at runtime (RESERVED: REC_TRIG_MUTE's RTM_MASK + RTM_TOAST are zero in the image);
  * each detour site still holds the exact stock bytes (proves no feature took it first);
  * assert_no_branch_into on every detour site (build_erase_empty_trigless_locks.py's guard, promoted here);
  * COMPOSITIONALITY: the composite's byte-delta vs stock is exactly the union of the
    feature's delta and a reference "bug-fixes only, at these same addresses, on stock"
    delta -- and those two deltas are disjoint.  That is the interlock proof: every
    changed byte has exactly one owner and no owner's bytes were altered.

Usage:  python3 tools/build_<feature>.py              one image (the normal way)
        python3 tools/feature_image.py [--only NAME,...]   every image (a sweep)
Until 2026-11-15 this was tools/build_bugbuilds.py (out/Bugbuilds/, OS VERSIONs BUG_*).
"""
import os, pathlib, subprocess, sys
import hashlib
from kyoti_status import seal
import feature_exclusions                      # pairs that never share an image (the user, 2026-11-07)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "dram"))
import dram                                    # noqa: E402  (tools/dram/dram.py)

BASE = 0x40000400
ROOT = pathlib.Path(__file__).parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
WORK = ROOT / "out/_feature_work"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
# From 0x400d6500, not the zero run's start 0x400d64da: 0x400d64ca is a runtime table of
# 24-byte records (fields +0x10/+0x14 written by 0x40001732; 0x400d64e2 its terminator) --
# reference/kb/caves.md 2b.  Every flashed build starts at 0x400d6500.
FREE_START, FREE_END = 0x400d6500, 0x400d7c3c
# The fallback when nothing in the cave fits (VARISPEED_EMUS leaves ~160 B): a DRAM unit behind
# tools/dram/'s loader (as KYOTI's RELOAD_FROM_PROJECT), one 6 KB arena page. Until 2026-11-01 it was
# midisc's "SAFE_CAVE" 0x400d24d0..0x400d2cdc -- which is the stock DELAY's coefficient table (entries
# 508..1022, stock 0): BUG_VEM10 put PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX there, so every
# DELAY with BASE+WDTH >= 127 read code as its filter pole. seal() now refuses that range.
# The pieces that can land here run on the UI task (partreapply: the UI loop's bug-3 hooks; pattern_led:
# the LED painters' content predicate); trigscale (step handler) fits the cave in every base so far.

o = lambda a: a - BASE

# --- the three bug fixes -----------------------------------------------------------
#   preferred: where the cave goes if that space is free in the base image; otherwise the
#              allocator picks the lowest free run that fits (see place()).
#   detours:   (site, symbol or None for the cave base, expected STOCK bytes, len, kind)
#              kind 'jsr' | 'jmp' | 'jmp18' (jmp + 6 nop, the 18-byte trigscale form).
#   NOTE detours[0] must target the cave BASE -- resolve_present() reads that instruction
#   back out of a base image to learn where an already-present fix was linked.
BUGFIX = {
    "patch_partreapply": (0x400d6500, [
        (0x40062216, None,    "4eb9400326a0", 6, "jsr"),   # tail
        (0x400621da, "cave2", "4eb940020898", 6, "jsr"),   # head, dirty-flag snapshot
    ]),
    "patch_pattern_led": (0x400d6694, [
        (0x4009a464, None, "2f02202f0008", 6, "jmp"),
    ]),
    "patch_trigscale": (0x400d7b00, [
        (0x4009b6f2, None, "203c0000091a", 18, "jmp18"),
    ]),
}

# --- the feature bases: name -> (builder, unit image, VERSTR, blurb) -------------------
#   BATCH_BUGFIXES has no unit: its base is stock.
FEATURES = {
    "MUTE_MODES": ("build_mute_modes.py", "out/mainos_mute_modes.bin", "140C_MM",
                    "PERSONALIZE -> MUTE MODE: OT | OTFX | OTFX-T | DT-T (default OT)."),
    "QUANTIZE_LIVE_REC_TOGGLE": ("build_quantize_live_rec_toggle.py", "out/mainos_quantize_live_rec_toggle.bin", "140C_QLR",
              "Hold [REC] + [PLAY] -> toast shows QUANTIZE LIVE REC; tap [PLAY] "
              "again while it is up to invert it.  (Stateless rewrite after the "
              "0x400522ca tick hook crashed hardware; hardware-confirmed 2026-09-25.)"),
    "SIDECHAIN_COMPRESSOR": ("build_sidechain_compressor.py", "out/mainos_sidechain_compressor.bin", "140C_SC",
                             "COMPRESSOR FX page 2: MON / KEY / KGN / KBAS / KWID (base-width key filter), cross-core."),
    "ERASE_EMPTY_TRIGLESS_LOCKS": ("build_erase_empty_trigless_locks.py", "out/mainos_erase_empty_trigless_locks.bin", "140C_TL",
                 "A trigless lock whose last param is LIVE-erased clears from the trig row."),
    "RELOAD_FROM_PROJECT": ("build_reload_from_project.py", "out/mainos_reload_from_project.bin", "140C_RL",
                "[PTN]+[TRACK n] reload track n's saved sequence; [BANK]+[TRACK n] also reloads that track's Part slice."),
    "DIRECT_JUMP_KYOTI": ("build_direct_jump_kyoti.py", "out/mainos_direct_jump_kyoti.bin", "140C_KDJ7",
                          "hold [PTN], tap [YES] -> DIRECT JUMP on/off (V7.2.2: clock-locked jumps, conditions carry on, Part per track at its first sounding trig)."),
    "REC_TRIG_MUTE": ("build_rec_trig_mute.py", "out/mainos_rec_trig_mute.bin", "140C_RTM",
                      "[TRACK]+[REC] toggles a track's recorder trigs muted; MIDI CC 80; ':' beside the tab letter."),
    "BLACKPYRAMIDS_303": ("build_blackpyramids_303.py", "out/mainos_blackpyramids_303.bin", "140C_BP303",
                          "BLKPYRAMD: a TB-303 voice as a track machine (one per DSP core)."),
    "VARISPEED": ("build_varispeed.py", "out/mainos_varispeed.bin", "140C_VARI1",
                  "STATIC/FLEX TSTR VARI: tempo-locked varispeed, QUAN ratios on PTCH."),
    # carries DSP payload changes (the S950 / SP12 kernel in SPRING REVERB's modules, SPRING off
    # both FX choosers), composed as the SIDECHAIN base is: the image as built, the fixes only
    # in the ColdFire cave zone, every feature byte preserved (the interlock proof)
    "VARISPEED_EMUS": ("build_varispeed_emus.py", "out/mainos_varispeed_emus.bin", "140C_VEM10",
                       "STATIC/FLEX TSTR VARI + EMUS (OT / S950 / SP12), DSP load guard."),
    "BATCH_BUGFIXES": (None, None, "140C_FIXES",
                       "MIDI_PLAYS_FREE_FIX + EMPTY_PATTERN_LED_FIX + PART_CHANGE_CARRYOVER_FIX on stock."),
}
# builder -> the image it gives when run on its own
BUILDERS = {b: n for n, (b, *_r) in FEATURES.items() if b}
BUILDERS.update({"build_midi_plays_free_fix.py": "BATCH_BUGFIXES", "build_empty_pattern_led_fix.py": "BATCH_BUGFIXES",
                 "build_part_change_carryover_fix.py": "BATCH_BUGFIXES", "build_batch_bugfixes.py": "BATCH_BUGFIXES"})
# built by another composer: builder -> its command
ELSEWHERE = {"build_clyps.py": ["tools/build_kyoti.py", "--clyps-standalone"]}
# Bytes a feature writes AT RUNTIME that are zero in its image: no bug-fix cave may cover
# them, though free_runs() would otherwise count them free.
RESERVED = {"REC_TRIG_MUTE": [(0x400d7c3a, 2)]}       # RTM_MASK, RTM_TOAST (build_rec_trig_mute.py)


def unit_dram(name, img, stock):
    """A unit image that carries its own DRAM unit behind tools/dram/'s loader (VARISPEED_EMUS since
    VEM11: its guard's UI section). One image has one loader, so the bug fixes' DRAM pieces must join
    that unit: -> (the stock-length ROM image with the loader's edits undone, the unit's DRAM bytes).
    The append must be exactly what dram.build gives for those bytes on that ROM image (checked).
    Any other image: (img, b"")."""
    if name != "VARISPEED_EMUS":
        return img, b""
    import json
    sy = json.loads((ROOT / f"out/{name.lower()}_syms.json").read_text())
    d = sy.get("dram")
    if not d:
        return img, b""
    raw = (ROOT / d["raw"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != d["sha256"] or d["base"] != dram.ARENA_BASE:
        sys.exit(f"{name}: {d['raw']} is not the DRAM unit out/{name.lower()}_syms.json describes")
    if len(img) <= len(stock):
        sys.exit(f"{name}: its symbols name a DRAM unit, the base image carries none")
    rom = bytearray(img[:len(stock)])
    for at, st, new, what in dram.arena_writes(d["pages"]):
        if bytes(rom[o(at):o(at) + 4]) != new:
            sys.exit(f"{name}: 0x{at:08x} ({what}) is not the loader's edit for {d['pages']} page(s)")
        rom[o(at):o(at) + 4] = st
    if bytes(rom[o(dram.BOOT_SITE):o(dram.BOOT_SITE) + 6]) != b"\x4e\xb9" + dram.LOADER_AT.to_bytes(4, "big"):
        sys.exit(f"{name}: the boot site does not call the loader")
    rom[o(dram.BOOT_SITE):o(dram.BOOT_SITE) + 6] = dram.BOOT_STOCK
    again = bytearray(rom)
    app, _ = dram.build(raw, WORK / "_dram" / f"{name.lower()}_check", again)
    if bytes(again) + app != bytes(img):
        sys.exit(f"{name}: the base image's DRAM append is not tools/dram's own for its DRAM unit")
    print(f"  base carries a DRAM unit: {len(raw):,} B at 0x{dram.ARENA_BASE:08x} -- the bug fixes' DRAM "
          f"pieces are linked behind it, one loader")
    return rom, raw


def reserved(name, img=None):
    """RESERVED, plus, for VARISPEED and VARISPEED_EMUS, EVERY zero byte inside the unit (cave ..
    end, from the builder's symbols): the runtime state -- vem_depth, rk_acc, rp_pb, vg_key,
    vg_last, vg_eng, the flags, em_ctx, ui_switch's sw_st ... -- and the zero words of its tables
    and glyphs alike, so no fix cave can start inside the unit. (VARISPEED reserved only its tail
    state until 2026-10-23, when tools/ui_switch.s joined the unit after it.)"""
    out = list(RESERVED.get(name, []))
    if name in ("VARISPEED", "VARISPEED_EMUS"):
        import json
        sy = json.loads((ROOT / f"out/{name.lower()}_syms.json").read_text())
        if img is None:
            sys.exit(f"reserved({name}) needs the base image")
        if not any(img[o(sy["cave"]):o(sy["end"])]):
            sys.exit(f"{name}: no unit in the base image at its symbols' address")
        if hashlib.sha256(img[o(sy["cave"]):o(sy["end"])]).hexdigest() != sy["unit_sha256"]:
            sys.exit(f"{name}: out/{name.lower()}_syms.json does not describe the base image's unit")
        a = sy["cave"]
        while a < sy["end"]:
            if img[o(a)] == 0:
                b = a
                while b < sy["end"] and img[o(b)] == 0:
                    b += 1
                out.append((a, b - a))
                a = b
            else:
                a += 1
    return out

PROBLEMS = []
# The three bug-fix sources now live in the batch-bugfixes module directory
# (one self-contained folder per octabam module: manifest.py + sources + README.md).
SRC_DIR = {"patch_trigscale": "octabam-modules/batch-bugfixes",
           "patch_pattern_led": "octabam-modules/batch-bugfixes",
           "patch_partreapply": "octabam-modules/batch-bugfixes"}


def flag(msg):
    PROBLEMS.append(msg)
    print(f"  !! {msg}")


def free_runs(img, lo=FREE_START, hi=FREE_END):
    """Zero runs of >=16 B inside the cave free zone (or lo..hi) of `img`."""
    runs, cur = [], None
    for i in range(o(lo), o(hi)):
        if img[i] == 0:
            if cur is None:
                cur = i
        else:
            if cur is not None and i - cur >= 16:
                runs.append([cur + BASE, i + BASE])
            cur = None
    if cur is not None and o(hi) - cur >= 16:
        runs.append([cur + BASE, hi])
    return runs


def place(runs, size, preferred):
    """Reserve `size` B from `runs` (mutated). Use `preferred` if it is free, else the
    lowest run that fits. Returns the address, or None if nothing fits."""
    for r in runs:
        if r[0] <= preferred and preferred + size <= r[1]:
            lo, hi = r[0], r[1]
            r[0], r[1] = preferred + size, hi          # keep the tail
            if lo < preferred:
                runs.append([lo, preferred])           # give the head back
                runs.sort()
            return preferred
    for r in runs:
        at = (r[0] + 3) & ~3
        if at + size <= r[1]:
            r[0] = at + size
            return at
    return None


def resolve_present(img, stem):
    """A bug fix already in `img`: read its cave address out of its first detour."""
    site = BUGFIX[stem][1][0][0]
    return int.from_bytes(img[o(site) + 2:o(site) + 6], "big")


def assert_no_branch_into(img, site, n, window=0x600):
    """Refuse a detour whose displaced bytes contain a branch TARGET (from build_erase_empty_trigless_locks.py)."""
    lo, hi = o(site) - window, o(site) + window
    bad, a = [], max(lo, 0)
    while a < min(hi, len(img) - 4):
        op = int.from_bytes(img[a:a + 2], "big")
        if 0x6000 <= op <= 0x6FFF:
            d8 = op & 0xFF
            if d8 == 0x00:
                disp = int.from_bytes(img[a + 2:a + 4], "big")
                disp -= 0x10000 if disp & 0x8000 else 0
            elif d8 == 0xFF:
                disp = int.from_bytes(img[a + 4:a + 8], "big")
                disp -= 0x100000000 if disp & 0x80000000 else 0
            else:
                disp = d8 - 0x100 if d8 & 0x80 else d8
            tgt = BASE + a + 2 + disp
            if site < tgt < site + n:
                bad.append((BASE + a, tgt))
        a += 2
    if bad:
        detail = ", ".join(f"0x{s:08x} -> 0x{t:08x}" for s, t in bad)
        sys.exit(f"REFUSING detour at 0x{site:08x}: a branch lands inside the displaced "
                 f"{n} bytes ({detail}).")


def link(stem, at):
    """Assemble + link one patch at `at`; return (blob, symbols)."""
    WORK.mkdir(parents=True, exist_ok=True)
    obj, elf, binf = WORK / f"{stem}.o", WORK / f"{stem}.elf", WORK / f"{stem}.bin"
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", str(obj),
                    f"{SRC_DIR.get(stem, 'tools')}/{stem}.s"],
                   check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", str(elf), str(obj)],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", str(elf), str(binf)],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", str(elf)], capture_output=True, text=True,
                        cwd=ROOT).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return binf.read_bytes(), syms


def apply_bugfixes(img, which, label, addrs):
    """Write the named bug-fix caves + detours into `img` at addrs[stem]."""
    rep = []
    for stem in which:
        at, detours = addrs[stem], BUGFIX[stem][1]
        blob, syms = link(stem, at)
        in_dram = at >= dram.ARENA_BASE           # linked there; the loader carries it (main())
        if not (FREE_START <= at and at + len(blob) <= FREE_END or in_dram):
            sys.exit(f"{label}: {stem} cave 0x{at:08x}+{len(blob)} escapes the free zone")
        co = o(at)
        if not in_dram and any(img[co:co + len(blob)]):
            sys.exit(f"{label}: cave for {stem} at 0x{at:08x} is NOT free in the base image: "
                     f"{bytes(img[co:co+16]).hex()}")
        for site, sym, expect_hex, n, kind in detours:
            expect = bytes.fromhex(expect_hex)
            got = bytes(img[o(site):o(site) + len(expect)])
            if got != expect:
                sys.exit(f"{label}: detour site 0x{site:08x} for {stem} is not stock: "
                         f"{got.hex()} != {expect.hex()} (the feature may already own it)")
            assert_no_branch_into(img, site, n)
        if not in_dram:
            img[co:co + len(blob)] = blob
        for site, sym, expect_hex, n, kind in detours:
            tgt = syms[sym] if sym else at
            if kind == "jsr":
                img[o(site):o(site) + 6] = b"\x4e\xb9" + tgt.to_bytes(4, "big")
            elif kind == "jmp":
                img[o(site):o(site) + 6] = b"\x4e\xf9" + tgt.to_bytes(4, "big")
            elif kind == "jmp18":
                img[o(site):o(site) + 18] = (b"\x4e\xf9" + tgt.to_bytes(4, "big")
                                             + b"\x4e\x71" * 6)
            rep.append(f"    0x{site:08x} -> {stem}:{sym or 'cave'} 0x{tgt:08x}  ({kind}, {n} B)")
        rep.insert(len(rep) - len(detours),
                   f"  {stem:<20} {len(blob):4d} B @ 0x{at:08x} .. 0x{at+len(blob):08x}")
    return rep


def delta(a, b):
    """Byte positions where a and b differ -> {offset: value_in_b}. A longer b (BLACKPYRAMIDS_303
    appends its DRAM loader and runtime after the OS) counts every byte past a's end as changed."""
    d = {i: b[i] for i in range(min(len(a), len(b))) if a[i] != b[i]}
    d.update({i: b[i] for i in range(len(a), len(b))})
    return d


def wrap(mainos, name, verstr, blurb, outdir):
    if not EFT.exists() or not STOCK_SYX.exists():
        flag(f"{name}: EFT tool or stock .syx missing -- no .syx/.bin wrap produced")
        return
    if len(verstr) > 10:
        sys.exit(f"{name}: VERSTR {verstr!r} is {len(verstr)} chars, ELEK field caps at 10")
    elek = WORK / f"elek_{name.lower()}.bin"
    syx = outdir / f"OCTATRACK_OS1.40C_{name}.syx"
    binf = outdir / f"OCTATRACK_{name}.bin"
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(elek))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(mainos),
                        "-V", verstr, "-o", str(syx)],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"{name}: EFT wrap failed:\n{r.stdout}\n{r.stderr}")
    subprocess.run(["python3", "tools/make_bin.py", str(elek), "-o", str(binf)],
                   check=True, cwd=ROOT, capture_output=True)
    chk = subprocess.run([str(EFT), str(syx)], capture_output=True, text=True, cwd=ROOT)
    ok = "OK" if chk.returncode == 0 else "PARSE FAILED"
    if chk.returncode != 0:
        flag(f"{name}: .syx container does not re-parse")
    print(f"  wrapped  {binf.name}  +  {syx.name}   version {verstr}   round-trip {ok}")
    print(f"           {blurb}")


def flashables():
    """The flashable files at the top of out/, with their mtimes."""
    out = ROOT / "out"
    return {f: f.stat().st_mtime for f in list(out.glob("OCTATRACK_*.syx")) + list(out.glob("OCTATRACK_*.bin"))}


def run_unit(name, builder):
    """The feature alone (KYOTI_UNIT=1): out/mainos_<feature>.bin. Whatever flashable file the unit run
    wrapped is deleted -- no image without the bug fixes is left to flash."""
    before = flashables()
    env = dict(os.environ, KYOTI_UNIT="1")
    r = subprocess.run([sys.executable, f"tools/{builder}"], capture_output=True, text=True, cwd=ROOT, env=env)
    for f, t in flashables().items():
        if before.get(f) != t:
            f.unlink()
    if r.returncode != 0:
        sys.exit(f"{name}: unit build {builder} failed:\n{r.stdout}\n{r.stderr}")
    print("\n".join("  | " + l for l in r.stdout.rstrip().splitlines()[-4:]))


def compose(name, builder, basepath, verstr, blurb, stock, rebuild=True):
    """One feature image: the feature's unit + the bug-fix caves, checked, sealed and wrapped."""
    if name != "BATCH_BUGFIXES":
        feature_exclusions.check(name.split("+"), who=f"feature_image {name}: ")
    print(f"════════════ {name} (with the three bug fixes) ════════════")
    unit_raw = b""
    if builder is None:
        img = bytearray(stock)
    else:
        if rebuild:
            run_unit(name, builder)
        base = ROOT / basepath
        if not base.exists():
            sys.exit(f"{name}: missing unit image {base} -- run KYOTI_UNIT=1 tools/{builder}")
        img = bytearray(base.read_bytes())
    img, unit_raw = unit_dram(name, img, stock)
    outdir = ROOT / "out" / name
    outdir.mkdir(parents=True, exist_ok=True)
    feat_d = delta(stock, img)

    # --- who is already here, and where does each cave go? -----------------------
    need, already, addrs = [], [], {}
    for stem, (pref, detours) in BUGFIX.items():
        site, _, expect_hex, _, _ = detours[0]
        expect = bytes.fromhex(expect_hex)
        if bytes(img[o(site):o(site) + len(expect)]) == expect:
            need.append(stem)
        else:
            already.append(stem)
            addrs[stem] = resolve_present(img, stem)     # honour where IT put it
    runs = free_runs(img)
    dram_at, dram_pieces = (dram.ARENA_BASE + len(unit_raw) + 3) & ~3, []
    res = reserved(name, bytes(img))        # (from the base, before any fix is written)
    for at, n in res:                       # carve out runtime-written bytes
        cut = []
        for r in runs:
            if r[0] < at + n and at < r[1]:
                cut += [x for x in ([r[0], at], [at + n, r[1]]) if x[1] - x[0] >= 16]
            else:
                cut.append(r)
        runs = sorted(cut)
    for stem in sorted(need, key=lambda s: -len(link(s, BUGFIX[s][0])[0])):
        size = len(link(stem, BUGFIX[stem][0])[0])
        at = place(runs, size, BUGFIX[stem][0])
        if at is None:                      # the cave is full: a DRAM unit (above)
            if stem == "patch_trigscale":
                sys.exit(f"{name}: no cave run fits {stem} ({size} B), and it is step-handler code")
            at, dram_at = dram_at, (dram_at + size + 3) & ~3
            dram_pieces.append(stem)
        addrs[stem] = at
    moved = [f"{s} -> 0x{addrs[s]:08x} (preferred 0x{BUGFIX[s][0]:08x} was taken)"
             for s in need if addrs[s] != BUGFIX[s][0]]
    for m in moved:
        print(f"  relocated: {m}")
    print(f"  base {basepath or 'stock'}: {len(feat_d)} B vs stock; "
          f"already present: {', '.join(already) or 'none'}; "
          f"adding: {', '.join(need) or 'none'}")

    # --- reference: the three fixes alone, on stock, at THESE addresses -----------
    ref_per = {}
    for stem in BUGFIX:
        one = bytearray(stock)
        apply_bugfixes(one, [stem], f"{name}/ref", addrs)
        ref_per[stem] = delta(stock, one)
    for x in BUGFIX:
        for y in BUGFIX:
            if x < y and set(ref_per[x]) & set(ref_per[y]):
                sys.exit(f"{name}: bug fixes {x} and {y} overlap each other")
    ref_all = {k: v for d in ref_per.values() for k, v in d.items()}

    for line in apply_bugfixes(img, need, name, addrs):
        print(line)
    comp_d = delta(stock, img)

    # --- interlock proof ----------------------------------------------------------
    new_d = {k: v for d in (ref_per[s] for s in need) for k, v in d.items()}
    clash = sorted(set(feat_d) & set(new_d))
    if clash:
        flag(f"{name}: {len(clash)} byte(s) claimed by BOTH the feature and a bug fix, "
             f"first at 0x{BASE + clash[0]:08x}")
    broke = sorted(k for k, v in feat_d.items() if comp_d.get(k) != v)
    if broke:
        flag(f"{name}: composite altered {len(broke)} feature byte(s), "
             f"first at 0x{BASE + broke[0]:08x}")
    mism = sorted(k for k, v in ref_all.items() if comp_d.get(k) != v)
    if mism:
        flag(f"{name}: {len(mism)} bug-fix byte(s) differ from the stock-only reference, "
             f"first at 0x{BASE + mism[0]:08x}")
    extra = sorted(k for k in comp_d if k not in feat_d and k not in ref_all)
    if extra:
        flag(f"{name}: {len(extra)} byte(s) belong to no contributor, "
             f"first at 0x{BASE + extra[0]:08x}")
    for at, n in res:
        if any(img[o(at):o(at) + n]):
            flag(f"{name}: runtime byte(s) 0x{at:08x}+{n} are no longer 0 in the composite")
            extra = extra or [o(at)]
    clean = not (clash or broke or mism or extra)
    print(f"  interlock: feature {len(feat_d)} B + bug fixes {len(ref_all)} B "
          f"-> composite {len(comp_d)} B   "
          f"{'DISJOINT, ALL PRESERVED, NO STRAYS' if clean else '*** SEE FLAGS ***'}")
    left = sum(r[1] - r[0] for r in free_runs(img))
    print(f"  cave zone: {left} B still free")

    if dram_pieces or unit_raw:         # after the interlock proof (it compares stock-length images)
        raw = bytearray(unit_raw)       # the unit's own DRAM unit first, where it was linked
        for stem in dram_pieces:
            off = addrs[stem] - dram.ARENA_BASE
            raw += bytes(off - len(raw)) + link(stem, addrs[stem])[0]
        append, r = dram.build(bytes(raw), WORK / "_dram" / name.lower(), img)
        img.extend(append)
        who = (["the unit's own"] if unit_raw else []) + dram_pieces
        print(f"  DRAM: {', '.join(who)} -- "
              f"{r['raw']:,} B linked at 0x{r['base']:08x}; "
              f"{r['pages']} arena page(s) = {r['reserve_bytes']:,} B of the sample pool; "
              f"loader + payload {r['append']:,} B at 0x{dram.LOADER_AT:08x}")
    mainos = outdir / f"mainos_{name.lower()}.bin"
    mainos.write_bytes(bytes(img))
    if PROBLEMS:
        sys.exit(f"{name}: {len(PROBLEMS)} problem(s), not sealed or wrapped:\n  - " + "\n  - ".join(PROBLEMS))
    seal(__file__, mainos)              # FINAL["feature_image.py"][mainos_<feature>.bin]
    print(f"  wrote    {mainos.relative_to(ROOT)}  sha256 {hashlib.sha256(bytes(img)).hexdigest()}  "
          f"({len(img):,} B, {len(comp_d)} changed vs stock)")
    wrap(mainos, name, verstr, blurb, outdir)
    for f in (outdir / f"OCTATRACK_OS1.40C_{name}.syx", outdir / f"OCTATRACK_{name}.bin"):
        if f.exists():
            print(f"  {f.relative_to(ROOT)}  sha256 {hashlib.sha256(f.read_bytes()).hexdigest()}")
    print()


def standalone(builder):
    """kyoti_status.gate()'s hand-off: `builder` was run on its own -> its feature image."""
    if builder in ELSEWHERE:
        r = subprocess.run([sys.executable, *ELSEWHERE[builder]], cwd=ROOT)
        sys.exit(r.returncode)
    name = BUILDERS[builder]
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    WORK.mkdir(parents=True, exist_ok=True)
    builder_, basepath, verstr, blurb = FEATURES[name]
    # a WIP test image may name itself (KYOTI_VERSTR, as build_kyoti.py; 2026-11-16): the OS VERSION is applied at
    # the wrap only, so the mainos -- and its pin -- are the same either way
    verstr = os.environ.get("KYOTI_VERSTR") or verstr
    compose(name, builder_, basepath, verstr, blurb, STOCK_SECT.read_bytes())
    sys.exit(0)



def main():
    """Every feature image (or --only NAME,...): a sweep."""
    rebuild = "--no-rebuild" not in sys.argv
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    stock = STOCK_SECT.read_bytes()
    WORK.mkdir(parents=True, exist_ok=True)
    only = None
    if "--only" in sys.argv:
        k = sys.argv.index("--only")
        only = (sys.argv[k + 1] if k + 1 < len(sys.argv) else "").split(",")
        if not only or set(only) - set(FEATURES):
            sys.exit(f"--only {','.join(only)}: names must be among {', '.join(FEATURES)}")
    for name, (builder, basepath, verstr, blurb) in FEATURES.items():
        if only is None or name in only:
            compose(name, builder, basepath, verstr, blurb, stock, rebuild)
    print("  no problems flagged")


if __name__ == "__main__":
    main()
