#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
RELOAD FROM PROJECT -- scaled-down / SEQ-focused variant (NOTES.md "Session 43"
/ "44" / "47").

A trimmed sibling of build_reload.py.  build_reload.py (SEQ / ALL PARTS / WHOLE
PATTERN, patch_reload.s) still builds.  This one builds a SEPARATE image from
patch_reload2.s:

  stock 1.40C + the MIDI manual-trig fix + a stay-open 3-item picker window.

  UX (Session 44 -- OT-native):
    Hold [PTN] ~0.5 s  opens a sticky picker window (the OS's own hold event, as
                       used by [PAGE]-hold).  It opens with TRK SEQ highlighted
                       -> [PTN]-hold then [YES] is a complete gesture, no arrows.
                       A quick [PTN] tap is unchanged.
    arrows      UP/RIGHT prev / DOWN/LEFT next (wrapping):
                       TRK SEQ / PTN SEQ / PART + PTN SEQ.
    [YES]       execute the highlight, close the window.
    [NO]        close the window, execute nothing.
    No timeout -- like every stock menu, the window stays until you answer it.
    While it is open [YES]/[NO] act ONLY on the picker.

  TRK SEQ        -- reload the sequence data of the ONE currently-addressed track
                    (audio track if on the audio pages, MIDI track if on the MIDI
                    pages -- 0x80000000 / 0x80000012).  Everything for that track
                    (trigs, recorder trigs, trigless trigs/locks + p-lock values,
                    swing/slide, micro-timing, trig conditions, step count); the
                    other 7 tracks + pattern length/scale + the Part link untouched.
  PTN SEQ        -- reload the whole active pattern's sequence data from
                    bankNN.strd.  The Part ASSIGNMENT is preserved (masked out).
  PART + PTN SEQ -- faithful restore: PTN SEQ including the Part link, then apply
                    that saved Part to the engine (FUN_40009094).

  Dropped vs build_reload.py: "ALL PARTS" (the FUN_4004aab4(0..3) loop).

  Session ??: FIXED a bug Session 60 (NOTES.md) flagged but never addressed --
  rl_yes (the [YES] detour @ 0x4005e4c8) sits on the identical dead-hook mechanism
  that made DIRECTJUMP_V3 do nothing when flashed: [PTN] press unconditionally
  pushes a UI overlay keymap layer whose own YES record is NULL, so the runtime
  dispatch slot for YES goes to 0 -- and 0x4005e4c8 is never entered at all --
  for as long as [PTN] stays physically held.  A user who presses YES while
  still holding PTN (plausible: DIRECT JUMP trains exactly that gesture) would
  see nothing happen.  Fixed the same way DIRECT JUMP v4 was
  (build_directjump_v4.py, --defsym DJ_KEYMAP=1): write the real handler
  straight into the dead slot instead of relying on the detour to be reached.
  RELOAD2 needs it for BOTH keys it uses -- NO's slot in that same layer isn't
  NULL (it's 0x40056aa8), but that function is an unconditional no-op for every
  PTN_MODE this project's own [PTN]-hold gesture can produce, so it's shadowed
  too, falling back to it byte-for-byte otherwise.  The ORIGINAL 0x4005e4c8 /
  0x4005e25c detours are kept, unchanged -- they're what answers the picker
  once [PTN] has been released, the documented no-timeout common case.  Arrow
  keys have no record in that layer's table at all, so they were never affected.
  Full RE + design rationale: patch_reload2.s's own header comment; dynamic
  proof against the real stock layer-push code: emu_reload2_keymap.py.

  1. patch_trigscale  -- MIDI manual-trig stall fix.  Byte-identical detour + cave
                         to build_trigscale_only.py / build_reload.py.
  2. patch_reload2    -- six detours:
       rl_ptn   @0x4005a044  PTN key handler FUN_4005a044.  event 2 (HOLD) +
                             gates (playing, no arranger, no popup, no reload
                             queued) -> open the window (bare-text popup
                             FUN_4005a0e0), set PTN_USED so the [PTN] release
                             doesn't also open SELECT PATTERN.  Otherwise replay
                             the displaced prologue -> stock (quick tap = SELECT
                             PATTERN unchanged).
       rl_no    @0x4005e25c  NO handler.  [NO] with the window open -> close it,
                             execute nothing, swallow.  Otherwise -> stock.
       rl_yes   @0x4005e4c8  YES handler.  [YES] with the window open -> close
                             it, then arm the worker: TRK SEQ -> rl_arm_trk
                             {G_KIND=3, G_TRK/G_TMIDI from 0x80000000/0x12};
                             PTN SEQ -> G_KIND=1; PART + PTN SEQ -> G_KIND=2 --
                             all post FUN_40022778(1<<curbank).  Toast + swallow.
                             Window closed -> replay the stock prologue (DJ's
                             [PTN]+[YES] toggle is untouched -- rl_yes only acts
                             while G_MENU==1).
       rl_arr_a @0x4004b970  UP/RIGHT key handler (keycodes 0x34/0x21).  Window
                             open -> G_SEL prev, redraw, swallow.  Closed ->
                             replay the displaced prologue, fall through.
       rl_arr_b @0x400491a0  DOWN/LEFT key handler (keycodes 0x33/0x20).  Window
                             open -> G_SEL next, redraw, swallow.  Closed -> ditto.
       rl_job   @0x40085864  the storage task's type-0x14 case.  When G_KIND==1:
                             open bankNN.strd (28 KB of the loader's own 64 KB
                             buffer), read the 22-byte header, parse patterns
                             0..P sequentially with the firmware's own per-
                             pattern parser FUN_4008cebc (0..P-1 discarded to a
                             36 KB scratch, pattern P kept), then per G_KIND:
                             1 -> memcpy the whole 0x8ed8 slab, restore the live
                             Part-link byte (slab+0x8e57); 2 -> memcpy the whole
                             slab (Part link included) + FUN_40009094(bank,part);
                             3 -> memcpy only the selected track's region
                             (audio slab+t*0x91a len 0x91a / MIDI slab+0x48d0+
                             t*0x8b0 len 0x8b0).  Set 0x46c8028a, rejoin the
                             case's exit.  Open ENOENT -> exit d0=-12 -> the
                             stock "THIS BANK HAS NEVER BEEN SAVED!" dialog for
                             free.  Inert when G_KIND==0; a re-entrant real
                             RELOAD BANK is unaffected (worker latches + clears
                             G_KIND).

  No scratch BANK is used.  The worker writes nothing but pattern P's live slab
  (TRK SEQ: nothing but the one track's region within it).  No PERSONALIZE entry,
  no persistent state -> no 'ANDY' shadow / pea 0x64->0x70.

  STATUS: PTN SEQ emu-validated end to end (emu_reload2.py --combo + --patched).
  TRK SEQ + PART + PTN SEQ + the picker: static + assembly checked, --combo drives
  the arming.  Needs a hardware pass (FLASHING.md 4.7).

  HW-only from Session 42, plus (Session 44):
    - the OS hold-event threshold + feel for [PTN] (same mechanism as [PAGE]-hold);
    - whether an arrow press reaches rl_arr_a/b while the FUN_4005a0e0 popup is up
      (the base-view arrow routing) -- if not, the fallback is a hook in the event
      dispatcher FUN_40061b60;
    - that FUN_4005a044 is only the PTN key handler (all its globals are PTN's).

Usage:   python3 tools/build_reload2.py [VERSTR]      (default VERSTR = "140C_KYOTI")
Outputs: out/mainos_reload2.bin, out/elek_reload2.bin,
         out/OCTATRACK_OS1.40C_RELOAD2.syx, out/OCTATRACK_RELOAD2.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_reload2.bin"
ELEK = ROOT / "out/elek_reload2.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_RELOAD2.syx"
OUT_BIN = ROOT / "out/OCTATRACK_RELOAD2.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# (source, load addr, defsym, [(detour site, symbol, expected bytes, len, kind)])
PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_reload2", 0x400d7400, None,
     # Session 80 continued (2): the rl_ptn detour @0x4005a044 is GONE -- the entry
     # gesture moved from [PTN]-hold to [BANK]+[YES] (see patch_reload2.s). [PTN] is
     # now byte-for-byte stock again as far as this build is concerned.
     [(0x4005e25c, "rl_no", "202f00086714", 6, "jmp"),         # NO handler: move.l 8(sp),d0 ; beq.s 0x4005e276
      (0x4005e4c8, "rl_yes", "222f0004202f0008", 8, "jmp"),    # YES handler: move.l 4(sp),d1 ; move.l 8(sp),d0
      (0x4004b970, "rl_arr_a", "4feffff448d7040c", 8, "jmp"),  # UP/RIGHT handler: lea -12(sp),sp ; movem.l d2-d3/a2,(sp)
      (0x400491a0, "rl_arr_b", "2f02206f0008", 6, "jmp"),      # DOWN/LEFT handler: move.l d2,-(sp) ; movea.l 8(sp),a0
      (0x40085864, "rl_job", "2d4afd762f2a0004", 8, "jmp"),    # 0x14 case: move.l a2,-650(fp) ; move.l 4(a2),-(sp)
      # Session 80 continued (3): move stock's SELECT BANK window from [BANK]
      # press to [BANK] release, so a [BANK]+[YES] reload never flashes it.
      # Both sites are private to [BANK]: 0x4007af30 (the press tail this first
      # site lives in) and 0x4007b408 (the teardown) have ZERO xrefs, "SELECT
      # BANK" (0x400b7302) has exactly one use -- the call we suppress -- and
      # nothing in the image branches into either displaced range (scanned).
      (0x4007af42, "rl_bank_press", "487a04c442a7", 6, "jmp"),   # press tail: pea 0x4007b408(pc) ; clr.l -(sp)
      (0x4007b3e0, "rl_bank_rel", "7002b0b9460e73c6", 8, "jmp"),  # release: moveq #2,d0 ; cmp.l 0x460e73c6,d0
      # Session 80 continued (4): the type-0x14 doneFn's SUCCESS path, which is
      # what re-reads all 16 patterns of the bank after our slice copy (measured
      # by diag_reload2_deser.py -- and NOT the `jsr 0x40080844` two lines above
      # it, which was tried first and changed nothing). Gated on a one-shot flag
      # rl_job sets, so a genuine stock RELOAD BANK is never suppressed.
      (0x40023c62, "rl_done", "71f9460bd910", 6, "jmp")]),          # doneFn success: mvs.w 0x460bd910,d0
]

# Session 80 continued (2): the [BANK]-held keymap overlay layer.
# [BANK] press (0x4007af80) pushes layer struct 0x400cff14 through the same
# FUN_40031494 push+rebuild [PTN] uses; [BANK] release (0x4007b3e0) pops it via
# 0x4003146c.  Its records live at 0x400cff34: trigs 0x00-0x0f, NO (0x32) ->
# 0x4007b25c, then YES (0x31) at record index 17 = 0x400d00ee with press = NULL
# -- structurally identical to the [PTN] layer's own dead YES slot.  We poke
# rl_bank_yes into that press field (record + 2).
#
# The two [PTN]-layer pokes this build used to make (rl_yes_ptnheld into
# 0x400bf0be+2, rl_no_ptnheld into 0x400bf0a4+2) are GONE: moving the gesture
# to [BANK]+[YES] frees the [PTN] layer's YES slot for DIRECT JUMP v4's
# dj_toggle exclusively, which removes the merged-build collision that
# reference/MERGE.md's [YES] trampoline was built to work around.
BANK_LAYER_YES = 0x400d00ee
BANK_LAYER_YES_STOCK = bytes([0x31, 0x00]) + bytes(24)

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
    print("=== assemble + detour ===")
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

    print("\n=== [BANK]-held keymap layer: YES press slot -> rl_bank_yes ===")
    rsyms = syms["patch_reload2"]
    yo = o(BANK_LAYER_YES)
    if bytes(img[yo:yo + 26]) != BANK_LAYER_YES_STOCK:
        sys.exit(f"BANK-layer YES record 0x{BANK_LAYER_YES:08x} unexpected: {bytes(img[yo:yo+26]).hex()}")
    img[yo + 2:yo + 6] = rsyms["rl_bank_yes"].to_bytes(4, "big")
    print(f"  0x{BANK_LAYER_YES + 2:08x}  press NULL -> rl_bank_yes 0x{rsyms['rl_bank_yes']:08x}")

    # [PTN] must now be untouched by this build (the gesture moved to [BANK]+[YES]).
    for addr, what in ((0x4005a044, "PTN key handler"),
                       (0x400bf0be, "PTN-layer YES record"),
                       (0x400bf0a4, "PTN-layer NO record")):
        a = o(addr)
        if bytes(img[a:a + 8]) != bytes(stock[a:a + 8]):
            sys.exit(f"{what} 0x{addr:08x} was modified -- [PTN] must be left stock now")
    print("  [PTN] handler + both [PTN]-layer records verified untouched (stock)")

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
    print("  Hold [BANK], tap [YES]   ->  picker window (sticky, no timeout), TRK SEQ highlighted")
    print("    (works whether the transport is running or stopped)")
    print("  arrows                   ->  TRK SEQ / PTN SEQ / PART + PTN SEQ")
    print("  [YES]                    ->  execute the highlight + close")
    print("  [NO]                     ->  close the window, execute nothing")
    print("  [PTN] is left completely stock by this build -- PTN+YES belongs to DIRECT JUMP.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()
