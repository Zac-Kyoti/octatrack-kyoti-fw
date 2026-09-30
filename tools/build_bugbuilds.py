#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Bugbuilds -- each finished FEATURE build, with all three BUG FIXES folded in.

Seven composite images, written ONLY to out/Bugbuilds/ (they do not replace, and are
not written alongside, the standalone per-feature images in out/):

    MUTE_MODES        + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    QUANTIZE_LIVE_REC_TOGGLE              + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    SIDECHAIN_COMPRESSOR   + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    ERASE_EMPTY_TRIGLESS_LOCKS           + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    RELOAD_FROM_PROJECT            + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    DIRECT_JUMP_KYOTI      + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX
    REPITCH_REPEAT98_KYOTI      + PART_CHANGE_CARRYOVER_FIX + EMPTY_PATTERN_LED_FIX + MIDI_PLAYS_FREE_FIX

Method -- compose onto the finished feature image, do not re-implement it.
Each feature builder is run first (so the base is current), then the bug-fix caves are
linked into free space in that image and their detours applied.  SIDE-CHAIN in particular
is never re-derived: its DSP payloads, COMPRESSOR descriptor and FX2 chooser edits come
through untouched, and its cave stays at its own address so the descriptor's formatter
pointers stay valid.

MIDI_PLAYS_FREE_FIX (patch_trigscale) is added to ALL SEVEN images: no feature builder carries a copy
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
    patch_trigscale     0x400d7b00    62 B   (added to all seven; REPITCH_REPEAT98_KYOTI's cave
                                              ends at 0x400d7afc, right below it)

Verification (every image, every run):
  * the feature's builder is promoted (on kyoti_status.FINAL), its rebuilt image still matches, and it is re-run
    first so the base is built from the current source (--no-rebuild skips that);
  * each cave region is all-zero in the base before it is written;
  * each detour site still holds the exact stock bytes (proves no feature took it first);
  * assert_no_branch_into on every detour site (build_erase_empty_trigless_locks.py's guard, promoted here);
  * COMPOSITIONALITY: the composite's byte-delta vs stock is exactly the union of the
    feature's delta and a reference "bug-fixes only, at these same addresses, on stock"
    delta -- and those two deltas are disjoint.  That is the interlock proof: every
    changed byte has exactly one owner and no owner's bytes were altered.

Usage:  python3 tools/build_bugbuilds.py [--no-rebuild]
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
    "SIDECHAIN_COMPRESSOR": ("build_sidechain_compressor.py", "out/mainos_sidechain_compressor.bin", "BUG_SC3X", "COMPRESSOR FX page 2: KEY / KFLT / KGAIN / MON, cross-core."),
    "ERASE_EMPTY_TRIGLESS_LOCKS": ("build_erase_empty_trigless_locks.py", "out/mainos_erase_empty_trigless_locks.bin", "BUG_TRIGLK",
                 "A trigless lock whose last param is LIVE-erased clears from the trig row."),
    "RELOAD_FROM_PROJECT": ("build_reload_from_project.py", "out/mainos_reload_from_project.bin", "BUG_RL3",
                "[PTN]+[TRACK n] reload track n's saved sequence; [BANK]+[TRACK n] also re-applies the Part."),
    "DIRECT_JUMP_KYOTI": ("build_direct_jump_kyoti.py", "out/mainos_direct_jump_kyoti.bin", "BUG_DJV7", "hold [PTN], tap [YES] -> DIRECT JUMP on/off (V7.0.1, clock-locked jumps)."),
    "REPITCH_REPEAT98_KYOTI": ("build_repitch_repeat98_kyoti.py", "out/mainos_repitch_repeat98_kyoti.bin", "BUG_RPK16", "SETUP TSTR RPCH/RPS9/RPSP: tempo-locked varispeed + QUAN ratios "
                             "(rev 16).  Removes SPRING REVERB."),
}

PROBLEMS = []
# The three bug-fix sources now live in the batch-bugfixes module directory
# (one self-contained folder per octabam module: manifest.py + sources + README.md).
SRC_DIR = {"patch_trigscale": "octabam-modules/batch-bugfixes",
           "patch_pattern_led": "octabam-modules/batch-bugfixes",
           "patch_partreapply": "octabam-modules/batch-bugfixes"}


def flag(msg):
    PROBLEMS.append(msg)
    print(f"  !! {msg}")


def free_runs(img):
    """Zero runs of >=16 B inside the cave free zone of `img`."""
    runs, cur = [], None
    for i in range(o(FREE_START), o(FREE_END)):
        if img[i] == 0:
            if cur is None:
                cur = i
        else:
            if cur is not None and i - cur >= 16:
                runs.append([cur + BASE, i + BASE])
            cur = None
    if cur is not None and o(FREE_END) - cur >= 16:
        runs.append([cur + BASE, FREE_END])
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
        if at < FREE_START or at + len(blob) > FREE_END:
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
    """Byte positions where a and b differ -> {offset: value_in_b}."""
    return {i: b[i] for i in range(len(a)) if a[i] != b[i]}


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


def main():
    rebuild = "--no-rebuild" not in sys.argv
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    stock = STOCK_SECT.read_bytes()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    for name, (builder, basepath, verstr, blurb) in FEATURES.items():
        if builder not in FINAL:
            print(f"---- {name}: {builder} is not promoted to FINAL -- skipped\n")
            continue
        print(f"════════════ {name} + BATCH_BUGFIXES ════════════")
        if rebuild:
            r = subprocess.run(["python3", f"tools/{builder}"], capture_output=True,
                               text=True, cwd=ROOT)
            if r.returncode != 0:
                sys.exit(f"{name}: feature builder {builder} failed:\n{r.stdout}\n{r.stderr}")
        base = ROOT / basepath
        if not base.exists():
            sys.exit(f"{name}: missing base image {base} -- run tools/{builder}")
        img = bytearray(base.read_bytes())
        if hashlib.sha256(bytes(img)).hexdigest() != FINAL[builder]:
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
        for stem in sorted(need, key=lambda s: -len(link(s, BUGFIX[s][0])[0])):
            size = len(link(stem, BUGFIX[stem][0])[0])
            at = place(runs, size, BUGFIX[stem][0])
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
        clean = not (clash or broke or mism or extra)
        print(f"  interlock: feature {len(feat_d)} B + bug fixes {len(ref_all)} B "
              f"-> composite {len(comp_d)} B   "
              f"{'DISJOINT, ALL PRESERVED, NO STRAYS' if clean else '*** SEE FLAGS ***'}")
        left = sum(r[1] - r[0] for r in free_runs(img))
        print(f"  cave zone: {left} B still free")

        mainos = OUTDIR / f"mainos_{name.lower()}_batch_bugfixes.bin"
        mainos.write_bytes(bytes(img))
        seal(__file__, mainos)
        print(f"  wrote    {mainos.relative_to(ROOT)}  "
              f"({len(img):,} B, {len(comp_d)} changed vs stock)")
        wrap(mainos, name, verstr, blurb)
        print()

    print("════════════════════ summary ════════════════════")
    if PROBLEMS:
        print(f"  {len(PROBLEMS)} problem(s) flagged:")
        for q in PROBLEMS:
            print(f"    - {q}")
        sys.exit(1)
    print("  no problems flagged")


if __name__ == "__main__":
    main()
