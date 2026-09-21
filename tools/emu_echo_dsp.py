#!/usr/bin/env python3
"""MUTE MODE "echo": drive octabam's REAL dual-core DSP-rendering port (ot_emu, C++)
against the user's own exported MMTESTDT project and measure the ACTUAL RENDERED AUDIO
around a mute event.

Why this exists (NOTES.md "Session 58 continued yet again, part 17"): the Python-only
"Route A" harness has the DSP fully stubbed, so it can count ColdFire hook hits but can
NEVER show whether sound actually comes out.  Part 17 proved with this port that hook 9
(`dt_trig`) blocks 100% of the trig dispatches it sees and the echo is audible ANYWAY --
so every measurement of this bug from here on has to be made on rendered audio.

Scenario (all from part 17, reproduced exactly):
  * project  MMTESTDT / test  -- a real hardware export, track 0 (0-based), trigs at
    steps 1/10/15, steps 10/15 sample-slot p-locked to a DIFFERENT sample.
  * GATE=2 (DT_MODE) poked early at 0x800000dc.
  * MUTE_STATE's MUTE byte is 0x8000000a  -- bits 8-15 are mute, 16-23 are cue, so
    0x80000009 would poke CUE and produce a bogus "breakthrough" (part 17 did exactly
    that once and had to retract it).  Do not change this without re-reading
    reference/kb/memory-map.md's mute/solo/cue table.
  * the transport runs at 120 BPM: 44100/16 = 2756.25 ColdFire frames/s, one 16-step
    loop = 5512 frames, one step = 344.5 frames.  Step N of loop L fires at
    (L-1)*5512 + (N-1)*344.5.

Usage:
    python3 tools/emu_echo_dsp.py --label echo_s1 --mute-frame 5512
    python3 tools/emu_echo_dsp.py --label nomute --no-mute
    python3 tools/emu_echo_dsp.py --label echo_s1 --analyze-only
"""
import argparse
import pathlib
import subprocess
import sys
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
OCTABAM = ROOT / "refs/octabam"
OT_EMU = OCTABAM / "out/emu/ot_emu"
CARD = OCTABAM / "out/mmtestdt_dsp_card.img"
IMAGE = ROOT / "out/mainos_mutemode_dt.bin"
OUTDIR = OCTABAM / "out"

SET_NAME, PROJECT_NAME = "MMTESTDT", "test"
GATE_ADDR = 0x800000DC          # patch_softmute.s's GATE (m68k-elf-nm out/patch_softmute_rs.elf)
MUTE_BYTE = 0x8000000A          # MUTE_STATE's MUTE byte -- NOT 0x80000009 (that is CUE)

FRAMES_PER_SEC = 44100.0 / 16.0  # 2756.25 ColdFire/DSP frames per second
LOOP_FRAMES = 5512               # 16 steps @ 120 BPM
STEP_FRAMES = LOOP_FRAMES / 16.0
TRIG_STEPS = (1, 10, 15)         # MMTESTDT track 0's real trigs


def run(label, mute_frame, frames, gate, load_ms, watch_read, watch_pc, coverage, extra, watch_mem="", extra_poke="", image=None):
    prefix = OUTDIR / f"echo_{label}"
    # --poke/--poke-early write ONE BYTE each (main.cpp's pokeBytes -> m.write8), but the
    # patch reads GATE with `move.l GATE,%d0` -- so poking the base address alone sets the
    # HIGH byte of a big-endian long (GATE reads 0x02000000, not 2) and every hook falls
    # through to its stock path.  That silently turns a soft-mute test into a stock-mute
    # test: measured 20 Sep 2026, it renders a clean instant cut and NO echo at all.
    # Write all four bytes explicitly.
    gate_poke = ";".join(f"{GATE_ADDR + i:#x}={(gate >> (8 * (3 - i))) & 0xFF}" for i in range(4))
    cmd = [str(OT_EMU), "--image", str(image or IMAGE), "--card", str(CARD),
           "--set", SET_NAME, "--project", PROJECT_NAME,
           "--sequencer", "--internal-clock", "--frames", str(frames),
           "--load-ms", str(load_ms), "--dsp", "--main-level", "64",
           "--poke-early", gate_poke,
           "--audio-out", str(prefix)]
    if mute_frame is not None:
        spec = f"{MUTE_BYTE:#x}=1"
        if extra_poke:
            spec += ";" + extra_poke
        cmd += ["--poke", spec, "--poke-at-frame", str(mute_frame)]
    if watch_mem:
        cmd += ["--watch-mem", watch_mem]
    if watch_read:
        cmd += ["--watch-read", watch_read]
    if watch_pc:
        cmd += ["--watch-pc", watch_pc]
    if coverage:
        cmd += ["--coverage", str(OUTDIR / f"echo_{label}_coverage.txt")]
    cmd += extra
    log = OUTDIR / f"echo_{label}.log"
    print("run:", " ".join(cmd[1:]), flush=True)
    with open(log, "w") as fh:
        subprocess.run(cmd, check=True, stdout=fh, stderr=subprocess.STDOUT)
    print(f"log  -> {log}")
    return prefix


def load_wav(path):
    w = wave.open(str(path), "rb")
    nch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    raw = w.readframes(n)
    w.close()
    if sw != 3:
        sys.exit(f"{path}: unexpected sample width {sw}")
    buf = np.frombuffer(raw, dtype=np.uint8).reshape(-1, nch, 3).astype(np.int32)
    val = buf[:, :, 0] | (buf[:, :, 1] << 8) | (buf[:, :, 2] << 16)
    val = np.where(val & 0x800000, val - 0x1000000, val)
    return val.astype(np.float64) / (1 << 23), sr


def find_transport_start(data, sr):
    """Locate the first real onset: loop 1 step 1 fires at ColdFire frame 0, so the
    first non-silent sample IS the transport start (to within a window).  Derived, not
    assumed -- part 17's hardcoded 896929 only held for its own --load-ms."""
    mono = np.abs(data).max(axis=1)
    win = int(sr * 0.005)
    nz = np.nonzero(mono > 1e-4)[0]
    if not len(nz):
        return None
    return max(0, int(nz[0]) - win)


def envelope(data, sr, start, frames, step_ms=20.0):
    win = int(sr * step_ms / 1000.0)
    end = min(len(data), start + int(frames * 16))
    seg = data[start:end]
    n = len(seg) // win
    out = []
    for i in range(n):
        chunk = seg[i * win:(i + 1) * win]
        out.append((i * win / sr * 1000.0, float(np.sqrt(np.mean(chunk ** 2)))))
    return out


def trig_frames(frames):
    """Every (loop, step, cf_frame) this project's track 0 fires at, within the run."""
    out = []
    loop = 0
    while True:
        for s in TRIG_STEPS:
            f = loop * LOOP_FRAMES + (s - 1) * STEP_FRAMES
            if f > frames:
                return out
            out.append((loop + 1, s, int(round(f))))
        loop += 1


def analyze(prefix, mute_frame, frames, slots):
    path = pathlib.Path(str(prefix) + "_core0.wav")
    data, sr = load_wav(path)
    start = find_transport_start(data, sr)
    print(f"\n{path.name}: {len(data)} samples, {data.shape[1]} slots, sr={sr}, "
          f"transport start detected at sample {start}")
    if start is None:
        return
    # per-trig RMS, 30 ms window at each predicted trig position
    win = int(sr * 0.030)
    print(f"\n  {'loop':>4} {'step':>4} {'cf_frame':>9} {'t_from_mute':>12}   " +
          "  ".join(f"slot{s}" for s in slots))
    for loop, step, f in trig_frames(frames):
        s0 = start + f * 16
        if s0 + win > len(data):
            break
        rms = [float(np.sqrt(np.mean(data[s0:s0 + win, s] ** 2))) for s in slots]
        tag = ""
        if mute_frame is not None:
            dt = (f - mute_frame) / FRAMES_PER_SEC * 1000.0
            tag = f"{dt:+.0f}ms" + (" [mute]" if abs(f - mute_frame) < STEP_FRAMES / 2 else "")
        print(f"  {loop:>4} {step:>4} {f:>9} {tag:>12}   " +
              "  ".join(f"{r:.4f}" for r in rms))
    # full envelope of the loudest slot, from the mute frame on
    slot = max(slots, key=lambda s: float(np.abs(data[start:, s]).mean()))
    env_start = start + (mute_frame or 0) * 16
    print(f"\n  20 ms RMS envelope of slot{slot} from "
          f"{'the mute frame' if mute_frame else 'the transport start'} on:")
    for t_ms, rms in envelope(data, sr, env_start, frames - (mute_frame or 0)):
        if rms > 1e-5:
            print(f"    {t_ms:7.0f}ms  {rms:.4f} {'#' * min(60, int(rms * 400))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--label", required=True, help="names the wav/log/coverage outputs")
    ap.add_argument("--mute-frame", type=int, default=5512,
                    help="ColdFire frame to engage mute at (loop L step N = (L-1)*5512 + (N-1)*344.5)")
    ap.add_argument("--no-mute", action="store_true", help="baseline: never engage mute")
    ap.add_argument("--frames", type=int, default=19300)
    ap.add_argument("--gate", type=int, default=2, help="2 = DT_MODE, 1 = OT+FX")
    ap.add_argument("--load-ms", type=int, default=20000)
    ap.add_argument("--watch-read", default="", help="ADDR,LEN -- log data READS with the reading PC")
    ap.add_argument("--watch-mem", default="", help="ADDR,LEN[;ADDR,LEN...] -- log WRITES with the writing PC")
    ap.add_argument("--extra-poke", default="", help="more 'addr=byte' pokes applied WITH the mute")
    ap.add_argument("--image", default=None, help="mainos .bin to run (default: the DT build)")
    ap.add_argument("--watch-pc", default="", help="comma-separated PCs -- log registers there")
    ap.add_argument("--coverage", action="store_true", help="every ColdFire PC from the transport start")
    ap.add_argument("--slots", default="0,2,4", help="ESAI TX0 slots to report")
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("extra", nargs="*", help="extra ot_emu args after --")
    a = ap.parse_args()

    mute_frame = None if a.no_mute else a.mute_frame
    slots = [int(s) for s in a.slots.split(",") if s != ""]
    prefix = OUTDIR / f"echo_{a.label}"
    if not a.analyze_only:
        for p in (OT_EMU, CARD, pathlib.Path(a.image) if a.image else IMAGE):
            if not p.exists():
                sys.exit(f"missing: {p}")
        prefix = run(a.label, mute_frame, a.frames, a.gate, a.load_ms,
                     a.watch_read, a.watch_pc, a.coverage, list(a.extra), a.watch_mem,
                     a.extra_poke, a.image)
    analyze(prefix, mute_frame, a.frames, slots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
