#!/usr/bin/env python3
"""MUTE MODE "echo": find WHICH host-port word changes at the post-mute burst steps.

Feed it an ot_emu --block-dump from a muted run (tools/emu_echo_dsp.py --label X --
--block-dump ...).  For one block class (a ping-pong pair is merged by frame), it
reports every word index whose value CHANGES, and when -- so a parameter that is
rewritten exactly at the track's trig steps stands out from the audio words that
change every frame and from the constants that never change.

    python3 tools/echo_blockdiff.py --dump refs/octabam/out/echo_bd.dump \
        --ram 0x800021d0,0x80002c50 --mute-frame 7579
"""
import argparse
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_bd_path = ROOT / "refs/octabam/tools/harness/blockdump.py"
_spec = importlib.util.spec_from_file_location("blockdump", _bd_path)
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)

STEP_FRAMES = 5512 / 16.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dump", required=True)
    ap.add_argument("--ram", required=True, help="comma-separated ColdFire addresses of the class(es)")
    ap.add_argument("--dir", default=">", help="'>' to the DSP, '<' back")
    ap.add_argument("--mute-frame", type=int, default=7579)
    ap.add_argument("--max-words", type=int, default=64, help="report at most this many changing words")
    ap.add_argument("--min-frame", type=int, default=0)
    a = ap.parse_args()

    rams = {int(x, 0) for x in a.ram.split(",")}
    blocks = bd.read(a.dump)
    frames = {}
    for d, frame, ch, core, ram, w in blocks:
        if d == a.dir and ram in rams and frame >= a.min_frame:
            frames[frame] = list(w)
    order = sorted(frames)
    print(f"{len(order)} frames, {len(frames[order[0]])} words per block, "
          f"frames {order[0]}..{order[-1]}")

    nwords = len(frames[order[0]])
    changes = {}          # word index -> [(frame, old, new), ...]
    prev = frames[order[0]]
    for f in order[1:]:
        cur = frames[f]
        for i in range(nwords):
            if cur[i] != prev[i]:
                changes.setdefault(i, []).append((f, prev[i], cur[i]))
        prev = cur

    def step_of(f):
        return (f % 5512) / STEP_FRAMES + 1

    # Which words change IN STEP with the track's own trigs?  The echo's bursts land on
    # them, so a parameter rewritten there -- and not on the other 13 steps -- is the
    # thing that re-attacks the still-sounding voice.
    trigs = set()
    loop = 0
    while loop * 5512 <= order[-1]:
        for s in (1, 10, 15):
            trigs.add(int(round(loop * 5512 + (s - 1) * STEP_FRAMES)))
        loop += 1
    print("\n  words whose changes line up with the trig steps (post-mute only):")
    scored = []
    for i, ev in changes.items():
        post = [f for f, _, _ in ev if f >= a.mute_frame]
        if not post:
            continue
        on = sum(1 for f in post if any(abs(f - t) <= 4 for t in trigs))
        scored.append((on / len(post), on, len(post), i))
    for frac, on, n, i in sorted(scored, reverse=True)[:12]:
        print(f"    word {i:4d}: {on:4d} of {n:5d} post-mute changes on a trig step ({frac:.0%})")

    quiet = [i for i in changes if len(changes[i]) <= 40]
    print(f"\n{len(changes)} of {nwords} words ever change; "
          f"{len(quiet)} change 40 times or fewer (parameter-like):")
    for i in sorted(quiet, key=lambda i: len(changes[i]))[:a.max_words]:
        ev = changes[i]
        print(f"\n  word {i:4d}  ({len(ev)} changes)")
        for f, o, n in ev[:24]:
            mark = "POST-MUTE" if f >= a.mute_frame else "         "
            print(f"      frame {f:6d}  step {step_of(f):5.1f}  {o:#06x} -> {n:#06x}  {mark}")
        if len(ev) > 24:
            print(f"      ... {len(ev) - 24} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
