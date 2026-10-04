"""REC_TRIG_MUTE -- [TRACK]+[NO] mutes, [TRACK]+[YES] unmutes the held tracks' recorder trigs.

The octabam form has not been flashed; the same source is hardware-confirmed as the standalone
image and inside KYOTI V1.0.

The trigs stay in the pattern; the sequencer simply stops seeing them, so a recording
already running finishes its RLEN and nothing new starts.  Global across pattern / Part /
bank changes, volatile (power-up = unmuted).  Toasts REC TRIGS MUTED / REC TRIGS UNMUTED.
MIDI CC 80: 0 = unmute, 1-127 = mute, on a track's channel (AUTO channel = active track),
gated by AUDIO CC IN; the keys send CC 80 (1 / 0) on each held track's channel, gated by
AUDIO CC OUT -- both exactly like stock's CC 52/53.  The track-edge status icon shows
"..[]" / "..>" on a muted track that is not recording.  [FUNC]+[YES]/[NO] stay stock.

SITES (our own disassembly of 1.40C; proofs: reference/handoffs/REC_TRIG_MUTE_SCOPE.md):
  * the [TRACK]-held input layer 0x400d164a: its YES / NO records (0x400d15e2 / 0x400d15fc)
    name stock's ARM / DISARM REC TRK handlers 0x400834d8 / 0x40083488 -> repointed here;
  * the step handler's recorder-trig test at 0x4009d9a4 (`tst.l %d3` = REC1/2/3 of track
    d7) -- the only producer of recorder events (0x46c7a6c0 has three references);
  * the edge renderer 0x4004bd48: its state cache load (0x4004bee2) and its 4-way draw
    switch (0x4004c00c);
  * the stock CC handler's fall-through for every CC it ignores (0x4000f210).

THE SOURCE is patch_rec_trig_mute.s here, one file for every layout.  The standalone
(tools/build_rec_trig_mute.py) and KYOTI V1.0 builds reuse four unreachable stock routines for its code; here it
is one DRAM unit octabam places (--defsym OCTABAM_UNIT: a single section, RTM_MASK inside
the unit, the step-handler hook a plain jmp so octabam's nop padding can follow it).

MEASURED: the standalone image (syx c1cd7381...) and KYOTI V1.0 (syx 5106f7fb...) are
hardware-confirmed on the author's MKI -- keys, toasts, the edge icons, recording stopping
and resuming; MIDI CC 80 not tried on hardware.  This octabam form (the OCTABAM_UNIT variant)
has not been flashed; its `reference` is the author's build of that form, made by
tools/build_rec_trig_mute.py with octabam's own oracle recipe.
"""

import os

from remix.schema import Detour, Kind, Linked, Module, SymbolRef

_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

# step handler: `tst.l %d3 ; beq.s 0x4009da16 ; move.l #0x91a,%d2` (10 B).  rtm_gate
# replays the move, then jmp 0x4009da16 (no recorder trig) or 0x4009d9ae (go on).
GATE = 0x4009d9a4
GATE_STOCK = bytes.fromhex("4a83676e243c0000091a")
# edge renderer: `lea 0x400c0cb8,%a0` -- rtm_glyph folds the mute into a4 and redoes it
GLYPH = 0x4004bee2
GLYPH_STOCK = bytes.fromhex("41f9400c0cb8")
# edge renderer: `moveq #3,%d0 ; cmpl %a4,%d0 ; bnes 0x4004c02a` -- rtm_draw adds 8 / 9
DRAW = 0x4004c00c
DRAW_STOCK = bytes.fromhex("7003b08c6618")
# CC handler fall-through: `moveq #119,%d6 ; cmp.l %d1,%d6 ; bge 0x4000f274`
CC = 0x4000f210
CC_STOCK = bytes.fromhex("7c77bc816c5e")

# the [TRACK]-held layer's YES / NO records: press + release handler fields
TRK_YES = (0x400d15e4, 0x400d15e8)
TRK_YES_STOCK = 0x400834d8          # ARM REC TRK
TRK_NO = (0x400d15fe, 0x400d1602)
TRK_NO_STOCK = 0x40083488           # DISARM REC TRK

# ---- the author's oracle -------------------------------------------------------
# tools/build_rec_trig_mute.py builds this on every run, with octabam's own DRAM-unit oracle
# recipe (m68k-elf-as -mcpu=54455 --defsym OCTABAM_UNIT=0x1; ld -Ttext=0x40000000 + the same
# defsym; objcopy -O binary), and refuses if this line no longer matches.
REFERENCE = (0x40000000, "d49e0d82ec7fe66fad0c3eb67b41c2a1e892af0db6320bae1ae745997edf5f19")


MODULE = Module(
    name="rec-trig-mute",
    key="REC_TRIG_MUTE",
    kind=Kind.CF_PATCH,
    doc="[TRACK]+[NO]/[YES] mute/unmute the held tracks' recorder trigs; MIDI CC 80; "
        "'..' beside a muted track's status icon.",
    linked=(
        Linked("rtm", os.path.join(_HERE, "patch_rec_trig_mute.s"), dram=True,
               defsyms=(("OCTABAM_UNIT", 1),), reference=REFERENCE),
    ),
    detours=(
        Detour(GATE, GATE_STOCK, "rtm", "rtm_gate",
               "step handler: a muted track's step has no recorder trig", pad_to=10),
        Detour(GLYPH, GLYPH_STOCK, "rtm", "rtm_glyph",
               "edge renderer: fold the mute into the cached state", kind="jsr"),
        Detour(DRAW, DRAW_STOCK, "rtm", "rtm_draw",
               "edge renderer: draw '..[]' / '..>' for states 8 / 9"),
        Detour(CC, CC_STOCK, "rtm", "rtm_cc",
               "CC handler fall-through: CC 80, else stock's compare replayed"),
    ),
    symbol_refs=tuple(
        SymbolRef(a, TRK_YES_STOCK, "rtm", "rtm_yes", "[TRACK]-layer YES record") for a in TRK_YES
    ) + tuple(
        SymbolRef(a, TRK_NO_STOCK, "rtm", "rtm_no", "[TRACK]-layer NO record") for a in TRK_NO
    ),
)
