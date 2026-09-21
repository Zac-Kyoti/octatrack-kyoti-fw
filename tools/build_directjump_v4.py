#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
DIRECT JUMP v4 -- v3 (the FUN_4005a2b8 toast) with the [PTN]+[YES] toggle actually
reachable on hardware.

  WHY v1-v3 DO NOTHING ON THE MKI (DIRECTJUMP_V3 flashed 2026-09-14: no toast, no toggle):
  they detour the stock YES handler 0x4005e4c8, but [PTN] press pushes the "PTN held"
  keymap layer 0x400bf0f2 (0x4004346c -> FUN_40031494), whose YES record (code 0x31 @
  0x400bf0be) has press/release/hold = NULL.  The layer rebuild (0x4003125c) overwrites
  every field that isn't -1 and the key dispatcher (0x40031734) skips NULL handlers, so
  [YES] is swallowed for as long as [PTN] is held -- the detour is never entered.  The
  emulator never saw it because emu_directjump*.py call dj_toggle directly.

  v4: NO detour at 0x4005e4c8.  The build writes dj_toggle's address into that NULL press
  slot (0x400bf0c0) and assembles with DJ_KEYMAP=1 (not-our-combo path = plain rts, since
  stock does nothing with [YES] in that layer).  Stock [YES] outside [PTN] is untouched
  byte-for-byte.  tools/emu_directjump_v4.py drives the real stock layer push/rebuild/
  dispatch code against both the v3 image (reproduces the HW failure) and this one.

  Session 61 (flashed this v4, "sort of works" -- two follow-up fixes, both DJ_KEYMAP-gated
  so v1/v2/v3 are untouched by either):

  1. Toast now closes the instant [PTN] is released, instead of riding out its own
     ~DJ_TOAST_DUR timer regardless.  New hook `dj_ptnrel` at FUN_40043418 (the stock
     "tear down the PTN-held overlay" cleanup -- confirmed its only jsr caller image-wide
     is inside FUN_4005a044's own RELEASE branch, so this fires on every [PTN] release,
     combo or not).

     Went through THREE tries to get this right, all documented in patch_directjump.s's
     dj_ptnrel comment and NOTES.md Sessions 61-63:
       - Session 61: `jsr NOTIFY_CLOSE` directly.  Flashed -- EXCEPTION VEC:04 @ 0x400BF0F2
         after a few [PTN] presses.
       - Session 62: diagnosed (wrongly) as an unsafe nesting with NOTIFY_CLOSE's own list
         surgery; rewrote to touch no code at all, only arm NOTIFY_COUNTDOWN so stock's own
         tick closes it a frame later.  Flashed -- IDENTICAL exception, proving that
         diagnosis wrong; the bug was never in what dj_ptnrel called.
       - Session 63 (the actual bug, in every earlier version): the detour was kind=jsr, so
         entering dj_ptnrel already has a correct return address auto-pushed on the stack.
         Every version then did `pea 0x400bf0f2 ; rts` to replay the displaced instruction --
         but that `pea` is not inert data, it's a stock PUSH whose value is MEANT TO SURVIVE
         as an argument FUN_40043418's own later code reads without popping.  Pushing it put
         it ON TOP of the auto-pushed return address, so `rts` popped THE PEA'D VALUE instead
         -- "returning" by jumping straight to 0x400bf0f2, the exact crash address, on every
         single call.  Fixed by switching the detour to kind=jmp (no auto-push) and ending
         with `pea 0x400bf0f2 ; jmp 0x4004341e` instead of `rts` -- the same idiom this
         file's own djt_stock already uses for its two-register-move replay, for exactly
         this reason.

     The toast-close *mechanism* itself (arm NOTIFY_COUNTDOWN, let stock's own per-frame
     tick call NOTIFY_CLOSE a frame later, never call it directly ourselves) was correct
     from Session 62 onward and is unchanged here.

  2. THE PLAYHEAD BUG: dj_c (Hook C, shared unconditionally by every DJ build, v1-v4) was
     also writing the resume step into D7 ("per-track positions derive from D7").  Wrong --
     stock code just above the hook site (0x400a47f6-0x400a4834, unmodified, runs on every
     manual pattern switch with or without DIRECT JUMP) already sets D7 correctly to
     `LEN_TBL[newScale] * DAT_80006628`, a TICK count consumed by the two per-track
     tick-phase loops that run immediately after the hook.  Stomping it with a raw,
     unscaled step index fed those loops garbage units, corrupting every track's own next-
     tick phase on every jump -- this, not the master step (DAT_800065b6, which the hook
     DOES set correctly), is what broke "no discernible change in sound" between two
     identically-triggered patterns.  Fix: dj_c no longer touches D7 at all.

----- v3's notes, unchanged -----

  v1 (build_directjump.py)   FUN_40059f8c -- the SELECT-BANK/PATTERN timed window:
                             text + 4 draining countdown boxes, borrows that window's
                             handle 0x460d1e5c for < 1 s.  The boxes are inherited
                             chrome (that routine paints them); they were never a
                             DIRECT JUMP design choice.
  v2 (build_directjump_v2.py) FUN_4005a0e0 -- the dead-code bare text popup, NO
                             timeout of its own, so v2 splices dj_tick2 into the engine
                             per-frame handler at 0x400522ca (next to the SOFT MUTE
                             release watchdog) to close it, and shares the popup handle
                             0x460d1e64 with RELOAD's picker.
  v3 (this, --defsym DJ_V3=1) FUN_4005a2b8(text, dur) -- the OS's OWN self-timing
                             notification: the call stock uses for "PART n RELOADED"
                             (ems-octakit GK_STOCK_NOTIFICATION_SHOW), also the one
                             patch_reload2's rl_yes uses.  Plain one-line toast, no
                             boxes, no borrowed/shared handle, and NO extra hook --
                             so v3's detour set is exactly v1's three sequencer hooks
                             + the [PTN]+[YES] toggle, nothing more.

  Everything else -- the toggle logic, the 'ANDY'-shadow persistence (pea 0x64->0x70),
  dj_a/dj_b/dj_c, the manual-trig fix -- is byte-for-byte v1's recipe.

  DJ_TOAST_DUR (default 0x44, the dwell patch_reload2 uses) is --defsym-tunable.

  ** v3 is the overlay build_merged.py uses.  It removes every DIRECT JUMP merge
     friction: no 0x400522ca splice (v2), no SELECT-window handle grab (v1), no
     FUN_4005a0e0 / 0x460d1e64 collision with the RELOAD picker (v2). **

  UNFLASHED -- emulator-checked only (tools/emu_directjump_v4.py).

Usage:   python3 tools/build_directjump_v4.py [VERSTR] [DJ_TOAST_DUR]
Outputs: out/mainos_directjump_v4.bin, out/elek_directjump_v4.bin,
         out/OCTATRACK_OS1.40C_DIRECTJUMP_V4.syx, out/OCTATRACK_DIRECTJUMP_V4.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_directjump_v4.bin"
ELEK = ROOT / "out/elek_directjump_v4.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_DIRECTJUMP_V4.syx"
OUT_BIN = ROOT / "out/OCTATRACK_DIRECTJUMP_V4.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"
TOAST_DUR = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x44

DEFSYM = f"DJ_V3=1,DJ_KEYMAP=1,DJ_TOAST_DUR=0x{TOAST_DUR:x}"

PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_directjump", 0x400d7400, DEFSYM,
     [(0x400a4006, "dj_a", "4a398000667e",     6, "jsr"),
      (0x400a42fa, "dj_b", "203c00008e56",     6, "jsr"),
      (0x400a4840, "dj_c", "420013c0800065b6", 8, "jsr"),
      (0x400a4220, "dj_scaleix_fix", "13c28000663d", 6, "jsr"),
      (0x400a3fe4, "dj_abstick", "13c0800065b6", 6, "jsr"),
      (0x400a4d36, "dj_pertrack_fix", "4ab946107568", 6, "jsr"),
      (0x40043418, "dj_ptnrel", "4879400bf0f2", 6, "jmp")]),
]

# [PTN]-held keymap layer 0x400bf0f2, 26-byte record for YES (code 0x31): all-NULL in stock.
# dj_toggle goes into its press field (+2).  Release (+6) / hold (+10) stay NULL.
PTN_LAYER_YES = 0x400bf0be
PTN_LAYER_YES_STOCK = bytes([0x31, 0x00]) + bytes(24)
STOCK_YES_HANDLER = 0x4005e4c8
PTN_LAYER_REL = 0x40043418      # FUN_40043418 entry -- dj_ptnrel's detour site (Session 61)

RESTORE_SITES = (0x4001f322, 0x4001f3be, 0x4001fb24)
FREE_END = 0x400d7c3c


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


def jsr(t):
    return b"\x4e\xb9" + t.to_bytes(4, "big")


def assemble(name, at, defsym):
    aso = ["m68k-elf-as", "-mcpu=5407"]
    for d in (defsym.split(",") if defsym else []):
        aso += ["--defsym", d]
    aso += ["-o", f"out/{name}.o", f"tools/{name}.s"]
    subprocess.run(aso, check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{name}.elf", f"out/{name}.o"],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{name}.elf", f"out/{name}.bin"],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", f"out/{name}.elf"], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return (ROOT / f"out/{name}.bin").read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)

    def o(a):
        return a - BASE

    syms, spans = {}, []
    print(f"=== assemble + detour  (DJ_V3, DJ_KEYMAP, DJ_TOAST_DUR=0x{TOAST_DUR:x}) ===")
    for name, at, defsym, detours in PATCHES:
        blob, s = assemble(name, at, defsym)
        syms[name] = s
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free: {bytes(img[co:co+16]).hex()}")
        spans.append((at, at + len(blob), name))
        img[co:co + len(blob)] = blob
        print(f"  {name:16s} {len(blob):3d} B @ 0x{at:08x} .. 0x{at+len(blob)-1:08x}")
        for site, sym, exp, n, kind in detours:
            exp = bytes.fromhex(exp)
            do = o(site)
            if bytes(img[do:do + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} ({name}:{sym}) unexpected: "
                         f"{bytes(img[do:do+len(exp)]).hex()} != {exp.hex()}")
            branch = jsr(s[sym]) if kind == "jsr" else jmp(s[sym])
            img[do:do + n] = branch + b"\x4e\x71" * ((n - 6) // 2)
            print(f"    0x{site:08x} -> {name}:{sym} 0x{s[sym]:08x}  ({kind}, {n} B)")

    print("\n=== [PTN]-held keymap layer: [YES] press -> dj_toggle ===")
    ro = o(PTN_LAYER_YES)
    if bytes(img[ro:ro + 26]) != PTN_LAYER_YES_STOCK:
        sys.exit(f"PTN-layer YES record 0x{PTN_LAYER_YES:08x} unexpected: {bytes(img[ro:ro+26]).hex()}")
    dj = syms["patch_directjump"]["dj_toggle"]
    img[ro + 2:ro + 6] = dj.to_bytes(4, "big")
    print(f"  0x{PTN_LAYER_YES + 2:08x}  press NULL -> dj_toggle 0x{dj:08x}")
    yo = o(STOCK_YES_HANDLER)
    if bytes(img[yo:yo + 8]) != bytes.fromhex("222f0004202f0008"):
        sys.exit("stock YES handler 0x4005e4c8 was modified -- v4 must not detour it")

    print("\n=== PERSONALIZE persistence ===")
    for site in RESTORE_SITES:
        so = o(site)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{site:08x}: {bytes(img[so:so+4]).hex()} != 48780064")
        img[so + 3] = 0x70
        print(f"  restore 0x{site:08x}  pea 0x64 -> pea 0x70")

    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[-1][1] > FREE_END:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x{FREE_END:x})")
    print("  no overlaps; all within the free cave")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    for ext in ("bin", "elf"):
        (ROOT / f"out/patch_directjump_v4.{ext}").write_bytes(
            (ROOT / f"out/patch_directjump.{ext}").read_bytes())

    # --- v4 = v3's byte set, minus the 0x4005e4c8 detour, plus the 4-byte slot poke and
    #     the 6-byte dj_ptnrel detour @ 0x40043418 (Session 61's PTN-release toast-close) ---
    v3 = ROOT / "out/mainos_directjump_v3.bin"
    if v3.exists():
        v3b = v3.read_bytes()
        v3_touched = {i for i in range(len(v3b)) if v3b[i] != stock[i]}
        v4_touched = {i for i in range(len(img)) if img[i] != stock[i]}
        cave = set(range(o(0x400d7400), o(0x400d7c3c)))
        # Session 70 (5th/7th/9th pass): new, deliberate hook sites -- SCALE_IX self-heal
        # (Hook D), the absolute-tick counter (Hook E), and the per-track resume fix
        # (Hook F) -- none present in v3 at all. Not a regression; expected divergence.
        # Session 79 (15th pass): Hooks G/G2 removed -- the STEP_IN_PAT fix in
        # dj_pertrack_fix stops the extra table-arm write from ever becoming due, so
        # suppressing its store is both redundant and a latent hazard (it would suppress a
        # LEGITIMATE write whose tick happened to match the commit's).
        SCALEIX_FIX_SITE = 0x400a4220
        ABSTICK_SITE = 0x400a3fe4
        PERTRACK_FIX_SITE = 0x400a4d36
        want = (v3_touched - set(range(o(STOCK_YES_HANDLER), o(STOCK_YES_HANDLER) + 8))) \
            | {i for i in range(ro + 2, ro + 6) if img[i] != stock[i]} \
            | {i for i in range(o(PTN_LAYER_REL), o(PTN_LAYER_REL) + 6) if img[i] != stock[i]} \
            | {i for i in range(o(SCALEIX_FIX_SITE), o(SCALEIX_FIX_SITE) + 6) if img[i] != stock[i]} \
            | {i for i in range(o(ABSTICK_SITE), o(ABSTICK_SITE) + 6) if img[i] != stock[i]} \
            | {i for i in range(o(PERTRACK_FIX_SITE), o(PERTRACK_FIX_SITE) + 6) if img[i] != stock[i]}
        stray = [i for i in (v4_touched ^ want) if i not in cave]
        print(f"  vs mainos_directjump_v3.bin: v4 touches {len(v4_touched)} vs v3 {len(v3_touched)}; "
              f"{len(stray)} unexpected outside the cave")
        if stray:
            sys.exit(f"  v4 DIVERGED from v3 outside the cave: {[hex(BASE+i) for i in stray[:8]]}")

    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        tsh = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in tsh)
        print(f"  manual-trig fix bytes identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("  MANUAL-TRIG FIX DIVERGED")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if "version" in l or "emitted" in l or "wrote" in l))
    if "too long" in r.stdout:
        sys.exit(f'  version string "{VERSTR}" ({len(VERSTR)}) does not fit the 10-char field')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)

    print(f"\n  {OUT_SYX.name}  (MIDI DIN)  +  {OUT_BIN.name}  (CF card)")
    print(f"  version screen / SYSTEM STATUS -> OS VERSION will read:  {VERSTR}")
    print("  hold [PTN], tap [YES]  ->  toggles DIRECT JUMP; a plain 'DIRECT JUMP ON / OFF'")
    print(f"    notification (OS toast, ~{TOAST_DUR} frames), no countdown boxes.")
    print("  Behaviour + persistence identical to build_directjump.py.  Default OFF = stock.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()
