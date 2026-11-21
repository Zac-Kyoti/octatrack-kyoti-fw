#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
CLYPS CL39b -- the whole Clyps window (x 8..119 of the composed screen) of two diag_clyps_lock.py runs, op WN by op WN:
a reference image (CL38) against a CL39 image, the same ops. Masked: the cued pattern's cell (stock's PEND when the
window was taken, in the shown bank) -- CL39's blinking box lives there. Anything else that differs is reported (FAIL).

  python3 tools/cmp_clyps_windows.py REF.json NEW.json
"""
import json, sys


def pixels(raw):            # lcd_view.pixels' layout, without importing octabam: 128 x 64, 8 rows per page byte
    import os, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "refs" / "octabam" / "tools" / "emu"))
    import lcd_view
    return lcd_view.pixels(raw)


def box(slot):              # as diag_clyps_lock.qbox (cl_colx: column 1 bar x 2..52, column 2 55..109; window x 8)
    x0, x1 = (10, 60) if slot < 8 else (63, 117)
    return (x0, 12 + 6 * (slot & 7), x1, 18 + 6 * (slot & 7))


def main(argv):
    a, b = (json.load(open(p))["windows"] for p in argv[:2])
    bad = 0
    for tag in a:
        if tag not in b:
            print(f"W{tag}: missing in {argv[1]}")
            bad += 1
            continue
        pa, pb = pixels(bytes.fromhex(a[tag]["scr"])), pixels(bytes.fromhex(b[tag]["scr"]))
        bank, pend = b[tag]["bank"], b[tag]["pend"]
        mask = set()
        if pend[1] < 16 and pend[0] == bank and (pend[0], pend[1]) != (bank, b[tag]["act"]):
            x0, y0, x1, y1 = box(pend[1])
            mask = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        d = [(x, y) for y in range(64) for x in range(8, 120) if pa[y][x] != pb[y][x] and (x, y) not in mask]
        st = "PASS" if not d else "FAIL"
        print(f"W{tag}: {st} -- {len(d)} px differ outside the cued cell (masked {len(mask)} px); "
              f"ref act {a[tag]['act']} pend {a[tag]['pend']} cph {a[tag]['cph']}, new act {b[tag]['act']} "
              f"pend {pend} cph {b[tag]['cph']}" + (f"; first {d[:8]}" if d else ""))
        bad += bool(d)
    print("VERDICT:", "PASS" if not bad else f"FAIL ({bad})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
