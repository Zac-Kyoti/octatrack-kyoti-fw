#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
RELOAD_FROM_PROJECT on the MIDI tracks (emulator, 2026-10-25).

0x80000012 (the "MIDI tracks are showing" flag) is a LONG; rl3_arm_n read it with move.b, i.e.
its high byte, which is always 0 -- so [PTN]+[TRACK n] on the MIDI side reloaded AUDIO track n.

Gate: a project that loads with the MIDI tracks showing (JAM2). In RAM, the playing pattern's M2
and audio T2 trig masks are both blanked; then real key events [PTN] down, [TRACK 2] down/up,
[PTN] up go through stock's set_key_state, and the storage task runs the reload.
  PASS: M2 is back to its SAVED bytes (bankNN.strd -- what RELOAD restores; the project loads
        bankNN.work) and T2 is still blank (only the MIDI track was reloaded).

  python3 tools/diag_reload_midi.py --image out/mainos_reload_from_project.bin --project DIR --name NAME
"""
import argparse, os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY = 0x40031734
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A, MIDI_BASE, TRAC_M = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A, 0x48D0, 0x8B0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--chord", choices=("ptn", "bank"), default="ptn",
                    help="ptn: [PTN]+[TRACK 2] (sequence); bank: [BANK]+[TRACK 2] (sequence + the saved Part)")
    a = ap.parse_args(argv)
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name, tree=f"out/_emu_reload_midi_{pathlib.Path(a.image).stem}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    rt.run(ms=300)
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")

    def key(code, ev):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY, args=(code, ev), budget=600000)
        rt.run(ms=60)

    pat = rd(0x800065BE, 1)
    slab = BLOB + bank * BANKSTRIDE + pat * PATSTRIDE
    m2, t2 = slab + MIDI_BASE + 1 * TRAC_M, slab + 1 * TRAC_A
    midi = rd(0x80000012, 4)
    print(f"bank {bank} pattern {pat}; MIDI tracks showing: 0x80000012 = 0x{midi:x}; track {rd(0x80000000, 1)}")
    if not midi:
        sys.exit("this project does not load with the MIDI tracks showing -- use one that does (JAM2)")
    m2_ram, t2_card = bytes(u.mem_read(m2, 8)), bytes(u.mem_read(t2, 8))
    strd = (pathlib.Path(a.project) / f"bank{bank + 1:02d}.strd").read_bytes()
    mtra = 0x16 + 0x8EEC * pat + 8 + 8 * 0x922 + 1 * 0x8B9     # the saved file's M2 block
    assert strd[mtra:mtra + 4] == b"MTRA", "unexpected bank file layout"
    m2_card = strd[mtra + 9:mtra + 17]
    print(f"M2 saved (.strd) trig mask {m2_card.hex()}  (in RAM after load: {m2_ram.hex()})")
    print(f"M2 trig mask {m2_card.hex()}  T2 trig mask {t2_card.hex()}")
    if m2_card == bytes(8) or t2_card == bytes(8):
        sys.exit("need trigs on both M2 and T2 of the playing pattern")
    u.mem_write(m2, bytes(8))
    u.mem_write(t2, bytes(8))
    calls = []
    u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad, sz, ud: calls.append(rd(uc.reg_read(er.eb.UC_M68K_REG_A7) + 4, 4)),
               begin=0x4004AAB4, end=0x4004AAB4)          # stock's Part reload (part)
    mod = 0x2E if a.chord == "ptn" else 0x2F
    key(mod, 1)
    key(0x11, 1)
    key(0x11, 0)
    key(mod, 0)
    rt.run(ms=4000)                     # the storage task's type-0x14 job reads the .strd
    m2_now, t2_now = bytes(u.mem_read(m2, 8)), bytes(u.mem_read(t2, 8))
    print(f"after the chord + [TRACK 2]: M2 {m2_now.hex()}  T2 {t2_now.hex()}")
    ok_m, ok_t = m2_now == m2_card, t2_now == bytes(8)
    print(f"stock Part reload 0x4004aab4 called {len(calls)}x, part args {calls}; "
          f"the playing pattern's Part (0x80000003) = {rd(0x80000003, 1)}")
    if a.chord == "bank":
        ok_p = calls == [rd(0x80000003, 1)]
        print(f"  {'ok  ' if ok_p else 'FAIL'} [BANK]+[TRACK]: the Part reload ran once, for the playing pattern's Part")
        ok_t = ok_t and ok_p
    print(f"  {'ok  ' if ok_m else 'FAIL'} the MIDI track M2 was reloaded from the saved bank (.strd)")
    print(f"  {'ok  ' if ok_t else 'FAIL'} the audio track T2 was left alone")
    print("VERDICT:", "PASS" if ok_m and ok_t else "FAIL")
    return 0 if ok_m and ok_t else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
