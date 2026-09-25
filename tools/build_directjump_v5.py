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
Outputs: out/mainos_directjump_v5.bin, out/elek_directjump_v5.bin,
         out/OCTATRACK_OS1.40C_DIRECTJUMP_V5.syx, out/OCTATRACK_DIRECTJUMP_V5.bin
"""
import hashlib, os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_directjump_v5.bin"
ELEK = ROOT / "out/elek_directjump_v5.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_DIRECTJUMP_V5.syx"
OUT_BIN = ROOT / "out/OCTATRACK_DIRECTJUMP_V5.bin"

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
      # Session 83: Hook E (dj_abstick @0x400a3fe4) REMOVED -- it maintained G_ABSTICK,
      # a SECOND position counter running alongside stock's own 0x800065b2. Deriving the
      # resume position from it while the metronome ran from 0x800065b2 is what made every
      # switch land on a different step and drift against the beat. The site is stock again.
      # Session 79 cont.29: Hook F (dj_pertrack_fix) REMOVED. It carried the same
      # LEN_TBL misreading as dj_c -- it computed G_ABSTICK mod LEN_TBL[scale], i.e.
      # mod TICKS-PER-STEP, and wrote that into BOTH the per-track STEP array
      # (0x800064d0) and the ticks-within-step array (0x800064f0). Measured on this
      # build: it clobbered 7 of 8 AUDIO tracks from the correct 10 down to 2, while
      # the MIDI tracks (which it never touches) kept 10 -- i.e. it desynced audio
      # against MIDI on every armed commit. Its original purpose (repairing per-track
      # state after a commit) is now done correctly upstream by stock's own rebuild
      # loop, seeded by Hook H. See NOTES.md Session 79 cont.28/29.
      # Hook H -- THE WHOLE FEATURE after the Session 83 AR port. Seeds stock's own
      # per-track rebuild loop (0x400a4884) by writing 0x80006628 before D7 is built from
      # it at 0x400a4812/0x400a4826, with ONE value: 0x800065b2 mod newMasterLen, i.e. AR's
      # `new_step = masterStep mod newPatternLen`. 0x800065b2 measured as a bounded playhead
      # (tools/diag_playhead.py: range 0..15, period 16 = MASTER LENGTH, both master scales),
      # the direct analogue of AR's DAT_405666e4. Stock then reseeds 0x800065b2 from our low
      # word at 0x400a483a, so the metronome and the patterns get the same number by
      # construction. See NOTES.md Session 83.
      (0x400a47f6, "dj_d7", "41f9400eb034", 6, "jsr"),
      # Session 85 -- Hook P: AR's per-track loop (0x4009927c-0x400992d2) written directly
      # over stock's rebuild output. Stock computes position in the TICK domain and so
      # rescales it by the ratio of the two master scales; AR divides new_step by the
      # track's LENGTH and nothing else. 0x400a4d36 is the common per-tick exit, reached
      # after the commit body's tail, and is gated on G_JUST_COMMITTED.
      (0x400a4d36, "dj_pertrack", "4ab946107568", 6, "jsr"),
      # Session 83: Hook T (dj_tstart @0x4009c3d4) REMOVED -- it existed only to reset
      # G_ABSTICK at transport start. No counter of ours survives, so the site is stock.
      (0x40043418, "dj_ptnrel", "4879400bf0f2", 6, "jmp")]),
]

# [PTN]-held keymap layer 0x400bf0f2, 26-byte record for YES (code 0x31): all-NULL in stock.
# dj_toggle goes into its press field (+2).  Release (+6) / hold (+10) stay NULL.
PTN_LAYER_YES = 0x400bf0be
PTN_LAYER_YES_STOCK = bytes([0x31, 0x00]) + bytes(24)
STOCK_YES_HANDLER = 0x4005e4c8
PTN_LAYER_REL = 0x40043418      # FUN_40043418 entry -- dj_ptnrel's detour site (Session 61)

RESTORE_SITES = (0x4001f322, 0x4001f3be, 0x4001fb24)
DJ_MODE_ADDR = 0x800000D8      # must match patch_directjump.s's .equ DJ_MODE
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

    # Session 83: DIRECT JUMP no longer persists -- it is a performance feature and must come
    # up OFF on every power-on. This block used to WIDEN the ANDY restore from 0x64 to 0x70 at
    # all three sites so DJ_MODE (0x800000d8, offset 0x68) would be restored from battery SRAM.
    # That widening is removed; what remains is the opposite -- an assertion that the restore
    # is still stock, i.e. that nothing writes DJ_MODE at boot except stock's own DSP-RAM
    # re-image, whose ROM seed for this word is verified to be zero just below.
    print("\n=== power-on default: DIRECT JUMP must come up OFF ===")
    for site in RESTORE_SITES:
        so = o(site)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{site:08x}: {bytes(img[so:so+4]).hex()} != 48780064 "
                     "-- the ANDY restore must stay stock so it never reaches DJ_MODE")
        print(f"  restore 0x{site:08x}  pea 0x64 LEFT STOCK "
              f"(covers 0x80000070..0x800000d3; DJ_MODE 0x800000d8 is outside)")

    # kb/memory-map.md: FUN_4000f938 re-images 0x80000000 from ROM 0x401086f4 (0x3e88 B) at
    # every boot, then zero-fills to 0x80004000. DJ_MODE is inside that span, so its power-on
    # value is a fixed byte in this very image -- assert it, do not assume it.
    DSP_ROM_IMAGE, DSP_WINDOW, REIMAGE_LEN = 0x401086F4, 0x80000000, 0x3E88
    dj_off = DJ_MODE_ADDR - DSP_WINDOW
    if dj_off >= REIMAGE_LEN:
        sys.exit(f"DJ_MODE offset 0x{dj_off:x} is outside the 0x{REIMAGE_LEN:x}-byte boot "
                 "re-image -- its power-on value would be undefined")
    seed_at = DSP_ROM_IMAGE + dj_off
    seed = bytes(img[o(seed_at):o(seed_at) + 4])
    if seed != b"\x00\x00\x00\x00":
        sys.exit(f"boot ROM seed for DJ_MODE at 0x{seed_at:08x} is {seed.hex()}, not 00000000 "
                 "-- DIRECT JUMP would not come up OFF")
    print(f"  boot ROM seed 0x{seed_at:08x} = {seed.hex()}  -> DJ_MODE forced to 0 every "
          f"power-on by stock's own FUN_4000f938")

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
        (ROOT / f"out/patch_directjump_v5.{ext}").write_bytes(
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
        D7_SEED_SITE = 0x400a47f6
        TSTART_SITE = 0x4009c3d4
        # Session 83: v3 widened the ANDY restore (pea 0x64 -> 0x70) at all three sites so
        # DIRECT JUMP would persist. v4 leaves those bytes stock, so they are bytes v3
        # touched and v4 deliberately does not -- drop them from `want` or they read as
        # strays. Verified to be exactly 0x4001f325 / 0x4001f3c1 / 0x4001fb27, the low byte
        # of each pea operand.
        restore_len_bytes = {o(site) + 3 for site in RESTORE_SITES}
        want = (v3_touched
                - set(range(o(STOCK_YES_HANDLER), o(STOCK_YES_HANDLER) + 8))
                - restore_len_bytes) \
            | {i for i in range(ro + 2, ro + 6) if img[i] != stock[i]} \
            | {i for i in range(o(PTN_LAYER_REL), o(PTN_LAYER_REL) + 6) if img[i] != stock[i]} \
            | {i for i in range(o(SCALEIX_FIX_SITE), o(SCALEIX_FIX_SITE) + 6) if img[i] != stock[i]} \
            | {i for i in range(o(ABSTICK_SITE), o(ABSTICK_SITE) + 6) if img[i] != stock[i]} \
            | {i for i in range(o(PERTRACK_FIX_SITE), o(PERTRACK_FIX_SITE) + 6) if img[i] != stock[i]} \
            | {i for i in range(o(D7_SEED_SITE), o(D7_SEED_SITE) + 6) if img[i] != stock[i]} \
            | {i for i in range(o(TSTART_SITE), o(TSTART_SITE) + 6) if img[i] != stock[i]}
        stray = [i for i in (v4_touched ^ want) if i not in cave]
        print(f"  vs mainos_directjump_v3.bin: v4 touches {len(v4_touched)} vs v3 {len(v3_touched)}; "
              f"{len(stray)} unexpected outside the cave")
        if stray:
            sys.exit(f"  v4 DIVERGED from v3 outside the cave: {[hex(BASE+i) for i in stray[:8]]}")

    # --- Session 88: measure every V5 build against the GOLD Session 87 image ---
    # 16df386 is hardware-confirmed working at 1x and cost seven sessions and two hardware
    # regressions. Session 88's Hook P change was emu-validated, flashed, and broke it
    # anyway. So every build from here on states its distance from gold explicitly, and
    # refuses outright if it differs ANYWHERE outside the patch cave.
    gold = ROOT / "out/GOLD_S87_mainos_directjump.bin"
    if gold.exists():
        gb = gold.read_bytes()
        cave = set(range(o(0x400d7400), o(0x400d7c3c)))
        diff = {i for i in range(len(img)) if img[i] != gb[i]}
        outside = sorted(i for i in diff if i not in cave)
        gsha = hashlib.sha256(gb).hexdigest()[:16]
        print(f"  vs GOLD_S87 ({gsha}): {len(diff)} bytes differ, "
              f"{len(outside)} of them OUTSIDE the cave")
        if outside:
            sys.exit("  V5 DIVERGED FROM GOLD OUTSIDE THE CAVE at "
                     f"{[hex(BASE + i) for i in outside[:8]]} -- refusing to build")
        if not diff:
            print("  V5 is BYTE-IDENTICAL to the gold Session 87 build")
    else:
        print(f"  NOTE: {gold.name} missing -- cannot measure distance from the gold build")

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
