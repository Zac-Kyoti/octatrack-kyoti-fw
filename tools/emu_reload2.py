#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
emu_reload2 -- the same emulator checks as emu_reload.py, pointed at the
scaled-down build (patch_reload2.s / build_reload2.py -> out/mainos_reload2.bin).

Thin shim: swaps emu_reload's image path + symbol source, and overrides
COMBO_ITEMS to the 2-item picker.  All the logic (cmd_combo modal test,
--slice / --strd / --patched) lives in emu_reload.py.

  --combo    single-step the Session-44 OT-native picker: hold [PTN] opens
             (rl_ptn) -> arrows move G_SEL -> rl_yes executes / rl_no cancels.
             3 items: TRK SEQ (kind 3) / PTN SEQ (kind 1) / PART + PTN SEQ (kind 2).
  --patched  boot out/mainos_reload2.bin and drive rl_yes end to end -- PTN SEQ
             (the whole-pattern worker; PATCHED_GSEL=1 selects item 1).
  --trk      TRK SEQ (item 0): the worker copies back EXACTLY the addressed
             track's region -- the other tracks + Part link are left alone.
             Run it WITHOUT --combo (which permanently stubs FUN_40022778, the
             storage-job post the worker needs); --trk alone or with --patched.

    python3 tools/emu_reload2.py --combo
    python3 tools/emu_reload2.py --trk
    python3 tools/emu_reload2.py --patched --trk
"""
import pathlib
import subprocess
import sys

import emu_reload as erl

ROOT = pathlib.Path(__file__).resolve().parent.parent
_ELF = ROOT / "out" / "patch_reload2.elf"

erl.RELOAD_IMAGE = ROOT / "out" / "mainos_reload2.bin"
erl.PATCHED_GSEL = 1        # patch_reload2 item 1 = PTN SEQ (item 0 is TRK SEQ)
# Session 80 continued (6): this build's picker is UP/DOWN only -- rl_arr_a/b
# test the keycode and require event==press. patch_reload.s has no such gate.
erl.ARROW_UPDOWN_ONLY = True

# the 3-item picker: (G_SEL, label, want_G_KIND, want_FUN_4004aab4_calls, want_seq_job_post)
erl.COMBO_ITEMS = [
    (0, "TRK SEQ",        3, 0, True),
    (1, "PTN SEQ",        1, 0, True),
    (2, "PART + PTN SEQ", 2, 0, True),
]


def _sym(name):
    nm = subprocess.run(["m68k-elf-nm", str(_ELF)], capture_output=True, text=True).stdout
    for ln in nm.splitlines():
        p = ln.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)
    raise KeyError(name)


erl._sym = _sym

if __name__ == "__main__":
    if not _ELF.exists():
        sys.exit(f"missing {_ELF} -- run python3 tools/build_reload2.py first")
    erl.main()
