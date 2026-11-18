#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
KYOTI V1.8BC: every effect the FX2 chooser still offers runs its own DSP code, on both cores (ot_emu, BOTLI;
verify_ot303's FX2 stopwatch job: the effect id poked into one core's four FX2 slots, the slot's DSP time per
track). Each effect's per-track cost is compared with stock's: the same code shows the same cost (verify's own
rule: equal, or inside stock's own spread + 100). PLATE REV and SPRING REV are given up: their ids must run
the passthrough stub (~45-70).

    python3 tools/kyoti_bc_check_fx2.py
"""
import concurrent.futures as cf, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kyoti_bc_check_voice as cv          # noqa: E402

v = cv.v
BASE = 0x40000400


def offered(img):
    b = open(img, "rb").read()
    u32 = lambda a: int.from_bytes(b[a - BASE:a - BASE + 4], "big")
    rows, ids = [], {}
    while (p := u32(0x400d6090 + 4 * len(rows))):
        rows.append(p)
    for fid in range(0x20):
        e = u32(0x400d5fdc + 4 * fid)
        if e in rows[1:]:
            ids[fid] = b[e - 0x38 - BASE + 0x41:e - 0x38 - BASE + 0x4d].split(b"\0")[0].decode("latin1")
    return ids


def main():
    ids = offered(v.IMAGE)
    jobs = {}
    for fid in list(ids) + [0x14, 0x15]:
        for core in (1, 0):
            jobs[(fid, core, "bc")] = (v.IMAGE, core, v.FX2[core], (), 2, fid)
            jobs[(fid, core, "stock")] = (v.STOCK, core, v.FX2[core], (), 2, fid)
    with cf.ThreadPoolExecutor(14) as ex:
        fut = {k: ex.submit(v.run, *a) for k, a in jobs.items()}
        res = {k: f.result()[0] for k, f in fut.items()}
    ok = True
    for fid in list(ids) + [0x14, 0x15]:
        for core in (1, 0):
            b, s = res[(fid, core, "bc")], res[(fid, core, "stock")]
            if not b or not s:
                print(f"  id 0x{fid:02x} core {core}: no stopwatch"); ok = False; continue
            if fid in (0x14, 0x15):
                good = all(x < 200 for x in b[-4:])
                print(f"  id 0x{fid:02x} {'PLATE REV' if fid == 0x14 else 'SPRING REV'} core {core}: {b[-4:]} "
                      f"(stock {s[-4:]}) -> the stub: {good}")
            else:
                good = True
                for t in range(4):
                    a_, b_ = s[t::4], b[t::4]
                    good &= (b_ == a_) if len(set(a_)) == 1 else (min(a_) <= min(b_) and max(b_) <= max(a_) + 100)
                print(f"  id 0x{fid:02x} {ids[fid]:12s} core {core}: {b[-4:]} vs stock {s[-4:]}: {'same' if good else 'DIFFERS'}")
            ok &= good
    print("ALL GOOD" if ok else "DIFFERENCES (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
