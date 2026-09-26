#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Bugbuilds -- each finished FEATURE build, with all three BUG FIXES folded in.

Four composite images, written ONLY to out/Bugbuilds/ (they do not replace, and are
not written alongside, the standalone per-feature images in out/):

    MUTEMODE_DT        + PARTREAPPLY + PATTERNLED + PLAYSFREEFIX
    QLREC              + PARTREAPPLY + PATTERNLED + PLAYSFREEFIX
    SIDECHAIN3_CROSS   + PARTREAPPLY + PATTERNLED + PLAYSFREEFIX
    TRIGLOCK           + PARTREAPPLY + PATTERNLED + PLAYSFREEFIX

Method -- compose onto the finished feature image, do not re-implement it.
Each feature builder is run first (so the base is current), then the bug-fix caves are
linked into free space in that image and their detours applied.  SIDE-CHAIN in particular
is never re-derived: its DSP payloads, COMPRESSOR descriptor and FX2 chooser edits come
through untouched, and its cave stays at its own address so the descriptor's formatter
pointers stay valid.

PLAYSFREEFIX (patch_trigscale) is already present in MUTEMODE_DT, QLREC and
SIDECHAIN3_CROSS; only TRIGLOCK needs it added.  It is placed at 0x400d7b00 in all four,
so every Bugbuild carries it at the same address the standalone builds use.

Cave layout is identical in all four images:

    patch_partreapply   0x400d64dc   402 B
    patch_pattern_led   0x400d6670   142 B
    patch_trigscale     0x400d7b00    62 B   (TRIGLOCK only -- the other three have it)

Verification (every image, every run):
  * each cave region is all-zero in the base before it is written;
  * each detour site still holds the exact stock bytes (proves no feature took it first);
  * assert_no_branch_into on every detour site (build_triglock.py's guard, promoted here);
  * COMPOSITIONALITY: the composite's byte-delta vs stock is exactly the union of the
    feature's delta and a reference "bug-fixes only, at these same addresses, on stock"
    delta -- and those two deltas are disjoint.  That is the interlock proof: every
    changed byte has exactly one owner and no owner's bytes were altered.

Usage:  python3 tools/build_bugbuilds.py [--no-rebuild]
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
ROOT = pathlib.Path(__file__).parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUTDIR = ROOT / "out/Bugbuilds"
WORK = OUTDIR / "_work"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
FREE_START, FREE_END = 0x400d64da, 0x400d7c3c

o = lambda a: a - BASE

# --- the three bug fixes -----------------------------------------------------------
#   preferred: where the cave goes if that space is free in the base image; otherwise the
#              allocator picks the lowest free run that fits (see place()).
#   detours:   (site, symbol or None for the cave base, expected STOCK bytes, len, kind)
#              kind 'jsr' | 'jmp' | 'jmp18' (jmp + 6 nop, the 18-byte trigscale form).
#   NOTE detours[0] must target the cave BASE -- resolve_present() reads that instruction
#   back out of a base image to learn where an already-present fix was linked.
BUGFIX = {
    "patch_partreapply": (0x400d64dc, [
        (0x40062216, None,    "4eb9400326a0", 6, "jsr"),   # tail
        (0x400621da, "cave2", "4eb940020898", 6, "jsr"),   # head, dirty-flag snapshot
    ]),
    "patch_pattern_led": (0x400d6670, [
        (0x4009a464, None, "2f02202f0008", 6, "jmp"),
    ]),
    "patch_trigscale": (0x400d7b00, [
        (0x4009b6f2, None, "203c0000091a", 18, "jmp18"),
    ]),
}

# --- the feature bases: name -> (builder, base image, VERSTR, wip, blurb) -------------
#   wip=True is skipped unless --with-wip is passed.  DIRECT JUMP is not
#   finished (see reference/MERGE.md); RELOAD3 was finished on 2026-09-25; they are wired up here so that folding the bug
#   fixes into them later is a one-flag operation, not a rewrite.
FEATURES = {
    "MUTEMODE_DT": ("build_mutemode_dt.py", "out/mainos_mutemode_dt.bin", "BUG_MUTEDT", False,
                    "PERSONALIZE -> MUTE MODE: OT | OTFX | OTFX-T | DT-T (default OT)."),
    "QLREC": ("build_qlrec.py", "out/mainos_qlrec.bin", "BUG_QLREC", False,
              "Hold [REC], tap [PLAY] twice -> toggles QUANTIZE LIVE REC."),
    "SIDECHAIN3_CROSS": ("build_sidechain3.py", "out/mainos_sidechain3_cross.bin", "BUG_SC3X",
                         False, "COMPRESSOR FX page 2: KEY / KFLT / KGAIN / MON, cross-core."),
    "TRIGLOCK": ("build_triglock.py", "out/mainos_triglock.bin", "BUG_TRIGLK", False,
                 "A trigless lock whose last param is LIVE-erased clears from the trig row."),
    "RELOAD3": ("build_reload3.py", "out/mainos_reload3.bin", "BUG_RL3", False,
                "[PTN]+[TRACK n] reload track n's saved sequence; [BANK]+[TRACK n] also re-applies the Part."),
    # --- not finished; build with --with-wip ---------------------------------------
    "DIRECTJUMP_V4": ("build_directjump_v4.py", "out/mainos_directjump_v4.bin", "BUG_DJV4",
                      True, "WIP: hold [PTN], tap [YES] -> DIRECT JUMP on/off."),
}

PROBLEMS = []
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
    """Refuse a detour whose displaced bytes contain a branch TARGET (from build_triglock.py)."""
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
    subprocess.run(["m68k-elf-as", "-mcpu=5407", "-o", str(obj), f"tools/{stem}.s"],
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
    syx = OUTDIR / f"OCTATRACK_OS1.40C_{name}_BUGFIX.syx"
    binf = OUTDIR / f"OCTATRACK_{name}_BUGFIX.bin"
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
    with_wip = "--with-wip" in sys.argv
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    stock = STOCK_SECT.read_bytes()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    for name, (builder, basepath, verstr, wip, blurb) in FEATURES.items():
        if wip and not with_wip:
            print(f"---- {name}: WIP, skipped (pass --with-wip to build it)\n")
            continue
        print(f"════════════ {name} + PARTREAPPLY + PATTERNLED + PLAYSFREEFIX ════════════")
        if wip:
            flag(f"{name} is WIP -- see reference/MERGE.md; this image is NOT shippable")
        if rebuild:
            r = subprocess.run(["python3", f"tools/{builder}"], capture_output=True,
                               text=True, cwd=ROOT)
            if r.returncode != 0:
                sys.exit(f"{name}: feature builder {builder} failed:\n{r.stdout}\n{r.stderr}")
        base = ROOT / basepath
        if not base.exists():
            sys.exit(f"{name}: missing base image {base} -- run tools/{builder}")
        img = bytearray(base.read_bytes())
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

        mainos = OUTDIR / f"mainos_{name.lower()}_bugfix.bin"
        mainos.write_bytes(bytes(img))
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
