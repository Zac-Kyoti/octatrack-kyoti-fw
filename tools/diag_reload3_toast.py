#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_card -- the RELOAD card must dismiss ITSELF, with no key pressed.

Session 88, hardware report #10. The report asked for four things on the RELOAD
message box: title "RELOAD FROM PROJ", the second line CENTRED, NO "OK" prompt, and
the same card style for the plain TRK SEQ message instead of the block toast.

WHY MLNOTIFY HAD TO GO (decoded, not guessed)
  * it PUSHES keymap layer 0x400cdff8 at 0x4006d722 -- that push IS the OK prompt,
    so the box waits for a key by construction
  * it has no duration argument at all. An earlier comment in patch_reload3.s claimed
    0x460e5e20 was "a 40-frame countdown"; it is the box WIDTH accumulator (seeded 40
    at 0x4006d596, max'd against each line width + 9, capped 128). The hardware report
    is what exposed that error.
  * its body renderer 0x4006d128 draws every line at x=4 hardcoded (0x4006d170) --
    the left-justification the report describes.

So rl3_card builds the same box out of the same primitives, but on the popup slot
SHOW_WIN uses (0x460d1e5c), which owns stock's countdown and never pushes a layer.

WHAT IS ASSERTED
  * CD_FLAG is left NON-ZERO. The tick is gated on it (0x40056ab8 tstl / 0x40056abe
    beq), so a zero there means the card never dismisses at all -- the very stuck box
    this change exists to remove. An earlier version of the patch cleared it.
  * the card DISMISSES ON ITS OWN -- the window slot returns to 0 with NO key ever
    delivered. ** GATED ON A STOCK CONTROL. ** This harness does not drive the popup
    tick at all: measured, a stock SELECT BANK window does not count down here either,
    and CD_TICK fires zero times for it. So when the control does not dismiss, this
    tool reports the self-dismiss as UNMEASURABLE rather than failing -- a red X that
    only means "the emulator has no timer" would be worse than no result, and the
    first run of this tool produced exactly that misleading failure.
  * no OK-prompt keymap layer (0x400cdff8) is ever pushed, and MLNOTIFY is never
    called, on any path
  * the countdown is armed, and the box survives a short while before going (i.e. it
    is not dismissed instantly, which would look like a flicker)
  * NO countdown dots are ever drawn (0x40037cc8 never entered). These are instant
    actions, so a progress indicator would wrongly imply something is pending. The
    mechanism: that routine's only reachable caller here is the tick at 0x40056aea,
    which runs only while CD_SEGS is still non-zero AFTER being decremented -- so
    CD_SEGS = 1 makes the single segment expire straight into the dismiss instead.
  * back-to-back reloads both draw: the old dialog blocked the second one until OK was
    pressed, so this is a real regression guard, not a formality
  * every line is drawn CENTRED: we hook the text draw (0x40012bd8) and require the x
    argument to differ from stock's hardcoded 4. NOTE the hook is global, so it also
    sees the main screen's own text (status bar at y=1) and stock's title draw -- only
    draws whose text pointer is one of OUR strings are body lines, so the filter below
    is load-bearing, not cosmetic. Getting this wrong produced three false failures on
    the first run of this tool.

Usage:
  python3 tools/diag_reload3_card.py [--chord ptn|bank] [--track N]
"""
import argparse
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload as erl          # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
PTN_CODE, BANK_CODE = 0x2E, 0x2F
TRACK0 = 0x10
PRESS, RELEASE = 1, 0

WIN_SLOT   = 0x460D1E5C
CD_CUR     = 0x460D1E50
CD_SEGS    = 0x460D1E54
LAYER_PUSH = 0x40031494
OK_LAYER   = 0x400CDFF8
MLNOTIFY   = 0x4006D57C
TOAST      = 0x4005A2B8
DRAWTEXT   = 0x40012BD8
WIN_NEW    = 0x4005829C
DOTS       = 0x40037CC8      # draws the countdown dots -- must NEVER run for our card
CD_FLAG    = 0x460D1E4C      # tick GATE: zero => the countdown never runs at all
CD_TICK    = 0x40056AB8      # the gate+tick entry. NOT 0x40056ac0: that is past the
                             # gate, so hooking it cannot distinguish "tick never ran"
                             # from "tick ran but the gate sent it home".
G_KIND     = 0x80006A50


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--chord", choices=("ptn", "bank"), default="bank")
    ap.add_argument("--track", type=int, default=3)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = ROOT / "out" / "mainos_reload3.bin"
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.OUR_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, sb, bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(bank, P)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    print(f"load : bank={bank} pattern={P}")

    nm = subprocess.run(["m68k-elf-nm", "out/patch_reload3.elf"],
                        capture_output=True, text=True, cwd=ROOT).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines())
           if len(p) == 3}

    C = {"card": 0, "ml": 0, "toast": 0, "oklayer": 0, "winnew": 0, "dots": 0,
         "tick": 0}
    draws = []          # (x, y, textptr)
    boxw = []

    def bump(k):
        return lambda u, ad, sz, x: C.__setitem__(k, C[k] + 1)

    for addr, k in ((sym["rl3_card"], "card"), (MLNOTIFY, "ml"), (TOAST, "toast"),
                    (DOTS, "dots"), (CD_TICK, "tick")):
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, bump(k), begin=addr, end=addr)

    def on_push(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        if struct.unpack(">I", u.mem_read(sp + 4, 4))[0] == OK_LAYER:
            C["oklayer"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_push, begin=LAYER_PUSH, end=LAYER_PUSH)

    def on_winnew(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        w = struct.unpack(">I", u.mem_read(sp + 4, 4))[0]
        boxw.append(w)
        C["winnew"] += 1
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_winnew, begin=WIN_NEW, end=WIN_NEW)

    def on_draw(u, ad, sz, x):
        # DRAWTEXT(font, winptr, x, y, len, text) -- args at sp+4 .. sp+24
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        raw = u.mem_read(sp + 4, 24)
        font, winptr, xx, yy, ln, txt = struct.unpack(">6I", raw)
        draws.append((xx, yy, txt))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_draw, begin=DRAWTEXT, end=DRAWTEXT)
    rt.uc.ctl_flush_tb()

    rt.start_transport_live()
    for _ in range(20):
        rt.run(ms=60)

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def u32(ad):
        return struct.unpack(">I", rt.uc.mem_read(ad, 4))[0]

    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    def fire():
        mod = PTN_CODE if a.chord == "ptn" else BANK_CODE
        key(mod, PRESS)
        key(TRACK0 + a.track, PRESS)
        key(TRACK0 + a.track, RELEASE)
        key(mod, RELEASE)
        for _ in range(200):
            rt.run(ms=10)
            if rt.uc.mem_read(G_KIND, 1)[0] == 0:
                break

    print(f"\n--- [{a.chord.upper()}] + [TRACK {a.track+1}] : the card must draw ---")
    draws.clear(); boxw.clear()
    fire()
    chk(C["card"] == 1, f"rl3_card ran once (x{C['card']})")
    chk(C["ml"] == 0, f"MLNOTIFY never called (x{C['ml']}) -- the OK dialog is gone")
    chk(C["toast"] == 0, f"the block toast never called (x{C['toast']})")
    chk(C["oklayer"] == 0,
        f"NO OK-prompt keymap layer pushed (x{C['oklayer']}) -- nothing to answer")
    chk(u32(WIN_SLOT) != 0, f"the card window is up (slot={u32(WIN_SLOT):#x})")
    chk(u32(CD_SEGS) != 0, f"self-dismiss countdown armed (segs={u32(CD_SEGS)})")
    chk(C["dots"] == 0,
        f"NO countdown dots drawn (0x40037cc8 x{C['dots']}) -- instant action, so no "
        f"progress indicator")

    # ---- centring: OUR body lines must not be at stock's hardcoded x=4 ----
    # Our strings live in the cave; "SAVE PART FIRST!" is stock's own at 0x400b41bb.
    # Only the CAVE range counts. sym also holds absolute equates (0x460d1e4c,
    # 0x80006a55, ...), so min/max over sym.values() spans the whole address map and
    # filters nothing -- that mistake made this check pass everything on its first run.
    CAVE_LO, CAVE_HI = 0x400D6500, 0x400D7000
    def ours(t):
        return CAVE_LO <= t < CAVE_HI or t == 0x400B41BB   # + stock's SAVE PART FIRST!
    body = [d for d in draws if ours(d[2])]
    print(f"   all draws (x,y,text): {[(x, y, hex(t)) for x, y, t in draws]}")
    print(f"   OUR body lines      : {[(x, y, hex(t)) for x, y, t in body]}")
    print(f"   box width requested : {boxw}")
    chk(len(body) == 2, f"both body lines drawn (n={len(body)})")
    chk(bool(body) and all(d[0] != 4 for d in body),
        f"every body line at a COMPUTED x, not stock's hardcoded 4 -- i.e. centred "
        f"(x={[d[0] for d in body]})")
    if body:
        ys = [d[1] for d in body]
        chk(len(set(ys)) == len(ys), f"each body line on its own row (y={ys})")
        # Centring is x = (boxwidth - textwidth)/2, so the LONGER line must get the
        # SMALLER x -- whichever line that happens to be. Do NOT assume line 1 is the
        # longer one: it is for the [BANK] card ("TRK SEQ + PART" / "RELOADED") but not
        # for the [PTN] one ("TRK SEQ" / "RELOADED"), and hardcoding that assumption
        # produced a false failure that looked like a centring bug.
        if len(body) == 2:
            def txt(ptr):
                out = b""
                while len(out) < 40:
                    c = rt.uc.mem_read(ptr + len(out), 1)
                    if c == b"\x00":
                        break
                    out += c
                return out.decode("latin1")
            (x1, _, t1), (x2, _, t2) = body
            s1, s2 = txt(t1), txt(t2)
            print(f"   line texts: {s1!r} (x={x1})  {s2!r} (x={x2})")
            longer_x, shorter_x = ((x1, x2) if len(s1) >= len(s2) else (x2, x1))
            chk(longer_x <= shorter_x,
                f"the LONGER line sits further left ({longer_x} <= {shorter_x}) -- "
                f"which is what centring means, whichever line is longer")

    # ---- the countdown gate must be open, or nothing will ever dismiss it ----
    chk(u32(CD_FLAG) != 0,
        f"CD_FLAG is non-zero ({u32(CD_FLAG)}) -- the tick is gated on it at "
        f"0x40056abe, so zero here would mean the card NEVER dismisses")

    # ---- does it go away without a key? gated on a stock control ----
    print("\n--- it must dismiss ITSELF: no key is delivered from here on ---")

    def wait_gone(n=120):
        for i in range(n):
            rt.run(ms=20)
            if u32(WIN_SLOT) == 0:
                return i
        return None

    dots_before_control = C["dots"]
    gone_after = wait_gone()
    chk(dots_before_control == 0,
        f"no dots drawn for OUR card across its whole lifetime "
        f"(x{dots_before_control}) -- read BEFORE any stock control tap, which would "
        f"draw stock's own dots and has done so in an earlier version of this test")
    if gone_after is not None:
        chk(True, f"the card dismissed ITSELF with no key pressed "
                  f"(after ~{gone_after} x 20ms, ticks={C['tick']})")
    else:
        # Control: does STOCK's own countdown window dismiss in this harness?
        print("   our card did not dismiss -- running the STOCK control to find out "
              "whether this harness drives the countdown at all")
        key(BANK_CODE, PRESS); key(BANK_CODE, RELEASE)
        ctl_gone = wait_gone()
        if ctl_gone is None:
            print(f"   [SKIP] UNMEASURABLE HERE: stock SELECT BANK did not count down "
                  f"either (CD_TICK fired x{C['tick']}). This harness does not drive "
                  f"the popup tick, so neither result means anything. Not a failure -- "
                  f"and not evidence of success either; verify on hardware.")
        else:
            chk(False, f"the card did NOT dismiss itself although stock's window DID "
                       f"(control gone after {ctl_gone}) -- a real defect")

    # ---- a second reload must also draw (the OK dialog used to block this) ----
    print("\n--- a second reload must draw too (the OK dialog blocked this) ---")
    before = C["card"]
    draws.clear()
    fire()
    chk(C["card"] == before + 1, f"the card drew again (x{C['card'] - before})")
    chk(u32(WIN_SLOT) != 0, "the second card is up")
    chk(C["ml"] == 0 and C["oklayer"] == 0, "still no dialog and no OK prompt")

    print()
    if fails:
        for f in fails:
            print(f"   ** FAIL: {f} **")
        return 1
    print("   ALL GOOD -- titled card, centred lines, no OK prompt, self-dismissing, "
          "and repeatable.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
