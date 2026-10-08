"""SIDECHAIN_COMPRESSOR -- stock COMPRESSOR with a side-chain KEY from any track.

    page 2  RMS (stock, slot 6), then
            KEY   OFF / T1..T8: the track whose audio drives the detector
            KFLT  the key's filter: 64 = bypass, below = low-pass, above = high-pass
            KGN   the key's gain, about -24..+24 dB around 64
            MON   ON = hear the processed key instead of the track (audition)

Hardware-confirmed in this octabam form (the author's MKI, 2026-10-04; see MEASURED).

COLDFIRE. One ROM unit, sc_cf (tools/patch_sidechain.s, 338 B): KEY's and KFLT's
formatters, KEY's list widget, and sc_norm, reached by a `jsr` detour at the first
instruction of both page-2 copiers (0x4000cae8, its twin 0x40003d1c). A COMPRESSOR saved
on stock firmware holds stock's slot 8..11 defaults 0x7f/0/0/0, i.e. KEY 127; sc_norm
resets any COMPRESSOR whose KEY is above 8 to KEY OFF, KFLT 64, KGN 64, MON OFF, in the
current part's working store and in the live lane, each judged by its own FX id, so the
side-chain stays off until the user sets it up. A KEY of 0..8 is never touched. The page-2 slots are written as raw descriptor words
(Param.formatter_word / widget_word), as the standalone builder writes them: this unit's
symbols for KEY's formatter and widget and KFLT's formatter, stock's bipolar formatter
for KGN and ON/OFF formatter and switch for MON, and widget 0 (a plain knob) for KFLT
and KGN.

DSP. MenuEntry(replaces="COMPRESSOR", stock_dsp=True): the effect IS stock COMPRESSOR,
its dispatch entry untouched. This module's code runs from three DspHooks, at different
addresses on the two payloads:
    sctap      dispatcher, every track every block: publish the track's audio to this
               core's keybus (core-private Y) and to the cross-core window
    scdet      COMPRESSOR proc+0: replace the detector input with the KEY track's audio,
               through KGN and KFLT; stash it for MON
    moncommit  dispatcher, per-track commit: with MON on, the stashed key replaces the
               track's output
The per-core values (own and foreign core base, the window addresses, the branch
sense) come from DspSection.subst; the 16 + 32 table words are one ptable, read at the
KEY GAIN site through the source's single base literal and at the KEY FLT site as
`lua (r1+$10),r1` + `nop` from that same base (r1 is not written between the two reads).

CLAIMS. Core-private Y $7f0-$9ff (MON words, keybus) on both cores, and the last $202
words of each core's half of the shared window (A $33dfe.., B $3bdfe..). BusDelay and
BusVerb use that window, so the ledger refuses this module beside them: a later version
moves the window.

MEASURED. The ColdFire unit, linked at the standalone image's own address, is that
image's bytes (5407 and 54455 alike). The DSP source is the standalone's
(tools/patch_sc_dsp3.asm), with the same per-core values; octabam assembles and places
it itself: on both payloads its code is the standalone's instruction for instruction except
the two table loads, and the 48 table words are identical. On the author's MKI, this octabam
form (2026-10-04, with all six KYOTI modules and REC_TRIG_MUTE): COMPRESSOR's two pages,
KEY ducking on one core and across cores both ways, KFLT, KGN, MON, no reverb cross-talk on
T7, a muted KEY in each MUTE MODE and the first kick after PLAY. Before that, the standalone
and KYOTI V1.0: KEY ducking, MON, a muted KEY with MUTE_MODES.
"""

import importlib.util
import os

from remix.schema import (Claims, Detour, DspHook, DspRange, DspSection, Kind, Linked,
                          MenuEntry, Module, Param, YBase)

# This module's own directory, relative to the build's cwd (octabam's repo root):
# "modules/sidechain-compressor" checked out directly, or
# "modules/sidechain-compressor/upstream/octabam-modules/sidechain-compressor" as
# octabam's submodule of Zac-Kyoti/octatrack-kyoti-fw. One manifest serves both layouts.
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))
_TOOLS = os.path.normpath(os.path.join(_HERE, "..", "..", "tools"))

# The standalone builder's tables and coefficients (tools/sc_tables.py, plain Python).
_spec = importlib.util.spec_from_file_location("kyoti_sc_tables", os.path.join(_TOOLS, "sc_tables.py"))
_sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sc)

E = 0x400d5a4a                  # stock COMPRESSOR's descriptor
FMT_BIPOLAR = 0x4003c7a0        # stock "-N" / "+N" about 64
FMT_ONOFF = 0x4003c14c          # stock "ON" / "OFF"
SWITCH_FN = 0x40046f10          # stock 2-position switch (FILTER's HOLD)

_SAME = {"@LPEDGE@": f"${_sc.lp_edge():x}",
         "@HPEDGE@": f"${_sc.hp_edge():x}",
         "@KGNA@": f"${_sc.kgn_smooth_a():x}",
         # `nop`: a cycle between writing r1 and reading through it, and the same
         # two words as the standalone's `move #>FTAB,r1`, so nothing after it moves.
         "@FTAB_R1@": "lua     (r1+$10),r1\n        nop"}
assert _sc.GAIN_N == 0x10, "@FTAB_R1@'s offset is the KEY GAIN table's length"

MODULE = Module(
    name="sidechain-compressor",
    key="SIDECHAIN_COMPRESSOR",
    kind=Kind.DSP_EFFECT,
    doc="Stock COMPRESSOR with a side-chain KEY from any of T1-T8, a key filter, "
        "key gain and a key listen switch on page 2.",
    menu=MenuEntry(fx2_id=0x18, donor_desc=E, abbr=b"COMP", fullname=b"COMPRESSOR",
                   replaces="COMPRESSOR", stock_dsp=True),
    # Slots 0-6 are stock COMPRESSOR's, unchanged: on a stock_dsp clone a Param() keeps the
    # donor's enable nibble and every other field (octabam #571). Slot 7 is stock's empty one.
    params=tuple(Param(doc=d) for d in (
        "stock: attack time",
        "stock: release time",
        "stock: threshold",
        "stock: ratio",
        "stock: make-up gain",
        "stock: dry/wet mix",
        "stock: the detector's RMS setting")) + (Param(),) + (
        Param(b"KEY", 0, count=9, active=True,
              formatter_word=("sc_cf", "key_fmt"), widget_word=("sc_cf", "key_list_fix"),
              labels=("OFF", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"),
              doc="the track whose audio drives the detector; OFF = stock (self)"),
        Param(b"KFLT", 64, count=128, active=True,
              formatter_word=("sc_cf", "kfilt_fmt"), widget_word=0,   # a plain knob, not the donor's switch
              doc="the key's filter: 64 bypass, below low-pass, above high-pass"),
        Param(b"KGN", 64, count=128, active=True,
              formatter_word=FMT_BIPOLAR, widget_word=0,
              doc="the key's gain, about -24..+24 dB; 64 = unity"),
        Param(b"MON", 0, count=2, active=True,
              formatter_word=FMT_ONOFF, widget_word=SWITCH_FN,
              labels=("OFF", "ON"),
              doc="ON: this track plays its processed key instead (audition)"),
    ),
    linked=(
        # At the standalone image's own address (tools/build_sidechain_compressor.py).
        Linked("sc_cf", os.path.join(_TOOLS, "patch_sidechain.s"),
               reference=(0x400d7000,
                          "76a4badcef6024b7de8bd6f05930146bdb6a47ffd577da340a6c252c316ff854")),
    ),
    # sc_norm: a COMPRESSOR saved before SIDE-CHAIN existed holds stock's slot 8..11 defaults
    # 0x7f/0/0/0 and comes up with its side-chain OFF. Both page-2 copiers; sc_norm replays
    # the displaced `lea 0x80000a50,%a3` and returns.
    detours=(
        Detour(0x4000cae8, bytes.fromhex("47f980000a50"), "sc_cf", "sc_norm",
               "frame builder's page-2 copier: a stale KEY (> 8) -> side-chain defaults",
               kind="jsr"),
        Detour(0x40003d1c, bytes.fromhex("47f980000a50"), "sc_cf", "sc_norm",
               "the copier's twin: the same check", kind="jsr"),
    ),
    dsp=DspSection(
        asm=os.path.join(_TOOLS, "patch_sc_dsp3.asm"),
        priority=30,
        ybase=YBase.NEVER,            # COMPRESSOR is on FX1; the bases come from subst
        ptable=tuple(_sc.gain_table()) + tuple(_sc.flt_table()),
        hooks=(
            DspHook({"A": 0x004a7, "B": 0x0029c}, (0x66f000, 0x000208), "sctap",
                    "dispatcher: publish every track's audio"),
            DspHook({"A": 0x01ab1, "B": 0x01871}, (0x221e00, 0x346100), "scdet",
                    "COMPRESSOR proc+0: the detector reads the KEY track"),
            DspHook({"A": 0x0050e, "B": 0x00303}, (0x60f000, 0x000206), "moncommit",
                    "dispatcher, per-track commit: MON"),
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
)
