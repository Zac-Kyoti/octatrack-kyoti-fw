#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 49 -- causation proof that `FUN_40009094(bank, part)` really does refresh the
recorder-page UI cache (`0x80000c94 + track*12`, 8 tracks, both pages) from the applied
Part's stored recorder record (`blob + part*0x18b2 + 0x8f382 + track*12`).

Written because a hand-disassembly attribution of *which instruction* inside
`FUN_40009094` does this copy turned out to be wrong (its traced source address didn't
match the recorder record's real offset) -- rather than re-guess from a third reading
pass, this settles the question the fix actually depends on directly: does calling the
function change the cache to match a freshly-poked, distinctive value. It does --
scribble the cache to `0x99`, poke a distinctive record (`0x70..0x7b`) into the blob for
all 8 tracks, call the function once, and the cache comes back holding exactly the poked
bytes for every track. Confirmed, not just claimed -- see NOTES.md "Session 49"
"Verification pass".

    python3 tools/check_reccache_causation.py

~2-3 min wall (one boot + one load + one direct call). Needs `python3 tools/refs/sync.py`
+ the EMAC-patched Unicorn, same as the other `emu_*` tools.
"""
import os
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK_IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn -> "
             "( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )")
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402
import emu_card as ec            # noqa: E402

REC_CACHE = 0x80000c94
REC_BLOB_OFF = 0x8f382
PART_STRIDE = 0x18b2
FUN_40009094 = 0x40009094


def main():
    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(STOCK_IMAGE), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} posted={posted} final_bank={final_bank}")

    blob = struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]
    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    curpart = rt.uc.mem_read(0x80000003, 1)[0]
    print(f"blob={blob:#x}  curbank={curbank}  curpart={curpart}")

    poke = bytes(range(0x70, 0x7C))
    for t in range(8):
        rt.uc.mem_write(blob + curpart * PART_STRIDE + REC_BLOB_OFF + t * 12, poke)
    for t in range(8):
        rt.uc.mem_write(REC_CACHE + t * 12, b"\x99" * 12)   # scribble first, rule out coincidence

    before = [bytes(rt.uc.mem_read(REC_CACHE + t * 12, 12)) for t in range(8)]
    print("cache before call:", before[0].hex(' '))

    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    try:
        d0 = rt.call_as_main(FUN_40009094, args=(curbank, curpart), budget=4_000_000)
        print(f"FUN_40009094({curbank},{curpart}) -> d0={d0:#x}")
    except Exception as e:
        print(f"call raised {type(e).__name__}: {e}")

    after = [bytes(rt.uc.mem_read(REC_CACHE + t * 12, 12)) for t in range(8)]
    all_match = True
    for t in range(8):
        match = after[t] == poke
        all_match &= match
        print(f"T{t+1}: cache after = {after[t].hex(' ')}   poked = {poke.hex(' ')}   match_poke={match}")
    print(f"\n{'ALL GOOD -- causal, all 8 tracks match the poke' if all_match else 'MISMATCH -- re-check'}")


if __name__ == "__main__":
    main()
