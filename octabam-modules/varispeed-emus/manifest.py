# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""VARISPEED_EMUS -- tempo-locked varispeed for STATIC and FLEX, with sampler emulations.

    TSTR    OFF AUTO NORM BEAT VARI (STATIC / FLEX; PICKUP keeps its own)
    VARI    the track plays dry at (project BPM x p) / (sample BPM x q), exact in
            integers; p/q is the QUAN ratio, RATE still applies. AUTO plays a sample
            whose TIMESTRETCH (audio editor, ATTR) is VARI the same way.
    QUAN    the PTCH knob on a VARI track: 1/2 2/3 3/4 4/5 1/1 5/4 4/3 3/2 2/1
    EMUS    the TSNS knob on a VARI track: OT / S950 / SP12 (left to right, four detents
            per step), the engine the DSP kernel renders the track with, taken at each trig
    GUARD   a DSP load estimate per core from the SETTINGS (base + the Part's FX types + the
            engines of its VARI tracks' EMUS); a change that would put a core over its
            budget is refused (EMUS stops at the highest engine that fits; an FX type does
            not land when emulated engines tip the core); a safety net, run in the UI task
            when a signature of those settings changes, sets just enough EMUS to OT however
            a core got over (SP12 first, then S950, highest track first) -- but a TSTR or
            ATTR TIMESTRETCH edit that puts a track on VARI over budget sets THAT track's
            EMUS to OT; each shows MAX DSP: EMU LIMIT (1.2 s). Nothing steps down at run
            time; EMUS shows what plays

COLDFIRE. One unit, vem_cf (varispeed_emus.s, its default VEM_EMUS = 1; the same source
with VEM_EMUS = 0 is the plain VARISPEED module, octabam-modules/varispeed/), the standalone
builder's own (tools/build_varispeed_emus.py). 22 detours: the render's increment store (the frame hook),
P2EDIT's delta conversion (EMUS steps), SRC SETUP's open (the EMUS detent count restarts),
five in the audio editor's ATTR page, the four
SETUP-page dial resolvers, the two Part applies, RELOAD PART, and hold wrappers on the
bulk writers (SRC page paste, track paste, the PART menu's paste core and CLEAR); the
guard's: the UI task's message-loop tail (its safety net and its toast) and the FX1 / FX2
choosers' YES. The
STATIC and FLEX descriptors: TSTR count 4 -> 5 with stock's 5-position select and this
unit's formatter; PTCH's widget and encoder step; TSNS's widget. The domain swap keeps
PTCH / TSNS of each machine in NEIGHBOR's '---' bytes of the same track (claimed below).

DSP. The S950 / SP12 kernel (rpk_dsp.asm, a copy of the hardware-proven one), two hooks:
zqrp at the voice kernel's prologue (A P:0x40b, B P:0x20e), zqboot at each payload's
one-time memory clear (A P:0x46, B P:0x47; their `do` words differ). Two table blocks
(81 + 384 words). Core-private Y $A00-$FFF. It needs a given-up effect for its words, as
the standalone gives up SPRING REV.

PLACE. DRAM (the default; ~5.3 KB) or CAVE (the classic cave, where the standalone puts it).
The ledger refuses this module beside any other that writes the STATIC / FLEX TSTR words
or the same sites (REPITCH_REPEAT98_KYOTI and octabam's REPITCH do): one design at a time.

MEASURED. The unit, linked at the standalone image's address, is that image's bytes
(5407 and 54455 alike). On the standalone image, in ot_emu with real hardware-exported
projects: bit-identical DSP increments with the shipped REPITCH_REPEAT98_KYOTI where the
designs coincide, and the new behaviour's tests (reference/handoffs/REPITCH_REWRITE_IMPL.md).
Not yet on hardware.
"""

import dataclasses
import importlib.util
import os

from remix.schema import (Category, Claims, Detour, DspHook, DspRange, DspSection, Keep, Kind,
                          Linked, Module, Poke, Proof, SymbolRef)

try:                                    # module settings (octabam since 2026-10): PLACE
    from remix.schema import Apply, Option, Setting
except ImportError:                     # an older octabam: DRAM, no setting
    Apply = Option = Setting = None

# This module's own directory, relative to the build's cwd (octabam's repo root), however
# the folder is reached (checked out directly, symlinked, or a submodule of this repo).
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

_spec = importlib.util.spec_from_file_location("vem_dsp_ptable", os.path.join(_HERE, "rpk_dsp_ptable.py"))
_pt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pt)

U = "vem_cf"
LINKED = (
    Linked(U, os.path.join(_HERE, "varispeed_emus.s"),
           reference=(0x400d6500,
                      "ca7cda3e18506db7dc7f13c69ac6481401c1c979bede5ca1a8ded069f97c8ed3")),
)

_X = bytes.fromhex
DETOURS = (
    Detour(0x40004100, _X("a1c0eca027400024"), U, "vem_frame",
           "render, second pass: the increment store (VARI speed, dry, engine tag, mask)", pad_to=8),
    Detour(0x4003a566, _X("4eb94003249c"), U, "emus_p2step",
           "P2EDIT's delta conversion: one EMUS stop per four detents; notes a TSTR edit",
           kind="jsr"),
    Detour(0x400585f4, _X("4eb9400326d4"), U, "emus_open",
           "SRC SETUP's open, its encoder set-up: the EMUS detent count restarts", kind="jsr"),
    Detour(0x4006e71c, _X("4879400b94f660000154"), U, "attr_label",
           "ATTR TIMESTRETCH label: 4 -> VARI", pad_to=10),
    Detour(0x4006ee48, _X("202801106608"), U, "attr_up", "ATTR TIMESTRETCH up: ... BEAT -> VARI"),
    Detour(0x4006ef7c, _X("20280110b280"), U, "attr_down", "ATTR TIMESTRETCH down: VARI -> BEAT ..."),
    Detour(0x4006eef0, _X("245f4ef94006dbdc"), U, "attr_tail", "ATTR up tail: poll the gates", pad_to=8),
    Detour(0x4006f026, _X("245f4ef94006dbdc"), U, "attr_tail", "ATTR down tail: poll the gates", pad_to=8),
    Detour(0x40036698, _X("206c00304a88660641f9400479b4"), U, "qdial1", "SETUP dial resolver 1", pad_to=14),
    Detour(0x4003690c, _X("206b00304a88660641f9400479b4"), U, "qdial2", "SETUP dial resolver 2", pad_to=14),
    Detour(0x4003786a, _X("206b00304a88660641f9400479b4"), U, "qdial3", "SETUP dial resolver 3", pad_to=14),
    Detour(0x40037c06, _X("206b00304a88660641f9400479b4"), U, "qdial4", "SETUP dial resolver 4", pad_to=14),
    Detour(0x40009094, _X("4fefff9848d77cfc"), U, "rp_apply1", "heavy Part apply: forget", pad_to=8),
    Detour(0x40009e00, _X("4fefffb448d77cfc"), U, "rp_apply2", "light Part apply: forget", pad_to=8),
    Detour(0x4004aab4, _X("4fefffe048d70c3c"), U, "rp_reload", "RELOAD PART: hold, forget", pad_to=8),
    Detour(0x40027e4c, _X("4fefffcc48d77cfc"), U, "vh_srcpaste", "SRC page paste (+ undo): hold, forget", pad_to=8),
    Detour(0x4002b654, _X("4fefffbc48d77cfc"), U, "vh_trkpaste", "track paste (+ undo): hold, forget", pad_to=8),
    Detour(0x40029a4c, _X("4fefffec48d7043c"), U, "vh_partpaste", "PART menu paste core (PASTE, UNDO): hold, forget",
           pad_to=8),
    Detour(0x4004a9d0, _X("4feffff048d70c0c"), U, "vh_partclear", "PART menu CLEAR: hold, forget", pad_to=8),
    Detour(0x40062d1c, _X("4ab946c7c72c"), U, "vg_tick",
           "UI task's message-loop tail: the guard's due check, its toast (the only NOTIFY)"),
    Detour(0x400526e4, _X("4fefffbc48d77cfc"), U, "vh_fx1", "FX1 chooser YES: refused if it overloads",
           pad_to=8),
    Detour(0x40052474, _X("4fefffbc48d77cfc"), U, "vh_fx2", "FX2 chooser YES: refused if it overloads",
           pad_to=8),
)

_u32 = lambda v: v.to_bytes(4, "big")
POKES = (
    Poke(0x400d30de, _u32(4), _u32(5), "STATIC TSTR count 4 -> 5"),
    Poke(0x400d3270, _u32(4), _u32(5), "FLEX TSTR count 4 -> 5"),
    Poke(0x400d313e, _u32(0x40046c28), _u32(0x40046ab4), "STATIC TSTR widget -> stock 5-position select"),
    Poke(0x400d32d0, _u32(0x40046c28), _u32(0x40046ab4), "FLEX TSTR widget -> stock 5-position select"),
)
SYMBOL_REFS = (
    SymbolRef(0x400d310e, 0x4003b6a4, U, "tstr_fmt", "STATIC TSTR formatter"),
    SymbolRef(0x400d32a0, 0x4003b6a4, U, "tstr_fmt", "FLEX TSTR formatter"),
    SymbolRef(0x400d3142, 0, U, "emus_widget", "STATIC TSNS widget"),
    SymbolRef(0x400d32d4, 0, U, "emus_widget", "FLEX TSNS widget"),
    SymbolRef(0x400d3116, 0x400479b4, U, "quant_widget", "STATIC PTCH widget"),
    SymbolRef(0x400d32a8, 0x400479b4, U, "quant_widget", "FLEX PTCH widget"),
    SymbolRef(0x400d3146, 0x40032d08, U, "quant_step", "STATIC PTCH encoder step"),
    SymbolRef(0x400d32d8, 0x40032d08, U, "quant_step", "FLEX PTCH encoder step"),
)
KEEPS = (
    Keep(0x40046b08, _X("7004b085"), "the 5-position select's bound (moveq #4): TSTR's five positions"),
    Keep(0x40046b9e, _u32(0x400be316), "the 5-position select's stock icons"),
)

# NEIGHBOR's '---' bytes of every track, in the Part window (offsets from 0x8ed80): the
# parks of STATIC's and FLEX's PTCH (page 1 slots 0 / 5) and TSNS (page 2 slots 5 / 3).
_PARKS = tuple(
    (base + 30 * t + slot, 1, f"T{t + 1} {what}")
    for t in range(8)
    for base, slot, what in ((0x2a, 18, "STATIC PTCH park"), (0x2a, 23, "FLEX PTCH park"),
                             (0x1da, 23, "STATIC TSNS park"), (0x1da, 21, "FLEX TSNS park")))

PLACES = ("DRAM", "CAVE")


def _variant(values):
    """PLACE -> vem_cf's placement (DRAM: octabam's platform runtime; CAVE: a ROM run)."""
    if values["PLACE"] == "DRAM":
        return {"linked": tuple(dataclasses.replace(u, dram=True) for u in LINKED)}
    return {}


_SETTINGS = {} if Setting is None else dict(
    settings=(Setting(1, "PLACE", Option(*PLACES), default="DRAM", apply=Apply.BUILD,
                      doc="DRAM: vem_cf in octabam's platform runtime; CAVE: in the ColdFire "
                          "free region (where the standalone image puts it)"),),
    variant=_variant)

MODULE = Module(
    name="varispeed-emus",
    key="VARISPEED_EMUS",
    kind=Kind.HYBRID,
    doc="STATIC/FLEX TSTR VARI: dry, tempo-locked varispeed (QUAN ratios on PTCH) with "
        "OT / S950 / SP12 engines on the TSNS knob (EMUS).",
    linked=LINKED if Setting is not None else tuple(dataclasses.replace(u, dram=True) for u in LINKED),
    detours=DETOURS,
    pokes=POKES,
    symbol_refs=SYMBOL_REFS,
    keeps=KEEPS,
    dsp=DspSection(
        asm=os.path.join(_HERE, "rpk_dsp.asm"),
        priority=32,
        ptable=tuple(_pt.PTABLE),
        ptable2=tuple(_pt.PTABLE2),
        hooks=(
            DspHook({"A": 0x0040b, "B": 0x0020e}, (0x76e500, 0x5edd00), "zqrp",
                    "voice kernel prologue: S950 / SP12 render the pass; OT leaves it to stock"),
            DspHook({"A": 0x00046, "B": 0x00047},
                    {"A": (0x06cf00, 0x000049), "B": (0x06cf00, 0x00004a)}, "zqboot",
                    "one-time memory clear at boot: also copies the tables into Y"),
        ),
    ),
    claims=Claims(
        dsp_ranges=(DspRange("y", 0xa00, 0x600, "per-track engine slots, the table tag, "
                                               "the engines' and the render's tables"),),
        part_window=_PARKS,
    ),
    category=Category.MACHINES,
    author="Zac-Kyoti",
    author_url="https://github.com/Zac-Kyoti/octatrack-kyoti-fw",
    proof=Proof.PORT,
    proof_note="ot_emu: the standalone image (tools/build_varispeed_emus.py) against the shipped "
               "REPITCH_REPEAT98_KYOTI and its own behaviour tests; not yet on hardware",
    **_SETTINGS,
)
