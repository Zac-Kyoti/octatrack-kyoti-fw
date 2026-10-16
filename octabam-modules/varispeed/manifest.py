# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""VARISPEED -- tempo-locked varispeed for STATIC and FLEX (VARI + QUAN, nothing emulated).

    TSTR    OFF AUTO NORM BEAT VARI (STATIC / FLEX; PICKUP keeps its own)
    VARI    the track plays dry at (project BPM x p) / (sample BPM x q), exact in
            integers, an octave fold above 2x; p/q is the QUAN ratio, RATE still applies.
            AUTO plays a sample whose TIMESTRETCH (audio editor, ATTR) is VARI the same
            way. A sample or project tempo outside 30..300 BPM plays as TSTR OFF.
    QUAN    the PTCH knob on a VARI track: 1/2 2/3 3/4 4/5 1/1 5/4 4/3 3/2 2/1

The plain build of VARISPEED_EMUS (octabam-modules/varispeed-emus/): the SAME source,
assembled with its switch VEM_EMUS = 0, so a fix to the shared code lands in both. No EMUS
(TSNS stays TSNS), no sampler engines, no load guard, no DSP section: SPRING REVERB stays.
A VARI track's increment is VARISPEED_EMUS's on EMUS = OT, bit for bit.

COLDFIRE. One unit, vari_cf: varispeed.s, two lines -- `.equ VEM_EMUS, 0` and
`.include "remix.inc"` -- whose remix.inc (Linked.include) is the text of
../varispeed-emus/varispeed_emus.s, so this folder needs that one beside it. 17 detours: the
render's increment store (the frame hook), five in the audio editor's ATTR page, the four
SETUP-page dial resolvers, the two Part applies, RELOAD PART, and hold wrappers on the bulk
writers (SRC page paste, track paste, the PART menu's paste core and CLEAR). The STATIC and
FLEX descriptors: TSTR count 4 -> 5 with stock's 5-position select and this unit's
formatter; PTCH's widget and encoder step. The PTCH <-> QUAN swap keeps PTCH of each
machine in NEIGHBOR's '---' bytes of the same track (claimed below).

PLACE. DRAM (the default) or CAVE (the classic cave, where the standalone puts it).
The ledger refuses this module beside VARISPEED_EMUS or any other that writes the STATIC /
FLEX TSTR words or the same sites: one design at a time.

MEASURED. The unit, linked at the standalone image's address, is that image's bytes
(tools/build_varispeed.py assembles this wrapper too and refuses a difference). On the
standalone image in ot_emu with real hardware-exported projects: VARI increments bit-identical
with VARISPEED_EMUS's on OT, stock tracks' with stock 1.40C (reference/handoffs/
VARISPEED_IMPL.md §14). On hardware: the author's MKI, 15 Oct 2026 (the standalone image
140C_VARI1 and its Bugbuild).
"""

import dataclasses
import os

from remix.schema import (Category, Claims, Detour, Keep, Kind, Linked, Module, Poke, Proof,
                          SymbolRef)

try:                                    # module settings (octabam since 2026-10): PLACE
    from remix.schema import Apply, Option, Setting
except ImportError:                     # an older octabam: DRAM, no setting
    Apply = Option = Setting = None

# This module's own directory, relative to the build's cwd (octabam's repo root), however
# the folder is reached (checked out directly, symlinked, or a submodule of this repo).
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))
_SHARED = os.path.join(_HERE, os.pardir, "varispeed-emus", "varispeed_emus.s")


def _shared_source(_modules):
    """remix.inc: the VARISPEED_EMUS source, which varispeed.s assembles with VEM_EMUS = 0."""
    with open(_SHARED) as f:
        return f.read()


U = "vari_cf"
LINKED = (
    Linked(U, os.path.join(_HERE, "varispeed.s"),
           reference=(0x400d6500,
                      "afd1eed15b32c93e615cfcdf3e26c21b5c56854c65cb5457cb4a88836f4cab9b"),
           include=_shared_source),
)

_X = bytes.fromhex
DETOURS = (
    Detour(0x40004100, _X("a1c0eca027400024"), U, "vem_frame",
           "render, second pass: the increment store (VARI speed, dry)", pad_to=8),
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
# parks of STATIC's and FLEX's PTCH (page 1 slots 0 / 5). TSNS has no park here.
_PARKS = tuple(
    (base + 30 * t + slot, 1, f"T{t + 1} {what}")
    for t in range(8)
    for base, slot, what in ((0x2a, 18, "STATIC PTCH park"), (0x2a, 23, "FLEX PTCH park")))

PLACES = ("DRAM", "CAVE")


def _variant(values):
    """PLACE -> vari_cf's placement (DRAM: octabam's platform runtime; CAVE: a ROM run)."""
    if values["PLACE"] == "DRAM":
        return {"linked": tuple(dataclasses.replace(u, dram=True) for u in LINKED)}
    return {}


_SETTINGS = {} if Setting is None else dict(
    settings=(Setting(1, "PLACE", Option(*PLACES), default="DRAM", apply=Apply.BUILD,
                      doc="DRAM: vari_cf in octabam's platform runtime; CAVE: in the ColdFire "
                          "free region (where the standalone image puts it)"),),
    variant=_variant)

MODULE = Module(
    name="varispeed",
    key="VARISPEED",
    kind=Kind.CF_PATCH,
    doc="STATIC/FLEX TSTR VARI: dry, tempo-locked varispeed with QUAN ratios on PTCH "
        "(the plain build of VARISPEED_EMUS: nothing emulated, stock DSP).",
    linked=LINKED if Setting is not None else tuple(dataclasses.replace(u, dram=True) for u in LINKED),
    detours=DETOURS,
    pokes=POKES,
    symbol_refs=SYMBOL_REFS,
    keeps=KEEPS,
    claims=Claims(part_window=_PARKS),
    category=Category.MACHINES,
    author="Zac-Kyoti",
    author_url="https://github.com/Zac-Kyoti/octatrack-kyoti-fw",
    proof=Proof.HARDWARE,
    proof_note="the author's MKI, 15 Oct 2026 (the standalone image 140C_VARI1 and its Bugbuild)",
    **_SETTINGS,
)
