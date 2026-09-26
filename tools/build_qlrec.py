#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
QUANTIZE LIVE REC front-panel toggle.

  [REC] held + [PLAY]                   opens a "QUANT LIVE REC ON/OFF" toast
                                        showing the CURRENT setting -- nothing
                                        changes yet
  [PLAY] again WHILE THAT TOAST IS UP   inverts the PERSONALIZE "QUANTIZE LIVE
                                        REC" row (0x800000ac); the toast
                                        re-opens on the new value.  Again, and
                                        it inverts again.
  [PLAY] once the toast has gone        just shows the current setting again

  The gesture is TOAST-GATED, not a double-tap: a press flips iff the toast is
  on screen, so the window you are tapping into is the one you can see.  Since
  Session 93 "is the toast on screen" is read from the OS's OWN notification
  state (0x460d1e70 handle / 0x460d1e6c countdown) rather than counted by a
  tick of ours -- the tick detour that did that crashed the unit.

  This is the all-or-nothing live-record quantize, not the per-track TRIG QUANT.

Base = stock 1.40C + the Bug-1 MIDI manual-trig fix (patch_trigscale), same as
every other Kyoti standalone build.  No PERSONALIZE menu surgery: the variable,
its getter/setter and its power-cycle persistence are all stock -- we only add a
front-panel gesture that writes the same word + 'ANDY' shadow and re-checksums.

Detours:
  0x40061778  6 B  jsr 0x4009b5c0        -> jmp qlr_play    ([PLAY] press)
  0x4004883a  6 B  clr.l 0x460d1726      -> jmp qlr_recrel   ([REC] release)

Session 93 removed a third detour (qlr_tick @ 0x400522ca).  It called
NOTIFY/NOTIFY_CLOSE -- hence the kernel post FUN_40000c3c, which wakes a task
and pokes the ready list -- from inside the engine frame handler, and hard-
crashed the unit on hardware: dead controls + a persistent HF crackle.  The
toast's life is now the OS's own countdown, read (never written) from
0x460d1e6c/0x460d1e70.

Session 50 REWRITE, still load-bearing: the toast is a periodically re-armed
dur>0 (self-timing) notification, never a one-shot dur<=0 ("persistent") one --
the dur<=0 form was flashed and confirmed to hang the unit (it registers on what
real disassembly of FUN_4005a2b8 shows is a modal window stack, not a passive
banner). See tools/patch_qlrec.s's header and NOTES.md "Session 50".

Usage:   python3 tools/build_qlrec.py [VERSTR] [LIVE_DUR]
Outputs: out/mainos_qlrec.bin, out/elek_qlrec.bin,
         out/OCTATRACK_OS1.40C_QLREC.syx, out/OCTATRACK_QLREC.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_qlrec.bin"
ELEK = ROOT / "out/elek_qlrec.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_QLREC.syx"
OUT_BIN = ROOT / "out/OCTATRACK_QLREC.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# The toast's life == the window in which a [PLAY] press flips, because they
# are the same thing: the OS's own notification countdown (0x460d1e6c).  The
# unit is one UI tick = 1/60 s (DTIM1 -> /2 prescaler -> the UI task; see
# tools/patch_qlrec.s's header), so the default 0x30 = 48 = 0.800 s -- which is
# also stock's own house value at 87 of its FUN_4005a2b8 call sites.
# Override on the command line for a feel-test.
LIVE_DUR = int(sys.argv[2], 0) if len(sys.argv) > 2 else None
if LIVE_DUR is not None and LIVE_DUR <= 0:
    sys.exit("LIVE_DUR must be > 0 -- dur <= 0 takes FUN_4005a2b8's modal path, "
             "which hung a real MKI (NOTES Session 50)")
_QLR_DEFSYM = f"LIVE_DUR={LIVE_DUR}" if LIVE_DUR is not None else None

PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18, "jmp")]),
    # Session 93: the third detour, `qlr_tick` @ 0x400522ca, is GONE.  It ran
    # NOTIFY/NOTIFY_CLOSE -- and so the kernel post FUN_40000c3c -- from inside
    # the engine frame handler, which hard-crashed the unit on hardware
    # (2026-09-25).  ASSERT_STOCK below proves the site is left untouched.
    ("patch_qlrec", 0x400d7400, _QLR_DEFSYM,
     [(0x40061778, "qlr_play",   "4eb94009b5c0", 6, "jmp"),
      (0x4004883a, "qlr_recrel", "42b9460d1726", 6, "jmp")]),
]

# Sites this build must leave byte-for-byte stock.  0x400522ca is the retired
# qlr_tick hook: if it is ever spliced again, the crash comes back.
ASSERT_STOCK = [
    (0x400522ca, "45f946c7dfba", "qlr_tick hook, RETIRED Session 93 (crashed the unit)"),
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

    # QUANTIZE LIVE REC is a stock PERSONALIZE word already inside the 0x64
    # 'ANDY' restore span -- assert stock leaves it there (so no pea 0x64->0x70).
    q = 0x800000ac - 0x80000070
    assert 0 <= q < 0x64, "QLR word slipped outside the stock restore span"
    for site in (0x4001f322, 0x4001f3be, 0x4001fb24):
        assert bytes(img[o(site):o(site) + 4]) == b"\x48\x78\x00\x64", \
            f"restore-length pea at 0x{site:08x} not stock -- another mod widened it?"
    print(f"  QLR word 0x800000ac is +0x{q:02x} in the stock restore span; no build change")

    for site, exp, why in ASSERT_STOCK:
        got = bytes(img[o(site):o(site) + len(exp) // 2])
        if got.hex() != exp:
            sys.exit(f"  0x{site:08x} MUST stay stock ({why}) -- found {got.hex()}")
        print(f"  0x{site:08x} left stock ({why})")

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
    print("  Hold [REC] + tap [PLAY] -> a toast shows the CURRENT QUANTIZE LIVE REC")
    print("  setting.  Tap [PLAY] again WHILE THAT TOAST IS UP -> the setting inverts")
    print("  and the toast re-opens on the new value; again inverts it back.  Once the")
    print("  toast has gone, the next tap only shows the setting again.  The toast is a")
    # Session 96 raised the default 0x30 -> 0x3c on the user's feel-test; this line
    # still said "default 0x30 ... 0.800 s" long after the patch shipped 0x3c, so derive
    # both the value and the seconds from LIVE_DUR instead of restating them.
    _dur = 0x3c if LIVE_DUR is None else LIVE_DUR       # patch_qlrec.s .ifndef default
    print(f"  single dur>0 notification ({'default ' if LIVE_DUR is None else ''}{_dur:#x}"
          f" = {_dur / 60:.3f} s at the 1/60 s UI tick) and")
    print("  closes instantly when [REC] is released.  Whether a press flips is read from")
    print("  the OS's OWN toast state -- this build ticks nothing of its own.")
    print("  PERSONALIZE row + power-cycle persistence unchanged.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()
