#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
RELOAD FROM PROJECT -- scaled-down / SEQ-focused variant (NOTES.md "Session 43"
/ "44" / "47").

A trimmed sibling of build_reload.py.  build_reload.py (SEQ / ALL PARTS / WHOLE
PATTERN, patch_reload.s) still builds.  This one builds a SEPARATE image from
patch_reload3.s:

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
  Full RE + design rationale: patch_reload3.s's own header comment; dynamic
  proof against the real stock layer-push code: emu_reload2_keymap.py.

  1. patch_trigscale  -- MIDI manual-trig stall fix.  Byte-identical detour + cave
                         to build_trigscale_only.py / build_reload.py.
  2. patch_reload3    -- six detours:
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
Outputs: out/mainos_reload3.bin, out/elek_reload3.bin,
         out/OCTATRACK_OS1.40C_RELOAD3.syx, out/OCTATRACK_RELOAD3.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_reload3.bin"
ELEK = ROOT / "out/elek_reload3.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_RELOAD3.syx"
OUT_BIN = ROOT / "out/OCTATRACK_RELOAD3.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# Session 83: the cave base moved 0x400d7400 -> 0x400d6500. Session 82 reported
# patch_reload3 at 2036 B against a 2044 B ceiling and called cave space the
# binding constraint -- that was a FALSE constraint. The contiguous zero run
# containing this cave starts at 0x400d64da, i.e. 3878 B BELOW the old base, and
# build_merged.py (Session 48) had already lowered its own FREE_START to
# 0x400d6500 for exactly this reason ("the whole 0x400d64da..0x400d7c3c span is
# zero in stock"). Verified again here: stock is zero across 0x400d6500..0x400d73ff.
# Budget is now 0x400d7bfc - 0x400d6500 = 5884 B instead of 2044.
FREE_START = 0x400d6500

# (source, load addr, defsym, [(detour site, symbol, expected bytes, len, kind)])
PATCHES = [
    # Session 80 continued (8): moved 0x400d7b00 -> 0x400d7bf0 (62 B) so
    # patch_reload3 had room for the picker's own keymap layer.
    # Session 82: moved again, 0x400d7bf0 -> 0x400d7bfc, for the rl_draw redraw
    # guard (hardware report #5). This is the TOP of the free zone: the address
    # must stay 4-BYTE ALIGNED or the source's own `.align` pads the blob from 62
    # to 64 B and the free-zone assert trips (0x400d7bfe was tried first and did
    # exactly that -- a useful reminder that the cave address is an alignment
    # constraint, not just an offset). 62 B at 0x400d7bfc ends 0x400d7c3a, inside
    # FREE_END 0x400d7c3c (measured: stock is zero from 0x400d7400 to 0x400d7c3b
    # and 0xff from 0x400d7c3c). patch_reload3's ceiling is therefore
    # 0x400d7bfc - 0x400d7400 = 2044 B; further growth must come out of its own
    # footprint, since this cannot move up again.
    ("patch_trigscale", 0x400d7bfc, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_reload3", FREE_START, "RL_DONE=1",
     # Session 85 redesign + Session 86's two [BANK]-deferral sites -- SIX
     # detours; RELOAD2 had ten. Neither chord site
     # pokes a keymap layer record, the mechanism behind the DIRECT JUMP slot
     # collision and several picker-era routing bugs. Both open with the same
     # 6-byte prologue, so a 6-byte jmp fits each with no padding.
     [(0x4007af42, "rl3_bank_show", "487a04c442a7", 6, "jmp"),
      # Session 86 item 2: SELECT BANK moves from the PRESS to the RELEASE.
      # This site is inside stock's SHARED show tail (0x4007af30), which is reached
      # from the [BANK] press handler's `bras` at 0x4007af98 and from NOTHING else
      # in the image. Displaces pea %pc@(0x4007b408) ; clr.l -(sp). The gate is a
      # one-shot: a press returns without showing, and the release handler below
      # opens it for exactly one pass and calls the same tail, so the window, its
      # duration and its teardown are all stock's own.
      (0x4007b3e0, "rl3_bank_rel", "7002b0b9460e73c6", 8, "jmp"),
      # [BANK] RELEASE handler: moveq #2,d0 ; cmp.l 0x460e73c6,d0 (8 B -> jmp+nop).
      # The cmp must be replayed, because the resume point 0x4007b3e8 is stock's
      # own beq on it.
      (0x40083dc4, "rl3_ptn_trk", "2f02242f0008", 6, "jmp"),
      # [PTN]-overlay TRACK handler: move.l d2,-(sp) ; move.l 8(sp),d2.
      # All 8 references to it are the 8 [PTN] overlay track slots
      # (0x400bf124..0x400bf1da), so arriving there IS [PTN]+[TRACK].
      (0x40040250, "rl3_bank_trk", "2f02222f0008", 6, "jmp"),
      # Base TRACK handler: move.l d2,-(sp) ; move.l 8(sp),d1.  [BANK] does NOT
      # override track keys, so [BANK]+[TRACK] lands here; the handler tests the
      # BANK held-flag and otherwise replays into stock's own track select.
      (0x40085864, "rl_job", "2d4afd762f2a0004", 8, "jmp"),    # 0x14 case -- worker, unchanged
      # Session 83, carried over: doneFn's SUCCESS path, 6 B, immediately before
      # the `bsr.w 0x40023b68` that re-reads all 16 patterns. This is the
      # suppression that cut a reload from 6852 card reads to 354.
      (0x40023c62, "rl_done", "71f9460bd910", 6, "jmp")]),
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

    syms, spans, placed = {}, [], {}
    print("=== assemble + detour ===")
    for name, at, defsym, detours in PATCHES:
        blob, s = assemble(name, at, defsym)
        syms[name] = s
        placed[name] = (at, blob)
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

    # Session 85: this build pokes NO keymap layer record at all. RELOAD2 poked
    # rl_bank_yes into the [BANK] overlay's NULL YES slot, and earlier builds poked
    # the [PTN] overlay -- that mechanism caused the DIRECT JUMP slot collision and
    # several routing bugs. The chord design reaches both gestures by detouring
    # ordinary key handlers instead, so assert every overlay record is untouched.
    print("\n=== keymap overlays must be byte-for-byte stock ===")
    for addr, what in ((0x400d00ee, "[BANK]-layer YES record"),
                       (0x400d00d4, "[BANK]-layer NO record"),
                       (0x4005a044, "[PTN] key handler"),
                       (0x400bf0be, "[PTN]-layer YES record"),
                       (0x400bf0a4, "[PTN]-layer NO record"),
                       (0x4007af80, "[BANK] key handler")):
        # Session 86: 0x4007b3e0 ([BANK] release) is DELIBERATELY detoured now
        # (rl3_bank_rel), so it is no longer in this list. 0x4007af80 STAYS: we
        # splice its shared show TAIL at 0x4007af42, never the handler entry, so
        # the dispatch table still points at stock code for the [BANK] press.
        a = o(addr)
        if bytes(img[a:a + 8]) != bytes(stock[a:a + 8]):
            sys.exit(f"{what} 0x{addr:08x} was modified -- this build must poke no layer records")
    print("  all [PTN]/[BANK] handlers and overlay records verified untouched")
    # the 8 [PTN]-overlay TRACK slots must still point at the handler we detour,
    # not at us -- we detour the handler, we do not repoint the records.
    for i in range(8):
        rec = 0x400bf122 + i * 26
        a = o(rec + 2)
        if int.from_bytes(bytes(img[a:a + 4]), "big") != 0x40083dc4:
            sys.exit(f"[PTN]-overlay TRACK slot {i} (0x{rec:08x}) no longer points at 0x40083dc4")
    print("  all 8 [PTN]-overlay TRACK slots still point at 0x40083dc4 (we detour it, not them)")

    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[0][0] < FREE_START:
        sys.exit(f"cave starts below the free zone (0x{spans[0][0]:x} < 0x{FREE_START:x})")
    if spans[-1][1] > FREE_END:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x{FREE_END:x})")
    print("  no overlaps; all within the free cave")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    # Cross-check the manual-trig fix against the standalone build.  The two builds place
    # the trigscale cave at DIFFERENT addresses -- build_trigscale_only.py uses 0x400d7b00,
    # while here it sits at 0x400d7bf0 because patch_reload3's cave grew over that address
    # in Session 80 continued (8) -- so comparing bytes at absolute offsets is meaningless.
    # It reports a "divergence" that is nothing but the relocation, and because the check
    # sys.exit()s BEFORE the .syx wrap below, from commit 83ce678 until Session 80
    # continued (10) every build aborted and the last flashable image on disk silently
    # stayed three sessions stale.  Relocation-aware check instead: same cave BODY, same
    # detour shape, and the reference image touching nothing beyond its own detour + cave.
    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        at, blob = placed["patch_trigscale"]
        site, _, _, n, _ = PATCHES[0][3][0]
        so, pad = o(site), b"\x4e\x71" * ((n - 6) // 2)
        ref_detour = bytes(tsb[so:so + n])
        if ref_detour[:2] != b"\x4e\xf9":
            sys.exit(f"  reference trigscale detour 0x{site:08x} is not a jmp: {ref_detour.hex()}")
        ref_at = int.from_bytes(ref_detour[2:6], "big")
        bad = []
        if bytes(img[so:so + n]) != jmp(at) + pad:
            bad.append(f"our detour 0x{site:08x} is not `jmp 0x{at:08x}` + nops")
        if ref_detour[6:] != pad:
            bad.append("reference detour padding differs")
        if bytes(tsb[o(ref_at):o(ref_at) + len(blob)]) != blob:
            bad.append(f"cave body differs: ours @0x{at:08x} vs reference @0x{ref_at:08x} "
                       "(relocation is not supposed to change the code)")
        ref_changed = {i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y}
        if not ref_changed <= set(range(so, so + n)) | set(range(o(ref_at), o(ref_at) + len(blob))):
            bad.append("reference image changes bytes outside its own detour + cave")
        print("  manual-trig fix vs build_trigscale_only.py: "
              + (f"identical (cave relocated 0x{ref_at:08x} -> 0x{at:08x})" if not bad else "DIVERGED"))
        for b in bad:
            print(f"    - {b}")
        if bad:
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
    print("  [PTN]  + [TRACK n]  ->  reload track n's CF-saved sequence. Part untouched.")
    print("                          toast: TRK SEQ RELOADED")
    print("  [BANK] + [TRACK n]  ->  the same, PLUS re-apply the saved Part from RAM.")
    print("                          two-line box: TRK SEQ + PART / RELOADED")
    print("                          never-saved Part: TRK SEQ RELOADED / SAVE PART FIRST!")
    print("                          (the sequence still reloads -- only the Part does not)")
    print("  SELECT BANK now opens on the [BANK] RELEASE, not the press, so neither")
    print("    chord flashes a window. A plain [BANK] tap still toggles it as stock does.")
    print("  Reloads NEVER touch the transport: the playhead and the internal metronome")
    print("    keep their phase (RELOAD_NOW is not armed on any path).")
    print("  Deferred to later, by the user's own scoping: all-tracks and whole-bank reload.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()
