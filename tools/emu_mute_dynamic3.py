#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Follow-up to emu_mute_dynamic2.py, which proved real trigs happen on track 1 (frames
1379, 2757, 4135, ...) but FUN_40005178 is NEVER entered for any of them -- the
trig_to_voice(0x400977cc)/FUN_40005178(0x40005178) theory from static disassembly is
WRONG for whatever machine is actually active on track 1 by default after LOAD PROJECT.

This traces the REAL executed code around a live trig instead of guessing from a static
Ghidra dump again: arms a short burst PC trace the moment FW_LIVE_NIBBLE is written for
track 0 (skipping the frame-1 boot artifact), then -- since every call in this codebase
so far has been `jsr abs.l` (opcode 0x4eb9) -- scans the ACTUALLY EXECUTED addresses in
that burst for `4eb9` opcodes and reports (caller, target) in execution order. This is
ground truth: whatever function real hardware/firmware calls to turn that trig into a
voice command, its call site will show up here.

    python3 tools/emu_mute_dynamic3.py [out/mainos_mutemode_dt.bin]
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

BASE = 0x40000400
FW_LIVE_NIBBLE = 0x46104d15
BURST_INSNS = 20000              # how many instructions to trace after the arming trig
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

    state = {"armed": False, "done": False, "count": 0, "arm_frame": None}
    pcs = []

    def on_live(u, acc, addr, size, val, d):
        val &= 0xFF
        track = addr - FW_LIVE_NIBBLE
        if val and track == TARGET_TRACK and not state["armed"] and not state["done"] \
           and rt.frame_count > 100:
            state["armed"] = True
            state["arm_frame"] = rt.frame_count
            print(f"  armed burst trace at frame={rt.frame_count} (track {track} val={val:#04x})")

    def on_code(u, addr, size, ctx):
        if state["armed"]:
            pcs.append(addr)
            state["count"] += 1
            if state["count"] >= BURST_INSNS:
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

    print(f"\ncaptured {len(pcs)} executed instructions starting frame={state['arm_frame']}")
    if not pcs:
        print("!! never armed -- no track-0 trig seen after frame 100 in this window.")
        return

    print(f"PC range: {min(pcs):#010x} .. {max(pcs):#010x}")

    calls = []
    seen_pcs = set(pcs)
    for pc in pcs:
        o = pc - BASE
        if 0 <= o < len(img_bytes) - 5 and img_bytes[o:o + 2] == b"\x4e\xb9":
            target = int.from_bytes(img_bytes[o + 2:o + 6], "big")
            calls.append((pc, target))

    print(f"\n`jsr abs.l` (4eb9) instructions actually executed in the burst: {len(calls)}")
    seen_targets = {}
    for pc, target in calls:
        seen_targets.setdefault(target, []).append(pc)
    for target, callers in sorted(seen_targets.items(), key=lambda kv: min(kv[1])):
        first = min(callers)
        idx = pcs.index(first)
        print(f"    target={target:#010x}  called {len(callers)}x  first at burst-offset {idx:5d}  from caller-pc={first:#010x}")

    print("\n--- known landmarks, were they in the trace? ---")
    for name_, addr in [("trig_to_voice", 0x400977cc), ("trig_to_voice+0xd0ish", 0x40097890),
                        ("FUN_40005178 (pre_v cave / stock fn)", 0x40005178),
                        ("FUN_40008f84 (note-off)", 0x40008f84),
                        ("FUN_40005030", 0x40005030)]:
        hit = addr in seen_pcs or any(addr - 0x20 <= p <= addr + 0x120 for p in pcs if p != addr)
        exact = addr in seen_pcs
        print(f"    {name_:38s} 0x{addr:08x}  exact_hit={exact}  near_hit={hit}")


if __name__ == "__main__":
    main()
