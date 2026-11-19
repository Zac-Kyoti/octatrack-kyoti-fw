#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
EMPTY_PATTERN_LED_FIX: the trigless-lock case matrix under [PTN] and [BANK] (2026-11-19).

    python3 tools/led_trigless_matrix.py --final out/baseline/final_unit.bin --new out/mainos_empty_pattern_led_fix.bin [--new ...]

Each case resets a bank the probe owns (bank 4, all 16 patterns, by stock's own initialiser
FUN_4009abdc), writes trig-mask bits and lock bytes into pattern 6 (or as the case says), then asks
  [PTN]   FUN_4009a464(pattern, bank)       -- the PTN page / chain view predicate
  [BANK]  bank_has_content 0x4000fd78(bank) -- the [BANK] grid (its call returns to 0x4000fd8c)
and compares with the expected answers: one column for the FINAL image (Session 119: [BANK] = stock),
one for the new one (the author's spec, 2026-11-19: a trigless lock that carries a locked parameter
lights [BANK] too; one with nothing locked stays off everywhere).

Two stock paths are also run (results printed, and asserted):
  * MIDI LIVE erase of a step's trigs, FUN_40038668(mask, clear_trigs=1, params=all): it clears
    MTRA +0x00 / +0x08 and the step's lock row but NOT +0x10 -> a stale MIDI trigless-lock bit.
    Audio's FUN_40038874 clears +0x10 too.  Either way the pattern must read empty afterwards.
  * the [FUNC]+trig toggle 0x40040f90 on a MIDI track: note -> +0x08 -> +0x10 -> +0x08 (the
    MIDI side's +0x10 is the trigless-lock layer, as audio's).

Runs on refs/octabam's ot_emu (call / poke / peek verbs of the local --steps patch); --emu picks another.
"""
import argparse, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCT = ROOT / "refs/octabam"
CARD = OCT / "out/kyoti_led_card.img"
HAS, BANKHAS, INIT = 0x4009A464, 0x4000FD78, 0x4009ABDC
MIDI_CLEAR, AUD_CLEAR, TOGGLE = 0x40038668, 0x40038874, 0x40040F90
PS, BS, AS, MS = 0x8ED8, 0x9B340, 0x91A, 0x8B0
AUD_ROW, MID_BLK, MID_ROW = 0x59, 0x48D0, 0x4900
BLOB0 = 0x400E21E0
BLOB_PTR, CUR_PAT, CUR_TRK, MIDI_SIDE = 0x46C82456, 0x100B14D0, 0x100B14CC, 0x80000012
PLAYHEAD = 0x800064E0                   # FUN_4009b2b0(t) = [0x800064e0 + t] & 0x3f; MIDI tracks t + 8
HELD, PAGE = 0x460D174A, 0x460D174C     # the toggle's held-trig word and its page's first step
B, P = 4, 6


def pat(p=P):
    return B * BS + p * PS


class W:
    """Byte writes into the bank, ORed for mask bits."""
    def __init__(self):
        self.b = {}

    def mask(self, side, t, off, step, p=P):
        base = pat(p) + (t * AS if side == "A" else MID_BLK + t * MS) + off
        a = base + 7 - (step >> 3)
        self.b[a] = self.b.get(a, 0) | (1 << (step & 7))
        return self

    def lock(self, side, t, step, byte=0, val=0x30, p=P):
        a = pat(p) + (t * AS + AUD_ROW if side == "A" else MID_ROW + t * MS) + 32 * step + byte
        self.b[a] = val
        return self

    def tl(self, side, t, step, locked=True, byte=0, p=P):     # a trigless lock (mask +0x10)
        self.mask(side, t, 0x10, step, p)
        return self.lock(side, t, step, byte, p=p) if locked else self

    def pokes(self):
        return [f"poke blob+{a:#x}={v:02x}" for a, v in sorted(self.b.items())]


def cases():
    """(label, writes, FINAL (ptn, bank), NEW (ptn, bank), pattern asked under [PTN])"""
    C = []
    def c(label, w, fin, new, p=P):
        C.append((label, w, fin, new, p))
    c("empty bank (16 patterns reset)", W(), (0, 0), (0, 0))
    c("A T2 trigless lock, nothing locked", W().tl("A", 1, 6, False), (0, 0), (0, 0))
    c("A T2 trigless lock + 1 p-lock", W().tl("A", 1, 6), (1, 0), (1, 1))
    c("A T2 lock byte, no mask bit", W().lock("A", 1, 6), (1, 0), (1, 0))
    c("A T2 trigless trig (+0x08)", W().mask("A", 1, 0x08, 6), (1, 1), (1, 1))
    c("A T2 sample trig (+0x00)", W().mask("A", 1, 0x00, 6), (1, 1), (1, 1))
    c("A T2 one-shot (+0x18)", W().mask("A", 1, 0x18, 6), (1, 1), (1, 1))
    c("A T2 recorder trig (+0x20)", W().mask("A", 1, 0x20, 6), (1, 1), (1, 1))
    c("A T2 swing/slide only (+0x38)", W().mask("A", 1, 0x38, 6), (0, 0), (0, 0))
    c("A T2 sample trig + p-lock", W().mask("A", 1, 0x00, 6).lock("A", 1, 6), (1, 1), (1, 1))
    c("M T4 trigless lock, nothing locked", W().tl("M", 3, 6, False), (0, 0), (0, 0))
    c("M T4 trigless lock + 1 p-lock", W().tl("M", 3, 6), (1, 0), (1, 1))
    c("M T4 lock byte, no mask bit", W().lock("M", 3, 6), (1, 0), (1, 0))
    c("M T4 +0x08 layer", W().mask("M", 3, 0x08, 6), (1, 1), (1, 1))
    c("M T4 note trig (+0x00)", W().mask("M", 3, 0x00, 6), (1, 1), (1, 1))
    c("M T4 +0x18 layer only", W().mask("M", 3, 0x18, 6), (0, 0), (0, 0))
    # mask word boundaries, first / last track, first / last byte of the row
    c("A T1 TL step 1 (lo bit 0), PTCH", W().tl("A", 0, 0), (1, 0), (1, 1))
    c("A T8 TL step 64 (hi bit 31), last row byte", W().tl("A", 7, 63, byte=31), (1, 0), (1, 1))
    c("A T8 TL step 33 (hi bit 0), byte 15", W().tl("A", 7, 32, byte=15), (1, 0), (1, 1))
    c("M T8 TL step 32 (lo bit 31), byte 31", W().tl("M", 7, 31, byte=31), (1, 0), (1, 1))
    c("M T1 TL step 64, byte 0", W().tl("M", 0, 63), (1, 0), (1, 1))
    c("A T3 lock value 0x00 (a real lock of 0)", W().tl("A", 2, 10).lock("A", 2, 10, 4, 0x00), (1, 0), (1, 1))
    # the right row: an empty TL on step 6, the lock on step 10 without a mask bit
    c("A T2 empty TL s6 + lock s10 w/o mask", W().tl("A", 1, 6, False).lock("A", 1, 10), (1, 0), (1, 0))
    c("A T2 empty TL s10 + lock s6 w/o mask", W().tl("A", 1, 10, False).lock("A", 1, 6), (1, 0), (1, 0))
    # several steps / tracks, and the budget (16 rows per call)
    w = W()
    for s in range(5):
        w.tl("A", 0, s, False)
    c("5 empty TLs A T1 + TL+lock M T3", w.tl("M", 2, 20), (1, 0), (1, 1))
    w = W()
    for s in range(15):
        w.tl("A", 0, s, False)
    c("15 empty TLs A T1 + TL+lock M T1 (16th row)", w.tl("M", 0, 0), (1, 0), (1, 1))
    w = W()
    for s in range(16):
        w.tl("A", 0, s, False)
    c("16 empty TLs A T1 + TL+lock M T1 (budget)", w.tl("M", 0, 0), (1, 0), (1, 0))
    w = W().tl("A", 0, 63)                           # first in scan order
    for t in range(8):
        for s in range(64):
            if (t, s) != (0, 63):
                w.tl("A", t, s, False)
                w.tl("M", t, s, False)
    c("TL+lock first in order, 1023 empty TLs", w, (1, 0), (1, 1))
    w = W()
    for t in range(8):
        for s in range(64):
            w.tl("A", t, s, False)
            w.tl("M", t, s, False)
    c("1024 empty TLs (nothing locked)", w, (0, 0), (0, 0))
    c("TL+lock in pattern 16 only", W().tl("A", 4, 40, p=15), (1, 0), (1, 1), 15)
    w = W()
    for p in range(16):
        w.tl("A", 2, 12, p=p)
    c("all 16 patterns: TL+lock", w, (1, 0), (1, 1))
    w = W()
    for p in range(16):
        w.tl("M", 5, 12, False, p=p)
    c("all 16 patterns: empty TL", w, (0, 0), (0, 0))
    return C


def steps():
    out = ["ptr blob=0x46c82456", f"echo BLOB0 {BLOB0:#x}"]
    probes = []
    def call(fn, *args, label):
        out.append("spin"); out.append("call " + ",".join([f"{fn:#x}", *args])); probes.append(label)
    def reset_bank():
        for p in range(16):
            out.append("spin"); out.append(f"call {INIT:#x},blob+{pat(p):#x}")
    for i, (label, w, fin, new, p) in enumerate(cases()):
        reset_bank()
        out.extend(w.pokes())
        call(HAS, f"{p:#x}", f"{B:#x}", label=("PTN", i))
        call(BANKHAS, f"{B:#x}", label=("BANK", i))
    # --- stock's LIVE erase of a step's trigs (clear_trigs=1, all params) -----------------
    st = 6
    for side, t, fn in (("M", 3, MIDI_CLEAR), ("A", 1, AUD_CLEAR)):
        reset_bank()
        w = W().tl(side, t, st).mask(side, t, 0x00, st)          # a note trig + a TL bit + a lock
        out.extend(w.pokes())
        out.append(f"poke {BLOB_PTR:#x}={BLOB0 + B * BS:08x}")   # the working bank := ours
        out.append(f"poke {CUR_PAT:#x}={P:02x}")
        out.append(f"poke {PLAYHEAD + t + (8 if side == 'M' else 0):#x}={st:02x}")
        out.append("spin"); out.append(f"call {fn:#x},{1 << t:#x},0x1,0xffffffff")
        out.append(f"poke {BLOB_PTR:#x}={BLOB0:08x}")
        base = pat() + (t * AS if side == "A" else MID_BLK + t * MS)
        row = pat() + (t * AS + AUD_ROW if side == "A" else MID_ROW + t * MS) + 32 * st
        out.append(f"peek blob+{base:#x},0x18")
        out.append(f"peek blob+{row:#x},0x20")
        call(HAS, f"{P:#x}", f"{B:#x}", label=("PTN", f"clear-{side}"))
        call(BANKHAS, f"{B:#x}", label=("BANK", f"clear-{side}"))
    # --- the [FUNC]+trig toggle on a MIDI track: note -> ? -> ? -> ? --------------------------
    reset_bank()
    t, st = 2, 3
    out.extend(W().mask("M", t, 0x00, st).pokes())
    out.append(f"poke {BLOB_PTR:#x}={BLOB0 + B * BS:08x}")
    out.append(f"poke {CUR_PAT:#x}={P:02x}")
    out.append(f"poke {CUR_TRK:#x}={t:02x}")
    out.append(f"poke {MIDI_SIDE:#x}=00000001")
    for k in range(3):
        out.append(f"poke {PAGE:#x}=00000000")
        out.append(f"poke {HELD:#x}={1 << st:04x}")
        out.append("spin"); out.append(f"call {TOGGLE:#x}")
        out.append(f"peek blob+{pat() + MID_BLK + t * MS:#x},0x18")
    out.append(f"poke {MIDI_SIDE:#x}=00000000")
    out.append(f"poke {BLOB_PTR:#x}={BLOB0:08x}")
    return out, probes


def run(emu, image):
    lines, probes = steps()
    sf = ROOT / "out" / f"led_matrix_steps_{pathlib.Path(image).stem}.txt"
    sf.write_text("\n".join(lines) + "\n")
    p = subprocess.run([str(emu), "--image", str(image), "--card", str(CARD), "--set", "OCTABAM",
                        "--project", "OT DEMO", "--steps", str(sf)], cwd=OCT, capture_output=True, text=True)
    blob = re.search(r"^step ptr\s*: blob = (0x[0-9a-f]+)", p.stdout, re.M)
    if not blob or int(blob.group(1), 16) != BLOB0:
        print(p.stdout[-3000:], p.stderr[-2000:]); sys.exit(f"blob pointer is not {BLOB0:#x}")
    got = re.findall(r"^step call   : (0x[0-9a-f]+) -> d0 = (0x[0-9a-f]+|0)$", p.stdout, re.M)
    res = [(int(f, 16), int(v, 16)) for f, v in got if int(f, 16) in (HAS, BANKHAS)]
    bad = re.findall(r"^(step .*(?:unknown|DID NOT|NOT PARK).*)$", p.stdout, re.M)
    if len(res) != len(probes) or bad:
        print(p.stdout[-4000:], p.stderr[-2000:]); print("BAD", bad); sys.exit(1)
    vals = {lab: (v & 0xff if fn == BANKHAS else v) for lab, (fn, v) in zip(probes, res)}
    peeks = re.findall(r"^step peek   : (0x[0-9a-f]+) : ([0-9a-f]+)$", p.stdout, re.M)
    return vals, peeks


def sweep(emu, image, card, sset, project):
    """No edits: [PTN] for all 256 (bank, pattern) and [BANK] for all 16 banks of a real project."""
    L = []
    for b in range(16):
        for p in range(16):
            L += ["spin", f"call {HAS:#x},{p:#x},{b:#x}"]
        L += ["spin", f"call {BANKHAS:#x},{b:#x}"]
    sf = ROOT / "out" / "led_sweep_steps.txt"
    sf.write_text("\n".join(L) + "\n")
    p = subprocess.run([str(emu), "--image", str(image), "--card", str(card), "--set", sset,
                        "--project", project, "--steps", str(sf)], cwd=OCT, capture_output=True, text=True)
    got = re.findall(r"^step call   : (0x[0-9a-f]+) -> d0 = (0x[0-9a-f]+|0)$", p.stdout, re.M)
    if len(got) != 16 * 17:
        print(p.stdout[-3000:], p.stderr[-1500:]); sys.exit(f"sweep {card} {project}: incomplete")
    return [int(v, 16) & (0xff if int(f, 16) == BANKHAS else 0xffffffff) for f, v in got]


SWEEP_FIXTURES = [("kyoti_led_card.img", "OCTABAM", "OT DEMO"), ("kv1_mm_card.img", "KYOTI", "kyoti_testMM"),
                  ("sctest6_card.img", "OCTABAM", "test6")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true", help="also compare all 256 patterns + 16 banks of real projects")
    ap.add_argument("--final", required=True, help="the FINAL image (Session 119 behaviour)")
    ap.add_argument("--new", action="append", required=True, help="an image with the 2026-11-19 change")
    ap.add_argument("--emu", default=str(OCT / "out/emu/ot_emu"))
    a = ap.parse_args()
    imgs = [("final", str(pathlib.Path(a.final).resolve()))] + [("new", str(pathlib.Path(n).resolve())) for n in a.new]
    results = {im: run(a.emu, im) for _, im in imgs}
    fails = []
    C = cases()
    print("case".ljust(48) + "".join(f"  img{i} PTN/BANK" for i in range(len(imgs))))
    for i, (label, _w, fin, new, _p) in enumerate(C):
        row = label.ljust(48)
        for k, (role, im) in enumerate(imgs):
            v = results[im][0]
            got = (v[("PTN", i)], v[("BANK", i)])
            want = fin if role == "final" else new
            ok = got == want
            row += f"  {got[0]}/{got[1]}{'' if ok else ' !=' + str(want[0]) + '/' + str(want[1])}".ljust(16)
            if not ok:
                fails.append(f"img{k} {label}: got {got}, want {want}")
        print(row)
    for side in ("M", "A"):
        row = f"LIVE erase of a {side} step's trigs (stock)".ljust(48)
        for k, (role, im) in enumerate(imgs):
            v = results[im][0]
            got = (v[("PTN", f"clear-{side}")], v[("BANK", f"clear-{side}")])
            row += f"  {got[0]}/{got[1]}".ljust(16)
            if got != (0, 0):
                fails.append(f"img{k} clear-{side}: got {got}, want (0, 0)")
        print(row)
    for k, (role, im) in enumerate(imgs):
        pk = results[im][1]
        # clear-M: masks, row; clear-A: masks, row; then 3 toggles
        mm, mrow, am, arow = pk[0][1], pk[1][1], pk[2][1], pk[3][1]
        print(f"img{k}: after MIDI clear  +0x00 {mm[0:16]} +0x08 {mm[16:32]} +0x10 {mm[32:48]}  row {'all FF' if set(mrow) == {'f'} else mrow}")
        print(f"img{k}: after audio clear +0x00 {am[0:16]} +0x08 {am[16:32]} +0x10 {am[32:48]}  row {'all FF' if set(arow) == {'f'} else arow}")
        if set(mrow) != {"f"} or set(arow) != {"f"}:
            fails.append(f"img{k}: a cleared step's lock row is not all 0xFF")
        if int(am[32:48], 16) != 0:
            fails.append(f"img{k}: audio clear left +0x10")
        for j in range(3):
            tg = pk[4 + j][1]
            print(f"img{k}: MIDI toggle #{j + 1}         +0x00 {tg[0:16]} +0x08 {tg[16:32]} +0x10 {tg[32:48]}")
    for i, (_r, im) in enumerate(imgs):
        print(f"img{i} = {im}")
    if a.sweep:
        for card, sset, proj in SWEEP_FIXTURES:
            r = {im: sweep(a.emu, im, OCT / "out" / card, sset, proj) for _, im in imgs}
            ref = r[imgs[0][1]]
            lit = sum(ref[b * 17 + p] != 0 for b in range(16) for p in range(16))
            banks = sum(ref[b * 17 + 16] != 0 for b in range(16))
            print(f"sweep {card} / {proj}: FINAL lights {lit}/256 patterns, {banks}/16 banks")
            for k, (_r, im) in enumerate(imgs[1:], 1):
                diff = [(i // 17, i % 17) for i, (x, y) in enumerate(zip(ref, r[im])) if bool(x) != bool(y)]
                print(f"  img{k}: {'identical' if not diff else 'differs at (bank, pattern|16=bank) ' + str(diff)}")
                if diff:
                    fails.append(f"img{k} sweep {proj}: {diff} (check whether these hold trigless locks with locks)")
    if fails:
        print("\nFAIL:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("\nALL GOOD")


if __name__ == "__main__":
    main()
