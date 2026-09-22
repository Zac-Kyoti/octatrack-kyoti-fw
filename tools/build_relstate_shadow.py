#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
EMULATOR-ONLY TEST BUILD -- NOT the shipping DT build. Session 58 continued yet again,
part 8: identical to build_mutemode_dt.py except hook 8's own standalone detour
(0x4000d0c4, "relcut", 18 B) is REPLACED by hook 13 ("relstate_shadow", 0x4000d0c2, 20 B,
patch_softmute.s), which closes the REL_STATE race by cross-checking SHADOW right where
stock's own branch would otherwise skip relcut for a momentarily-wrong REL_STATE bit.
relcut's own body is completely unmodified -- reached only via relstate_shadow's branches
now. See patch_softmute.s's hook 13 header comment and NOTES.md "part 8" for the full
mechanism and why this avoids both previously-poisoned sites (0x4000bf22, 0x4000d0ba) and
the hook-12 EMAC danger zone entirely.

Deliberately writes to DIFFERENT output paths than build_mutemode_dt.py
(out/mainos_relstate_shadow.bin, no .syx/.bin wrap needed for emulator-only validation) so
the known-good, hardware-tested baseline build is never at risk of being overwritten by
an unvalidated experiment.

Usage:   python3 tools/build_relstate_shadow.py
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
OUT = ROOT / "out/mainos_relstate_shadow.bin"

# --- code stubs: (source, load addr, defsym, [(detour site, symbol, expected bytes, len)]) ---
PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18)]),
    ("patch_softmute", 0x400d7400, "DT_MODE=1",
     [(0x40004dc6, "pre",       "2a3980000008", 6),
      (0x40006844, "mt_trig",   "40c246fc2700", 6),
      (0x4000f4dc, "mt_rebind", "254d0004254c0008", 8),
      # hook 13 (relstate_shadow) REPLACES hook 8 (relcut)'s own standalone entry: this
      # span starts 2 B earlier (owns the `bccs` too) and is a strict superset of relcut's
      # own 18 B (0x4000d0c4..0x4000d0d6). Expected-bytes = relcut's own string with "6412"
      # (the bccs opcode) prepended. relcut's LABEL/BODY stay in patch_softmute.s completely
      # unmodified, reached only via relstate_shadow's own branches now.
      (0x4000d0c2, "relstate_shadow", "6412426800024228002bb46800046e0431420004", 20),
      (0x4000d498, "dt_trig",  "2f002f034e90", 6),
      (0x40006820, "fresh_bind", "2f0a2f02222f000c", 8),
      ]),
    # relstate_shadow's extra bcs (vs relcut alone) grows patch_softmute past
    # build_mutemode_dt.py's own patch_mutemode start (0x400d76c0) -- bumped 0x40 further
    # out, same convention as every prior cave-growth in this file's history.
    ("patch_mutemode", 0x400d7700, "DT_MODE=1", []),
]

OLD_LBL, OLD_GET, OLD_SET, N_OLD = 0x400b2a34, 0x400b2a74, 0x400b2ac0, 16
SPLICE_AT = 2
LBL_AT, GET_AT, SET_AT = 0x400d7790, 0x400d77f0, 0x400d7850
REFS = [(0x40068efe, OLD_LBL, "labels  move.l #imm,D5"),
        (0x40068f0a, OLD_GET, "getters lea"),
        (0x40069022, OLD_SET, "setters lea #1"),
        (0x4006903e, OLD_SET, "setters lea #2"),
        (0x40069056, OLD_SET, "setters lea #3")]
COUNT_AT = 0x40068fb2


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


def assemble(name, at, defsym):
    out = f"{name}_rs"
    aso = ["m68k-elf-as", "-mcpu=5407"]
    for d in (defsym.split(",") if defsym else []):
        aso += ["--defsym", d]
    aso += ["-o", f"out/{out}.o", f"tools/{name}.s"]
    subprocess.run(aso, check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{out}.elf", f"out/{out}.o"],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{out}.elf", f"out/{out}.bin"],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", f"out/{out}.elf"], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return (ROOT / f"out/{out}.bin").read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)

    def o(a):
        return a - BASE

    blobs, syms = {}, {}
    spans = []
    print("=== assemble + detour ===")
    for name, at, defsym, detours in PATCHES:
        blob, s = assemble(name, at, defsym)
        blobs[name], syms[name] = blob, s
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free: {bytes(img[co:co+16]).hex()}")
        spans.append((at, at + len(blob), name))
        img[co:co + len(blob)] = blob
        print(f"  {name:16s} {len(blob):3d} B @ 0x{at:08x} .. 0x{at+len(blob)-1:08x}"
              + (f"   [--defsym {defsym}]" if defsym else ""))
        for site, sym, exp, n in detours:
            exp = bytes.fromhex(exp)
            do = o(site)
            if bytes(img[do:do + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} ({name}:{sym}) unexpected: "
                         f"{bytes(img[do:do+len(exp)]).hex()} != {exp.hex()}")
            img[do:do + n] = jmp(s[sym]) + b"\x4e\x71" * ((n - 6) // 2)
            print(f"    0x{site:08x} -> {name}:{sym} 0x{s[sym]:08x}  ({n} B)")

    print("\n=== PERSONALIZE menu ===")
    new_entry = {OLD_LBL: syms["patch_mutemode"]["lbl_mutemode"],
                 OLD_GET: syms["patch_mutemode"]["get_mutemode"],
                 OLD_SET: syms["patch_mutemode"]["set_mutemode"]}
    dst = {OLD_LBL: LBL_AT, OLD_GET: GET_AT, OLD_SET: SET_AT}
    for old in (OLD_LBL, OLD_GET, OLD_SET):
        ents = [int.from_bytes(img[o(old + i * 4):o(old + i * 4) + 4], "big") for i in range(N_OLD)]
        ents = ents[:SPLICE_AT] + [new_entry[old]] + ents[SPLICE_AT:]
        d = dst[old]
        spans.append((d, d + len(ents) * 4, f"menu@{d:08x}"))
        if any(img[o(d):o(d + len(ents) * 4)]):
            sys.exit(f"menu array cave 0x{d:08x} not free")
        for i, v in enumerate(ents):
            img[o(d + i * 4):o(d + i * 4) + 4] = v.to_bytes(4, "big")
        print(f"  array 0x{d:08x}: {len(ents)} entries (16 stock + MUTE MODE @ idx {SPLICE_AT})")

    for a, old, tag in REFS:
        if bytes(img[o(a):o(a) + 4]) != old.to_bytes(4, "big"):
            sys.exit(f"ref 0x{a:08x} ({tag}) is not 0x{old:08x}: {bytes(img[o(a):o(a)+4]).hex()}")
        img[o(a):o(a) + 4] = dst[old].to_bytes(4, "big")
        print(f"  repoint 0x{a:08x}  {tag}: -> 0x{dst[old]:08x}")

    if bytes(img[o(COUNT_AT):o(COUNT_AT) + 2]) != b"\x72\x0f":
        sys.exit(f"count 0x{COUNT_AT:08x} is not moveq #15: {bytes(img[o(COUNT_AT):o(COUNT_AT)+2]).hex()}")
    img[o(COUNT_AT):o(COUNT_AT) + 2] = b"\x72\x10"
    print(f"  count   0x{COUNT_AT:08x}  moveq #15 -> #16")

    for site in (0x4001f322, 0x4001f3be, 0x4001fb24):
        so = o(site)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{site:08x}: {bytes(img[so:so+4]).hex()} != 48780064")
        img[so + 3] = 0x70
        print(f"  restore 0x{site:08x}  pea 0x64 -> pea 0x70")

    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[-1][1] > 0x400d7c3c:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x400d7c3c)")
    print("  no overlaps; all within the free cave")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    # --- the manual-trig fix must stay byte-identical to build_trigscale_only.py ---
    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        tsh = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in tsh)
        print(f"  manual-trig fix bytes identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("  MANUAL-TRIG FIX DIVERGED")

    # --- vs the hardware-good baseline (build_mutemode_dt.py's own OUT): every diff must
    #     be inside the DT cave region or the relstate_shadow detour site itself. This is
    #     the single most important check for THIS build: it proves relstate_shadow only
    #     touches what it says it touches, nothing else in the OT/OT+FX/DT paths shifted.
    baseline = ROOT / "out/mainos_mutemode_dt.bin"
    if baseline.exists():
        bb = baseline.read_bytes()
        diff = [i for i, (x, y) in enumerate(zip(bb, img)) if x != y]
        allowed = [(0x400d7400, 0x400d7c3c),   # the whole cave region (patch_softmute grew
                                                # by 2 B for relstate_shadow's extra bcs vs
                                                # relcut alone; patch_mutemode + arrays follow,
                                                # each shifted 0x40 further out to make room)
                   (0x4000d0c2, 0x4000d0d6),   # the detour site itself: 2 B earlier than
                                                # build_mutemode_dt.py's relcut entry
                   # every OTHER detour's own jmp-target address word: unchanged SITE bytes
                   # (asserted identical above), but the TARGET moved because the cave
                   # shifted, exactly like build_mutemode_dt.py's own allowed-diff list
                   # for the same reason vs build_mutemode.py
                   (0x40006820, 0x40006828), (0x4000d498, 0x4000d49e),
                   (0x40068efe, 0x40068f02), (0x40068f0a, 0x40068f0e),
                   (0x40069022, 0x40069026), (0x4006903e, 0x40069042),
                   (0x40069056, 0x4006905a)]
        stray = [i for i in diff if not any(lo - BASE <= i < hi - BASE for lo, hi in allowed)]
        print(f"  vs mainos_mutemode_dt.bin (hardware-good baseline): {len(diff)} bytes differ, "
              f"{len(stray)} outside the expected relstate_shadow delta")
        if stray:
            sys.exit(f"  DIVERGES OUTSIDE THE EXPECTED DELTA: {[hex(BASE+i) for i in stray[:8]]}")
        print("  (every diff is exactly the hook-13-for-hook-8 swap; nothing else moved)")
    else:
        print("  (no out/mainos_mutemode_dt.bin baseline to diff against -- build it first "
              "with tools/build_mutemode_dt.py for the most important check this script does)")

    print(f"\n  {OUT}  -- emulator-only, not wrapped to .syx/.bin, NOT for flashing")


if __name__ == "__main__":
    main()
