#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Bugbuilds -- each finished FEATURE build, with all three BUG FIXES folded in.

Ten composite images, written ONLY to out/Bugbuilds/ (they do not replace, and are
not written alongside, the standalone per-feature images in out/):

    MUTE_MODES        + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    QUANTIZE_LIVE_REC_TOGGLE              + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    SIDECHAIN_COMPRESSOR   + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    ERASE_EMPTY_TRIGLESS_LOCKS           + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    RELOAD_FROM_PROJECT            + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    DIRECT_JUMP_KYOTI      + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    REC_TRIG_MUTE          + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    BLACKPYRAMIDS_303      + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    VARISPEED              + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    VARISPEED_EMUS         + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX

Method -- compose onto the finished feature image, do not re-implement it.
Each feature builder is run first (so the base is current), then the bug-fix caves are
linked into free space in that image and their detours applied.  SIDE-CHAIN in particular
is never re-derived: its DSP payloads, COMPRESSOR descriptor and FX2 chooser edits come
through untouched, and its cave stays at its own address so the descriptor's formatter
pointers stay valid. VARISPEED_EMUS's DSP payload edits (the S950 / SP12 kernel in SPRING
REVERB's modules) come through the same way.

MIDI_PLAYS_FREE_FIX (patch_trigscale) is added to ALL TEN images: no feature builder carries a copy
any more.  Each of them used to (RELOAD_FROM_PROJECT's sat at 0x400d7bfc, the rest at 0x400d7b00), and
every copy wrote the same site 0x4009b6f2 -- which octabam's remix ledger refuses, so no two
of those features could ever be selected into one remix.  The fix is its own contribution
now (the batch-bugfixes module upstream) and this composer is where a combined image gets it.
Nothing here needed changing for that: `already`/`need` are computed per image by scanning
for each fix's detour, so the bases simply all report "already present: none".

Cave layout, where each fix is placed if that space is free in the base (it is in all but
RELOAD_FROM_PROJECT, whose own cave starts at 0x400d6500, so the allocator moves the two fixes up):

    patch_partreapply   0x400d6500   402 B   (RELOAD_FROM_PROJECT: relocated above its own cave)
    patch_pattern_led   0x400d6694   158 B   (RELOAD_FROM_PROJECT: likewise)
    (never below 0x400d6500 -- 0x400d64ca.. is a runtime record table, kb/caves.md 2b)
    patch_trigscale     0x400d7b00    62 B   (added to all ten)

Verification (every image, every run):
  * the feature's builder is promoted (on kyoti_status.FINAL), its rebuilt image still matches, and it is re-run
    first so the base is built from the current source (--no-rebuild skips that);
  * each cave region is all-zero in the base before it is written, and never covers a byte a
    feature writes at runtime (RESERVED: REC_TRIG_MUTE's RTM_MASK is zero in the image);
  * each detour site still holds the exact stock bytes (proves no feature took it first);
  * assert_no_branch_into on every detour site (build_erase_empty_trigless_locks.py's guard, promoted here);
  * COMPOSITIONALITY: the composite's byte-delta vs stock is exactly the union of the
    feature's delta and a reference "bug-fixes only, at these same addresses, on stock"
    delta -- and those two deltas are disjoint.  That is the interlock proof: every
    changed byte has exactly one owner and no owner's bytes were altered.

Usage:  python3 tools/build_bugbuilds.py [--no-rebuild] [--only NAME[,NAME...]]

--only builds just those Bugbuilds (FEATURES names, e.g. --only VARISPEED,VARISPEED_EMUS).

WIP OPT-IN, for one base at a time:

    KYOTI_ALLOW_WIP=1 python3 tools/build_bugbuilds.py --wip NAME

builds ONLY that base's Bugbuild (WIP_FEATURES below, empty while no WIP base is wired in),
with every check above except the promotion ones: its builder is WIP and is run with the
opt-in, the result is announced as WIP, and it is NEVER sealed (kyoti_status.seal is not
called, so it can never pass for a promoted image). Without KYOTI_ALLOW_WIP=1 it refuses. A
run without --wip is unchanged: the final Bugbuilds, and any base not on FINAL is skipped.
"""
import os, pathlib, subprocess, sys
import hashlib
from kyoti_status import gate, seal, FINAL

gate(__file__)

BASE = 0x40000400
ROOT = pathlib.Path(__file__).parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUTDIR = ROOT / "out/Bugbuilds"
WORK = OUTDIR / "_work"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
# From 0x400d6500, not the zero run's start 0x400d64da: 0x400d64ca is a runtime table of
# 24-byte records (fields +0x10/+0x14 written by 0x40001732; 0x400d64e2 its terminator) --
# reference/kb/caves.md 2b.  Every flashed build starts at 0x400d6500.
FREE_START, FREE_END = 0x400d6500, 0x400d7c3c
# The fallback when nothing in the cave fits (2026-10-23: VARISPEED_EMUS leaves 152 B): midisc's
# SAFE_CAVE, hardware-proven in every KYOTI image since V1.1 (build_kyoti.py ZONES["SAFE"]; stock
# references 0x400d2cdc). Only ever used when the cave has no room, so the other Bugbuilds keep
# their bytes.
SAFE_START, SAFE_END = 0x400d24d0, 0x400d2cdc

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

# --- the feature bases: name -> (builder, base image, VERSTR, blurb) -------------------
#   A base is used only while its builder is on kyoti_status.FINAL, and a rebuilt base that
#   no longer matches its promoted image is flagged (it carries unpromoted changes).
FEATURES = {
    "MUTE_MODES": ("build_mute_modes.py", "out/mainos_mute_modes.bin", "BUG_MUTEDT",
                    "PERSONALIZE -> MUTE MODE: OT | OTFX | OTFX-T | DT-T (default OT)."),
    "QUANTIZE_LIVE_REC_TOGGLE": ("build_quantize_live_rec_toggle.py", "out/mainos_quantize_live_rec_toggle.bin", "BUG_QLREC",
              "Hold [REC] + [PLAY] -> toast shows QUANTIZE LIVE REC; tap [PLAY] "
              "again while it is up to invert it.  (Stateless rewrite after the "
              "0x400522ca tick hook crashed hardware; hardware-confirmed 2026-09-25.)"),
    "SIDECHAIN_COMPRESSOR": ("build_sidechain_compressor.py", "out/mainos_sidechain_compressor.bin", "BUG_SC3X",
                             "COMPRESSOR FX page 2: MON / KEY / KGN / KBAS / KWID (base-width key filter), cross-core."),
    "ERASE_EMPTY_TRIGLESS_LOCKS": ("build_erase_empty_trigless_locks.py", "out/mainos_erase_empty_trigless_locks.bin", "BUG_TRIGLK",
                 "A trigless lock whose last param is LIVE-erased clears from the trig row."),
    "RELOAD_FROM_PROJECT": ("build_reload_from_project.py", "out/mainos_reload_from_project.bin", "BUG_RL3",
                "[PTN]+[TRACK n] reload track n's saved sequence; [BANK]+[TRACK n] also re-applies the Part."),
    "DIRECT_JUMP_KYOTI": ("build_direct_jump_kyoti.py", "out/mainos_direct_jump_kyoti.bin", "BUG_DJV7", "hold [PTN], tap [YES] -> DIRECT JUMP on/off (V7.0.1, clock-locked jumps)."),
    "REC_TRIG_MUTE": ("build_rec_trig_mute.py", "out/mainos_rec_trig_mute.bin", "BUG_RTM",
                      "[TRACK]+[REC] toggles a track's recorder trigs muted; MIDI CC 80; '..' edge icon."),
    "BLACKPYRAMIDS_303": ("build_blackpyramids_303.py", "out/mainos_blackpyramids_303.bin", "BUG_BP303",
                          "BLKPYRAMD: a TB-303 voice as a track machine (one per DSP core)."),
    "VARISPEED": ("build_varispeed.py", "out/mainos_varispeed.bin", "BUG_VARI",
                  "STATIC/FLEX TSTR VARI: tempo-locked varispeed, QUAN ratios on PTCH."),
    # carries DSP payload changes (the S950 / SP12 kernel in SPRING REVERB's modules, SPRING off
    # both FX choosers), composed as the SIDECHAIN base is: the image as built, the fixes only
    # in the ColdFire cave zone, every feature byte preserved (the interlock proof)
    "VARISPEED_EMUS": ("build_varispeed_emus.py", "out/mainos_varispeed_emus.bin", "BUG_VEM10",
                       "STATIC/FLEX TSTR VARI + EMUS (OT / S950 / SP12), DSP load guard."),
}
# WIP bases, composed ONLY with the explicit opt-in `--wip NAME` (and KYOTI_ALLOW_WIP=1): one
# per run, never sealed, never part of the default run above.
WIP_FEATURES = {}
# Bytes a feature writes AT RUNTIME that are zero in its image: no bug-fix cave may cover
# them, though free_runs() would otherwise count them free.
RESERVED = {"REC_TRIG_MUTE": [(0x400d7c3a, 1)]}       # RTM_MASK (build_rec_trig_mute.py)


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
        if not (FREE_START <= at and at + len(blob) <= FREE_END
                or SAFE_START <= at and at + len(blob) <= SAFE_END):
            sys.exit(f"{label}: {stem} cave 0x{at:08x}+{len(blob)} escapes the free zone")
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"{label}: cave for {stem} at 0x{at:08x} is NOT free in the base image: "
                     f"{bytes(img[co:co+16]).hex()}")
        for site, sym, expect_hex, n, kind in detours:
            expect = bytes.fromhex(expect_hex)
            got = bytes(img[o(site):o(site) + len(expect)])
            if got != expect:
                sys.exit(f"{label}: detour site 0x{site:08x} for {stem} is not stock: "
                         f"{got.hex()} != {expect.hex()} (the feature may already own it)")
            assert_no_branch_into(img, site, n)
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


def wrap(mainos, name, verstr, blurb):
    if not EFT.exists() or not STOCK_SYX.exists():
        flag(f"{name}: EFT tool or stock .syx missing -- no .syx/.bin wrap produced")
        return
    if len(verstr) > 10:
        sys.exit(f"{name}: VERSTR {verstr!r} is {len(verstr)} chars, ELEK field caps at 10")
    elek = WORK / f"elek_{name.lower()}.bin"
    syx = OUTDIR / f"OCTATRACK_OS1.40C_{name}_BATCH_BUGFIXES.syx"
    binf = OUTDIR / f"OCTATRACK_{name}_BATCH_BUGFIXES.bin"
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


def compose(name, builder, basepath, verstr, blurb, stock, rebuild, wip=False):
    """One Bugbuild: the feature's image + the bug-fix caves, checked and wrapped."""
    if not wip and builder not in FINAL:
        print(f"---- {name}: {builder} is not promoted to FINAL -- skipped\n")
        return
    print(f"════════════ {name} + BATCH_BUGFIXES ════════════" + ("   (WIP)" if wip else ""))
    if rebuild:
        r = subprocess.run(["python3", f"tools/{builder}"], capture_output=True,
                           text=True, cwd=ROOT)
        if r.returncode != 0:
            sys.exit(f"{name}: feature builder {builder} failed:\n{r.stdout}\n{r.stderr}")
    base = ROOT / basepath
    if not base.exists():
        sys.exit(f"{name}: missing base image {base} -- run tools/{builder}")
    img = bytearray(base.read_bytes())
    if wip:
        print(f"  WIP base: {builder} is not promoted; this Bugbuild is WIP and is not sealed")
    elif hashlib.sha256(bytes(img)).hexdigest() != FINAL[builder]:
        flag(f"{name}: the base image is not {builder}'s promoted build -- it carries "
             "unpromoted changes")
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
    safe = free_runs(img, SAFE_START, SAFE_END)
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
        if at is None:                      # the cave is full: SAFE_CAVE
            at = place(safe, size, SAFE_START)
        if at is None:
            sys.exit(f"{name}: no free run fits {stem} ({size} B). Free: "
                     + ", ".join(f"0x{r[0]:08x}+{r[1]-r[0]}" for r in runs))
        addrs[stem] = at
    moved = [f"{s} -> 0x{addrs[s]:08x} (preferred 0x{BUGFIX[s][0]:08x} was taken)"
             for s in need if addrs[s] != BUGFIX[s][0]]
    for m in moved:
        print(f"  relocated: {m}")
    print(f"  base {base.name}: {len(feat_d)} B vs stock; "
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

    mainos = OUTDIR / f"mainos_{name.lower()}_batch_bugfixes.bin"
    mainos.write_bytes(bytes(img))
    if not wip:                         # a WIP Bugbuild is never sealed
        seal(__file__, mainos)
    print(f"  wrote    {mainos.relative_to(ROOT)}  "
          f"({len(img):,} B, {len(comp_d)} changed vs stock)")
    wrap(mainos, name, verstr, blurb)
    print()



def main():
    rebuild = "--no-rebuild" not in sys.argv
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    stock = STOCK_SECT.read_bytes()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    wip = None
    if "--wip" in sys.argv:
        k = sys.argv.index("--wip")
        wip = sys.argv[k + 1] if k + 1 < len(sys.argv) else ""
        if wip not in WIP_FEATURES:
            sys.exit(f"--wip {wip!r}: not a WIP base this composer knows ({', '.join(WIP_FEATURES)})")
        if os.environ.get("KYOTI_ALLOW_WIP") != "1":
            print(f"\n  Refusing to build: --wip {wip} composes a work-in-progress base, and an image\n"
                  f"  built from it is not something to flash. If you meant it, set KYOTI_ALLOW_WIP=1:\n\n"
                  f"      KYOTI_ALLOW_WIP=1 python3 tools/build_bugbuilds.py --wip {wip}\n", file=sys.stderr)
            sys.exit(2)
        print("  " + "-" * 72)
        print(f"  WIP Bugbuild: {wip} only -- not promoted, not sealed, not one of the final seven")
        print("  " + "-" * 72 + "\n")
        compose(wip, *WIP_FEATURES[wip], stock, rebuild, wip=True)
    else:
        only = None
        if "--only" in sys.argv:
            k = sys.argv.index("--only")
            only = (sys.argv[k + 1] if k + 1 < len(sys.argv) else "").split(",")
            if not only or set(only) - set(FEATURES):
                sys.exit(f"--only {','.join(only)}: names must be among {', '.join(FEATURES)}")
        for name, (builder, basepath, verstr, blurb) in FEATURES.items():
            if only is None or name in only:
                compose(name, builder, basepath, verstr, blurb, stock, rebuild)

    print("════════════════════ summary ════════════════════")
    if PROBLEMS:
        print(f"  {len(PROBLEMS)} problem(s) flagged:")
        for q in PROBLEMS:
            print(f"    - {q}")
        sys.exit(1)
    print("  no problems flagged")


if __name__ == "__main__":
    main()
