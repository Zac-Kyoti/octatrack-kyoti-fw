#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 52 fallout, continued: trig_to_voice/FUN_40005178 are proven unrelated to
ordinary sequencer trigs (emu_mute_dynamic5.py: 0 hits across 79 real trigs). Traced the
real trig flag (FW_LIVE_NIBBLE) back to a step-evaluator around 0x4000b700 that writes
its own per-track command words directly (0x46c7e998+track*4 etc.) with no jsr handoff
visible in ~0x700 bytes of disassembly, and doesn't appear to test MUTE_STATE anywhere
in that span -- so mute suppression, if it exists for ordinary trigs, must be downstream
of it, closer to where a voice ACTUALLY starts.

This watches the VOICE STRUCT itself (0x800049d8 + track*0xA8, this project's own
`diff_flex_static.py` already treats `active`(+0)/`SETTINGS`(+8) as the ground-truth
"a voice really started" signal) for track 0, across the whole 6s playback window,
capturing the writer PC every time -- that PC is, almost by definition, inside whatever
function ACTUALLY dispatches a new voice, muted or not.

    python3 tools/emu_mute_dynamic7.py [out/mainos_mutemode_dt.bin]
"""
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
IMAGE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_dt.bin")
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn -> "
             "( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )")
import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402
import emu_card as ec            # noqa: E402

VOICE_BASE = 0x800049d8
VOICE_STRIDE = 0xA8
T = 0
MUTE_STATE = 0x80000008
GATE = 0x800000dc


def main():
    img_path = ROOT / IMAGE
    if not img_path.exists():
        sys.exit(f"missing {img_path} -- run tools/build_mutemode_dt.py first")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} saved_bank={saved_bank} final_bank={final_bank} ({elapsed:.0f} ms)")

    vbase = VOICE_BASE + T * VOICE_STRIDE

    writes = []

    def on_write(u, acc, addr, size, val, d):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        writes.append((rt.frame_count, pc, addr - vbase, size, val))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=vbase, end=vbase + VOICE_STRIDE - 1)

    rt.install_trig_log()
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print(f"playing 6000ms, watching writes to track {T+1}'s voice struct (0x{vbase:08x}..0x{vbase+VOICE_STRIDE-1:08x})...")
    rt.run(ms=6000)

    t_trigs = [x for x in rt.live_nibble_log if x[1] == T]
    print(f"\nreal trigs on track {T+1}: {len(t_trigs)}: {t_trigs[:15]}")

    print(f"\n{len(writes)} writes to the voice struct's +0 (active) / +8 (SETTINGS) fields (all offsets shown):")
    interesting = [w for w in writes if w[2] in (0, 8, 9, 10, 11)]
    for frame, pc, off, size, val in interesting[:60]:
        print(f"    frame={frame:<6d} pc={pc:#010x} off=+{off} size={size} val={val:#x}")
    if len(interesting) > 60:
        print(f"    ... ({len(interesting)-60} more)")

    pcs = sorted({w[1] for w in interesting})
    print(f"\ndistinct writer PCs touching +0/+8..+11: {[hex(p) for p in pcs]}")


if __name__ == "__main__":
    main()
