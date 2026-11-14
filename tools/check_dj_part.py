#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
DIRECT_JUMP_KYOTI V7.2 -- does "the Part-wide items at the jump + every track's own apply at its first
sounding trig" reproduce what stock's light Part apply 0x40009e00 does at a pattern change?

  python3 tools/check_dj_part.py DUMP.npz --image IMG --elf DJ.elf [--part P] [--lfo 0|1]

Replays, in a bare Unicorn loaded with a tools/diag_dj_partpub.py --dump snapshot (no interrupts, no
timing), each variant from the same state and diffs the memory it writes:

  LIGHT    0x40009e00(bank, P)                         -- stock's pattern-change apply
  WIDE     DIRECT JUMP's dj_pwide(bank, P)             -- the Part-wide items kept at the jump
  TRACKS   DIRECT JUMP's dj_tpub(bank, P, t), t = 0..15 -- each track's deferred publish
  BOTH     WIDE, then TRACKS (as the jump + every publish leave it)

PASS when BOTH == LIGHT on every byte LIGHT writes, and BOTH writes nothing LIGHT does not (outside the
kernel's queue bookkeeping, which LIGHT's two UI posts and ours touch alike).  --lfo forces LFO AUTO
CHANGE (0x80000050) for the run: stock applies the per-track LFO setups only when it is set.
"""
import argparse
import os
import pathlib
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
LIGHT = 0x40009E00
SENT = 0x4001FC9C            # main's idle `bra .`: the return address every call goes back to
STACK = 0x46F00000           # top of a scratch stack (must lie in a mapped region; checked)
KERNEL = [(0x460D17A0, 0x460D1800), (0x800068C0, 0x80006900)]  # UI queue + ready list (KPOST)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--elf", required=True)
    ap.add_argument("--part", type=int)
    ap.add_argument("--lfo", type=int, choices=(0, 1))
    a = ap.parse_args(argv)
    d = np.load(a.dump)
    bank, parts = int(d["bank"]), [int(x) for x in d["parts"]]
    regions = {int(k[2:], 16): d[k] for k in d.files if k.startswith("r_")}
    nm = subprocess.run(["m68k-elf-nm", a.elf], capture_output=True, text=True, check=True).stdout
    sym = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_bringup as eb

    cur_part = None
    base = regions
    for b, arr in regions.items():
        if b <= 0x80001829 < b + len(arr):
            cur_part = int(arr[0x80001829 - b])
    part = a.part if a.part is not None else next((p for p in sorted(set(parts)) if p != cur_part), (cur_part + 1) % 4)
    print(f"bank {bank}, playing Part {cur_part}, applying Part {part}; patterns -> Parts {parts}")

    def fresh():
        uc = eb.Uc(eb.UC_ARCH_M68K, eb.UC_MODE_BIG_ENDIAN)
        uc.ctl_set_cpu_model(eb.UC_CPU_M68K_CFV4E)
        for b, arr in base.items():
            uc.mem_map(b, len(arr))
            uc.mem_write(b, arr.tobytes())
        if a.lfo is not None:
            uc.mem_write(0x80000050, bytes([a.lfo]))
        uc.reg_write(eb.UC_M68K_REG_SR, 0x2700)
        return uc

    def call(uc, addr, *args):
        sp = STACK - 4 * (1 + len(args))
        uc.mem_write(sp, b"".join(x.to_bytes(4, "big") for x in (SENT,) + args))
        uc.reg_write(eb.UC_M68K_REG_A7, sp)
        uc.emu_start(addr, SENT, count=2_000_000)

    def writes(uc, ref):
        out = {}
        for b, arr in ref.items():
            now = np.frombuffer(bytes(uc.mem_read(b, len(arr))), dtype=np.uint8)
            for i in np.nonzero(now != arr)[0]:
                ad = b + int(i)
                if any(lo <= ad < hi for lo, hi in KERNEL) or STACK - 0x1000 <= ad < STACK:
                    continue
                out[ad] = int(now[i])
        return out

    ref = {b: (arr.copy() if a.lfo is None else arr.copy()) for b, arr in base.items()}
    if a.lfo is not None:
        for b, arr in ref.items():
            if b <= 0x80000050 < b + len(arr):
                arr[0x80000050 - b] = a.lfo
    lfo = None
    for b, arr in ref.items():
        if b <= 0x80000050 < b + len(arr):
            lfo = int(arr[0x80000050 - b])
    print(f"LFO AUTO CHANGE = {lfo}")

    uc = fresh(); call(uc, LIGHT, bank, part); W_L = writes(uc, ref)
    uc = fresh(); call(uc, sym["dj_pwide"], bank, part); W_W = writes(uc, ref)
    uc = fresh()
    for t in range(16):
        call(uc, sym["dj_tpub"], bank, part, t)
    W_T = writes(uc, ref)
    uc = fresh(); call(uc, sym["dj_pwide"], bank, part)
    for t in range(16):
        call(uc, sym["dj_tpub"], bank, part, t)
    W_B = writes(uc, ref)

    def ranges(ads):
        ads = sorted(ads)
        out, s, p = [], None, None
        for x in ads:
            if s is None:
                s = p = x
            elif x == p + 1:
                p = x
            else:
                out.append((s, p)); s = p = x
        if s is not None:
            out.append((s, p))
        return ", ".join(f"{s:#x}" + (f"..{e:#x}" if e != s else "") for s, e in out[:40]) + (" ..." if len(out) > 40 else "")

    print(f"LIGHT writes {len(W_L)} bytes: {ranges(W_L)}")
    print(f"WIDE  writes {len(W_W)} bytes: {ranges(W_W)}")
    print(f"TRACKS write {len(W_T)} bytes")
    miss = [x for x in W_L if x not in W_B]
    diff = [x for x in W_L if x in W_B and W_B[x] != W_L[x]]
    extra = [x for x in W_B if x not in W_L]
    print(f"BOTH vs LIGHT: missing {len(miss)} {ranges(miss)}")
    print(f"               different {len(diff)} {ranges(diff)}")
    print(f"               extra (TRK_APPLY / MIDI apply beyond the light apply) {len(extra)}: {ranges(extra)}")
    ok = not miss and not diff
    print(f"\nLIGHT's effect reproduced: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
