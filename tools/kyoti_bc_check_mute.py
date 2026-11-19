#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
KYOTI V1.8BC: MUTE_MODES on a BLKPYRAMD track (ot_emu, BOTLI, the sequencer playing; verify_ot303's setup and
pokes through tools/kyoti_bc_check_voice.py). T2 (core 1) and T6 (core 0) are made BLKPYRAMD with verify's
test lines; one of them is muted after the load, in each MUTE MODE (GATE 0x800000dc: 0 OT, 1 OTFX-T, 2 DT-T,
3 OTFX), and the run counts what the voice did:

  notes   the renderer's notes for that track (its event log, ot_evlog: track << 28) -- a note sent to the DSP
  starts  hq_start arrivals on that track's core (the DSP starting a note; the other BLKPYRAMD track is on the
          other core, so the count is this track's alone)

A muted BLKPYRAMD track in OTFX-T / DT-T keeps its level words open (FX tails ring), so any note it starts is
heard; in OT / OTFX stock's post-FX cut / the zeroed VOL silence it whatever it does. Modwerk #777 (FM Synth):
a machine that starts its own notes before stock binds the voice escapes MUTE_MODES' trig drop.

    python3 tools/kyoti_bc_check_mute.py [frames]
"""
import concurrent.futures as cf, os, re, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kyoti_bc_check_voice as cv          # noqa: E402  (configures verify_ot303 for the combined image)

v = cv.v
FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 12000
MODES = {0: "OT", 1: "OTFX-T", 2: "DT-T", 3: "OTFX"}


def one(mode, muted, S, hs):
    """(notes per track, DSP note starts on the muted track's core)"""
    t = muted
    core = 1 if t is None or t < 4 else 0
    pokes = v.ot303_pokes((1, 5)) + v.line_pokes((5,)) + v.line_pokes((1,), v.LINE2, v.LOCKS2, v.CONDS2)
    pokes += [f"0x800000dc=0", "0x800000dd=0", "0x800000de=0", f"0x800000df={mode}"]
    if muted is not None:
        pokes.append(f"0x8000000a={1 << t:#x}")
    dump = dict(evn=(S["ot_evn"], 4), evlog=(S["ot_evlog"], 128), trigs=(S["ot_trigs"], 4))
    with tempfile.TemporaryDirectory() as td:
        args = ["--sequencer", "--internal-clock", "--frames", str(FRAMES), "--main-level", "64",
                "--step", "-:poke:" + ";".join(pokes),
                "--dsp-pcwatch", f'{core}:{hs["B" if core == 1 else "A"]:x}',
                "--mem-dump", ";".join(f"{a:#x},{n}={td}/{k}.bin" for k, (a, n) in dump.items())]
        p = v.emu(v.IMAGE, args, td)
        got = {k: open(f"{td}/{k}.bin", "rb").read() for k in dump if os.path.exists(f"{td}/{k}.bin")}
    sec = p.stdout.split("dsp pcwatch:", 1)
    hits = 0
    if len(sec) == 2:
        m = re.search(r"last (\d+) arrival", sec[1])
        hits = int(m.group(1)) if m else 0
    evn = int.from_bytes(got.get("evn", b"\0" * 4), "big")
    log = got.get("evlog", b"")
    ring = [int.from_bytes(log[i:i + 4], "big") for i in range(0, len(log), 4)]
    m = min(evn, 32)
    ents = [ring[(evn - m + i) & 31] for i in range(m)]
    per = {k: sum(1 for e in ents if e >> 28 == k and (e >> 24) & 1) for k in (1, 5)}
    return p.returncode, per, hits, evn, int.from_bytes(got.get("trigs", b"\0" * 4), "big")


def main():
    S = v.syms()
    hs = {tag: v.hwprobe_image.build(tag, host=True)["syms"]["hq_start"] for tag in ("A", "B")}
    jobs = {(m, t): (m, t) for m in MODES for t in (1, 5)}
    jobs.update({(m, None): (m, None) for m in (0, 2)})
    with cf.ThreadPoolExecutor(len(jobs)) as ex:
        fut = {k: ex.submit(one, *a, S, hs) for k, a in jobs.items()}
        res = {k: f.result() for k, f in fut.items()}
    print(f"{FRAMES} frames; notes = the renderer's last-32 event ring per track (T2 / T6), starts = DSP hq_start "
          f"arrivals on the muted track's core (pcwatch, last window)")
    for (m, t), (rc, per, hits, evn, trigs) in sorted(res.items(), key=lambda kv: (kv[0][0], kv[0][1] or -1)):
        who = f"T{t + 1} muted" if t is not None else "none muted"
        print(f"  {MODES[m]:7} {who:11}: rc {rc}  notes in ring T2 {per[1]:2d} T6 {per[5]:2d}  "
              f"(total events {evn}, renderer notes {trigs})  DSP starts on the core {hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
