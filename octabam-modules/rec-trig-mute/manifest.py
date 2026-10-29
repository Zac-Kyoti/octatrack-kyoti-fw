"""REC_TRIG_MUTE -- [TRACK]+[REC] toggles the held tracks' recorder trigs muted / unmuted.

The octabam form has not been flashed.  The [TRACK]+[REC] gesture (2026-10-29) replaced the
earlier [TRACK]+[NO] / [TRACK]+[YES]; the earlier form was hardware-confirmed as the standalone
image and inside KYOTI, the [TRACK]+[REC] form not yet.

The trigs stay in the pattern; the sequencer simply stops seeing them, so a recording
already running finishes its RLEN and nothing new starts.  Global across pattern / Part /
bank changes, volatile (power-up = unmuted).  With several track keys held, [REC] mutes them
all unless all are already muted, which unmutes them.  While a track key is held [REC] does not
switch GRID REC; without one [REC] is stock.  Toasts REC TRIGS MUTED / REC TRIGS UNMUTED.
MIDI CC 80: 0 = unmute, 1-127 = mute, on a track's channel (AUTO channel = active track),
gated by AUDIO CC IN; the keys send CC 80 (1 / 0) on each held track's channel, gated by
AUDIO CC OUT -- both exactly like stock's CC 52/53.  The track-edge status icon shows
"..[]" / "..>" on a muted track that is not recording.  [TRACK]+[YES]/[NO] and
[FUNC]+[YES]/[NO] stay stock.

SITES (our own disassembly of 1.40C; proofs: reference/handoffs/REC_TRIG_MUTE_SCOPE.md):
  * the base keymaps' [REC] records (T1 0x400bfc3a, T2 0x400c061e): press + release name
    stock's REC handler 0x40048774 -> repointed here; rtm_rec jumps back to 0x40048774 for
    everything but a press with a track key held (so a detour on 0x40048774 itself, e.g.
    STEM REC's UP+REC, still runs).  The [TRACK]-held layer 0x400d164a has no [REC] record;
  * the step handler's recorder-trig test at 0x4009d9a4 (`tst.l %d3` = REC1/2/3 of track
    d7) -- the only producer of recorder events (0x46c7a6c0 has three references);
  * the edge renderer 0x4004bd48: its state cache load (0x4004bee2) and its 4-way draw
    switch (0x4004c00c);
  * the stock CC handler's fall-through for every CC it ignores (0x4000f210).

THE SOURCE is patch_rec_trig_mute.s here, one file for every layout.  The standalone
(tools/build_rec_trig_mute.py) and KYOTI builds reuse three unreachable stock routines for its code; here it
is one DRAM unit octabam places (--defsym OCTABAM_UNIT: a single section, RTM_MASK inside
the unit, the step-handler hook a plain jmp so octabam's nop padding can follow it).

MEASURED: the earlier [TRACK]+[NO]/[YES] form was hardware-confirmed on the author's MKI as
the standalone image and inside KYOTI -- keys, toasts, the edge icons, recording stopping and
resuming; MIDI CC 80 not tried on hardware.  The [TRACK]+[REC] form is emulator-checked only
(tools/emu_rec_trig_mute.py).  This octabam form (the OCTABAM_UNIT variant) has not been
flashed; its `reference` is the author's build of that form, made by
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

# the base keymaps' [REC] records (T1 0x400bfc3a, T2 0x400c061e): press + release fields
REC_FIELDS = (0x400c003c, 0x400c0040, 0x400c0620, 0x400c0624)
REC_STOCK = 0x40048774              # stock [REC]: GRID REC toggle, "REC held"

# ---- the author's oracle -------------------------------------------------------
# tools/build_rec_trig_mute.py builds this on every run, with octabam's own DRAM-unit oracle
# recipe (m68k-elf-as -mcpu=54455 --defsym OCTABAM_UNIT=0x1; ld -Ttext=0x40000000 + the same
# defsym; objcopy -O binary), and refuses if this line no longer matches.
REFERENCE = (0x40000000, "14f5c3eeae873d8c538bc0f130d57109fce9508e81193ef329d97b30884dc8ca")


MODULE = Module(
    name="rec-trig-mute",
    key="REC_TRIG_MUTE",
    kind=Kind.CF_PATCH,
    doc="[TRACK]+[REC] mutes/unmutes the held tracks' recorder trigs; MIDI CC 80; "
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
        SymbolRef(a, REC_STOCK, "rtm", "rtm_rec", "[REC] keymap record: track held -> toggle")
        for a in REC_FIELDS
    ),
)
