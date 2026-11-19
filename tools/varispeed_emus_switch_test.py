#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
VARISPEED_EMUS VEM11 -- the Part-switch gates (emulator, ot_emu with tools/varispeed_emus_ot_emu.patch
plus the per-pair executed-count stamp of OT_SW_OUT): the load guard across a sequencer Part switch.

What it tests. A Part switch moves each track to the new Part's FX and engine at THAT track's first
trig in the new Part (stock copies the live FX types there, 0x4000c40e / 0x4000c41e; the engine
latch moves with it), so the old Part's carried tracks and the new Part's triggered ones play mixed.
VEM11 prices that transition before the switch (vgx_tick), clamps a carried engine once at the real
switch frame (vem_frame, keyed on APPLIED_B / APPLIED_P) and keeps a playing voice on its VARI
engine / increment until that frame (vf_win / vf_eng). Every case is set by runtime pokes on the REAL
export MMTESTDT (T1-T8 STATIC, part 0, 120 BPM): T5-T8 (DSP core 0) on the settings below, Part 0
playing pattern 0, pattern 1 (poked to use Part 1) cued at frame 100 (or as the variant says).

  python3 tools/varispeed_emus_switch_test.py run   [--img unit|feature|base_unit|base_feature]...
                                                    [--only CASE,...] [--jobs N] [--audio]
  python3 tools/varispeed_emus_switch_test.py check [--img ...]        the gates (needs base_* runs)
  python3 tools/varispeed_emus_switch_test.py timeline RUN_DIR         one run's events + DSP frames

Images (paths overridable by environment):
  unit          out/mainos_varispeed_emus.bin                  + out/varispeed_emus_syms.json
  feature       out/VARISPEED_EMUS/mainos_varispeed_emus.bin   + the unit's symbols
  base_unit     VEM_BASE_UNIT (default out/base_unit.bin)      + VEM_BASE_SYMS (out/base_syms.json)
  base_feature  VEM_BASE_FEATURE (default out/base_feature.bin) + VEM_BASE_SYMS
the base_* being the promoted FINAL VARISPEED_EMUS (VEM10) unit and feature image.

Gates (check): per case and image, after the fix
  * no DSP core-0 frame's actually-running estimate (the guard's model on the engines the DSP runs
    and the live FX ids) exceeds the budget; the max (model and datasheet cycles/sample) reported;
  * a step (vg_step_ot / vgx_step) comes with the toast (NOTIFY from vg_tick) in the same UI pass;
  * mix_nonvari: no engine or increment change on the carried T5 / T6 before the apply frame;
  * the cases where nothing has to act (ref_clean, carry_fit_step1) are byte-for-byte the base's:
    no step, no toast, the same per-frame engines and increments on T5-T8.
"""
import argparse, bisect, json, os, pathlib, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "out/vem/switch"
os.environ.setdefault("VEM_STUB_AT", "0x47fd8000")        # the unit's cave tail holds no stubs
os.environ.setdefault("VEM_EMU", str(ROOT / "out/emu/octabam/out/emu/ot_emu"))
sys.path.insert(0, str(ROOT / "tools"))
import varispeed_emus_test as V  # noqa: E402

IMGS = {
    "unit": (ROOT / "out/mainos_varispeed_emus.bin", ROOT / "out/varispeed_emus_syms.json"),
    "feature": (ROOT / "out/VARISPEED_EMUS/mainos_varispeed_emus.bin", ROOT / "out/varispeed_emus_syms.json"),
    "base_unit": (pathlib.Path(os.environ.get("VEM_BASE_UNIT", ROOT / "out/base_unit.bin")),
                  pathlib.Path(os.environ.get("VEM_BASE_SYMS", ROOT / "out/base_syms.json"))),
    "base_feature": (pathlib.Path(os.environ.get("VEM_BASE_FEATURE", ROOT / "out/base_feature.bin")),
                     pathlib.Path(os.environ.get("VEM_BASE_SYMS", ROOT / "out/base_syms.json"))),
    # VARISPEED, the plain build (VARIG1: the same per-track freeze, no engines, no guard)
    "vari": (ROOT / "out/mainos_varispeed.bin", ROOT / "out/varispeed_syms.json"),
    "vari_feature": (ROOT / "out/VARISPEED/mainos_varispeed.bin", ROOT / "out/varispeed_syms.json"),
    "base_vari": (pathlib.Path(os.environ.get("VARI_BASE_UNIT", ROOT / "out/base_vari_unit.bin")),
                  pathlib.Path(os.environ.get("VARI_BASE_SYMS", ROOT / "out/base_vari_syms.json"))),
    "base_vari_feature": (pathlib.Path(os.environ.get("VARI_BASE_FEATURE", ROOT / "out/base_vari_feature.bin")),
                          pathlib.Path(os.environ.get("VARI_BASE_SYMS", ROOT / "out/base_vari_syms.json"))),
}
# the plain build's gates (check --plain): speeds only (it has no engine); FINAL VARISPEED as the base
PLAIN_HELD = {"mix_nonvari": (4, 5), "nonvari_fit": (4, 5), "rev_vari": (4, 5)}
PLAIN_EARLY = ("own_xbank", "mix_xbank")          # nothing may change before the switch frame
PLAIN_SAME = ("ref_clean", "carry_fit", "carry_fit_step1", "own_step1", "own_step1_stopped", "cert_sure",
              "cancel_mix_max")                    # increments byte-for-byte FINAL's
MMDB, GT = V.MMDB, V.GT
CARD = V.MM["card"]
MIDI_PC = OUT / "midi_pc1.txt"                    # frame 100: PROGRAM CHANGE ch 1 -> pattern 1

ALL = lambda v: {t: v for t in GT}
CASES = {
    # B's OWN settings over budget (SP12 x4 + DJ EQ x4 + DARK x4 = 3,681 > 3,350): the guard steps
    # B's T8, T7 to OT. Every B track trigs on step 1 (the boundary).
    "own_step1": dict(a_emus=ALL("SP12"), a_fx1=ALL("NONE"), a_fx2=ALL("DARK"),
                      b_emus=ALL("SP12"), b_fx1=ALL("DJEQ"), b_fx2=ALL("DARK"),
                      a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs=ALL([1])),
    # the same, B's T7 / T8 (the ones stepped) trig on step 9: they carry A's SP12 latch
    "own_late78": dict(a_emus=ALL("SP12"), a_fx1=ALL("NONE"), a_fx2=ALL("DARK"),
                       b_emus=ALL("SP12"), b_fx1=ALL("DJEQ"), b_fx2=ALL("DARK"),
                       a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs={4: [1], 5: [1], 6: [9], 7: [9]}),
    # B fits (EMUS OT x4 + DJ EQ x4 + DARK x4 = 2,933); A's SP12 latches carry into B until step 9
    "carry_fit": dict(a_emus=ALL("SP12"), a_fx1=ALL("NONE"), a_fx2=ALL("DARK"),
                      b_emus=ALL("OT"), b_fx1=ALL("DJEQ"), b_fx2=ALL("DARK"),
                      a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs=ALL([9])),
    # control: carry_fit's B, every B track on step 1 (nothing carries)
    "carry_fit_step1": dict(a_emus=ALL("SP12"), a_fx1=ALL("NONE"), a_fx2=ALL("DARK"),
                            b_emus=ALL("OT"), b_fx1=ALL("DJEQ"), b_fx2=ALL("DARK"),
                            a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs=ALL([1])),
    # each Part fits (2,079), per track opposite: A heavy on T5/T6, B on T7/T8 (SP12 + DJ EQ + DARK)
    "mix_late": dict(a_emus={4: "SP12", 5: "SP12", 6: "OT", 7: "OT"},
                     a_fx1={4: "DJEQ", 5: "DJEQ", 6: "NONE", 7: "NONE"},
                     a_fx2={4: "DARK", 5: "DARK", 6: "NONE", 7: "NONE"},
                     b_emus={4: "OT", 5: "OT", 6: "SP12", 7: "SP12"},
                     b_fx1={4: "NONE", 5: "NONE", 6: "DJEQ", 7: "DJEQ"},
                     b_fx2={4: "NONE", 5: "NONE", 6: "DARK", 7: "DARK"},
                     a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs={4: [9], 5: [9], 6: [1], 7: [1]}),
    # mix_late, B's T5 / T6 never trig: the mix for as long as the Part plays
    "mix_never": dict(a_emus={4: "SP12", 5: "SP12", 6: "OT", 7: "OT"},
                      a_fx1={4: "DJEQ", 5: "DJEQ", 6: "NONE", 7: "NONE"},
                      a_fx2={4: "DARK", 5: "DARK", 6: "NONE", 7: "NONE"},
                      b_emus={4: "OT", 5: "OT", 6: "SP12", 7: "SP12"},
                      b_fx1={4: "NONE", 5: "NONE", 6: "DJEQ", 7: "DJEQ"},
                      b_fx2={4: "NONE", 5: "NONE", 6: "DARK", 7: "DARK"},
                      a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs={4: [], 5: [], 6: [1], 7: [1]},
                      frames=11600),
    # the worst mix: a heavy track = SP12 + DJ EQ + DJ EQ (881); each Part 2,239, the mix 4,001
    "mix_max": dict(a_emus={4: "SP12", 5: "SP12", 6: "OT", 7: "OT"},
                    a_fx1={4: "DJEQ", 5: "DJEQ", 6: "NONE", 7: "NONE"},
                    a_fx2={4: "DJEQ", 5: "DJEQ", 6: "NONE", 7: "NONE"},
                    b_emus={4: "OT", 5: "OT", 6: "SP12", 7: "SP12"},
                    b_fx1={4: "NONE", 5: "NONE", 6: "DJEQ", 7: "DJEQ"},
                    b_fx2={4: "NONE", 5: "NONE", 6: "DJEQ", 7: "DJEQ"},
                    a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs={4: [9], 5: [9], 6: [1], 7: [1]}),
    # calibration, no switch: the most the guard admits on one Part (4 x SP12, DARK x4, DJ EQ x3)
    "ref_clean": dict(a_emus=ALL("SP12"), a_fx1={4: "DJEQ", 5: "DJEQ", 6: "DJEQ", 7: "NONE"}, a_fx2=ALL("DARK"),
                      b_emus=ALL("OT"), b_fx1=ALL("NONE"), b_fx2=ALL("NONE"),
                      a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs=ALL([1]), cue=-1, frames=4000),
    # B has NO VARI track (TSTR OFF): only its T7/T8 FX are heavy (DJ EQ x2); A's T5/T6 (SP12 + DJ EQ
    # x2) carry into it: the old voices must keep VARI until the real switch frame (the pitch jump)
    "mix_nonvari": dict(a_emus={4: "SP12", 5: "SP12", 6: "OT", 7: "OT"},
                        a_fx1={4: "DJEQ", 5: "DJEQ", 6: "NONE", 7: "NONE"},
                        a_fx2={4: "DJEQ", 5: "DJEQ", 6: "NONE", 7: "NONE"},
                        b_emus=ALL("OT"), b_tstr=ALL(0),
                        b_fx1={4: "NONE", 5: "NONE", 6: "DJEQ", 7: "DJEQ"},
                        b_fx2={4: "NONE", 5: "NONE", 6: "DJEQ", 7: "DJEQ"},
                        a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs={4: [9], 5: [9], 6: [1], 7: [1]}),
}
CASES["mix_max_s2"] = dict(CASES["mix_max"], b_trigs={4: [9], 5: [9], 6: [2], 7: [2]})
# carry_fit with other engines: four carried S950 voices into a Part that has them on OT, and four
# carried SP12 voices into a Part that has them on S950 (the clamp's other two steps)
CASES["carry_s950_ot"] = dict(CASES["carry_fit"], a_emus=ALL("S950"))
# a cue into ANOTHER bank (0-based bank 1, pattern 1, its Part 1): not priced at the cue (the cued Part is not
# the working bank's), but from the bank / PART_B move to the apply (message 21 / 20, ~7 ticks)
CASES["own_xbank"] = dict(CASES["own_step1"], b_bank=1)
CASES["mix_xbank"] = dict(CASES["mix_max"], b_bank=1)
# VEMG2: a cue cancelled (pattern 0, the playing one, cued again at frame 3000) and a cue changed
# (to pattern 2, which uses the current Part 0) before the switch: nothing written, nothing heard
CASES["cancel_mix_max"] = dict(CASES["mix_max"], recue=(3000, 0, 0))
CASES["change_mix_max"] = dict(CASES["mix_max"], recue=(3000, 0, 2))
# VEMG2: the first-step certainty. A's T5 / T6 hold SP12 + DJ EQ x2 (881); B (fits alone, 3,307) has
# them on OT + DJ EQ + DARK and T7 / T8 on SP12 + DJ EQ + DARK, every B track on step 1. Sure trigs:
# B alone, nothing to do. A condition (Fill), a probability (50 %) or a micro-timing (+1) on T5 /
# T6's step 1: they may carry their A notes (3,841): priced as carrying -- clamped, then B's T8 capped
_CERT = dict(a_emus={4: "SP12", 5: "SP12", 6: "OT", 7: "OT"},
             a_fx1={4: "DJEQ", 5: "DJEQ", 6: "NONE", 7: "NONE"},
             a_fx2={4: "DJEQ", 5: "DJEQ", 6: "NONE", 7: "NONE"},
             b_emus={4: "OT", 5: "OT", 6: "SP12", 7: "SP12"},
             b_fx1=ALL("DJEQ"), b_fx2=ALL("DARK"),
             a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs=ALL([1]))
CASES["cert_sure"] = dict(_CERT)
CASES["cert_fill"] = dict(_CERT, b_tw={4: 0x0001, 5: 0x0001})
CASES["cert_prob"] = dict(_CERT, b_tw={4: 0x0013, 5: 0x0013})
CASES["cert_micro"] = dict(_CERT, b_tw={4: 0x0080, 5: 0x0080})
# VEMG2, decision 4: a held VARI note into a Part where that track is not VARI keeps its VARI speed
# (and, when it fits, its engine) until its own next trig; the reverse -- a held non-VARI note
# (TSTR NORM) into a Part where it is VARI SP12 -- changes only at its own next trig too
CASES["nonvari_fit"] = dict(a_emus={4: "SP12", 5: "SP12", 6: "OT", 7: "OT"}, a_fx1=ALL("NONE"), a_fx2=ALL("NONE"),
                            b_emus=ALL("OT"), b_tstr=ALL(0), b_fx1=ALL("NONE"), b_fx2=ALL("NONE"),
                            a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs={4: [9], 5: [9], 6: [1], 7: [1]})
CASES["rev_vari"] = dict(a_emus=ALL("OT"), a_tstr={4: 2, 5: 2}, a_fx1=ALL("NONE"), a_fx2=ALL("NONE"),
                         b_emus={4: "SP12", 5: "SP12", 6: "OT", 7: "OT"}, b_fx1=ALL("NONE"), b_fx2=ALL("NONE"),
                         a_trigs={4: [1], 5: [3], 6: [5], 7: [7]}, b_trigs={4: [9], 5: [9], 6: [1], 7: [1]})
CASES["carry_sp12_s950"] = dict(CASES["carry_fit"], b_emus=ALL("S950"))
# the timing variants of own_step1: the cue late in the bar (just before / after the commit point,
# after it), PROGRAM CHANGE, a change length of 4, the transport stopped at the cue
# the cost runs (verb cost): steady (4 x SP12, no cue: the idle UI pass while the transport runs)
# and pending (the cue at frame 100: vgx_tick prices every pass until the commit at ~5111)
COST = {"cost_steady": dict(cue=-1, frames=6000), "cost_pending": dict(frames=6000)}
for tag, over in (("cue5100", dict(cue=5100, frames=11600)), ("cue5120", dict(cue=5120, frames=11600)),
                  ("cue5500", dict(cue=5500, frames=11600)), ("midipc", dict(cue=-1, midi=True)),
                  ("chg4", dict(chg=4)), ("stopped", dict(cue_pre=True))):
    CASES[f"own_step1_{tag}"] = dict(CASES["own_step1"], **over)
# nothing has to act here: byte-for-byte the base (FINAL) -- engines, increments, steps and toasts.
# VEMG2: the clamp acts only when the transition needs it, so the carry cases that fit are controls
# too; and the cases whose next Part is over on its own see the net act as FINAL does.
CONTROLS = ("ref_clean", "carry_fit_step1", "carry_fit", "carry_s950_ot", "carry_sp12_s950", "own_late78",
            "own_step1", "own_step1_cue5100", "own_step1_midipc", "own_step1_chg4",
            "cancel_mix_max", "change_mix_max", "cert_sure")
# (own_xbank is not one: FINAL drops every voice to plain OT 400 frames early there -- fix 3's case)
# nothing may be written: the Part blocks at the end byte-for-byte the base's
UNWRITTEN = ("cancel_mix_max", "change_mix_max", "cert_sure", "carry_fit", "mix_late")
# a held note must keep its speed (and its engine unless clamped) until its own next trig
HELD = {"mix_nonvari": (4, 5), "nonvari_fit": (4, 5), "rev_vari": (4, 5)}
# the clamp acts here (a carried engine above the next Part's): the audible change of VEM11
CLAMPED = ("own_late78", "carry_fit", "carry_s950_ot", "carry_sp12_s950", "mix_late", "mix_never", "mix_max",
           "mix_max_s2", "mix_nonvari")
# the A/B listening pack (at most 10, the author's rule): the clamp's cases, the pitch jump, two controls
PACK = ("mix_late", "mix_max", "mix_nonvari", "nonvari_fit", "cert_fill", "own_xbank", "rev_vari",
        "carry_fit", "cancel_mix_max", "ref_clean")
RENDER = 0x80004898                               # + 40t: the render state; +36 the increment


def trig_mask(pattern, t, steps):
    m = 0
    for s in steps:
        m |= 1 << (s - 1)
    a = MMDB + pattern * 0x8ed8 + t * 0x91a
    return [V.b(a + i, (m >> (8 * (7 - i))) & 0xff) for i in range(8)]


def part_cfg(part, emus, fx1, fx2, live, tstr=None):
    """(tstr: per track; 4 = VARI with emus, else that TSTR and no EMUS)"""
    pk = []
    for t in GT:
        ts = (tstr or {}).get(t, 4)
        pk += V.track_cfg(t, part, emus=emus[t] if ts == 4 else None, tstr=ts, live=live)
        pk += V.mm_byte(V.O_MACH + t, V.ST, part)
    for t in GT:
        for off, n in ((t, fx1[t]), (8 + t, fx2[t])):
            pk += V.mm_byte(off, V.FXID[n], part)
            if live:
                pk.append(V.b((0x80000ec4 if off < 8 else 0x80000ecc) + t, V.FXID[n]))
    return pk


def watches(syms):
    S = syms["syms"]
    mem = [(0x80000003, 1), (0x80001828, 2), (0x800065bd, 4), (0x46104d10, 4)]
    mem += [(S[k], n) for k, n in (("vg_toast", 1), ("vg_last", 4)) if k in S]
    mem += [
           (V.mmpart(1) + V.O_P2 + 30 * 4, 120), (V.mmpart(0) + V.O_P2 + 30 * 4, 120),
           (0x80000ec8, 4), (0x80000ed0, 4), (0x800000e0, 1)]
    mem += [(RENDER + 40 * t + 36, 4) for t in GT]
    pcs = [0x4005a2b8] + [S[k] for k in ("vg_fix", "vg_step_ot") if k in S] + \
        [0x400621e2, 0x40009e00, 0x400a44d0, 0x40009094]
    if "vgx_step" in S:
        pcs.append(S["vgx_step"])
    if ".xt_commit" in S:
        pcs.append(S[".xt_commit"])
    return mem, pcs


def run_case(name, img, audio=False):
    if name in COST:
        c = dict(CASES["own_step1"], **COST[name])
    else:
        c = dict(CASES[name])
    image, symsf = IMGS[img]
    syms = json.loads(symsf.read_text())
    d = OUT / img / name
    d.mkdir(parents=True, exist_ok=True)
    pk = part_cfg(0, c["a_emus"], c["a_fx1"], c["a_fx2"], live=True, tstr=c.get("a_tstr"))
    pb = part_cfg(1, c["b_emus"], c["b_fx1"], c["b_fx2"], live=False, tstr=c.get("b_tstr"))
    pb += [V.b(MMDB + 1 * 0x8ed8 + 0x8e57, 1)]          # pattern 1 uses Part 1
    for t in GT:
        pk += trig_mask(0, t, c["a_trigs"][t])
        pb += trig_mask(1, t, c["b_trigs"][t])
    for t, w in c.get("b_tw", {}).items():             # B's step-1 trig word (condition / micro-timing)
        a = MMDB + 1 * 0x8ed8 + int(t) * 0x91a + 0x89a
        pb += [V.b(a, w >> 8), V.b(a + 1, w & 0xff)]
    if c.get("recue"):
        pk += [V.b(MMDB + 2 * 0x8ed8 + 0x8e57, 0)]       # pattern 2 uses Part 0 (the playing one)
    xb = c.get("b_bank", 0)
    if xb:                                              # B in another bank's blob (DB only: the SRAM
        out = []                                        #   copy is the working bank's)
        for x in pb:
            a, v = x.split("=")
            a = int(a, 16)
            if MMDB <= a < MMDB + 0x9b340:
                out.append(V.b(a + xb * 0x9b340, int(v, 16)))
        pb = out
    pk += pb
    if c.get("midi"):
        pk += [V.b(0x8000002b, 1), V.b(0x8000002d, 0)]    # PROG CH RECEIVE on, channel 1
    if c.get("chg") is not None:
        pk += [V.b(MMDB + 0 * 0x8ed8 + 0x8e56, c["chg"])]
    frames = c.get("frames", 9000)
    steps = ["-:poke:" + ";".join(pk)]
    cue = c.get("cue", 100)
    if c.get("cue_pre"):
        steps.append("-:call:0x400a1030,0x0,0x1")
    elif cue >= 0:
        steps.append(V.call(cue, 0x400a1030, xb, 1))
    if c.get("recue"):
        f, bk, pt = c["recue"]
        steps.append(V.call(f, 0x400a1030, bk, pt))
    steps.append(f"{frames - 30}:dump:{V.mmpart(1):#x},{V.PSTRIDE:#x}={d / 'end_p1.part'};"
                 f"{V.mmpart(0):#x},{V.PSTRIDE:#x}={d / 'end_p0.part'}")
    mem, pcs = watches(syms)
    cmd = [os.environ["VEM_EMU"], "--image", str(image), "--card", str(CARD),
           "--set", V.MM["set"], "--project", V.MM["project"], "--load-ms", "20000", "--dsp", "--main-level", "64",
           "--sequencer", "--internal-clock", "--frames", str(frames),
           "--dsp-stopwatch", "0:372:53e",
           "--watch-mem", ";".join(f"{x:#x},{n}" for x, n in mem),
           "--watch-pc", ",".join(f"{x:#x}" for x in pcs)]
    if c.get("midi"):
        MIDI_PC.parent.mkdir(parents=True, exist_ok=True)
        MIDI_PC.write_text("100 C0 01\n")
        cmd += ["--midi", str(MIDI_PC)]
    if audio:
        cmd += ["--audio-out", str(d / "audio")]
    if name in COST:
        cmd += ["--coverage", str(d / "cov.txt")]
    for st in steps:
        cmd += ["--step", st]
    env = dict(os.environ, OT_VEM_LOG=str(d / "vem.log"), OT_SW_OUT=str(d / "sw.txt"), OT_SW_EXTRA="1:17a:333")
    (d / "cmd.json").write_text(json.dumps(dict(cmd=cmd, case=c, img=str(image), syms=str(symsf)), indent=1))
    with open(d / "log.txt", "w") as f:
        r = subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=4 * 3600)
    return f"{img}/{name} rc {r.returncode}"


# ---------------------------------------------------------------------------------- analysis
VG = V.vg_constants()
FXPRICE = {i: V.fx_price(n) for n, i in V.FXID.items()}
ENGP = [0, VG["VG_S950"], VG["VG_SP12"], VG["VG_S950"]]
BASE0, BUD0 = VG["VG_BASE_C0"] + VG["VG_SC"], VG["VG_BUDGET_C0"]
ENG_N = {0: "OT", 1: "S9", 2: "SP", 3: "S9"}
MW = re.compile(r"\[\s*([\d.]+)\] \[(0x[0-9a-f]+)\] <- (0x[0-9a-f]+|0) \((\d)\) at pc (0x[0-9a-f]+) in (\S+)\s+i=(\d+)")
PW = re.compile(r"\[\s*(\d+)\] at (0x[0-9a-f]+) d0=(\S+) d1=(\S+)")


def analyze(d):
    d = pathlib.Path(d)
    meta = json.loads((d / "cmd.json").read_text())
    syms = json.loads(pathlib.Path(meta["syms"]).read_text())["syms"]
    case = meta["case"]
    log = (d / "log.txt").read_text(errors="replace")
    mw = [(float(m[1]), int(m[2], 16), int(m[3], 16), int(m[4]), int(m[5], 16), m[6], int(m[7]))
          for m in MW.finditer(log)]
    pcs = []
    sec = log.split("watch-pc   :")[-1] if "hit(s)" in log else ""
    for m in PW.finditer(sec):
        pcs.append((int(m[1]), int(m[2], 16), int(m[3], 16), int(m[4], 16)))
    frames = [w[0] for w in mw if w[1] == 0x800000e0]
    instr = sorted((w[6], w[0]) for w in mw)
    ins_i = [x[0] for x in instr]

    def cf_frame(sample):
        return bisect.bisect_right(frames, sample) - 1

    def pc_sample(i):
        k = min(max(bisect.bisect_left(ins_i, i), 0), len(instr) - 1)
        return instr[k][1]

    trigs = {t: [] for t in GT}      # CF frames of each track's trigs (TRIGB bit 4)
    ev = []                          # (cf frame, sample, kind, data)
    inc = {t: [] for t in GT}        # (cf frame, increment) on every change
    fxc = []
    fx_state = {}
    for s, ad, val, sz, pc, task, i in mw:
        f = cf_frame(s)
        if ad == 0x80000003:
            ev.append((f, s, "PART_B", val))
        elif ad == 0x80001828:
            ev.append((f, s, "APPLIED", val))
        elif 0x46104d10 <= ad <= 0x46104d13 and val & 0x10:
            trigs[ad - 0x46104d0c].append(f)
        elif ad == syms.get("vg_toast") and val:
            ev.append((f, s, "vg_toast", val))
        elif 0x80000ec8 <= ad <= 0x80000ed3:
            for j in range(sz):
                aa = ad + j
                vv = (val >> (8 * (sz - 1 - j))) & 0xff
                key = ("FX1" if aa < 0x80000ecc else "FX2", (aa - 0x80000ec4) % 8)
                if fx_state.get(key) != vv:
                    fx_state[key] = vv
                    fxc.append((f, key, vv))
        elif any(ad == RENDER + 40 * t + 36 for t in GT):
            t = (ad - RENDER - 36) // 40
            if not inc[t] or inc[t][-1][1] != val:
                inc[t].append((f, val))
    names = {0x4005a2b8: "NOTIFY", 0x400621e2: "msg20", 0x40009e00: "light_apply", 0x400a44d0: "commit",
             0x40009094: "heavy_apply"}
    names.update({syms[k]: k for k in ("vg_fix", "vg_step_ot") if k in syms})
    if "vgx_step" in syms:
        names[syms["vgx_step"]] = "vgx_step"
    if ".xt_commit" in syms:
        names[syms[".xt_commit"]] = "vgx_commit"
    for i, pc, d0, d1 in pcs:
        s = pc_sample(i)
        ev.append((cf_frame(s), s, names.get(pc, hex(pc)), (d0, d1)))
    ev.sort(key=lambda x: x[1])
    # DSP core 0, per frame: the engine each T5-T8 voice runs, the trig, datasheet cycles/sample
    sw = {0: [], 1: []}
    for line in (d / "sw.txt").read_text().split("\n"):
        f = line.split()
        if len(f) == 4:
            sw[int(f[0])].append((int(f[1]), int(f[2]), int(f[3])))
    stops = [x[2] for x in sw[0]]
    per = {}
    for line in open(d / "vem.log"):
        f = line.split()
        if len(f) < 8 or f[0] != "0":
            continue
        ex, x418, lc, y40, rec = int(f[1]), int(f[2], 16), int(f[3], 16), int(f[5], 16), int(f[7], 16)
        k = bisect.bisect_left(stops, ex)
        if k >= len(sw[0]):
            continue
        t = 4 + x418 // 0x20
        e = per.setdefault(k, {})
        if lc == 1:
            e[t] = (y40 & 3, (rec >> 12) & 1 or e.get(t, (0, 0))[1])
        else:
            e.setdefault(t, (None, (rec >> 12) & 1))
    # DSP frame k <-> CF frame f: the offset from the first trig after the transport start
    cf_tr = sorted((f, (a - 0x46104d0c)) for s, a, v, sz, pc, task, i in mw
                   if 0x46104d10 <= a <= 0x46104d13 and v & 0x10 for f in [cf_frame(s)] if f >= 0)
    dsp_tr = sorted((k, t) for k, e in per.items() for t, (en, tr) in e.items() if tr)
    off = 0
    if cf_tr and dsp_tr:
        f0, t0 = cf_tr[0]
        cand = [k for k, t in dsp_tr if t == t0 and k >= f0]
        off = (cand[0] - f0) if cand else 0
    a_fx1, a_fx2 = case["a_fx1"], case["a_fx2"]
    g = lambda dct, t: dct[str(t)] if str(t) in dct else dct[t]
    init = [(-1, ("FX1", t), V.FXID[g(a_fx1, t)]) for t in GT] + [(-1, ("FX2", t), V.FXID[g(a_fx2, t)]) for t in GT]
    chg = sorted(init + [(f + off, k, v) for f, k, v in fxc if f >= 0])
    rows, cur, ci = [], {}, 0
    for k in range(len(sw[0])):
        while ci < len(chg) and chg[ci][0] <= k:
            cur[chg[ci][1]] = chg[ci][2]
            ci += 1
        e = per.get(k, {})
        fxs = sum(FXPRICE.get(cur.get((b, t), 0), 0) for b in ("FX1", "FX2") for t in GT)
        eng = {t: (e.get(t, (0, 0))[0] or 0) for t in GT}
        est = BASE0 + fxs + sum(ENGP[x] for x in eng.values())
        trig = [t + 1 for t in GT if e.get(t, (0, 0))[1]]
        rows.append(dict(k=k, f=k - off, cyc=sw[0][k][1] / 16, ins=sw[0][k][0] / 16, eng=eng, est=est,
                         trig=trig, fx=fxs))
    return dict(ev=ev, rows=rows, off=off, inc=inc, case=case, name=d.name, img=d.parent.name, trigs=trigs)


def summary(a):
    rows = [r for r in a["rows"] if r["f"] >= 0]
    over = [r for r in rows if r["est"] > BUD0]
    applies = [f for f, s, k, v in a["ev"] if k == "APPLIED"]
    steps = [(f, k) for f, s, k, v in a["ev"] if k in ("vg_step_ot", "vgx_step")]
    toasts = [f for f, s, k, v in a["ev"] if k == "NOTIFY"]
    commits = [f for f, s, k, v in a["ev"] if k == "vgx_commit"]
    # the cycles after the first DSP frame of a steady second (skip the boundary frame's own spike)
    return dict(est_max=max((r["est"] for r in rows), default=0),
                cyc_max=max((r["cyc"] for r in rows), default=0),
                over=len(over), over_ms=len(over) * 16 / 44.1,
                over_cyc_max=max((r["cyc"] for r in over), default=0),
                applies=applies, steps=steps, toasts=toasts, commits=commits)


def engine_changes(a, t, lo=0):
    """CF frames where track t's running engine (DSP) or increment (CF render state) changes"""
    out = []
    prev = None
    for r in a["rows"]:
        if r["f"] < lo:
            continue
        e = r["eng"][t]
        if prev is not None and e != prev:
            out.append(("engine", r["f"], ENG_N[prev], ENG_N[e]))
        prev = e
    pv = None
    for f, v in a["inc"][t]:
        if f < lo:
            pv = v
            continue
        if pv is not None and v != pv:
            out.append(("increment", f, hex(pv), hex(v)))
        pv = v
    return sorted(out, key=lambda x: x[1])


def timeline(run):
    a = analyze(run)
    print(f"run {a['img']}/{a['name']}: DSP frame = CF frame + {a['off']}; model base {BASE0} budget {BUD0}")
    for f, s, k, v in a["ev"]:
        print(f"  f{f:6d} s{s:12.1f}  {k} {v if not isinstance(v, int) else hex(v)}")
    prev = None
    for r in a["rows"]:
        key = (tuple(r["eng"].values()), r["fx"], tuple(r["trig"]))
        if key != prev:
            print(f"  k{r['k']:6d} (f{r['f']:6d}) eng {' '.join(ENG_N[r['eng'][t]] for t in GT)} fx {r['fx']:4d} "
                  f"est {r['est']:5d}{' OVER' if r['est'] > BUD0 else '     '} cyc/smp {r['cyc']:7.1f} trig {r['trig']}")
        prev = key
    for t in GT:
        for c in engine_changes(a, t):
            print(f"  T{t + 1} {c}")
    print(summary(a))


def cost(imgs):
    """ColdFire cost from ot_emu --coverage (instructions per PC over the whole run): the UI loop's
    pass (vg_tick + vg_sig + vgx_tick's tests, per vg_tick entry) idle and while a switch is on its
    way (vgx_fix .. per pricing pass), and the frame hook's body (vem_frame .. voice_set) per frame."""
    rows = []
    for img in imgs:
        sy = json.loads(IMGS[img][1].read_text())
        g = {k: v for k, v in sy["syms"].items() if not k.startswith(".")}
        nxt = lambda a: min(v for v in g.values() if v > a)
        for c in COST:
            d = OUT / img / c
            if not (d / "cov.txt").exists():
                continue
            cov = [(int(a, 16), int(n)) for a, n in (l.split() for l in open(d / "cov.txt"))]
            cnt = dict(cov)
            log = (d / "log.txt").read_text()
            n = int(re.search(r"frames run : (\d+)", log).group(1))
            rng = lambda lo, hi: sum(k for a, k in cov if lo <= a < hi)
            ticks = cnt.get(g["vg_tick"], 0) if "vg_tick" in g else 0
            tail = rng(g["vg_tick"], nxt(g["vg_tick"])) + rng(g["vg_sig"], nxt(g["vg_sig"])) if ticks else 0
            idle = pend = npend = 0
            if "vgx_tick" in g:
                idle = rng(g["vgx_tick"], g["vgx_clear"])          # vgx_tick's own code
                npend = cnt.get(g["vgx_price"], 0)
                # the pricing's own code (rp_gate_a lands in rp_gate_m's body in the cave, shared
                # with the frame path: not counted here)
                pend = rng(g["vgx_clear"], nxt(g["vgx_step"]))
            frame = rng(g["vem_frame"], g["voice_set"])
            rows.append((img, c, n, ticks, tail / ticks if ticks else 0, idle / ticks if ticks else 0,
                         npend, pend / npend if npend else 0, frame / n, rng(sy["cave"], sy["end"]) / n,
                         sum(k for a, k in cov) / n))
    print(f"{'image':10s} {'scenario':13s} {'frames':>6s} {'UI passes':>9s} {'tick+sig/pass':>13s} "
          f"{'vgx tests/pass':>14s} {'pricings':>8s} {'vgx/pricing':>11s} {'vem_frame/fr':>12s} {'unit/fr':>8s} {'allCF/fr':>9s}")
    for r in rows:
        print(f"{r[0]:10s} {r[1]:13s} {r[2]:6d} {r[3]:9d} {r[4]:13.1f} {r[5]:14.1f} {r[6]:8d} {r[7]:11.1f} "
              f"{r[8]:12.1f} {r[9]:8.1f} {r[10]:9.1f}")


# ------------------------------------------------------------------------------------- gates
def check(imgs):
    res, fails = {}, []
    for img in imgs:
        for name in CASES:
            d = OUT / img / name
            if (d / "sw.txt").exists():
                res[(img, name)] = analyze(d)
    print(f"{'image':13s} {'case':22s} {'est max':>8s} {'over':>5s} {'cyc max':>8s} {'steps':>18s} toasts")
    for (img, name), a in sorted(res.items()):
        s = summary(a)
        st = ",".join(f"{k[:4]}@{f}" for f, k in s["steps"]) or "-"
        print(f"{img:13s} {name:22s} {s['est_max']:8d} {s['over']:5d} {s['cyc_max']:8.1f} {st[:18]:>18s} "
              f"{','.join(map(str, s['toasts'])) or '-'}")
    for img in imgs:
        if img.startswith("base"):
            continue
        base = "base_" + img
        for name in CASES:
            a = res.get((img, name))
            if a is None:
                fails.append(f"{img}/{name}: not run")
                continue
            s = summary(a)
            if s["over"]:
                fails.append(f"{img}/{name}: {s['over']} frame(s) over budget, est max {s['est_max']}")
            # a step comes with its toast (the same UI pass: within a frame or two)
            for f, k in s["steps"]:
                if not any(0 <= tf - f <= 2 for tf in s["toasts"]):
                    fails.append(f"{img}/{name}: step {k} at f{f} without a toast")
            for tf in s["toasts"]:
                if not any(0 <= tf - f <= 2 for f in [f for f, k in s["steps"]] + s["commits"]):
                    fails.append(f"{img}/{name}: toast at f{tf} without a step or a commit")
            # VEMG2: nothing reaches a Part before its switch -- a step comes after the apply
            # (vgx_step at the commit) or from the net once PART_B has moved
            ap = [f for f in s["applies"] if f > 0]
            pbm = [f for f, s_, k, v in a["ev"] if k == "PART_B" and f > 0]
            for f, k in s["steps"]:
                if k == "vgx_step" and not (ap and f >= ap[0]):
                    fails.append(f"{img}/{name}: vgx_step at f{f}, before the switch")
                if k == "vg_step_ot" and f >= 0 and not (pbm and f >= pbm[0]):
                    fails.append(f"{img}/{name}: a step at f{f}, before PART_B's move")
            if name == "mix_nonvari":
                ap = [f for f in s["applies"] if f > 0]
                sw = ap[0] if ap else None
                # from 50 frames before PART_B's move (message 20): A's own trigs are long over
                pb = [f for f, s_, k, v in a["ev"] if k == "PART_B" and f > 0]
                lo = (pb[0] - 50) if pb else 0
                for t in (4, 5):
                    early = [c for c in engine_changes(a, t, lo=lo) if sw is None or c[1] < sw]
                    if early:
                        fails.append(f"{img}/{name}: T{t + 1} changes before the switch frame f{sw}: {early}")
            if name in HELD:
                for t in HELD[name]:
                    own = [f for f in a["trigs"][t] if ap and f > ap[0]]
                    hi = own[0] if own else 10 ** 9
                    lo = (pbm[0] - 50) if pbm else 0
                    for c in engine_changes(a, t, lo=lo):
                        if c[1] >= hi:
                            continue
                        if c[0] == "increment" and (int(c[2], 16) & ~0xf) != (int(c[3], 16) & ~0xf):
                            fails.append(f"{img}/{name}: T{t + 1}'s speed changes at f{c[1]}, before its own "
                                         f"trig f{hi}: {c}")
                        elif c[0] == "engine" and not (ap and c[1] == ap[0] and c[3] == "OT"):
                            fails.append(f"{img}/{name}: T{t + 1}'s engine changes at f{c[1]} (not a clamp "
                                         f"on the switch frame), before its own trig f{hi}: {c}")
            b = res.get((base, name))
            if name in UNWRITTEN and b is not None:
                for part in ("end_p0.part", "end_p1.part"):
                    if (OUT / img / name / part).read_bytes() != (OUT / base / name / part).read_bytes():
                        fails.append(f"{img}/{name}: {part} differs from {base}'s (something was written)")
            if name in CONTROLS and b is not None:
                sb = summary(b)
                # the same steps and toasts; their CF frame within 2 (the ColdFire load differs, so a
                # UI-task event can fall a frame either side of the frame-ISR edge)
                near = lambda x, y: len(x) == len(y) and all(abs(i - j) <= 2 for i, j in zip(x, y))
                if not (near([f for f, k in s["steps"]], [f for f, k in sb["steps"]])
                        and [k for f, k in s["steps"]] == [k for f, k in sb["steps"]]
                        and near(s["toasts"], sb["toasts"])):
                    fails.append(f"{img}/{name}: steps / toasts {s['steps']} {s['toasts']} differ from "
                                 f"{base}'s {sb['steps']} {sb['toasts']}")
                ea = [tuple(r["eng"].values()) for r in a["rows"]]
                eb = [tuple(r["eng"].values()) for r in b["rows"]]
                n = min(len(ea), len(eb))
                if ea[:n] != eb[:n]:
                    k = next(i for i in range(n) if ea[i] != eb[i])
                    fails.append(f"{img}/{name}: engines differ from {base} at DSP frame {k}")
                for t in GT:
                    if [v for f, v in a["inc"][t]] != [v for f, v in b["inc"][t]]:
                        fails.append(f"{img}/{name}: T{t + 1}'s increments differ from {base}")
    print()
    for f in fails:
        print("FAIL", f)
    print(f"\n{'ALL GATES PASS' if not fails else f'{len(fails)} gate failure(s)'}")
    return not fails


# ------------------------------------------------------------------------------- A/B pack
LISTEN = {
    "mix_late": "Each Part fits, the mix does not (A: 3,681 for 1 s). T5 / T6 hold SP12 notes into a Part that has "
                "them on OT: B clamps the two held notes to OT on the switch (temporary; the toast); the Part is "
                "not changed. A keeps them on SP12 until their step-9 trigs.",
    "mix_max": "The worst mix (A: 4,001 for 1 s). B clamps the held T5 / T6 SP12 notes to OT on the switch and, "
               "since that is not enough, plays Part B's T7 / T8 on OT (committed to the Part at the switch, toast).",
    "mix_nonvari": "Part B has no VARI track. A: T5 / T6 leave VARI (speed and engine) 145 ms BEFORE the switch. "
                   "B: they keep their VARI speed to their own step-9 trig; their engine is clamped to OT on the "
                   "switch (the mix needs it).",
    "nonvari_fit": "As mix_nonvari without FX (it fits). A: T5 / T6 leave VARI 145 ms before the switch. B: speed "
                   "and engine kept to their step-9 trigs.",
    "cert_fill": "Part B fits alone; its T5 / T6 step-1 trigs carry a Fill condition (they do not fire), so A's "
                 "T5 / T6 SP12 + DJ EQ x2 notes play on into B (A: 3,841, over). B: those notes clamped to OT on "
                 "the switch and B's T8 on OT (toast).",
    "own_xbank": "A cue into another bank. A: every T5-T8 voice drops to plain OT 400 frames before the switch. "
                 "B: they play on to the switch.",
    "rev_vari": "The reverse case: T5 / T6 hold NORM notes into a Part that has them on VARI SP12: both keep the "
                "held notes as they are until the step-9 trigs (expected identical).",
    "carry_fit": "Control (VEMG1 changed it): held SP12 notes into a Part that has them on OT; the mix fits: "
                 "A and B identical (SP12 to step 9).",
    "cancel_mix_max": "Control: mix_max cued, then cancelled before the switch: nothing written, A and B identical.",
    "ref_clean": "Control, no Part switch: A and B identical.",
}


# the plain VARISPEED pack (VARIG1): A = FINAL VARISPEED, B = the port
PLAIN_PACK = ("mix_nonvari", "nonvari_fit", "rev_vari", "own_xbank", "carry_fit", "ref_clean")
PLAIN_LISTEN = {
    "mix_nonvari": "Part B has T5 / T6 off VARI. A: T5's held VARI note changes speed 145 ms BEFORE the switch "
                   "(T7 too). B: T5 keeps its VARI speed to its own step-9 trig; T7 changes at its own trig, on "
                   "the switch.",
    "nonvari_fit": "As mix_nonvari without FX: A changes T5's speed 145 ms before the switch, B at its step-9 trig.",
    "rev_vari": "The reverse: T5 / T6 hold NORM notes into a Part that has them on VARI: both change at the "
                "step-9 trig (identical).",
    "own_xbank": "A cue into another bank. A: T5 / T7 drop to stock speed 400 frames before the switch and come "
                 "back 7 frames later (a glitch). B: nothing changes before the switch.",
    "carry_fit": "Control: held VARI notes into a Part where they are VARI too: identical.",
    "ref_clean": "Control, no Part switch: identical.",
}


def pack(dest, plain=False):
    """The A/B listening pack: A = the FINAL feature image (base_feature), B = VEM11 (feature), each case's
    main out (core 0 TX slots 2 / 3, T5-T8) from 1.0 s before the switch (2.0 s after the transport start)
    to the end of the render; 24-bit stereo WAVs, 44.1 kHz, and a manifest."""
    import struct, wave
    sys.path.insert(0, str(ROOT / "out"))
    dest = pathlib.Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    man = []
    names = PLAIN_PACK if plain else PACK
    imgs = (("A_final", "base_vari_feature"), ("B_vemg2", "vari_feature")) if plain else \
        (("A_final", "base_feature"), ("B_vemg2", "feature"))
    btag = "B_vrg1" if plain else "B_vemg2"
    listen = PLAIN_LISTEN if plain else LISTEN
    for i, name in enumerate(names, 1):
        clips = {}
        for tag, img in imgs:
            d = OUT / img / name
            w = wave.open(str(d / "audio_core0.wav"))
            n, ch, sw = w.getnframes(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(n)
            log = (d / "log.txt").read_text()
            # (the log's earlier audio lines are other DSP sessions' summaries, at frame 0)
            st = max(int(x) for x in re.findall(r"transport start at ESAI frame (\d+) out", log))
            lo = st + (int(0.2 * 44100) if name == "ref_clean" else int(1.0 * 44100))
            fr = bytearray()
            for k in range(lo, n):
                o = (k * ch) * sw
                fr += raw[o + 2 * sw:o + 3 * sw] + raw[o + 3 * sw:o + 4 * sw]
            clips[tag] = bytes(fr)
        # the two loads end a few samples apart: align B on A, each channel by the lag (whole samples)
        # that makes its first 0.5 s identical (before the switch nothing differs), if one does (the
        # emulator's TX slots can also rotate by a sample between two runs, so L and R may differ)
        A, Bc = clips["A_final"], clips["B_vemg2"]
        ch = lambda x, c: b"".join(x[k + 3 * c:k + 3 * c + 3] for k in range(0, len(x) - 5, 6))
        lags, outs = [], []
        for c in (0, 1):
            ac, bc = ch(A, c), ch(Bc, c)
            lag = 0
            for g in sorted(range(-32, 33), key=abs):
                sa, sb = (0, g) if g >= 0 else (-g, 0)
                if ac[3 * sa:3 * (sa + 22050)] == bc[3 * sb:3 * (sb + 22050)]:
                    lag = g
                    break
            else:
                print(f"  {name} ch {c}: no lag in -32..32 makes the first 0.5 s identical -- unaligned")
            sa, sb = (0, lag) if lag >= 0 else (-lag, 0)
            lags.append(lag)
            outs.append((ac[3 * sa:], bc[3 * sb:]))
        L = min(len(x) for pr in outs for x in pr) // 3
        inter = lambda i: b"".join(outs[0][i][3 * k:3 * k + 3] + outs[1][i][3 * k:3 * k + 3] for k in range(L))
        a, b = inter(0), inter(1)
        L = len(a)
        lag = lags
        first = next((k // 6 for k in range(0, L, 3) if a[k:k + 3] != b[k:k + 3]), None)
        files = {}
        for tag, data in (("A_final", a), ("B_vemg2", b)):
            f = dest / f"{i:02d}_{name}_{btag if tag == 'B_vemg2' else tag}.wav"
            with wave.open(str(f), "wb") as o:
                o.setnchannels(2)
                o.setsampwidth(3)
                o.setframerate(44100)
                o.writeframes(data)
            files[tag] = f.name
        man.append(dict(n=i, case=name, listen=listen[name], A=files["A_final"], B=files["B_vemg2"],
                        switch_at_s=None if name == "ref_clean" else 1.0,
                        first_difference_s=None if first is None else round(first / 44100, 4), lag=lag,
                        seconds=round(L / 6 / 44100, 3)))
    (dest / "manifest.json").write_text(json.dumps(man, indent=1))
    md = ([f"# VARISPEED VRG1 A/B pack (emulator renders, ot_emu --audio-out)", "",
           "A = the promoted FINAL VARISPEED feature image (mainos c3af514f...), B = VRG1 (the port: a held VARI "
           "note keeps its speed through a Part switch until its own next trig). "] if plain else
          ["# VARISPEED_EMUS VEMG2 A/B pack (emulator renders, ot_emu --audio-out)", "",
           "A = the promoted FINAL VARISPEED_EMUS feature image (mainos 52823ea6...), B = VEMG2 (the WIP fix). "])
    md[-1] += (
          "MMTESTDT (a hardware export), T5-T8 on DSP core 0, set by runtime pokes "
          "(tools/varispeed_emus_switch_test.py). Each clip is the main out, from 1.0 s before the Part switch "
          "(ref_clean: no switch) to the end of the render. 24-bit stereo, 44.1 kHz. B is aligned on A to the "
          "sample (the two emulated loads end a few samples apart); before what changes, A and B are "
          "bit-identical.")
    md += [""]
    for m in man:
        md += [f"## {m['n']:02d} {m['case']}", "", m["listen"], "",
               f"- A: `{m['A']}`  B: `{m['B']}`  ({m['seconds']} s; switch at {m['switch_at_s']} s)",
               f"- first sample where A and B differ: "
               + ("none (identical)" if m["first_difference_s"] is None else f"{m['first_difference_s']} s"), ""]
    (dest / "MANIFEST.md").write_text("\n".join(md))
    for m in man:
        print(f"{m['n']:02d} {m['case']:18s} first difference "
              f"{'none' if m['first_difference_s'] is None else str(m['first_difference_s']) + ' s'}")


def check_plain(imgs):
    """VARISPEED (plain): a held VARI note keeps its speed until its own next trig (and the reverse);
    nothing changes before a cross-bank switch; elsewhere the increments are FINAL's."""
    fails = []
    for img in imgs:
        base = "base_" + img
        for name in sorted(set(PLAIN_HELD) | set(PLAIN_EARLY) | set(PLAIN_SAME)):
            d = OUT / img / name
            if not (d / "sw.txt").exists():
                fails.append(f"{img}/{name}: not run")
                continue
            a = analyze(d)
            ap = [f for f, s_, k, v in a["ev"] if k == "APPLIED" and f > 0]
            pbm = [f for f, s_, k, v in a["ev"] if k == "PART_B" and f > 0]
            lo = (pbm[0] - 50) if pbm else 0
            spd = lambda c: c[0] == "increment" and (int(c[2], 16) & ~0xf) != (int(c[3], 16) & ~0xf)
            note = []
            if name in PLAIN_HELD:
                for t in PLAIN_HELD[name]:
                    own = [f for f in a["trigs"][t] if ap and f > ap[0]]
                    hi = own[0] if own else 10 ** 9
                    bad = [c for c in engine_changes(a, t, lo=lo) if c[1] < hi and spd(c)]
                    note.append(f"T{t + 1} speed changes {[c[1] for c in engine_changes(a, t, lo=lo) if spd(c)]} "
                                f"own trig f{hi}")
                    if bad:
                        fails.append(f"{img}/{name}: T{t + 1}'s speed changes before its own trig f{hi}: {bad}")
            if name in PLAIN_EARLY:
                for t in GT:
                    bad = [c for c in engine_changes(a, t, lo=lo) if spd(c) and ap and c[1] < ap[0]]
                    if bad:
                        fails.append(f"{img}/{name}: T{t + 1} changes before the switch f{ap[0]}: {bad}")
            if name in PLAIN_SAME and (OUT / base / name / "sw.txt").exists():
                b = analyze(OUT / base / name)
                for t in GT:
                    if [v for f, v in a["inc"][t]] != [v for f, v in b["inc"][t]]:
                        fails.append(f"{img}/{name}: T{t + 1}'s increments differ from {base}")
            first = {t: next((hex(v) for f, v in a["inc"][t] if f >= 0), None) for t in GT}
            print(f"{img:13s} {name:18s} switch f{ap[0] if ap else '-'}  first incs {first}  {'; '.join(note)}")
    for f in fails:
        print("FAIL", f)
    print(f"\n{'ALL PLAIN GATES PASS' if not fails else f'{len(fails)} gate failure(s)'}")
    return not fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("verb", choices=("run", "check", "timeline", "cost", "pack"))
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--img", action="append", default=[])
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--audio", action="store_true")
    ap.add_argument("--plain", action="store_true", help="check: VARISPEED's gates (check_plain)")
    a = ap.parse_args()
    imgs = a.img or ["unit", "feature"]
    names = [n for n in list(CASES) + list(COST) if (not a.only and n in CASES) or n in a.only.split(",")]
    if a.verb == "cost":
        return cost(imgs)
    if a.verb == "timeline":
        return timeline(a.arg)
    if a.verb == "pack":
        return pack(a.arg or ROOT / ("out/ab_vari_port" if a.plain else "out/ab_emus_guard2"), plain=a.plain)
    if a.verb == "run":
        jobs = [(n, i) for i in imgs for n in names]
        with ThreadPoolExecutor(a.jobs) as ex:
            for r in ex.map(lambda j: run_case(j[0], j[1], a.audio), jobs):
                print(r, flush=True)
        return
    sys.exit(0 if (check_plain(imgs) if a.plain else check(imgs)) else 1)


if __name__ == "__main__":
    main()
