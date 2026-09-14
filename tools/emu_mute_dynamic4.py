#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Follow-up to emu_mute_dynamic3.py: the 20000-instruction burst AFTER a real track-0 trig
write (FW_LIVE_NIBBLE) contained almost no `jsr abs.l` calls, and none were
trig_to_voice/FUN_40005178 -- meaning either the live-nibble write is a TRAILING side
effect of a dispatch that already happened (need to look BEFORE it, not just after), or
the RTOS scheduler switched to an unrelated task right after arming and the real
dispatch runs on a later time-slice this burst missed.

This keeps a continuously-updated ROLLING window of the last N executed PCs (cheap:
append + trim) so that the moment a track-0 trig is seen, we already have everything
leading UP TO it, plus a forward burst as before. Scans both halves for `jsr abs.l`
(4eb9) call sites.

    python3 tools/emu_mute_dynamic4.py [out/mainos_mutemode_dt.bin]
"""
import pathlib
import sys
from collections import deque

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

BASE = 0x40000400
FW_LIVE_NIBBLE = 0x46104d15
PRE_WINDOW = 8000
POST_BURST = 20000
TARGET_TRACK = 0


def main():
    img_path = ROOT / IMAGE
    if not img_path.exists():
        sys.exit(f"missing {img_path} -- run tools/build_mutemode_dt.py first")
    img_bytes = img_path.read_bytes()

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} saved_bank={saved_bank} final_bank={final_bank} ({elapsed:.0f} ms)")

    ring = deque(maxlen=PRE_WINDOW)
    state = {"armed": False, "done": False, "count": 0, "arm_frame": None, "pre": None}
    post = []

    def on_live(u, acc, addr, size, val, d):
        val &= 0xFF
        track = addr - FW_LIVE_NIBBLE
        if val and track == TARGET_TRACK and not state["armed"] and not state["done"] \
           and rt.frame_count > 100:
            state["armed"] = True
            state["arm_frame"] = rt.frame_count
            state["pre"] = list(ring)
            print(f"  armed at frame={rt.frame_count} (track {track} val={val:#04x}); "
                  f"pre-window has {len(state['pre'])} instructions")

    def on_code(u, addr, size, ctx):
        ring.append(addr)
        if state["armed"]:
            post.append(addr)
            state["count"] += 1
            if state["count"] >= POST_BURST:
                state["armed"] = False
                state["done"] = True

    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_live, begin=FW_LIVE_NIBBLE, end=FW_LIVE_NIBBLE + 7)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_code)

    rt.install_trig_log()
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print("playing until a track-0 trig arms the trace + burst completes (up to 3000ms)...")
    rt.run(ms=3000, until=lambda r: state["done"])

    if state["pre"] is None:
        print("!! never armed.")
        return

    def scan(pcs, label):
        calls = []
        for pc in pcs:
            o = pc - BASE
            if 0 <= o < len(img_bytes) - 5 and img_bytes[o:o + 2] == b"\x4e\xb9":
                target = int.from_bytes(img_bytes[o + 2:o + 6], "big")
                calls.append((pc, target))
        print(f"\n{label}: {len(pcs)} instructions, {len(calls)} `jsr abs.l` calls")
        seen = {}
        for pc, target in calls:
            seen.setdefault(target, []).append(pc)
        for target, callers in sorted(seen.items(), key=lambda kv: pcs.index(min(kv[1]))):
            idx = pcs.index(min(callers))
            print(f"    target={target:#010x}  {len(callers)}x  offset {idx:5d}  caller={min(callers):#010x}")
        return calls

    scan(state["pre"], f"PRE-window (last {len(state['pre'])} instrs BEFORE the trig write)")
    scan(post, f"POST-burst ({len(post)} instrs AFTER the trig write)")

    print("\n--- known landmarks: exact-hit in PRE or POST? ---")
    all_pcs = set(state["pre"]) | set(post)
    for name_, addr in [("trig_to_voice", 0x400977cc),
                        ("FUN_40005178", 0x40005178),
                        ("FUN_40008f84 (note-off)", 0x40008f84),
                        ("FUN_40005030", 0x40005030),
                        ("FUN_40004db8 (frame builder)", 0x40004db8)]:
        print(f"    {name_:32s} 0x{addr:08x}  hit={addr in all_pcs}")


if __name__ == "__main__":
    main()
