#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
emu_mute_dynamic9.py (post stack-fix) showed the muted track's per-trig arena rebind
still happening at every trig -- mt_trig apparently never takes the silenced branch.
emu_mute_dynamic10.py ruled out MUTE_STATE being overwritten (it holds the poked value
the whole run). This directly instruments our OWN mt_trig cave during the real run:
logs D1 (track), MUTE_STATE, GATE, and which branch got taken, every single time
mt_trig is entered -- ground truth instead of more static reasoning about registers
whose real values I haven't actually observed.

    python3 tools/emu_mute_dynamic11.py [out/mainos_mutemode_dt.bin]
"""
import pathlib
import struct
import subprocess
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
IMAGE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_dt.bin")
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"
ELF = "out/patch_softmute_dt.elf" if str(IMAGE).endswith("_dt.bin") else "out/patch_softmute.elf"

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

    nm = subprocess.run(["m68k-elf-nm", str(ROOT / ELF)], capture_output=True, text=True,
                         cwd=str(ROOT)).stdout
    sym = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    MT_TRIG, MT_SILENCED, MT_PASS = sym["mt_trig"], sym["mt_silenced"], sym["mt_pass"]
    print(f"mt_trig={MT_TRIG:#x} mt_silenced={MT_SILENCED:#x} mt_pass={MT_PASS:#x}")

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

    entries = []

    def on_entry(u, addr, size, ctx):
        d1 = u.reg_read(er.eb.UC_M68K_REG_D1)
        gate = struct.unpack(">I", u.mem_read(GATE, 4))[0]
        ms = struct.unpack(">I", u.mem_read(MUTE_STATE, 4))[0]
        entries.append((rt.frame_count, d1, gate, ms))
    h1 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_entry, begin=MT_TRIG, end=MT_TRIG + 1)

    branch = []

    def on_branch(u, addr, size, ctx):
        branch.append((rt.frame_count, "silenced" if addr == MT_SILENCED else "pass"))
    h2 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_branch, begin=MT_SILENCED, end=MT_SILENCED + 1)
    h3 = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_branch, begin=MT_PASS, end=MT_PASS + 1)

    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print("playing 4000ms, instrumenting every mt_trig entry...")
    rt.run(ms=4000)
    rt.uc.hook_del(h1)
    rt.uc.hook_del(h2)
    rt.uc.hook_del(h3)

    print(f"\n{len(entries)} mt_trig entries:")
    for (frame, d1, gate, ms), (bframe, btag) in zip(entries, branch):
        print(f"    frame={frame:<6d} D1(track)={d1} GATE={gate} MUTE_STATE={ms:#010x} -> {btag}")
    if len(entries) != len(branch):
        print(f"  !! entries ({len(entries)}) != branch outcomes ({len(branch)}) -- something else "
              f"reached mt_silenced/mt_pass without going through mt_trig's own entry, or vice versa")


if __name__ == "__main__":
    main()
