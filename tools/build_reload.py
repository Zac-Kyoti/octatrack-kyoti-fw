#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
RELOAD FROM PROJECT (NOTES.md "Session 42" / "Session 43") -- stock 1.40C + the
MIDI manual-trig fix + a stay-open 3-item picker window (PTN SEQ / ALL PARTS /
PARTS + PTN SEQ).  Reloads the active pattern's sequence data and/or the 4 Parts from
the CF card's last SAVE BANK snapshot, without stopping the sequencer.

  UX (Session 44 -- OT-native):
    Hold [PTN] ~0.5 s  opens a sticky picker window (the OS's own hold event, as
                       used by [PAGE]-hold).  A quick [PTN] tap is unchanged.
    arrows      move the highlight (UP/RIGHT prev, DOWN/LEFT next, wrapping).
    [YES]       execute the highlight, close the window.
    [NO]        close the window, execute nothing.
    No timeout -- like every stock menu, the window stays until you answer it.
    While it is open [YES]/[NO] act ONLY on the picker.

  1. patch_trigscale  -- MIDI manual-trig stall fix.  Byte-identical detour + cave
                         to build_trigscale_only.py / build_directjump.py.
  2. patch_reload     -- six detours:
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
                             it, then: ALL PARTS / PARTS + PTN SEQ -> FUN_4004aab4(0..3) (stock
                             RELOAD PART x4) + the stock UI refresh, here in the
                             key handler; PTN SEQ / PARTS + PTN SEQ -> arm
                             {G_KIND=1, G_PAT=active} + post FUN_40022778(1<<curbank).
                             Toast + swallow.  Window closed -> replay the stock
                             prologue (DJ's [PTN]+[YES] toggle is untouched --
                             rl_yes only acts while G_MENU==1).
       rl_arr_a @0x4004b970  UP/RIGHT key handler (keycodes 0x34/0x21).  Window
                             open -> previous item, redraw, swallow.  Closed ->
                             replay the displaced prologue, fall through.
       rl_arr_b @0x400491a0  DOWN/LEFT key handler (keycodes 0x33/0x20).  Window
                             open -> next item, redraw, swallow.  Closed -> ditto.
       rl_job   @0x40085864  the storage task's type-0x14 case.  When G_KIND==1:
                             open bankNN.strd (28 KB of the loader's own 64 KB
                             buffer), read the 22-byte header, parse patterns
                             0..P sequentially with the firmware's own per-
                             pattern parser FUN_4008cebc (0..P-1 discarded to a
                             36 KB scratch, pattern P kept), memcpy P -> the live
                             slab (restoring the live slab+0x8e57 Part-link byte
                             afterwards -- a sequence reload never re-points the
                             pattern at a different Part), set 0x46c8028a, rejoin
                             the case's exit.  Open
                             ENOENT -> exit d0=-12 -> the stock "THIS BANK HAS
                             NEVER BEEN SAVED!" dialog for free.  Inert when
                             G_KIND==0; a re-entrant real RELOAD BANK is
                             unaffected (worker latches + clears G_KIND).

  No scratch BANK is used (an earlier design borrowed one -- rejected: it put a
  bystander bank's data at risk).  PTN SEQ writes nothing but pattern P's live
  slab; ALL PARTS is the stock per-part reload path.  No PERSONALIZE entry, no
  persistent state -> no 'ANDY' shadow / pea 0x64->0x70.

  STATUS: PTN SEQ emu-validated end to end (emu_reload.py --combo + --patched).
  ALL PARTS / PARTS + PTN SEQ + the picker: static + assembly checked; parts =
  the stock FUN_4004aab4 path.  Needs a hardware pass (FLASHING.md 4.7).

  HW-only from Session 42, plus (Session 44):
    - the OS hold-event threshold + feel for [PTN] (same mechanism as [PAGE]-hold);
    - whether an arrow press reaches rl_arr_a/b while the FUN_4005a0e0 popup is up
      -- if not, fall back to a hook in the event dispatcher FUN_40061b60;
    - that FUN_4005a044 is only the PTN key handler (all its globals are PTN's).

Usage:   python3 tools/build_reload.py [VERSTR]      (default VERSTR = "140C_KYOTI")
Outputs: out/mainos_reload.bin, out/elek_reload.bin,
         out/OCTATRACK_OS1.40C_RELOAD.syx, out/OCTATRACK_RELOAD.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_reload.bin"
ELEK = ROOT / "out/elek_reload.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_RELOAD.syx"
OUT_BIN = ROOT / "out/OCTATRACK_RELOAD.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# (source, load addr, defsym, [(detour site, symbol, expected bytes, len, kind)])
PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    ("patch_reload", 0x400d7400, None,
     [(0x4005a044, "rl_ptn", "202f00087201", 6, "jmp"),        # PTN handler: move.l 8(sp),d0 ; moveq #1,d1  (event 2 = HOLD)
      (0x4005e25c, "rl_no", "202f00086714", 6, "jmp"),         # NO handler: move.l 8(sp),d0 ; beq.s 0x4005e276
      (0x4005e4c8, "rl_yes", "222f0004202f0008", 8, "jmp"),    # YES handler: move.l 4(sp),d1 ; move.l 8(sp),d0
      (0x4004b970, "rl_arr_a", "4feffff448d7040c", 8, "jmp"),  # UP/RIGHT handler: lea -12(sp),sp ; movem.l d2-d3/a2,(sp)
      (0x400491a0, "rl_arr_b", "2f02206f0008", 6, "jmp"),      # DOWN/LEFT handler: move.l d2,-(sp) ; movea.l 8(sp),a0
      (0x40085864, "rl_job", "2d4afd762f2a0004", 8, "jmp")]),  # 0x14 case: move.l a2,-650(fp) ; move.l 4(a2),-(sp)
]

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
    print("  Hold [PTN] ~0.5 s  (while playing)  ->  opens the picker window (sticky, no timeout)")
    print("  arrows                             ->  move the highlight: PTN SEQ / ALL PARTS / PARTS + PTN SEQ")
    print("  [YES]                              ->  execute the highlight + close, no transport stop")
    print("  [NO]                               ->  close the window, execute nothing")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()
