#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_pattern_switch_io -- does a PATTERN SWITCH touch the CF card?

Architecture question (Session 83): when the OT changes pattern, where does the
new sequence data come from -- the card, or RAM?

Measures card-path activity across three events, with the transport running:
  1. idle playback            (baseline)
  2. pattern switch, SAME bank
  3. bank switch              (contrast -- this one SHOULD hit the card)

Instrumented (counting entries, not inferring):
  FOPEN   0x40016864   buffered open
  FREAD   0x40016564   buffered read
  PARSEPAT 0x4008cebc  pattern deserialise from a file handle
  MKCURRENT 0x4000faf0 "make bank current" -- documented RAM->RAM memcpy

CAVEAT, same as diag_reload2_transport.py: this harness does not stream audio
from the card, so a zero FREAD count during plain playback is NOT evidence that
hardware playback avoids the card. The comparison that IS meaningful here is
pattern switch vs bank switch within this same harness.

Usage: python3 tools/diag_pattern_switch_io.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload2 as erl2        # noqa: E402
import emu_reload as erl          # noqa: E402
er = erl.er

SITES = {"FOPEN": 0x40016864, "FREAD": 0x40016564,
         "PARSEPAT": 0x4008CEBC, "MKCURRENT": 0x4000FAF0}


def main():
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
    pat = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(final_bank, pat)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    print(f"load : mounted={mounted} bank={final_bank} pattern={pat}")

    counts = {k: 0 for k in SITES}

    def mk(k):
        return lambda u, ad, sz, x: counts.__setitem__(k, counts[k] + 1)

    for k, a in SITES.items():
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk(k), begin=a, end=a)
    rt.uc.ctl_flush_tb()

    rt.start_transport_live()
    for _ in range(40):
        rt.run(ms=60)

    def phase(label, fn):
        base = dict(counts)
        fn()
        for _ in range(40):
            rt.run(ms=60)
        d = {k: counts[k] - base[k] for k in SITES}
        print(f"  {label:<28} " + "  ".join(f"{k}={d[k]:<6d}" for k in SITES))
        return d

    print(f"\n{'phase':<30}card-path activity")
    phase("1. idle playback", lambda: None)
    newpat = (pat + 1) % 16
    phase(f"2. pattern switch {pat}->{newpat}",
          lambda: rt.seq_select_live(final_bank, newpat))
    otherbank = 1 if final_bank == 0 else 0
    phase(f"3. bank switch {final_bank}->{otherbank}",
          lambda: rt.seq_select_live(otherbank, 0))
    print("\n(FREAD/FOPEN/PARSEPAT > 0 means the card path was entered; "
          "MKCURRENT is the RAM->RAM bank copy.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
