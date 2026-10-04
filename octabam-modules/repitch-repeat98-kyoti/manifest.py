"""REPITCH_REPEAT98_KYOTI -- tempo-locked varispeed for STATIC/FLEX tracks, as seven
TSTR positions, plus a QUAN ratio quantizer on the PTCH knob.

    TSTR  the four stock values, then
          RPCH  tempo-following varispeed (the basic Repitch)
          RPS9  S900/S950-style repitch emulation
          RPSP  SP-1200-style repitch emulation (channels 1/2)
    PTCH  on a repitch track: QUAN -- one detent per ratio

CREDIT. Jannik Aßfalg (repeat98) wrote the basic Repitch (octabam's modules/repitch:
the seven detour sites, the rate gate, the TSTR formatter). Zac Kyoti wrote the S900/S950
and SP-1200 repitch emulations (RPS9 / RPSP) and the Quantizer (QUAN).

⚠️ WORK IN PROGRESS: not run on a unit in this form, and octabam's dsp_asm builds the
kernel's XY+ALU moves only once sambanks/octabam#561's assembler fix lands.

DSP. One hook, zqrp, at the voice kernel's prologue (A P:0x40b, B P:0x20e): RPS9 and RPSP
render the pass there; RPCH runs stock's kernel. rpk_dsp.asm is generated from the
hardware-tested kernel by tools/repitch_dsp_octabam.py (constants resolved; the tables as
one ptable block read through `p:(rN)`; the block's base checked and stored at first use,
since it moves between remixes). The section needs donor words: the test remix gives up
SPRING REV, as the standalone build does.

COLDFIRE. Three DRAM units: rpk_logic (patch_repitch_kyoti.s -- gates, QUAN, the swap
bookkeeping, the four page-1 dial renderers), rpk_glyphs (the seven TSTR glyphs) and
rpk_reload (stock RELOAD PART treated as a Part apply). Fourteen jmp detours: Jannik's
seven, the four page-1 dials, the two Part applies and stock RELOAD PART.

THE 7-POSITION SELECTOR. Stock 1.40C carries a 5-position select widget at 0x40046ab4
that NOTHING references (no pointer, no jsr, no PC-relative call -- measured on the
stock image); Jannik's REPITCH uses it, unmodified, as TSTR's widget. This module patches
it in place to seven positions -- its bound `moveq #4` -> `#6`, and its icon-table
operand -> rpk_glyph_tab -- and points TSTR at it. The standalone builder makes the same
two changes to a copy in its cave; here no stock byte is copied.

PLACEMENT. DRAM, because octabam's floating ROM run cannot hold ~2.6 KB next to the other
KYOTI modules. A remix with this module carries the platform loader and its 10 MiB
reserve unless another DRAM module already does.

MEASURED. Hardware-confirmed on the author's MKI (the standalone image, rev 16, and the
KYOTI V1.0 combined image). rpk_logic and rpk_glyphs, linked at the standalone image's
own addresses, are byte for byte that image (5407 and 54455 alike). rpk_dsp.asm, run in the
stock voice module on both payloads with the table block in P and in the X curve bank, is
bit-exact with the reference model's DSP twin in all 176 cases
(tools/repitch_dsp_octabam_check.py). The octabam form has not been run on hardware.
"""

import os

import importlib.util

from remix.schema import (Claims, Detour, DspHook, DspRange, DspSection, Kind, Linked, Module,
                          Poke, SymbolRef, YBase)

# This module's own directory, relative to the build's cwd (octabam's repo root):
# "modules/repitch-repeat98-kyoti" checked out directly, or
# "modules/repitch-repeat98-kyoti/upstream/octabam-modules/repitch-repeat98-kyoti" as
# octabam's submodule of Zac-Kyoti/octatrack-kyoti-fw. One manifest serves both layouts.
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

H = bytes.fromhex

# The DSP tables (generated with rpk_dsp.asm by tools/repitch_dsp_octabam.py).
_spec = importlib.util.spec_from_file_location("rpk_dsp_ptable", os.path.join(_HERE, "rpk_dsp_ptable.py"))
_tab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tab)

# ---- the fourteen detours (site, displaced bytes, unit, symbol, what) -----------------
DETOURS = (
    (0x4000406A, "082f000400436608",             "rpk_logic", "rate_gate",
     "resolve the repitch mode for the track the increment is built for"),
    (0x4000409E, "71d6a3460c404000",             "rpk_logic", "pitch_gate",
     "PTCH not applied on a repitch track (QUAN instead)"),
    (0x40004100, "a1c0eca027400024",             "rpk_logic", "rate_hook",
     "scale the shared CPU/DSP playback increment"),
    (0x40007D96, "712a00147404",                 "rpk_logic", "tstr_resolve",
     "the voice renderer resolves a repitch mode to OFF"),
    (0x4006E71C, "4879400b94f660000154",         "rpk_logic", "attr_label",
     "audio editor ATTR: TIMESTRETCH prints the repitch modes"),
    (0x4006EE56, "7202b28066000094",             "rpk_logic", "attr_up",
     "audio editor ATTR: TIMESTRETCH up"),
    (0x4006EF7C, "20280110b2806608",             "rpk_logic", "attr_down",
     "audio editor ATTR: TIMESTRETCH down"),
    (0x40036698, "206c00304a88660641f9400479b4", "rpk_logic", "qdial1",
     "page-1 dial renderer: QUAN widget on a repitch track"),
    (0x4003690C, "206b00304a88660641f9400479b4", "rpk_logic", "qdial2",
     "page-1 dial renderer: QUAN widget on a repitch track"),
    (0x4003786A, "206b00304a88660641f9400479b4", "rpk_logic", "qdial3",
     "page-1 dial renderer: QUAN widget on a repitch track"),
    (0x40037C06, "206b00304a88660641f9400479b4", "rpk_logic", "qdial4",
     "page-1 dial renderer: QUAN widget on a repitch track"),
    (0x40009094, "4fefff9848d77cfc",             "rpk_logic", "rp_apply1",
     "Part apply (by event): adopt, never swap"),
    (0x40009E00, "4fefffb448d77cfc",             "rpk_logic", "rp_apply2",
     "Part apply: adopt, never swap"),
    (0x4004AAB4, "4fefffe048d70c3c",             "rpk_reload", "rp_reload",
     "stock RELOAD PART: hold, then forget, as a Part apply"),
)

KNOB = 0x400479B4          # stock knob widget
SELECT4 = 0x40046C28       # stock 4-position select (TSTR's own)
SELECT5 = 0x40046AB4       # stock 5-position select -- unreferenced in stock
STOCK_FMT = 0x4003B6A4     # stock TSTR formatter
STOCK_STEP = 0x40032D08    # stock encoder-step handler, PTCH slot

MODULE = Module(
    name="repitch-repeat98-kyoti",
    key="REPITCH_REPEAT98_KYOTI",
    kind=Kind.HYBRID,
    doc="TSTR RPCH / RPS9 / RPSP: tempo-locked varispeed with S900/S950 and SP-1200 "
        "repitch emulations, and QUAN ratios on PTCH.",
    conflicts=(("REPITCH",
                "grows the same REPITCH (the same seven detour sites and TSTR words) "
                "-- take one"),),
    linked=(
        # At the standalone image's own addresses (tools/build_repitch_repeat98_kyoti.py).
        Linked("rpk_logic", os.path.join(_HERE, "patch_repitch_kyoti.s"), dram=True,
               reference=(0x400d6f80,
                          "b1208b324e4e2f057c1c2665e78fb1f8a5fc0ebcfb65752541a5187a130a29ce")),
        Linked("rpk_glyphs", os.path.join(_HERE, "rpk_glyphs.s"), dram=True,
               reference=(0x400d7870,
                          "5f3a4808fa88fcbb217afb632c8f205275cda31125a82dde55597bb04bff3fe9")),
        # Names rpk_logic's rp_prev / rp_forget, resolved in the one DRAM link; linked
        # alone it cannot resolve them, so it has no reference of its own (46 B).
        Linked("rpk_reload", os.path.join(_HERE, "patch_repitch_reload.s"), dram=True),
    ),
    detours=tuple(
        Detour(site, H(stock), unit, sym, what, pad_to=len(H(stock)) if len(H(stock)) > 6 else None)
        for site, stock, unit, sym, what in DETOURS
    ),
    symbol_refs=(
        SymbolRef(0x400D310E, STOCK_FMT, "rpk_logic", "tstr_fmt", "STATIC TSTR formatter"),
        SymbolRef(0x400D32A0, STOCK_FMT, "rpk_logic", "tstr_fmt", "FLEX TSTR formatter"),
        SymbolRef(0x400D3116, KNOB, "rpk_logic", "quant_widget", "STATIC PTCH widget -> QUAN"),
        SymbolRef(0x400D32A8, KNOB, "rpk_logic", "quant_widget", "FLEX PTCH widget -> QUAN"),
        # P+0x12a slot 0, the encoder-step handler: one detent, one ratio
        SymbolRef(0x400D3146, STOCK_STEP, "rpk_logic", "quant_step", "STATIC PTCH step"),
        SymbolRef(0x400D32D8, STOCK_STEP, "rpk_logic", "quant_step", "FLEX PTCH step"),
        # the unreferenced 5-position select, made seven: its icon table
        SymbolRef(SELECT5 + 0xEA, 0x400BE316, "rpk_glyphs", "rpk_glyph_tab",
                  "7-position select: icon table -> the seven glyphs"),
    ),
    pokes=(
        Poke(0x400D30DE, H("00000004"), H("00000007"), "STATIC TSTR count 4 -> 7"),
        Poke(0x400D3270, H("00000004"), H("00000007"), "FLEX TSTR count 4 -> 7"),
        Poke(0x400D313E, SELECT4.to_bytes(4, "big"), SELECT5.to_bytes(4, "big"),
             "STATIC TSTR widget -> the 7-position select"),
        Poke(0x400D32D0, SELECT4.to_bytes(4, "big"), SELECT5.to_bytes(4, "big"),
             "FLEX TSTR widget -> the 7-position select"),
        Poke(SELECT5 + 0x54, H("7004"), H("7006"),
             "7-position select: bound moveq #4 -> #6"),
    ),
    dsp=DspSection(
        asm=os.path.join(_HERE, "rpk_dsp.asm"),
        priority=31,
        ybase=YBase.NEVER,
        ptable=_tab.PTABLE,
        hooks=(DspHook({"A": 0x0040b, "B": 0x0020e}, (0x76e500, 0x5edd00), "zqrp",
                       "voice kernel prologue: RPS9 / RPSP render the pass"),),
    ),
    claims=Claims(dsp_ranges=(
        DspRange("y", 0xa00, 0x600, "RPSP slots and tag, the copied ADC and render tables, "
                                    "the aux blocks, the table base (TABB/TABG)"),
    )),
)
