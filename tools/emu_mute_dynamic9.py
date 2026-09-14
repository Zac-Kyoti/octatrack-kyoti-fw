#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Decisive dynamic validation of the mt_trig fix (patch_softmute.s, detours FUN_40006844):
drives the REAL firmware (full-firmware Unicorn, refs/octabam) through the same real
sequencer playback used to find the bug, with the track muted BEFORE any trigs fire, and
watches the exact per-trig side effects identified as the real "start a voice" signature
(emu_mute_dynamic8.py): writes to VOICE_BASE+track*0xA8+0x04/+0x08 (the arena rebind) and
+0x90 (the per-trig counter). If the fix works, a MUTED track's real trigs must produce
NONE of these writes; an UNMUTED control track must be completely unaffected (same writes,
same frames, as the pre-fix baseline).

    python3 tools/emu_mute_dynamic9.py [out/mainos_mutemode_dt.bin] [--dt]

Pass --dt to also test MUTE MODE=2 (DT) instead of the default OT+FX (1).
~10-20 min wall (one boot + LOAD PROJECT + playback run).
"""
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
DT_MODE = "--dt" in sys.argv
IMAGE = pathlib.Path(ARGS[0] if ARGS else "out/mainos_mutemode_dt.bin")
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
MUTE_STATE = 0x80000008
GATE = 0x800000dc
T_MUTED = 0     # track 1: the FLEX track this whole investigation has used
T_CONTROL = 6   # track 7: an unmuted control track that also trigs regularly (per dynamic8's log)


def watch_offsets(rt, track, tag):
    vbase = VOICE_BASE + track * VOICE_STRIDE
    hits = []

    def on_write(u, acc, addr, size, val, d):
        off = addr - vbase
        if off in (0x04, 0x08, 0x90):
            hits.append((rt.frame_count, off, val))
    h = rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=vbase + 0x04, end=vbase + 0x90 + 3)
    return hits, h


def main():
    img_path = ROOT / IMAGE
    if not img_path.exists():
        sys.exit(f"missing {img_path} -- run tools/build_mutemode_dt.py first")
    gate = 2 if DT_MODE else 1
    print(f"MUTE MODE = {'DT' if DT_MODE else 'OT+FX'} (gate={gate}), muting track {T_MUTED+1}, "
          f"control track {T_CONTROL+1} left unmuted")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} saved_bank={saved_bank} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)   # pattern index 1 = P2 (Part2/T1=FLEX)
    rt.run(ms=500)

    # mute BEFORE any trig fires
    rt.uc.mem_write(GATE, struct.pack(">I", gate))
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 1 << (8 + T_MUTED)))

    hits_muted, h1 = watch_offsets(rt, T_MUTED, "muted")
    hits_control, h2 = watch_offsets(rt, T_CONTROL, "control")

    rt.install_trig_log()
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print("playing 6000ms with the mute already engaged...")
    rt.run(ms=6000)
    rt.uc.hook_del(h1)
    rt.uc.hook_del(h2)

    trig_frames_muted = sorted({f for f, tr, v in rt.live_nibble_log if tr == T_MUTED})
    trig_frames_control = sorted({f for f, tr, v in rt.live_nibble_log if tr == T_CONTROL})
    print(f"\nreal trig frames, muted track {T_MUTED+1}:   {trig_frames_muted}")
    print(f"real trig frames, control track {T_CONTROL+1}: {trig_frames_control}")

    print(f"\nmuted track {T_MUTED+1}: {len(hits_muted)} writes to +0x04/+0x08/+0x90 "
          f"(want 0 if the fix works):")
    for frame, off, val in hits_muted[:20]:
        print(f"    frame={frame:<6d} off=+{off:#04x} val={val:#010x}")

    print(f"\ncontrol track {T_CONTROL+1}: {len(hits_control)} writes to +0x04/+0x08/+0x90 "
          f"(want one set per real trig, same as the pre-fix baseline):")
    for frame, off, val in hits_control[:20]:
        print(f"    frame={frame:<6d} off=+{off:#04x} val={val:#010x}")

    print("\n=== VERDICT ===")
    muted_clean = len(hits_muted) == 0
    control_intact = len(hits_control) >= len(trig_frames_control)  # 2 writes (+4,+8) per trig at minimum
    print(f"  muted track produced per-trig arena/counter writes: {not muted_clean}   (want False)")
    print(f"  control (unmuted) track still gets its per-trig writes: {control_intact}   (want True)")
    if muted_clean and control_intact:
        print("\n  PASS: the muted track's real trigs no longer touch the voice-start path at "
              "all; the unmuted control track is unaffected.")
    else:
        print("\n  DID NOT CONFIRM the expected pattern -- look closer before trusting this fix.")


if __name__ == "__main__":
    main()
