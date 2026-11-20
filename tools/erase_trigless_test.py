#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
ERASE_EMPTY_TRIGLESS_LOCKS on AUDIO and MIDI tracks, through the real LIVE-erase entry, on a real
project, with the trig row's LEDs read back (2026-11-20).

    python3 tools/erase_trigless_test.py --stock out/raw/section_3_MAIN_OS.bin --new IMAGE [--new ...]
                                         [--old IMAGE]   (the audio-only ERASE: MIDI cases fail there)

ot_emu (the `key` step verb: tools/refs/local-patches/octabam-ot-emu-steps-key.patch) loads OT DEMO
(the factory demo, a real export, kyoti_led_card.img), selects a track with its track key and turns
GRID REC on with [REC], so stock's trig-row painter (FUN_43fdc -> FUN_40034bd4) repaints the 16 trig
LEDs from the masks on every UI pass. Each case then:
  * resets the working pattern with stock's initialiser FUN_4009abdc (swing +0x18 / +0x40 = 0xAA..,
    every lock row 0xFF) and copies it into the 0x1001614e mirror (which equals the loaded blob byte
    for byte: checked);
  * builds the step the way stock does: a note trig bit, then the [FUNC]+trig toggle 0x40040f90 twice
    (note -> trigless trig -> trigless lock: blob + mirror, by stock's own code), lock bytes poked
    into the row (blob + mirror), other layers' bits poked where a case needs them;
  * erases through FUN_40041af4 (opcode 8's LIVE branch: [NO]+knob as the playhead passes) with
    stock's own gate words -- 0x460d1a94 = 1, 0x460d1a98 = the param mask (0x460d1a90 = 1 and
    0x460d1a9c = the track mask for the erase-the-trigs gesture) -- and the playhead
    0x800064e0[track (+8 MIDI)] on the step: FUN_40038668 (MIDI) / FUN_40038874 (AUDIO) do the rest;
  * reads back the masks, the mirror's +0x10 byte, the row, the per-step lock bitmap
    (0x46c7d2e4 MIDI / 0x46c7d48c AUDIO) and, after 10 frames, the step's two LED bits
    (framebuffer 0x460ba98c, ids 2s / 2s+1 via 0x400a766e) and their brightness (0x400b9714).

Expected: --new = the spec (both sides); --stock = the bug (every emptied trigless lock stays lit);
--old = the bug on MIDI only. Every image: the "must stay" cases unchanged.
What the emulator cannot show: the panel itself (it reads the framebuffer the panel is driven
from), and the real knob + [NO] gesture (the erase is entered at FUN_40041af4 with the words the
gesture sets, as on the unit's traced path, NOTES "ARTLTEST8").
"""
import argparse, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCT = ROOT / "refs/octabam"
CARD = OCT / "out/kyoti_led_card.img"
INIT, TOGGLE, LIVE_ERASE = 0x4009ABDC, 0x40040F90, 0x40041AF4
BLOB0, MIRROR = 0x400E21E0, 0x1001614E
PS, AS, MS, MID_BLK, AUD_ROW, MID_ROW = 0x8ED8, 0x91A, 0x8B0, 0x48D0, 0x59, 0x4900
MIDI_SIDE, CUR_TRK, CUR_TRK2, CUR_PAT = 0x80000012, 0x100B14CC, 0x80000000, 0x100B14D0
HELD, PAGE, PLAYHEAD = 0x460D174A, 0x460D174C, 0x800064E0
ER_TRIGS, ER_KNOB, ER_MASK, ER_TMASK = 0x460D1A90, 0x460D1A94, 0x460D1A98, 0x460D1A9C
LOCKMAP = {"M": 0x46C7D2E4, "A": 0x46C7D48C}
LEDS, BRIGHT = 0x460BA98C, 0x400B9714
TRACK_KEY, REC_KEY = 0x10, 0x29
P = 0                                    # the working pattern (OT DEMO loads A01)


def blk(side, t):
    return P * PS + (MID_BLK + t * MS if side == "M" else t * AS)


def row(side, t, s):
    return P * PS + (MID_ROW + t * MS if side == "M" else t * AS + AUD_ROW) + 32 * s


def bit(s):
    return 7 - (s >> 3), 1 << (s & 7)


class Case:
    """One step's story as a step list. The layers a case pokes (+0x00 / +0x08 and the veto layers) are
    zero after FUN_4009abdc on both sides (swing +0x18 MIDI / +0x40 AUDIO is 0xAA.., never poked), so
    their bytes are modelled here; +0x10 is only ever set by stock's own toggle."""
    def __init__(self, name, side, t, s):
        self.name, self.side, self.t, self.s = name, side, t, s
        self.L, self.reads, self.model = [], [], {}

    def poke_both(self, off, val):           # blob + its mirror, as stock's edits do
        self.L += [f"poke {BLOB0 + off:#x}={val:02x}", f"poke {MIRROR + off:#x}={val:02x}"]

    def _set(self, off, s, t, on):
        b, m = bit(s)
        a = blk(self.side, t) + off + b
        v = self.model.get(a, 0)
        self.model[a] = (v | m) if on else (v & ~m)
        self.poke_both(a, self.model[a])

    def layer(self, off, s=None, t=None):
        self._set(off, self.s if s is None else s, self.t if t is None else t, True)
        return self

    def tl(self, s=None, t=None):            # note trig -> [FUNC]+trig twice -> trigless lock (stock's toggle)
        s = self.s if s is None else s
        t = self.t if t is None else t
        self._set(0x00, s, t, True)
        self.L += [f"poke {MIDI_SIDE:#x}={1 if self.side == 'M' else 0:08x}", f"poke {CUR_TRK:#x}={t:02x}",
                   f"poke {CUR_PAT:#x}={P:02x}"]
        for _ in range(2):
            self.L += [f"poke {PAGE:#x}={(s // 16) * 16:08x}", f"poke {HELD:#x}={1 << (s % 16):04x}",
                       "spin", f"call {TOGGLE:#x}"]
        b, m = bit(s)
        a = blk(self.side, t) + b
        self.model[a] = self.model.get(a, 0) & ~m    # the toggle moved the note to +0x08, then +0x10
        self.L += [f"poke {CUR_TRK:#x}={self.t:02x}"]
        return self

    def lock(self, p, val=0x40, s=None, t=None):
        self.poke_both(row(self.side, self.t if t is None else t, self.s if s is None else s) + p, val)
        return self

    def erase(self, params=(), trigs=False):
        sel = [f"poke {MIDI_SIDE:#x}={1 if self.side == 'M' else 0:08x}", f"poke {CUR_TRK:#x}={self.t:02x}",
               f"poke {CUR_TRK2:#x}={self.t:02x}", f"poke {CUR_PAT:#x}={P:02x}",
               f"poke {PLAYHEAD + self.t + (8 if self.side == 'M' else 0):#x}={self.s:02x}"]
        mask = sum(1 << p for p in params)
        if trigs:
            gate = [f"poke {ER_TRIGS:#x}=00000001", f"poke {ER_KNOB:#x}=00000000", f"poke {ER_TMASK:#x}={1 << self.t:02x}"]
        else:
            gate = [f"poke {ER_TRIGS:#x}=00000000", f"poke {ER_KNOB:#x}=00000001", f"poke {ER_MASK:#x}={mask:08x}"]
        self.L += sel + gate + ["spin", f"call {LIVE_ERASE:#x}",
                                f"poke {ER_TRIGS:#x}=00000000", f"poke {ER_KNOB:#x}=00000000"]
        return self

    def read(self, tag, s=None, t=None):
        s = self.s if s is None else s
        t = self.t if t is None else t
        # repaint the way the panel does on a track select: that track's key (the painter redraws on
        # stock's own edit events, not on a raw poke), then let the UI pass run
        self.L += [f"poke {MIDI_SIDE:#x}={1 if self.side == 'M' else 0:08x}",
                   f"key {TRACK_KEY + t:#x} down", "frames 3", f"key {TRACK_KEY + t:#x} up", "frames 10",
                   f"echo R {tag}", f"peek {CUR_TRK:#x},1"]
        b, _ = bit(s)
        off = blk(self.side, t)
        self.L += [f"peek {BLOB0 + off:#x},0x28", f"peek {MIRROR + off + 0x10 + b:#x},1",
                   f"peek {BLOB0 + row(self.side, t, s):#x},0x20",
                   f"peek {LOCKMAP[self.side] + s:#x},1",
                   f"peek {LEDS:#x},8", f"peek {BRIGHT:#x},32"]
        self.reads.append((tag, s, t))
        return self


def build_cases():
    """[(Case, {read tag: (stock, old, new)})]; each expectation = (TL bit 'tl' / '--', LED)
    LED: 'lit' = the trigless-lock LED (green, dim), 'dark', 'note' (red), 'trigless' (green, full),
    'oneshot' (red + green, audio). Each read first selects the read track with its track key."""
    C = []
    LIT, DARK = ("tl", "lit"), ("--", "dark")
    for side, t in (("M", 1), ("A", 1)):
        S = "MIDI" if side == "M" else "AUDIO"
        fixed_old = DARK if side == "A" else LIT          # the audio-only ERASE: fixed on audio, the bug on MIDI
        def three(x):
            return (x, x, x)
        C.append((Case(f"{S} T2 s4: its one lock erased", side, t, 4).tl().lock(5)
                  .read("before").erase([5]).read("after"),
                  {"before": three(LIT), "after": (LIT, fixed_old, DARK)}))
        C.append((Case(f"{S} T2 s3 (a swing step): its one lock erased", side, t, 3).tl().lock(0x12)
                  .read("before").erase([0x12]).read("after"),
                  {"before": three(LIT), "after": (LIT, fixed_old, DARK)}))
        C.append((Case(f"{S} T2 s6: two locks, one erased, then the other", side, t, 6).tl().lock(0).lock(12, 0x00)
                  .read("before").erase([0]).read("after 1st").erase([12]).read("after 2nd"),
                  {"before": three(LIT), "after 1st": three(LIT), "after 2nd": (LIT, fixed_old, DARK)}))
        C.append((Case(f"{S} T2 s8: empty trigless lock ([FUNC]+trig), a never-locked param erased", side, t, 8).tl()
                  .read("before").erase([3]).read("after"),
                  {"before": three(LIT), "after": three(LIT)}))
        C.append((Case(f"{S} T2 s9: its one lock erased by a two-param mask", side, t, 9).tl().lock(2)
                  .read("before").erase([2, 7]).read("after"),
                  {"before": three(LIT), "after": (LIT, fixed_old, DARK)}))
        C.append((Case(f"{S} T2 s10: note trig + a lock", side, t, 10).layer(0x00).lock(4)
                  .read("before").erase([4]).read("after"),
                  {"before": three(("--", "note")), "after": three(("--", "note"))}))
        C.append((Case(f"{S} T2 s11: note trig + TL bit + a lock (veto)", side, t, 11).tl().layer(0x00).lock(4)
                  .read("before").erase([4]).read("after"),
                  {"before": three(("tl", "note")), "after": three(("tl", "note"))}))
        C.append((Case(f"{S} T2 s12: trigless trig + a lock", side, t, 12).layer(0x08).lock(4)
                  .read("before").erase([4]).read("after"),
                  {"before": three(("--", "trigless")), "after": three(("--", "trigless"))}))
        C.append((Case(f"{S} T2 s13: trigless trig + TL bit + a lock (veto)", side, t, 13).tl().layer(0x08).lock(4)
                  .read("before").erase([4]).read("after"),
                  {"before": three(("tl", "trigless")), "after": three(("tl", "trigless"))}))
        if side == "M":
            C.append((Case("MIDI T2 s14: slide (+0x20) + TL + a lock (veto)", side, t, 14).tl().layer(0x20).lock(4)
                      .read("before").erase([4]).read("after"),
                      {"before": three(LIT), "after": three(LIT)}))
        else:
            C.append((Case("AUDIO T2 s14: one-shot (+0x18) + TL + a lock (veto)", side, t, 14).tl().layer(0x18).lock(4)
                      .read("before").erase([4]).read("after"),
                      {"before": three(("tl", "oneshot")), "after": three(("tl", "oneshot"))}))
            C.append((Case("AUDIO T2 s7: recorder trig (+0x28) + TL + a lock (veto)", side, t, 7).tl().layer(0x28).lock(4)
                      .read("before").erase([4]).read("after"),
                      {"before": three(LIT), "after": three(LIT)}))
        # the neighbours: the same step on another track, the next step on this track
        C.append((Case(f"{S} T2 s5: its last lock erased; T3 s5 and T2 s6 kept", side, t, 5).tl().lock(1)
                  .tl(t=t + 1).lock(1, t=t + 1).tl(s=6).lock(1, s=6)
                  .read("before").erase([1]).read("after").read("T2 s6 after", s=6).read("T3 s5 after", t=t + 1),
                  {"before": three(LIT), "after": (LIT, fixed_old, DARK), "T2 s6 after": three(LIT),
                   "T3 s5 after": three(LIT)}))
        # the erase-the-trigs gesture (clear_trigs = 1, every param): audio stock clears +0x10 itself,
        # MIDI stock leaves it (NOTES 2026-11-19 led-fix: the stale MIDI bit)
        C.append((Case(f"{S} T2 s15: the erase-the-trigs gesture on a TL with a lock", side, t, 15).tl().lock(9)
                  .read("before").erase(trigs=True).read("after"),
                  {"before": three(LIT), "after": (fixed_old, fixed_old, DARK)}))
    # mask addressing at the edges: first / last track, a high byte of the mask, the row's last byte
    # (off the trig row's first page, so the TL bit and its mirror are checked, not the LED)
    OFF = ("tl", None)
    for side, t, st, prm in (("M", 7, 40, 31), ("M", 0, 63, 0), ("A", 0, 63, 31), ("A", 7, 32, 15)):
        S = "MIDI" if side == "M" else "AUDIO"
        fixed_old = ("--", None) if side == "A" else OFF
        C.append((Case(f"{S} T{t + 1} s{st + 1}: its one lock (param {prm}) erased", side, t, st).tl().lock(prm)
                  .read("before").erase([prm]).read("after"),
                  {"before": (OFF, OFF, OFF), "after": (OFF, fixed_old, ("--", None))}))
    return C


def steps(cases):
    L = ["ptr blob=0x46c82456", "frame on", f"poke {MIDI_SIDE:#x}=00000001", "spin",
         f"key {TRACK_KEY + 1:#x} down", "frames 5", f"key {TRACK_KEY + 1:#x} up", "frames 5",
         f"key {REC_KEY:#x} down", "frames 5", f"key {REC_KEY:#x} up", "frames 10",
         "echo GRIDREC", "peek 0x460d1736,4", f"peek {CUR_TRK:#x},1", f"peek {CUR_PAT:#x},1"]
    for case, _exp in cases:
        L += ["echo CASE " + case.name, "spin", f"call {INIT:#x},{BLOB0 + P * PS:#x}",
              f"copy {MIRROR + P * PS:#x}={BLOB0 + P * PS:#x},{PS:#x}"]
        L += case.L
    return L


def run(emu, image, cases):
    sf = ROOT / "out" / f"erase_tl_steps_{pathlib.Path(image).stem}.txt"
    sf.write_text("\n".join(steps(cases)) + "\n")
    p = subprocess.run([str(emu), "--image", str(image), "--card", str(CARD), "--set", "OCTABAM",
                        "--project", "OT DEMO", "--steps", str(sf)], cwd=OCT, capture_output=True, text=True)
    blob = re.search(r"^step ptr\s*: blob = (0x[0-9a-f]+)", p.stdout, re.M)
    if not blob or int(blob.group(1), 16) != BLOB0:
        print(p.stdout[-3000:], p.stderr[-1500:]); sys.exit(f"{image}: blob pointer is not {BLOB0:#x}")
    bad = re.findall(r"^(step .*(?:unknown|DID NOT|NOT PARK|ENDED EARLY).*)$", p.stdout, re.M)
    probs = re.search(r"^steps\s+: \d+ lines? executed, (\d+) problem", p.stdout, re.M)
    if bad or not probs or probs.group(1) != "0":
        print(p.stdout[-3000:], p.stderr[-1500:]); sys.exit(f"{image}: the step list did not run cleanly {bad}")
    return p.stdout


def decode(stdout):
    g = [l for l in stdout.splitlines() if l.startswith("step peek") or l.startswith("step echo")]
    res, cur, gr, i = {}, None, None, 0
    val = lambda k: g[k].split(" : ")[-1]
    while i < len(g):
        l = g[i]
        if l == "step echo   : GRIDREC":
            gr = [val(i + 1), val(i + 2), val(i + 3)]; i += 4; continue
        m = re.match(r"^step echo   : CASE (.*)$", l)
        if m:
            cur = m.group(1); res[cur] = {}; i += 1; continue
        m = re.match(r"^step echo   : R (.*)$", l)
        if m:
            res[cur][m.group(1)] = [bytes.fromhex(val(i + k)) for k in range(1, 8)]
            i += 8; continue
        i += 1
    return gr, res


def state(side, s, t, vals):
    trk, masks, mir, rw, lmap, leds, br = vals
    b, m = bit(s)
    lay = lambda off: bool(masks[off + b] & m)
    sp = s % 16                              # the LED ids are per page; only page 1 is shown here
    red = bool(leds[(2 * sp) >> 3] & (1 << ((2 * sp) & 7)))
    grn = bool(leds[(2 * sp + 1) >> 3] & (1 << ((2 * sp + 1) & 7)))
    led = {(True, False): "note", (False, False): "dark", (True, True): "oneshot"}.get(
        (red, grn), "lit" if br[2 * sp + 1] < 15 else "trigless") if s < 16 else "(page 2+)"
    return dict(tl=lay(0x10), mir=bool(mir[0] & m), note=lay(0x00), tt=lay(0x08), led=led if trk[0] == t else None,
                locks=sum(x != 0xFF for x in rw), lmap=bool(lmap[0] & (1 << t)), bright=br[2 * sp + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", required=True)
    ap.add_argument("--old", action="append", default=[], help="the audio-only ERASE (FINAL before 2026-11-20)")
    ap.add_argument("--new", action="append", default=[])
    ap.add_argument("--emu", default=str(ROOT / "out/otemu/build/ot_emu"))
    a = ap.parse_args()
    cases = build_cases()
    imgs = [("stock", a.stock)] + [("old", x) for x in a.old] + [("new", x) for x in a.new]
    col = {"stock": 0, "old": 1, "new": 2}
    fails, summary = [], []
    for role, im in imgs:
        im = str(pathlib.Path(im).resolve())
        gr, res = decode(run(a.emu, im, cases))
        print(f"\n=== {role}: {im}\n    GRID REC {gr[0]}, track index {gr[1]}, pattern {gr[2]}")
        if gr[0] != "00000001":
            fails.append(f"{role}: GRID REC did not come on"); continue
        nbad = 0
        for case, exp in cases:
            r = res.get(case.name, {})
            line = []
            for tag, s, t in case.reads:
                st = state(case.side, s, t, r[tag])
                want_tl, want_led = exp[tag][col[role]]
                ok = st["tl"] == (want_tl == "tl") and st["mir"] == st["tl"] and \
                    (want_led is None or st["led"] == want_led)
                if want_led == "dark" or (want_led is None and tag == "after" and want_tl == "--"):
                    ok = ok and st["locks"] == 0 and not st["lmap"]
                line.append(f"{tag:12s} TL {int(st['tl'])} mirror {int(st['mir'])} locks {st['locks']} "
                            f"lockmap {int(st['lmap'])} LED {st['led']}"
                            f"{'' if ok else '   <-- WANT TL ' + want_tl + ', LED ' + str(want_led)}")
                if not ok:
                    nbad += 1
                    fails.append(f"{role} {pathlib.Path(im).name}: {case.name} [{tag}] {st}, want {exp[tag][col[role]]}")
            print(f"  {case.name}\n      " + "\n      ".join(line))
        summary.append(f"{role:5s} {pathlib.Path(im).name}: {'as expected' if not nbad else f'{nbad} UNEXPECTED'}")
    print("\n" + "\n".join(summary))
    if fails:
        print("\nFAIL:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("\nALL GOOD")


if __name__ == "__main__":
    main()
