"""SIDECHAIN_COMPRESSOR_BW (Sidechain Compressor B-W) -- stock COMPRESSOR with a side-chain KEY
from any track and a base-width key filter.

    page 2  RMS (stock, slot 6), then
            MON   ON = hear the processed key instead of the track (audition); slot 7,
                  stored inverted (1 = OFF); switching it, or changing KEY while it is
                  on, crossfades over 64 samples instead of clicking
            KEY   OFF / T1..T8: the track whose audio drives the detector
            KGN   the key's gain, about -24..+24 dB around 64
            KBAS  the key's high-pass, 18 dB/oct Butterworth: OFF, 20 Hz..19.6 kHz (in Hz)
            KWID  the key's low-pass, 12 dB/oct Butterworth, as a distance above KBAS:
                  0.5..9.9 octaves, OFF (in octaves); with KBAS OFF a plain low-pass
                  counted from 20 Hz

The base-width filter isolates the key better than SIDECHAIN_COMPRESSOR's one-knob KFLT --
a kick's fundamental, say, with KBAS cutting the sub-sonic rumble -- which reduces distortion
and keeps the compression smooth at short attack and release settings. The two modules
are the same effect (stock COMPRESSOR, the same hooks and page-2 slots): one per remix.

Hardware-confirmed in the standalone image (the author's MKI, 2026-10-22, 140C_SCKF4: page
2, KBAS / KWID readouts and ranges, the kick-fundamental case at short attack and release,
MON and KEY declick, load with 1 + 7 and 4 + 4 COMPRESSOR / DJ EQ per core). This octabam
form is not flashed yet.

COLDFIRE. One ROM unit, scbw_cf (tools/patch_sidechain_bw.s, 600 B): MON's inverted ON/OFF,
KEY's formatter and list widget, KBAS's Hz and KWID's octave formatters, and sc_norm, reached
by a `jsr` detour at the first instruction of both page-2 copiers (0x4000cae8, its twin
0x40003d1c). A COMPRESSOR saved on stock firmware holds stock's slot 8..11 defaults
0x7f/0/0/0, i.e. KEY 127; sc_norm resets any COMPRESSOR whose KEY is above 8 to MON OFF,
KEY OFF, KGN 64, KBAS OFF, KWID OFF, in the current part's working store and in the live
lane, each judged by its own FX id. A KEY of 0..8 is never touched.

DSP. MenuEntry(replaces="COMPRESSOR", stock_dsp=True): the effect IS stock COMPRESSOR, its
dispatch entry untouched. This module's code (tools/patch_sc_bw_dsp3.asm; tools/sc_keyfilt.py
is the filters' bit-exact model) runs from four DspHooks:
    sctap      dispatcher, every track every block: publish the track's audio to this
               core's keybus (core-private Y) and to the cross-core window
    scdet      COMPRESSOR proc+0: the detector reads the KEY track's audio through KGN and
               the key filters (a TPT one-pole HP x a TPT SVF HP at KBAS, a TPT SVF LP KWID
               above it; coefficients from a 49-word table and `div`, recomputed only while
               a cutoff glides); a KEY change made while MON is audible waits for MON to fade
    moncommit  dispatcher, per-track commit: MON's crossfade to the stashed key; MON_ON is
               consumed every block. `scmonbody` uses a, b, x0, x1, y1, r1, n1, r3
    scinit     COMPRESSOR init: the key filters start over (another effect in the slot may
               have used their r7 words)
State at COMPRESSOR's r7+$1c..$2d (free while COMPRESSOR runs: an r7 canary, emulator and
hardware, 2026-10-19). The 16 + 49 table words are one ptable.

CLAIMS. As SIDECHAIN_COMPRESSOR: core-private Y $7f0-$9ff (MON words, keybus) on both cores,
and the last $202 words of each core's half of the shared window (A $33dfe.., B $3bdfe..).

MEASURED. The ColdFire unit, linked at the standalone image's own address, is that image's
bytes. The DSP source is the standalone's, with the same per-core values; tools/
emu_sc_bw_dsp3.py --layout octabam (these addresses) is ALL GOOD: the filters bit-exact
against the model, the crossfade, the KEY hold.
"""

import dataclasses
import importlib.util
import os

from remix.schema import (Apply, Claims, Detour, DspHook, DspRange, DspSection, Kind, Linked,
                          MenuEntry, Module, Option, Param, Setting, Store, YBase)

# This module's own directory, relative to the build's cwd (octabam's repo root):
# "modules/sidechain-compressor-bw" checked out directly, or
# "modules/sidechain-compressor-bw/upstream/octabam-modules/sidechain-compressor-bw" as
# octabam's submodule of Zac-Kyoti/octatrack-kyoti-fw. One manifest serves both layouts.
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))
_TOOLS = os.path.normpath(os.path.join(_HERE, "..", "..", "tools"))

# The standalone builder's tables and coefficients (tools/sc_tables.py, plain Python).
_spec = importlib.util.spec_from_file_location("kyoti_sc_tables", os.path.join(_TOOLS, "sc_tables.py"))
_sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sc)
# The key filters' table and constants (tools/sc_keyfilt.py, the DSP's bit-exact model).
_kspec = importlib.util.spec_from_file_location("kyoti_sc_keyfilt", os.path.join(_TOOLS, "sc_keyfilt.py"))
_kf = importlib.util.module_from_spec(_kspec)
_kspec.loader.exec_module(_kf)

E = 0x400d5a4a                  # stock COMPRESSOR's descriptor
FMT_BIPOLAR = 0x4003c7a0        # stock "-N" / "+N" about 64
FMT_ONOFF = 0x4003c14c          # stock "ON" / "OFF"
SWITCH_FN = 0x40046f10          # stock 2-position switch (FILTER's HOLD)

_SAME = {"@KGNA@": f"${_sc.kgn_smooth_a():x}",
         **_kf.asm_tokens(),
         # `nop`: a cycle between writing r1 and reading through it, and the same
         # two words as the standalone's `move #>FTAB,r1`, so nothing after it moves.
         "@FTAB_R1@": "lua     (r1+$10),r1\n        nop",
         # The keybus and MON words at Session 115's Y:$7f0..$9ff, which no FX2 slot reaches
         # (the standalone builder's KEYBUS puts them in the first internal slot's tail).
         "@KEYB@": "$800", "@KEYB1@": "$820", "@MONB@": "$7f0"}
assert _sc.GAIN_N == 0x10, "@FTAB_R1@'s offset is the KEY GAIN table's length (the key-filter table follows it)"

# At the standalone image's own address (tools/build_sidechain_compressor_bw.py).
LINKED = (
    Linked("scbw_cf", os.path.join(_TOOLS, "patch_sidechain_bw.s"),
           reference=(0x400d7000,
                      "4984aba27a91d2bc526219f82f1b3311ef5716443d2b682d3c04204a815a2f9f")),
)

# PLACE: where octabam links scbw_cf. CAVE (the default) is the ColdFire free
# region, as the standalone image; DRAM puts it in octabam's platform runtime
# (as rl3 and dj7), still re-linked at 0x400d7000 and compared with the bytes
# above. The store id is octabam.sidechain-compressor-bw (its module directory).
# tools/build_sidechain_compressor_bw.py does not read this manifest.
PLACES = ("CAVE", "DRAM")


def _variant(values):
    """PLACE -> scbw_cf's placement."""
    if values["PLACE"] == "DRAM":
        return {"linked": tuple(dataclasses.replace(u, dram=True) for u in LINKED)}
    return {}


MODULE = Module(
    name="sidechain-compressor-bw",
    key="SIDECHAIN_COMPRESSOR_BW",
    kind=Kind.DSP_EFFECT,
    doc="Sidechain Compressor B-W: stock COMPRESSOR with a side-chain KEY from any of T1-T8, "
        "key gain, a base-width key filter (KBAS high-pass in Hz, KWID low-pass in octaves above "
        "it) and a key listen switch on page 2.",
    menu=MenuEntry(fx2_id=0x18, donor_desc=E, abbr=b"COMP", fullname=b"COMPRESSOR",
                   replaces="COMPRESSOR", stock_dsp=True),
    # Slots 0-6 are stock COMPRESSOR's, unchanged: on a stock_dsp clone a Param() keeps the
    # donor's enable nibble and every other field (octabam #571). Page 2 since the major
    # version: RMS MON KEY KGN KBAS KWID. MON sits in stock's hidden slot 7, stored inverted
    # (1 = OFF), so a compressor saved before comes up with MON off.
    params=tuple(Param(doc=d) for d in (
        "stock: attack time",
        "stock: release time",
        "stock: threshold",
        "stock: ratio",
        "stock: make-up gain",
        "stock: dry/wet mix",
        "stock: the detector's RMS setting")) + (
        Param(b"MON", 1, count=2, active=True,
              formatter_word=("scbw_cf", "mon_fmt"), widget_word=SWITCH_FN,
              labels=("ON", "OFF"),
              doc="ON: this track plays its processed key instead (audition); stored 1 = OFF"),
        Param(b"KEY", 0, count=9, active=True,
              formatter_word=("scbw_cf", "key_fmt"), widget_word=("scbw_cf", "key_list_fix"),
              labels=("OFF", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"),
              doc="the track whose audio drives the detector; OFF = stock (self)"),
        Param(b"KGN", 64, count=128, active=True,
              formatter_word=FMT_BIPOLAR, widget_word=0,   # a plain knob, not the donor's widget
              doc="the key's gain, about -24..+24 dB; 64 = unity"),
        Param(b"KBAS", 0, count=128, active=True,
              formatter_word=("scbw_cf", "hp_fmt"), widget_word=0,
              doc="the key's high-pass, 18 dB/oct: OFF, then 20 Hz to 19.6 kHz"),
        Param(b"KWID", 127, count=128, active=True, link=True,
              formatter_word=("scbw_cf", "lp_fmt"), widget_word=0,
              doc="the key's low-pass, 12 dB/oct: 0.5-9.9 octaves above KBAS (20 Hz if OFF), then OFF"),
    ),
    linked=LINKED,
    # sc_norm: a COMPRESSOR saved before SIDE-CHAIN existed holds stock's slot 8..11 defaults
    # 0x7f/0/0/0 and comes up with its side-chain OFF. Both page-2 copiers; sc_norm replays
    # the displaced `lea 0x80000a50,%a3` and returns.
    detours=(
        Detour(0x4000cae8, bytes.fromhex("47f980000a50"), "scbw_cf", "sc_norm",
               "frame builder's page-2 copier: a stale KEY (> 8) -> side-chain defaults",
               kind="jsr"),
        Detour(0x40003d1c, bytes.fromhex("47f980000a50"), "scbw_cf", "sc_norm",
               "the copier's twin: the same check", kind="jsr"),
    ),
    dsp=DspSection(
        asm=os.path.join(_TOOLS, "patch_sc_bw_dsp3.asm"),
        priority=30,
        ybase=YBase.NEVER,            # COMPRESSOR is on FX1; the bases come from subst
        ptable=tuple(_sc.gain_table()) + tuple(_kf.GT),
        hooks=(
            DspHook({"A": 0x004a7, "B": 0x0029c}, (0x66f000, 0x000208), "sctap",
                    "dispatcher: publish every track's audio"),
            DspHook({"A": 0x01ab1, "B": 0x01871}, (0x221e00, 0x346100), "scdet",
                    "COMPRESSOR proc+0: the detector reads the KEY track"),
            DspHook({"A": 0x0050e, "B": 0x00303}, (0x60f000, 0x000206), "moncommit",
                    "dispatcher, per-track commit: MON"),
            DspHook({"A": 0x01aa4, "B": 0x01864}, (0x44f400, 0x0020c5), "scinit",
                    "COMPRESSOR init: the key filters start over"),
        ),
        subst={
            "A": {"@COREBASE@": "4", "@FCOREBASE@": "0",
                  "@SBASE@": "$33e00", "@FSBASE@": "$3be00",
                  "@GCNT@": "$33dff", "@GSEED@": "$33dfe",
                  "@FOREIGN_BR@": "beq zz24", **_SAME},
            "B": {"@COREBASE@": "0", "@FCOREBASE@": "4",
                  "@SBASE@": "$3be00", "@FSBASE@": "$33e00",
                  "@GCNT@": "$3bdff", "@GSEED@": "$3bdfe",
                  "@FOREIGN_BR@": "bne zz24", **_SAME},
        },
    ),
    claims=Claims(dsp_ranges=(
        DspRange("y", 0x7f0, 0x210, "MON words ($7f0..$7ff) and the keybus ($800..$9ff)"),
        DspRange("y", 0x3dfe, 0x202, "the cross-core key window: GSEED, GCNT, "
                                     "4 tracks x 4 generations x 32 words",
                 half_relative=True),
    )),
    store=Store("octabam.sidechain-compressor-bw"),
    settings=(Setting(1, "PLACE", Option(*PLACES), default="CAVE", apply=Apply.BUILD,
                      doc="CAVE: scbw_cf in the ColdFire free region (the standalone image's "
                          "placement); DRAM: in octabam's platform runtime"),),
    variant=_variant,
    conflicts=(("SIDECHAIN_COMPRESSOR", "the same effect (stock COMPRESSOR) with the light key "
                                        "filter: the same hooks and page-2 slots, one per remix"),),
)
