#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
EMPTY_PATTERN_LED_FIX: the Session 119 stall gate -- ColdFire instructions in 0.6 s with [BANK] held.

    python3 tools/led_bank_stall.py --emu out/otemu/build/ot_emu IMAGE [IMAGE ...]

While [BANK] is held the bank grid calls bank_has_content 0x4000fd78 -> FUN_4009a464 for the patterns of
all 16 banks on every LED refresh, and with the sequencer playing it refreshes on every step (stopped, it
paints once: the transport is started here, as on the unit in S119's report). Session 119 measured, for KYOTI V1.0, 71.4M
cave instructions in a 0.6 s window with the 32 KB-per-empty-pattern scan, against an idle 44.5M; after
its fix ~ idle. This script measures, per image and per bank content (all 16 banks, 256 patterns):

  demo      the OT DEMO project as loaded (kyoti_led_card.img)
  empty     every pattern reset by stock's initialiser -- every call is an "empty" call
  tl_lock   every pattern: one trigless lock with a locked parameter (audio T3 step 13)
  tl_empty  every pattern: 1,024 trigless locks with nothing locked (all 64 steps x 16 tracks):
            the most work the [BANK] path can be given (it stops at its budget of rows)

and reports, for an idle window and a [BANK]-held window of 1,654 frames (0.6 s at 16 samples/frame):
all ColdFire instructions, the instructions inside the cave, and the number of calls into it.

Needs ot_emu with the `key` and `icount` step verbs (tools/refs/local-patches/octabam-ot-emu-steps-key.patch,
built privately -- see that file; never rebuild the shared clone's binaries under another session).
"""
import argparse, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCT = ROOT / "refs/octabam"
CARD = OCT / "out/kyoti_led_card.img"
INIT = 0x4009ABDC
PS, BS, AS, MS = 0x8ED8, 0x9B340, 0x91A, 0x8B0
AUD_ROW, MID_BLK, MID_ROW = 0x59, 0x48D0, 0x4900
DETOUR, BASE = 0x4009A464, 0x40000400
CONT_JMP = bytes.fromhex("4ef94009a46a")
BANK_KEY = 0x2F
KEYS = {"bank": 0x2F, "ptn": 0x2E}             # NOTES: BANK 0x2f (0x4007af80), PTN 0x2e
WINDOW = 1654                                    # 0.6 s


CAVE_LEN = {}                                     # --cave-len: the cave's length when it lives in DRAM


def cave_range(image):
    img = pathlib.Path(image).read_bytes()
    d = DETOUR - BASE
    if img[d:d + 2] != b"\x4e\xf9":
        sys.exit(f"{image}: no jmp at 0x{DETOUR:08x}")
    at = int.from_bytes(img[d + 2:d + 6], "big")
    if not BASE <= at < BASE + len(img):            # a DRAM unit (KYOTI): not at its address in the file
        if "n" not in CAVE_LEN:
            sys.exit(f"{image}: the cave 0x{at:08x} is in DRAM -- give --cave-len")
        return at, at + CAVE_LEN["n"]
    end = img.find(CONT_JMP, at - BASE)
    if end < 0 or end - (at - BASE) > 0x400:
        sys.exit(f"{image}: cannot find the cave's end")
    return at, end + len(CONT_JMP) + BASE


def scenario_pokes(name):
    out = []
    if name == "demo":
        return out
    for b in range(16):
        for p in range(16):
            out += ["spin", f"call {INIT:#x},blob+{b * BS + p * PS:#x}"]
    if name == "empty":
        return out
    for b in range(16):
        for p in range(16):
            pat = b * BS + p * PS
            if name == "tl_lock":
                t, s = 2, 12
                out.append(f"poke blob+{pat + t * AS + 0x10 + 7 - (s >> 3):#x}={1 << (s & 7):02x}")
                out.append(f"poke blob+{pat + t * AS + AUD_ROW + 32 * s:#x}=30")
            elif name == "tl_empty":
                for t in range(8):
                    out.append(f"poke blob+{pat + t * AS + 0x10:#x}=ffffffffffffffff")
                    out.append(f"poke blob+{pat + MID_BLK + t * MS + 0x10:#x}=ffffffffffffffff")
    return out


def run(emu, image, scen, settle, key=BANK_KEY):
    lo, hi = cave_range(image)
    rng = f"{lo:#x},{hi:#x}"
    ent = f"{lo:#x},{lo + 2:#x}"
    def fr(n):         # in chunks: ot_emu's `frames` has a wall-clock ceiling (5x real time + 2 s)
        return [f"frames {min(50, n - k)}" for k in range(0, n, 50)]
    L = ["ptr blob=0x46c82456"] + scenario_pokes(scen) + [
        "frame on", "transport", *fr(settle), "coverage",
        f"icount {rng}", f"icount {ent}", *fr(WINDOW), f"icount {rng}", f"icount {ent}",
        f"key {key:#x} down", *fr(settle),
        f"icount {rng}", f"icount {ent}", *fr(WINDOW), f"icount {rng}", f"icount {ent}",
        f"key {key:#x} up", "frames 50"]
    sf = ROOT / "out" / f"led_stall_steps_{scen}_{pathlib.Path(image).stem}.txt"
    sf.write_text("\n".join(L) + "\n")
    p = subprocess.run([str(emu), "--image", str(image), "--card", str(CARD), "--set", "OCTABAM",
                        "--project", "OT DEMO", "--steps", str(sf)], cwd=OCT, capture_output=True, text=True)
    ic = [(int(a), int(f), int(r)) for a, f, r in
          re.findall(r"^step icount : (\d+) instructions, frame (\d+), in range (\d+)$", p.stdout, re.M)]
    fr = re.findall(r"^step frames : (\d+) frame\(s\) of (\d+)", p.stdout, re.M)
    bad = re.findall(r"^(step .*(?:unknown|DID NOT|NOT PARK|FAILED).*)$", p.stdout, re.M)
    if len(ic) != 8 or bad or any(a != b for a, b in fr):
        print(p.stdout[-3000:], p.stderr[-1500:]); sys.exit(f"{scen} {image}: run incomplete {bad} {fr}")
    def win(i):        # (all, cave, calls, frames) between icount pairs i, i+2
        a0, f0, c0 = ic[i]; _, _, e0 = ic[i + 1]; a1, f1, c1 = ic[i + 2]; _, _, e1 = ic[i + 3]
        return a1 - a0, c1 - c0, e1 - e0, f1 - f0
    return win(0), win(4), (lo, hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--emu", default=str(ROOT / "out/otemu/build/ot_emu"))
    ap.add_argument("--scenarios", default="demo,empty,tl_lock,tl_empty")
    ap.add_argument("--settle", type=int, default=300)
    ap.add_argument("--key", default="bank", choices=sorted(KEYS), help="the key held in the second window")
    ap.add_argument("--cave-len", type=lambda x: int(x, 0), help="the cave's length (a DRAM-placed cave)")
    a = ap.parse_args()
    if a.cave_len:
        CAVE_LEN["n"] = a.cave_len
    print(f"window {WINDOW} frames (0.6 s); M = 1e6 ColdFire instructions\n")
    print("scenario   image".ljust(52) + f"idle all     cave   | [{a.key.upper()}] all   cave      calls   cave/call")
    for scen in a.scenarios.split(","):
        for im in a.images:
            im = str(pathlib.Path(im).resolve())
            idle, held, (lo, hi) = run(a.emu, im, scen, a.settle, KEYS[a.key])
            per = held[1] / held[2] if held[2] else 0
            print(f"{scen:<10} {pathlib.Path(im).name[:38]:<40}"
                  f"{idle[0] / 1e6:7.2f}M {idle[1]:>8} | {held[0] / 1e6:7.2f}M {held[1]:>9} {held[2]:>7}   {per:7.0f}"
                  f"   (cave 0x{lo:08x}..0x{hi:08x})")


if __name__ == "__main__":
    main()
