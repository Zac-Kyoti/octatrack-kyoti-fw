#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
emu_mute_dynamic9.py (post stack-fix, no crash) showed the muted track's per-trig arena
rebind (+0x04/+0x08) STILL happens at every trig -- meaning mt_trig's mute check never
finds the track muted, despite MUTE_STATE being poked to the muted bit before playback
starts. This checks the obvious remaining explanation: does something in the real RTOS
overwrite MUTE_STATE (0x80000008) after our poke, before any trig fires? A raw memory
poke bypasses whatever the real FUNC+TRACK mute path does; if MUTE_STATE is a derived/
synced value (not the authoritative store), our poke could get silently undone.

    python3 tools/emu_mute_dynamic10.py [out/mainos_mutemode_dt.bin]
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

MUTE_STATE = 0x80000008
GATE = 0x800000dc
T_MUTED = 0


def main():
    img_path = ROOT / IMAGE
    if not img_path.exists():
        sys.exit(f"missing {img_path} -- run tools/build_mutemode_dt.py first")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)
    rt.run(ms=500)

    rt.uc.mem_write(GATE, struct.pack(">I", 1))
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 1 << (8 + T_MUTED)))
    print(f"poked MUTE_STATE={rt.uc.mem_read(MUTE_STATE,4).hex()} GATE={rt.uc.mem_read(GATE,4).hex()}")

    writes = []

    def on_write(u, acc, addr, size, val, d):
        pc = u.reg_read(er.eb.UC_M68K_REG_PC)
        writes.append((rt.frame_count, pc, val))
    h = rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=MUTE_STATE, end=MUTE_STATE + 3)

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print("playing 3000ms, watching every write to MUTE_STATE...")
    rt.run(ms=3000)
    rt.uc.hook_del(h)

    final = rt.uc.mem_read(MUTE_STATE, 4).hex()
    print(f"\nfinal MUTE_STATE = {final}")
    print(f"\n{len(writes)} writes to MUTE_STATE after our poke:")
    for frame, pc, val in writes[:30]:
        print(f"    frame={frame:<6d} pc={pc:#010x} val={val:#010x}")
    if len(writes) > 30:
        print(f"    ... ({len(writes)-30} more)")

    if not writes:
        print("\n-- MUTE_STATE was NEVER overwritten after our poke; the mute bit should have "
              "stayed set the whole run. The mt_trig check itself must be the problem.")
    else:
        print(f"\n-- MUTE_STATE WAS overwritten {len(writes)}x after our poke -- our raw memory "
              "poke does not stick under the real scheduler. Need to find the real mute-set "
              "mechanism (or keep re-poking) instead of a one-shot write.")


if __name__ == "__main__":
    main()
