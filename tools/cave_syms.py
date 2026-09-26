#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
cave_syms -- read cave symbol addresses from the built ELF. NEVER hardcode them.

** Why this module exists. ** The cave is packed sequentially, so ANY source edit that
changes the size of anything shifts every symbol after it. Session 93 added a 2-byte
rl_msg, the build went 1844 -> 1898 B, and rl_own moved 0x400d6b2c -> 0x400d6b60.
Two diagnostics with hardcoded addresses then read a byte of unrelated cave data, got
`rl_own=102`, and reported confident findings from it:
  * diag_reload3_honest.py  -- its own liveness GATE went invalid (fixed in place)
  * diag_reload3_repeat.py  -- reported "the worker never ran on iterations [1,2,3,4]"
                               and "rl_own left non-zero -- the accumulating shape the
                               rl_done header warns about". Both were pure artifact, and
                               the second one impersonated exactly the real bug this
                               thread is hunting.
A stale address does not fail loudly; it returns a plausible number. Use this.

    from cave_syms import syms
    S = syms()                      # {'rl_own': 0x400d6b60, ...}
    S['rl_own']                     # KeyError if the symbol vanished -- fail loud
"""
import functools
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_ELF = ROOT / "out" / "patch_reload3.elf"


@functools.lru_cache(maxsize=8)
def syms(elf: str | None = None) -> dict:
    path = pathlib.Path(elf) if elf else DEFAULT_ELF
    if not path.exists():
        raise SystemExit(f"cave_syms: {path} missing -- build first "
                         f"(python3 tools/build_reload3.py)")
    out = subprocess.run(["m68k-elf-nm", str(path)],
                         capture_output=True, text=True, check=True).stdout
    d = {}
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) == 3 and parts[1] in "tTdDbBaA":
            try:
                d[parts[2]] = int(parts[0], 16)
            except ValueError:
                pass
    return d
