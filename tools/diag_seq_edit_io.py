#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_seq_edit_io -- make the FIRMWARE edit a sequence, then see what it touches.

WHY THIS EXISTS (Session 84)
----------------------------
Hardware report #7 says RELOAD BUSY appears after EDITING the sequence with the
transport running. Nothing in this repo could test that claim, because nothing
here has ever made the firmware edit anything:

  * `emu_reload.py`'s `scribble()` and octabam's `poke_trig()` both edit by
    WRITING MEMORY DIRECTLY. They change the data but never run a single
    instruction of the firmware's own edit path, so they cannot reveal what that
    path touches.
  * A first attempt (`diag_scratch_clobber.py`) drove trig keycodes and reported
    "0 writes to 0x80006a50..55" -- a VACUOUS result, because it never verified
    an edit had happened at all. Zero writes including our own should have been
    the tell.

So this tool's core is a **liveness gate on the EDIT itself**: it watches the
pattern's own trig-mask bytes and refuses to report a scratch verdict unless the
firmware actually wrote them. It tries several input strategies and reports which
ones really edit, so the working recipe is discovered rather than assumed.

WHAT IT WATCHES
  edit signal : blob + P*PAT_STRIDE + trk*TRAC_STRIDE + 0x00..0x0f (trig masks)
                and the p-lock window, for ALL 8 audio tracks
  suspect     : 0x80006a50..55 -- G_KIND / G_PAT / G_MENU / G_SEL / G_TRK / G_TMIDI
                (RELOAD2's scratch; "genuinely free" was concluded from an
                ABSOLUTE-LONG-only scan, which cannot see register-indirect
                writes -- the same blind spot that already forced an xref
                retraction in this thread)

Every write is reported with the writing PC, so ours and stock's are separable.

Usage: python3 tools/diag_seq_edit_io.py [--trigs N]
"""
import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload2 as erl2        # noqa: E402
import emu_reload as erl          # noqa: E402
er = erl.er

SET_KEY_STATE = 0x40031734
PRESS, RELEASE = 1, 0
SCRATCH_LO, SCRATCH_HI = 0x80006A50, 0x80006A55
NAMES = {0x80006A50: "G_KIND", 0x80006A51: "G_PAT", 0x80006A52: "G_MENU",
         0x80006A53: "G_SEL", 0x80006A54: "G_TRK", 0x80006A55: "G_TMIDI"}
CAVE_LO, CAVE_HI = 0x400D6500, 0x400D7C3C


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--trigs", type=int, default=6)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = erl.RELOAD_IMAGE
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.RELOAD_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(final_bank, P)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    print(f"load : bank={final_bank} pattern={P}")

    blob = erl.BANK_BLOB + final_bank * erl.BANK_STRIDE
    pP = blob + P * erl.PAT_STRIDE
    print(f"     : pattern slab 0x{pP:08x}  (blob 0x{blob:08x}, "
          f"stride 0x{erl.PAT_STRIDE:x}, trac 0x{erl.TRAC_STRIDE:x})")

    edits, scratch = [], []
    phase = ["boot"]

    def on_edit(u, access, addr, size, value, x):
        edits.append((phase[0], addr, size, value, u.reg_read(er.eb.UC_M68K_REG_PC)))

    def on_scratch(u, access, addr, size, value, x):
        scratch.append((phase[0], addr, size, value, u.reg_read(er.eb.UC_M68K_REG_PC)))

    # Session 84, second pass: the first version watched a NARROW guessed window
    # (trig-mask bytes in the cold blob) and reported zero writes -- which the
    # edit-liveness gate correctly refused to turn into a conclusion. Two things
    # could make that window wrong rather than the edit absent: trig edits might
    # land in the LIVE copy (0x1001614e) rather than the cold blob, and the
    # keycodes might not be dispatching at all. So: verify dispatch directly, and
    # diff the WHOLE of both stores rather than trusting an offset guess.
    DISPATCH_BASE = 0x46C7D8DE
    LIVE = 0x1001614E
    LIVE_LEN = 0x8ED80

    def slot(code):
        return struct.unpack(">I", rt.uc.mem_read(DISPATCH_BASE + code * 24, 4))[0]

    dispatched = {}

    def mk_disp(code):
        def cb(u, ad, sz, x):
            dispatched[code] = dispatched.get(code, 0) + 1
        return cb

    print("\n  keycode -> live dispatch-table handler (is a trig key even wired?)")
    for code in range(0, 0x10):
        h = slot(code)
        if code < 4 or code == 0x0F:
            print(f"    code 0x{code:02x} -> 0x{h:08x}")
        if 0x40000000 <= h < 0x40200000:
            rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk_disp(code), begin=h, end=h)

    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_scratch, begin=SCRATCH_LO, end=SCRATCH_HI)
    rt.uc.ctl_flush_tb()

    def snap_stores():
        return (bytes(rt.uc.mem_read(blob, erl.BANK_STRIDE)),
                bytes(rt.uc.mem_read(LIVE, LIVE_LEN)))

    def diff_stores(before, after, base_names=("blob", "live")):
        out = []
        for (b, a_), nm in zip(zip(before, after), base_names):
            n = sum(1 for x, y in zip(b, a_) if x != y)
            out.append((nm, n))
        return out

    rt.start_transport_live()
    for _ in range(30):
        rt.run(ms=60)

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=4_000_000)

    def trigs(n):
        for i in range(n):
            key(i & 0x0F, PRESS)
            key(i & 0x0F, RELEASE)
            for _ in range(3):
                rt.run(ms=60)

    def strategy(name, fn):
        phase[0] = name
        s0 = len(scratch)
        d0 = dict(dispatched)
        before = snap_stores()
        try:
            fn()
        except Exception as ex:
            print(f"  {name:<26} ** fault: {ex} **")
            return 0, 0
        after = snap_stores()
        d = diff_stores(before, after)
        ds = len(scratch) - s0
        fired = sum(dispatched.get(c, 0) - d0.get(c, 0) for c in range(0x10))
        changed = sum(n for _, n in d)
        print(f"  {name:<26} handlers-fired={fired:<4} "
              + "  ".join(f"{nm}-bytes-changed={n}" for nm, n in d)
              + f"  scratch-writes={ds}")
        return changed, ds

    print(f"\n{'strategy':<28}did the firmware actually edit?")
    results = {}
    results["plain trigs"] = strategy("plain trigs", lambda: trigs(a.trigs))
    results["REC then trigs"] = strategy(
        "REC then trigs", lambda: (rt.press_rec_live(), trigs(a.trigs)))
    results["REC again then trigs"] = strategy(
        "REC again then trigs", lambda: (rt.press_rec_live(), trigs(a.trigs)))

    total_edits = sum(v[0] for v in results.values())
    print(f"\n  trig handlers that ever fired: "
          f"{ {hex(k): v for k, v in sorted(dispatched.items())} }")
    print()
    if total_edits == 0:
        print("  ** ABORT: no strategy changed a single byte of either the cold\n"
              "     blob or the live copy. The harness still cannot edit a\n"
              "     sequence, so NO conclusion may be drawn about the scratch.\n"
              "     If handlers-fired is non-zero the keys ARE dispatching and the\n"
              "     blocker is UI mode (grid-record), not the keycodes. **")
        return 2

    print(f"  EDIT LIVENESS OK -- {total_edits} byte(s) of pattern store changed "
          "by firmware")
    print(f"\n  scratch 0x80006a50..55: {len(scratch)} write(s)")
    foreign = [w for w in scratch if not (CAVE_LO <= w[4] < CAVE_HI)]
    sseen = {}
    for ph, addr, size, val, pc in scratch:
        sseen[(ph, addr, size, pc)] = sseen.get((ph, addr, size, pc), 0) + 1
    for (ph, addr, size, pc), n in sorted(sseen.items()):
        who = "OURS" if CAVE_LO <= pc < CAVE_HI else "** STOCK **"
        print(f"    [{ph:<22}] {NAMES.get(addr, hex(addr)):<7} size={size} "
              f"pc=0x{pc:08x} {who} x{n}")
    print("\n  final: " + "  ".join(
        f"{NAMES[k]}={rt.uc.mem_read(k,1)[0]}" for k in sorted(NAMES)))

    print()
    if foreign:
        print(f"  ** FOUND IT: {len(foreign)} scratch write(s) from OUTSIDE our "
              "cave, during real firmware editing. The scratch is NOT free. **")
        return 1
    print("  no foreign scratch writes during editing that DID land -- so\n"
          "  sequence editing is not what corrupts our scratch.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
