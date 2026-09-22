#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
emu_mute_dynamic5.py PROVED trig_to_voice/FUN_40005178 is unrelated to ordinary
sequencer step-trigs: 79 real trigs fired across 6 seconds of playback and FUN_40005178
was entered zero times, neither voice-command mailbox was ever written. The whole
Session-52 "fix" patched dead code for this scenario -- which is exactly why the
hardware re-test showed no change at all.

This finds the REAL writer instead of guessing again: hooks the FW_LIVE_NIBBLE write
directly and captures the PC of the instruction that performs it (not just its
neighbourhood) -- this is, by definition, inside whatever function the real sequencer
uses to fire a trig. Then statically disassembles a window around that PC from the ROM
bytes we already have on disk (cheap, no more emulation needed) to find the enclosing
function and any nearby `jsr abs.l` calls -- which should include the real voice-start
dispatch.

    python3 tools/emu_mute_dynamic6.py [out/mainos_mutemode_dt.bin]
"""
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
IMAGE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_dt.bin")
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"
BASE = 0x40000400
FW_LIVE_NIBBLE = 0x46104d15

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

    hits = []

    def on_live(u, acc, addr, size, val, d):
        val &= 0xFF
        if val:
            pc = u.reg_read(er.eb.UC_M68K_REG_PC)
            hits.append((rt.frame_count, pc, addr - FW_LIVE_NIBBLE, val))
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_live, begin=FW_LIVE_NIBBLE, end=FW_LIVE_NIBBLE + 7)

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print("playing for 3000ms, capturing the PC of every FW_LIVE_NIBBLE write...")
    rt.run(ms=3000)

    print(f"\n{len(hits)} writes captured:")
    pcs_seen = set()
    for frame, pc, track, val in hits[:60]:
        print(f"    frame={frame:<6d} pc={pc:#010x} track={track} val={val:#04x}")
        pcs_seen.add(pc)
    if len(hits) > 60:
        print(f"    ... ({len(hits)-60} more)")

    print(f"\ndistinct writer PCs: {sorted(hex(p) for p in pcs_seen)}")

    for pc in sorted(pcs_seen):
        o = pc - BASE
        print(f"\n=== disassembly window around writer pc={pc:#010x} (raw bytes, manual scan) ===")
        lo, hi = max(0, o - 0x60), min(len(img_bytes), o + 0x80)
        window = img_bytes[lo:hi]
        # scan for jsr abs.l (4eb9) within this window
        i = 0
        while i < len(window) - 5:
            if window[i] == 0x4e and window[i + 1] == 0xb9:
                target = int.from_bytes(window[i + 2:i + 6], "big")
                caller = BASE + lo + i
                marker = " <-- BEFORE writer" if caller < pc else " <-- AFTER writer" if caller > pc else ""
                print(f"    jsr caller={caller:#010x} target={target:#010x}{marker}")
                i += 6
            else:
                i += 2
        # raw hex around the writer instruction itself (16 bytes centered)
        centre = o - lo
        seg = window[max(0, centre - 8):centre + 8]
        print(f"    raw bytes at writer pc-8..pc+8: {seg.hex()}")


if __name__ == "__main__":
    main()
