#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
The shared form (tools/sc_shared.py) against the per-core source, under dsp_host: what one
copy of the code does for each core equals what that core's own copy does.

    python3 tools/emu_sc_shared.py [--org HEX]     (default --org 38100; always --layout octabam)

Both forms are assembled at the same P address with emu_sc_dsp3.py's assembler (the code, then
the KEY GAIN and key-filter tables), the per-core one with each payload's own tokens from
octabam-modules/sidechain-compressor/manifest.py.

  sctap   emu_sc_sctap.py's wrapper (NBLK blocks of a core's four tracks, a counter as audio),
          for payload B (tracks 0-3) and payload A (tracks 4-7): internal Y equal (the keybus);
          every window word the per-core form wrote, SBASE + (local*4 + g)*$20, equal to the
          shared form's zzwn + (track*4 + g + 1)*$20 (the shared counter starts at 0 and
          advances on the first block, where GSEED seeds the per-core one to 0); the core's
          counter one ahead of GCNT, the other core's untouched; nothing else in the window
          written by either.
  scdet   for each payload, MY track its first, and every KEY track 0..7: X:$40 equal. A
          same-core KEY reads the keybus (unchanged code). A foreign KEY reads the window: both
          layouts hold the same four generations of the KEY track, the per-core GCNT is G
          (it reads G + 2) and the shared form's counter of the KEY track's core is G + 3 (it
          reads that minus 1), for G = 0..3; then the shared counter one off must read a
          different generation.
"""
import pathlib, sys

if "--org" not in sys.argv:
    sys.argv += ["--org", "38100"]
if "--layout" not in sys.argv and "--manifest" not in sys.argv:
    sys.argv += ["--layout", "octabam"]

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import emu_sc_dsp3 as E                      # noqa: E402
import emu_sc_sctap as S                     # noqa: E402
import sc_shared                             # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        fails.append(name)


def assemble(src, payload):
    """emu_sc_dsp3.assemble() of `src` with `payload`'s layout tokens: (words, syms). syms["rts"] is
    the address emu_sc_dsp3 runs as -init (sctap's own rts), which differs between the forms."""
    keep_src, keep_b = E.SRC, E.LAYOUT["B"]
    E.SRC = type("Src", (), {"read_text": staticmethod(lambda: src)})()
    E.LAYOUT["B"] = E.LAYOUT[payload]
    try:
        words = E.assemble()[0]
        syms = {n: int(a, 16) for n, a in (l.split() for l in (E.SCRATCH / "sc3_test.sym").read_text().splitlines()
                                            if l.strip())}
        syms["rts"] = E.RTS_ADDR
    finally:
        E.SRC, E.LAYOUT["B"] = keep_src, keep_b
    return words, syms


def tok(payload, name):
    return int(E.LAYOUT[payload][name].lstrip("$"), 16)


SRC = E.SRC.read_text()
SHARED = sc_shared.shared_form(SRC)
SH_WORDS, SH_SYMS = assemble(SHARED, "B")
SH_A, _ = assemble(SHARED, "A")
WIN = sc_shared.window_base(SH_SYMS["zzend"])
CNT = WIN + sc_shared.WINDOW_WORDS
KB = E.KB_BASE
WRAP2 = 0x1f80                               # scdet's wrapper: x:$420 is reset by dsp_host's setup


def scdet_wrapper(syms, track):
    """Set x:$420 to `track`, then branch to scdet (dsp_asm writes a long branch's operand as the
    displacement itself, so it is spelled as one: target - the branch's address)."""
    txt = (f"zzw1:\n        move    #>${track:x},x0\n        move    x0,x:>$420\n"
           f"        bra     >${(syms['scdet'] - (WRAP2 + 4)) & 0xffffff:x}\n")
    a, o = E.SCRATCH / "w2.asm", E.SCRATCH / "w2.bin"
    a.write_text(txt)
    E.sh(E.DSP_ASM, "-in", a, "-org", f"{WRAP2:x}", "-out", o)
    raw = o.read_bytes()
    return [int.from_bytes(raw[i:i + 3], "little") for i in range(0, len(raw), 3)]


def scdet_x40(words, syms, track, seed, params, pokey):
    E.RTS_ADDR = syms["rts"]
    m = E.base_mem(words, syms["scdet"], syms["moncommit"], False, seed + [(0, WRAP2, scdet_wrapper(syms, track))], None)
    (x40,) = E.run(m, WRAP2, [("x", 0x40, 0x60)], params, pokey=pokey, audio=0)
    return x40


def main():
    print(f"shared form: {len(SH_WORDS)} words at P:0x{E.CAVE_ORG:x} (window P:0x{WIN:x}, counters P:0x{CNT:x})")
    check("the shared form assembles to the same words with payload A's and payload B's tokens", SH_A == SH_WORDS)

    print("\nsctap, NBLK blocks of the core's four tracks:")
    for payload in ("B", "A"):
        cb = 4 if payload == "A" else 0
        per_words, per_syms = assemble(SRC, payload)
        sbase, gcnt, gseed = (tok(payload, t) for t in ("@SBASE@", "@GCNT@", "@GSEED@"))
        S.COREBASE = cb
        E.RTS_ADDR = per_syms["rts"]
        per = S.run(per_words, True)
        E.RTS_ADDR = SH_SYMS["rts"]
        sh, base = S.run(SH_WORDS, True), S.run(SH_WORDS, False)
        check(f"payload {payload}: internal Y (the keybus) equal", per["y"] == sh["y"])
        w = lambda d, a: d["w"][a - 0x30000]
        diff = [(t, g, i) for t in range(4) for g in range(4) for i in range(32)
                if w(per, sbase + (t * 4 + g) * 0x20 + i) != w(sh, WIN + ((cb + t) * 4 + ((g + 1) & 3)) * 0x20 + i)]
        check(f"payload {payload}: every window word of the core's tracks, all four generations, equal", not diff,
              f"{len(diff)} differ, first {diff[:2]}")
        g_last = w(per, gcnt)
        own, other = w(sh, CNT + (cb == 4)), w(sh, CNT + (cb != 4))
        check(f"payload {payload}: the core's counter one ahead of GCNT ({g_last}), the other core's untouched",
              own == (g_last + 1) & 3 and other == 0, f"own {own}, other {other}")
        mine = {WIN + ((cb + t) * 4 + g) * 0x20 + i for t in range(4) for g in range(4) for i in range(32)} | {CNT + (cb == 4)}
        stray = [hex(0x30000 + j) for j, v in enumerate(sh["w"]) if v != base["w"][j] and 0x30000 + j not in mine]
        check(f"payload {payload}: the shared form writes nothing else in the window", not stray, f"{stray[:4]}")
        perm = ({sbase + j for j in range(0x200)} | {gcnt, gseed})
        stray = [hex(0x30000 + j) for j, v in enumerate(per["w"]) if v != base["w"][j] and 0x30000 + j not in perm]
        check(f"payload {payload}: (reference) the per-core form writes nothing else in the window", not stray, f"{stray[:4]}")

    print("\nscdet, KEY 1..8 from each core's first track, filters off, KGN 64:")
    E.RTS_ADDR = SH_SYMS["rts"]
    probe = E.base_mem(SH_WORDS, SH_SYMS["scdet"], SH_SYMS["moncommit"], False, None, None)
    r7 = E.r7_of(probe)
    E.S17, E.KFB = r7 + 0x17, r7 + 0x1c
    pat = lambda t, g: [((0x100 + t * 0x10 + g) << 12 | i) & 0xffffff for i in range(32)]
    for payload in ("B", "A"):
        cb = 4 if payload == "A" else 0
        per_words, per_syms = assemble(SRC, payload)
        fsbase, gcnt = tok(payload, "@FSBASE@"), tok(payload, "@GCNT@")
        for key in range(8):
            foreign = (key & 4) != (cb & 4)
            params = f"0,0,0,0,0,0,0,2,{key + 1},64,0,127"
            seed = [(1, r7 + 0x2c, [key + 1, 0])]                         # the key in use, steady
            for G in (range(4) if foreign else (0,)):
                per_y = {KB + key * 0x40 + i: v for i, v in enumerate(pat(key, 9))}
                sh_y = dict(per_y)
                if foreign:
                    fl = key - (4 - cb)
                    for g in range(4):
                        for i, v in enumerate(pat(key, g)):
                            per_y[fsbase + (fl * 4 + g) * 0x20 + i] = v
                            sh_y[WIN + (key * 4 + g) * 0x20 + i] = v
                    per_y[gcnt] = G
                    sh_y[CNT + (key >= 4)] = (G + 3) & 3
                pk = lambda d: ",".join(f"{a:x}={v:x}" for a, v in d.items())
                x_per = scdet_x40(per_words, per_syms, cb, seed, params, pk(per_y))
                x_sh = scdet_x40(SH_WORDS, SH_SYMS, cb, seed, params, pk(sh_y))
                what = f"payload {payload}, KEY T{key + 1} ({'foreign, G ' + str(G) if foreign else 'same core'})"
                check(f"{what}: X:$40 equal", x_per == x_sh, f"per[:2] {[hex(v) for v in x_per[:2]]} shared[:2] {[hex(v) for v in x_sh[:2]]}")
                if foreign:
                    sh_y[CNT + (key >= 4)] = (G + 4) & 3
                    x_off = scdet_x40(SH_WORDS, SH_SYMS, cb, seed, params, pk(sh_y))
                    check(f"{what}: the shared counter one off reads another generation", x_off != x_sh)

    print("\nALL GOOD" if not fails else f"\nFAIL -- {len(fails)}: " + ", ".join(fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
