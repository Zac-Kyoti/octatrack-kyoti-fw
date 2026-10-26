# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""SIDECHAIN_COMPRESSOR (Modwerk form) -- stock COMPRESSOR with a side-chain KEY from any track and a base-width
key filter.

    page 2  RMS (stock, slot 6), then
            MON   ON = hear the processed key instead of the track (audition); slot 7,
                  OFF (left) / ON (right); switching it, or changing KEY while it is on,
                  crossfades over 256 samples instead of clicking
            KEY   OFF / T1..T8: the track whose audio drives the detector
            KGN   the key's gain, about -24..+24 dB around 64
            KBAS  the key's high-pass, 18 dB/oct Butterworth: OFF, 20 Hz..19.6 kHz (in Hz)
            KWID  the key's low-pass, 12 dB/oct Butterworth, as a distance above KBAS:
                  0.5..9.9 octaves, OFF (in octaves); with KBAS OFF a plain low-pass
                  counted from 20 Hz

CHANGED 2026-10-22. The base-width filter replaced the previous version's one-knob KFLT: it
isolates the key better (a kick's fundamental without its sub-sonic rumble, say), which
reduces distortion and keeps the compression smooth at short attack and release settings. Page
2 was RMS KEY KFLT KGN MON; a COMPRESSOR saved with that version keeps its KEY, but its other
page-2 values now land on different knobs (KGN = the old KFLT, KBAS = the old KGN, KWID = the
old MON; MON comes up OFF), so it sounds different until KGN, KBAS, KWID and MON are set again.

Hardware-confirmed in the standalone image (the author's MKI, 2026-10-22, 140C_SCKF4: page 2,
the KBAS / KWID readouts and ranges, the kick-fundamental case at short attack and release,
MON and KEY declick, load with 1 + 7 and 4 + 4 COMPRESSOR / DJ EQ per core) and in the KYOTI
V1.6 combined image. The KEY switch and KWID's clip (2026-10-23): hardware-confirmed in the
standalone image. MON 2/3, KEY's step handler and the 256-sample fade (2026-10-25):
hardware-confirmed in the standalone image (140C_SCKD3). This Modwerk form is not flashed yet
(MW_SC020, 2026-10-24, had the key-filter table bug since fixed by ptable2).

MODWERK FORM. The same sources as octabam-modules/sidechain-compressor and the standalone
(tools/*), copied into this folder, which Modwerk imports as it is. Differences from the octabam
manifest: every stock expectation is an address/length/SHA-256 guard read from the builder's own
OS file (Modwerk ships no stock bytes); no PLACE setting or Store (Modwerk's remix schema has
neither, and links the units where its own builder puts them); author and category fields.

COLDFIRE. Two ROM units. sc_ui (ui_switch.s, 616 B; shared with VARISPEED's QUAN): KEY's
widget, a 9-position rotary switch (stock CHORUS TAPS's switch, as Spectrum's LADR, in 22.5-degree
steps: stock's five glyphs and four of its own), and KWID's, the stock knob plus the link clip to
KBAS, which the FX SETUP window does not draw itself. sc_cf (patch_sidechain.s, 698 B): MON's step handler, label and switch, KEY's step handler and
formatter, KBAS's Hz and KWID's octave formatters, and sc_norm, reached by a
`jsr` detour at the first instruction of both page-2 copiers (0x4000cae8, its twin
0x40003d1c). A COMPRESSOR saved on stock firmware holds stock's slot 8..11 defaults
0x7f/0/0/0, i.e. KEY 127; sc_norm resets any COMPRESSOR whose KEY is above 8 to MON OFF,
KEY OFF, KGN 64, KBAS OFF, KWID OFF, in the current part's working store and in the live lane,
each judged by its own FX id. A KEY of 0..8 is never touched.

DSP. MenuEntry(replaces="COMPRESSOR", stock_dsp=True): the effect IS stock COMPRESSOR, its
dispatch entry untouched. This module's code (patch_sc_dsp3.asm; sc_keyfilt.py is
the filters' bit-exact model) runs from four DspHooks:
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
hardware, 2026-10-19). The 16 KEY GAIN words are the ptable and the 49 key-filter words the ptable2.

CLAIMS. Core-private Y $7f0-$9ff (MON words, keybus) on both cores, and the last $202 words of
each core's half of the shared window (A $33dfe.., B $3bdfe..).

MEASURED. The ColdFire unit, linked at the standalone image's own address, is that image's
bytes. The DSP source is the standalone's, with the same per-core values; tools/emu_sc_dsp3.py
(the author's repository) --layout octabam (these addresses) is ALL GOOD: the filters bit-exact against the model, the
crossfade, the KEY hold.
"""

import importlib.util
import os

from remix.stock_guard import stock_dsp_words, stock_guard

from remix.schema import (Category, Claims, Detour, DspHook, DspRange, DspSection, Kind, Linked,
                          MenuEntry, Module, Param, YBase)

# This module's own directory, relative to the build's cwd; its sources sit beside it.
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))
_TOOLS = _HERE

# The standalone builder's tables and coefficients (sc_tables.py, plain Python).
_spec = importlib.util.spec_from_file_location("kyoti_sc_tables", os.path.join(_TOOLS, "sc_tables.py"))
_sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sc)
# The key filters' table and constants (sc_keyfilt.py, the DSP's bit-exact model).
_kspec = importlib.util.spec_from_file_location("kyoti_sc_keyfilt", os.path.join(_TOOLS, "sc_keyfilt.py"))
_kf = importlib.util.module_from_spec(_kspec)
_kspec.loader.exec_module(_kf)

E = 0x400d5a4a                  # stock COMPRESSOR's descriptor
FMT_BIPOLAR = 0x4003c7a0        # stock "-N" / "+N" about 64
FMT_ONOFF = 0x4003c14c          # stock "ON" / "OFF"
SWITCH_FN = 0x40046f10          # stock 2-position switch (FILTER's HOLD)

_SAME = {"@KGNA@": f"${_sc.kgn_smooth_a():x}",
         **_kf.asm_tokens(),
         # The keybus and MON words at Session 115's Y:$7f0..$9ff, which no FX2 slot reaches
         # (the standalone builder's KEYBUS puts them in the first internal slot's tail).
         "@KEYB@": "$800", "@KEYB1@": "$820", "@MONB@": "$7f0"}

# At the standalone image's own address (tools/build_sidechain_compressor.py).
LINKED = (
    Linked("sc_cf", os.path.join(_TOOLS, "patch_sidechain.s"),
           reference=(0x400d7000,
                      "976f9f958bf378f54d92f66719f9f59388aec7170efbe78c80b74d7ac7771a35")),
    Linked("sc_ui", os.path.join(_TOOLS, "ui_switch.s"),
           reference=(0x400d7300,
                      "b2c45834b780a1e8b361c1104fca7a875ad25fdcc89a578b6d13d2ec9d2d6978")),
)

MODULE = Module(
    name="sidechain-compressor",
    key="SIDECHAIN_COMPRESSOR",
    kind=Kind.DSP_EFFECT,
    author="Zac-Kyoti",
    author_url="https://github.com/Zac-Kyoti",
    category=Category.TRACK,
    doc="Stock COMPRESSOR with a side-chain KEY from any of T1-T8, "
        "key gain, a base-width key filter (KBAS high-pass in Hz, KWID low-pass in octaves above "
        "it) and a key listen switch on page 2.",
    menu=MenuEntry(fx2_id=0x18, donor_desc=E, abbr=b"COMP", fullname=b"COMPRESSOR",
                   replaces="COMPRESSOR", stock_dsp=True),
    # Slots 0-6 are stock COMPRESSOR's, unchanged: on a stock_dsp clone a Param() keeps the
    # donor's enable nibble and every other field (octabam #571). Page 2 since the major
    # version: RMS MON KEY KGN KBAS KWID. MON sits in stock's hidden slot 7: 2 = OFF, 3 = ON; sc_norm
    # turns an older compressor's 0/1 into OFF.
    params=tuple(Param(active=None, doc=d) for d in (
        "stock: attack time",
        "stock: release time",
        "stock: threshold",
        "stock: ratio",
        "stock: make-up gain",
        "stock: dry/wet mix",
        "stock: the detector's RMS setting")) + (
        Param(b"MON", 2, count=4, active=True,
              formatter_word=("sc_cf", "mon_fmt"), widget_word=("sc_cf", "mon_widget"),
              word_12a=("sc_cf", "mon_step"),   # 2 = OFF, 3 = ON; 0/1 = saved before, OFF
              labels=("OFF", "ON", "OFF", "ON"),
              doc="ON: this track plays its processed key instead (audition)"),
        Param(b"KEY", 0, count=9, active=True,
              formatter_word=("sc_cf", "key_fmt"), widget_word=("sc_ui", "sw9_widget"),
              word_12a=("sc_cf", "key_step"),   # a pressed turn steps like a plain one
              labels=("OFF", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"),
              doc="the track whose audio drives the detector; OFF = stock (self)"),
        Param(b"KGN", 64, count=128, active=True,
              formatter_word=FMT_BIPOLAR, widget_word=0,   # a plain knob, not the donor's widget
              doc="the key's gain, about -24..+24 dB; 64 = unity"),
        Param(b"KBAS", 0, count=128, active=True,
              formatter_word=("sc_cf", "hp_fmt"), widget_word=0,
              doc="the key's high-pass, 18 dB/oct: OFF, then 20 Hz to 19.6 kHz"),
        Param(b"KWID", 127, count=128, active=True, link=True,
              formatter_word=("sc_cf", "lp_fmt"), widget_word=("sc_ui", "clip_knob"),
              doc="the key's low-pass, 12 dB/oct: 0.5-9.9 octaves above KBAS (20 Hz if OFF), then OFF"),
    ),
    linked=LINKED,
    # sc_norm: a COMPRESSOR saved before SIDE-CHAIN existed holds stock's slot 8..11 defaults
    # 0x7f/0/0/0 and comes up with its side-chain OFF. Both page-2 copiers; sc_norm replays
    # the displaced `lea 0x80000a50,%a3` and returns.
    detours=(
        Detour(0x4000cae8, stock_guard(0x4000cae8, 6, "9a4b68c7876e6a4b172ba77e67b4305494b67444bae1a8e13c5f6e62ac6e7c2c"), "sc_cf", "sc_norm",
               "frame builder's page-2 copier: a stale KEY (> 8) -> side-chain defaults",
               kind="jsr"),
        Detour(0x40003d1c, stock_guard(0x40003d1c, 6, "9a4b68c7876e6a4b172ba77e67b4305494b67444bae1a8e13c5f6e62ac6e7c2c"), "sc_cf", "sc_norm",
               "the copier's twin: the same check", kind="jsr"),
    ),
    dsp=DspSection(
        asm=os.path.join(_TOOLS, "patch_sc_dsp3.asm"),
        priority=30,
        ybase=YBase.NEVER,            # COMPRESSOR is on FX1; the bases come from subst
        ptable=tuple(_sc.gain_table()),
        ptable2=tuple(_kf.GT),
        hooks=(
            DspHook({"A": 0x004a7, "B": 0x0029c}, stock_dsp_words("A", 0x004a7, 2, "92441a8fc9f1dd20359d87c8342e3d5653d8c853a274358df0cfc0451c57115b"), "sctap",
                    "dispatcher: publish every track's audio"),
            DspHook({"A": 0x01ab1, "B": 0x01871}, stock_dsp_words("A", 0x01ab1, 2, "114aacb95ee45437fff14f2dcd91b67e26d8bc42ef3ba2e9f6ae0cb8be1574fa"), "scdet",
                    "COMPRESSOR proc+0: the detector reads the KEY track"),
            DspHook({"A": 0x0050e, "B": 0x00303}, stock_dsp_words("A", 0x0050e, 2, "9dad4262559be3a41c85136d50f7d017f161cff9a609d17d21da895cd2137118"), "moncommit",
                    "dispatcher, per-track commit: MON"),
            DspHook({"A": 0x01aa4, "B": 0x01864}, stock_dsp_words("A", 0x01aa4, 2, "9eb96aa9abbf3d522e54911d6fa634dbcfc8820ad32d593e405bacc87193f305"), "scinit",
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
)
