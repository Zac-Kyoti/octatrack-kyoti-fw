#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 58 continued yet again, part 8: the unmuted control for hook 13
(`relstate_shadow`). GATE stays 0 (stock OT mode) so SHADOW should read 0 for every
track, every frame -- meaning `btst %d3,SHADOW` always finds the bit clear and hook 13
should take the exact same "do nothing" path stock's own `bcc` already took, byte for
byte. This checks that DIRECTLY: records the FULL write sequence (not just resting
values) to track 1's four level-word slots across an identical, unmuted, densely-
retriggered run on both images, and asserts the two sequences are IDENTICAL -- proof
this hook never misfires and force-clears a track that should be playing normally.

    python3 tools/emu_relstate_shadow_unmuted.py [--ms 3000] [--track 1]
"""
import argparse
import pathlib
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
BOTLI = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "BOTLI"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn")
import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402


def run_scenario(img_path, track, ms):
    card, name = er.stage_project(str(BOTLI), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"  boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"  load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)
    rt.run(ms=500)

    for step in range(1, 65, 4):
        rt.poke_mask(0x00, step, track=track)
    # deliberately NO GATE / MUTE_STATE writes -- stays fully stock (GATE=0, nothing muted)

    log = []

    def make_watch(addr, tag):
        def on_write(u, acc, a, size, val, user):
            if size == 2 and a == addr:
                log.append((rt.frame_count, tag, val))
        rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=addr, end=addr + 1)

    make_watch(0x80000110 + track * 0x40 + 2, "ping0-dry")
    make_watch(0x80000110 + track * 0x40 + 4, "ping0-route")
    make_watch(0x80000310 + track * 0x40 + 2, "ping1-dry")
    make_watch(0x80000310 + track * 0x40 + 4, "ping1-route")
    rt.uc.ctl_flush_tb()

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    rt.run(ms=ms)
    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ms", type=int, default=3000)
    ap.add_argument("--track", type=int, default=1)
    args = ap.parse_args()

    images = [ROOT / "out/mainos_mutemode_dt.bin", ROOT / "out/mainos_relstate_shadow.bin"]
    logs = []
    for path in images:
        print(f"\n=== {path.name} (unmuted control) ===")
        log = run_scenario(path, args.track, args.ms)
        print(f"  {len(log)} total word-writes to the four level-word slots")
        logs.append(log)

    print("\n=== verdict ===")
    if logs[0] == logs[1]:
        print(f"IDENTICAL: {len(logs[0])} writes, byte-for-byte the same sequence on both "
              f"images. Confirms hook 13 is a true no-op in stock/unmuted mode -- it never "
              f"misfires and force-clears a track that should be playing normally.")
    else:
        n = min(len(logs[0]), len(logs[1]))
        first_diff = next((i for i in range(n) if logs[0][i] != logs[1][i]), n)
        print(f"DIVERGES at write #{first_diff}: baseline={logs[0][first_diff:first_diff+3]} "
              f"candidate={logs[1][first_diff:first_diff+3]}")
        print(f"lengths: baseline={len(logs[0])} candidate={len(logs[1])}")
        print("!! hook 13 changes behaviour even when nothing is muted -- DO NOT trust it "
              "until this is understood.")


if __name__ == "__main__":
    main()
