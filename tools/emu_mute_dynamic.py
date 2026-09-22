#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 52 fallout: the caller-address fix to patch_softmute.s `pre_v` (drop iff the
return address is one of trig_to_voice's 2 real jsr sites) was flashed and HW-reported
as making NO difference at all -- DT still suppresses nothing, OT+FX's blip is still
there. Static disassembly said this should have worked. This script actually DRIVES the
real sequencer against the real image bytes (full-firmware Unicorn, refs/octabam) and
watches every call that reaches FUN_40005178 (our pre_v cave, post-detour), logging its
return address / track / cmd and which path pre_v takes -- instead of guessing further
from source reading alone.

Loads the factory OT DEMO, selects pattern 2 (Part2/T1 = FLEX, confirmed audible on real
hardware in this project's own testing), mutes track 1, plays, and watches.

    python3 tools/emu_mute_dynamic.py [out/mainos_mutemode_dt.bin]

~1-2 min wall (one LOAD PROJECT + playback run).
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
SOLO_FLAG = 0x80000037
GATE = 0x800000dc
FUN_40005178 = 0x40005178       # our pre_v cave entry, post-detour
TTV_CALL1 = 0x400978a2
TTV_CALL2 = 0x400978dc
V_DROP = None                   # filled in below from the elf symbol table
T = 0                            # track 1 (0-indexed)


def main():
    img_path = ROOT / IMAGE
    if not img_path.exists():
        sys.exit(f"missing {img_path} -- run tools/build_mutemode_dt.py first")

    import subprocess
    elf = "out/patch_softmute_dt.elf" if str(IMAGE).endswith("_dt.bin") else "out/patch_softmute.elf"
    nm = subprocess.run(["m68k-elf-nm", str(ROOT / elf)], capture_output=True, text=True,
                         cwd=str(ROOT)).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    v_drop = sym["v_drop"]
    print(f"pre_v={sym['pre_v']:#x}  v_drop={v_drop:#x}  (from {elf})")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]

    for label, gate in [("OT+FX", 1), ("DT", 2)]:
        print(f"\n===== MUTE MODE = {label} (gate={gate}), track {T+1} muted, pattern 2 (FLEX) =====")
        rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")   # stop transport
        rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
        rt.seq_select_live(curbank, 1)                      # pattern index 1 = P2 (Part2/T1=FLEX)
        rt.run(ms=500)

        rt.uc.mem_write(GATE, struct.pack(">I", gate))
        rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 1 << (8 + T)))   # mute track T
        rt.uc.mem_write(SOLO_FLAG, b"\x00")

        calls = []

        def on_hit(u, addr, size, ctx):
            sp = u.reg_read(er.eb.UC_M68K_REG_A7)
            ret = struct.unpack(">I", u.mem_read(sp, 4))[0]
            track = struct.unpack(">i", u.mem_read(sp + 4, 4))[0]
            cmd = struct.unpack(">I", u.mem_read(sp + 8, 4))[0]
            calls.append((rt.frame_count, ret, track, cmd))

        drops = []

        def on_drop(u, addr, size, ctx):
            drops.append(rt.frame_count)

        h1 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_hit, begin=FUN_40005178, end=FUN_40005178 + 1)
        h2 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_drop, begin=v_drop, end=v_drop + 1)

        rt.internal_clock()
        rt.frame = True
        rt.next_frame = rt.sample + er.FRAME_PERIOD
        rt.exact_clock()
        rt.start_transport_live()
        rt.run(ms=4000)

        rt.uc.hook_del(h1)
        rt.uc.hook_del(h2)

        print(f"  FUN_40005178 entered {len(calls)} times while track {T+1} muted:")
        for frame, ret, track, cmd in calls[:30]:
            tag = ("TTV_CALL1" if ret == TTV_CALL1 else
                   "TTV_CALL2" if ret == TTV_CALL2 else "other-caller")
            print(f"    frame={frame:<6d} ret={ret:#010x} ({tag:11s}) track={track} cmd={cmd:#06x}")
        if len(calls) > 30:
            print(f"    ... ({len(calls)-30} more)")
        t_calls = [c for c in calls if c[2] == T]
        ttv_t_calls = [c for c in t_calls if c[1] in (TTV_CALL1, TTV_CALL2)]
        print(f"  calls for track {T+1}: {len(t_calls)}   of those from trig_to_voice: {len(ttv_t_calls)}")
        print(f"  v_drop actually taken: {len(drops)} times")
        if not calls:
            print("  !! FUN_40005178 was NEVER entered at all -- trig_to_voice may not even "
                  "run for this track/pattern in this scenario, or track 1 never re-trigs "
                  "(a held/looping voice with no fresh 'start' needed).")
        elif not ttv_t_calls:
            print("  !! FUN_40005178 WAS entered for other things, but never from "
                  "trig_to_voice for this track -- the 2 return addresses this fix relies "
                  "on are wrong for what's actually happening here.")
        elif not drops:
            print("  !! trig_to_voice calls for this muted track were seen, but v_drop was "
                  "NEVER taken -- the mute/solo check itself (or the GATE check before it) "
                  "is failing to recognize this state.")
        else:
            print("  looks correct: trig_to_voice calls for the muted track were dropped.")


if __name__ == "__main__":
    main()
