#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 52 fallout, continued (round 3): +0(active)/+8(SETTINGS) of the voice struct
were the wrong fields to watch -- SETTINGS is written ONCE at the initial machine bind
(frame 1) and never again despite 15+ real trigs afterward; +0 is only ever cleared by
an unrelated per-frame idle loop (pc=0x4000685e). Neither tracks "did THIS trig start
playback".

Widens to the WHOLE 0xA8-byte voice struct for track 0, drops the one known-noise
writer (pc=0x4000685e, off=0, val=0 -- confirmed harmless housekeeping), and prints
everything else with its frame number so we can eyeball which offsets change exactly
at the real trig frames (from install_trig_log) versus which just drift on their own
schedule.

    python3 tools/emu_mute_dynamic8.py [out/mainos_mutemode_dt.bin]
"""
import pathlib
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
NOISE_PC = 0x4000685e


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
        off = addr - vbase
        if pc == NOISE_PC and off == 0 and val == 0:
            return
        writes.append((rt.frame_count, pc, off, size, val))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=vbase, end=vbase + VOICE_STRIDE - 1)

    rt.install_trig_log()
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print(f"playing 6000ms, watching ALL writes (minus the known noise write) to track {T+1}'s "
          f"full voice struct 0x{vbase:08x}..0x{vbase+VOICE_STRIDE-1:08x}...")
    rt.run(ms=6000)

    trig_frames = sorted({f for f, tr, v in rt.live_nibble_log if tr == T})
    print(f"\nreal trig frames on track {T+1}: {trig_frames}")

    print(f"\n{len(writes)} non-noise writes to the voice struct:")
    for frame, pc, off, size, val in writes[:120]:
        near = min((abs(frame - tf), tf) for tf in trig_frames) if trig_frames else (None, None)
        tag = f" <-- {near[0]} frames from trig@{near[1]}" if near[0] is not None and near[0] <= 3 else ""
        print(f"    frame={frame:<6d} pc={pc:#010x} off=+{off:#04x} size={size} val={val:#010x}{tag}")
    if len(writes) > 120:
        print(f"    ... ({len(writes)-120} more)")

    print("\ndistinct (pc, offset) writer pairs:")
    seen = {}
    for frame, pc, off, size, val in writes:
        seen.setdefault((pc, off), []).append(frame)
    for (pc, off), frames in sorted(seen.items(), key=lambda kv: min(kv[1])):
        print(f"    pc={pc:#010x} off=+{off:#04x}  {len(frames)}x  frames={frames[:8]}{'...' if len(frames)>8 else ''}")


if __name__ == "__main__":
    main()
