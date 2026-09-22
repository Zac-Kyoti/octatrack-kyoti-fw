#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Follow-up to emu_mute_dynamic.py: that script saw FUN_40005178 NEVER entered at all in
4000ms of simulated playback after `seq_select_live(curbank, 1)` -- meaning either (a)
`seq_select_live` doesn't drive the full pattern->Part apply pipeline (a real risk --
this project's own PARTREAPPLY work found that a `sys` handler most UI paths call, not
a raw bank/pattern store, does the actual Part-apply), so track 1 never actually became
the assumed FLEX machine, or (b) FUN_40005178/trig_to_voice isn't the real per-step
dispatch path at all. Removes that variable: makes NO pattern/Part assumption, touches
NOTHING except starting the transport on whatever Part is active immediately after
LOAD PROJECT (stock reset = bank A / pattern 1), and independently logs real trig
events via `rt.install_trig_log()` (FW_LIVE_NIBBLE writes) alongside FUN_40005178 hits,
for ALL 8 audio tracks, unmuted -- so we can see directly whether trigs happen at all
and whether they correlate with a FUN_40005178 call.

    python3 tools/emu_mute_dynamic2.py [out/mainos_mutemode_dt.bin]
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

FUN_40005178 = 0x40005178


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

    calls = []

    def on_hit(u, addr, size, ctx):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        ret = struct.unpack(">I", u.mem_read(sp, 4))[0]
        track = struct.unpack(">i", u.mem_read(sp + 4, 4))[0]
        cmd = struct.unpack(">I", u.mem_read(sp + 8, 4))[0]
        calls.append((rt.frame_count, ret, track, cmd))
    h1 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_hit, begin=FUN_40005178, end=FUN_40005178 + 1)

    rt.install_trig_log()
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print("playing for 2000ms (unmuted, default Part/pattern straight off LOAD PROJECT)...")
    rt.run(ms=2000)
    rt.uc.hook_del(h1)

    print(f"\nlive_nibble_log (real trig events, FW_LIVE_NIBBLE writes): {len(rt.live_nibble_log)}")
    for frame, track, val in rt.live_nibble_log[:40]:
        print(f"    frame={frame:<6d} track={track} val={val:#04x}")
    if len(rt.live_nibble_log) > 40:
        print(f"    ... ({len(rt.live_nibble_log)-40} more)")

    print(f"\nFUN_40005178 entered {len(calls)} times:")
    for frame, ret, track, cmd in calls[:40]:
        print(f"    frame={frame:<6d} ret={ret:#010x} track={track} cmd={cmd:#06x}")
    if len(calls) > 40:
        print(f"    ... ({len(calls)-40} more)")

    if not rt.live_nibble_log:
        print("\n!! NO real trig events at all in 2000ms -- the transport/step engine "
              "likely isn't actually advancing in this scenario; the setup, not the "
              "FUN_40005178 theory, needs fixing first.")
    elif not calls:
        print("\n!! Real trigs DID happen but FUN_40005178 was NEVER entered for any of "
              "them -- trig_to_voice/FUN_40005178 is NOT the real per-step dispatch path "
              "for at least this project's default track/machine. The whole caller-address "
              "theory needs to be re-derived from a live trace, not re-guessed.")
    else:
        print("\ncorrelate the two logs above by frame number.")


if __name__ == "__main__":
    main()
