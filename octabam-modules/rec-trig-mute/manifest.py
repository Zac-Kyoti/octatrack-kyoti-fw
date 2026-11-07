"""REC_TRIG_MUTE -- [TRACK]+[REC] toggles the held tracks' recorder trigs muted / unmuted.

The octabam form has not been flashed.  The [TRACK]+[REC] gesture (2026-10-29) replaced the
earlier [TRACK]+[NO] / [TRACK]+[YES]; both ran on the author's MKI (the new one inside KYOTI
V1.6, with its 1 s toast that closes on release).

The trigs stay in the pattern; the sequencer simply stops seeing them, so a recording
already running finishes its RLEN and nothing new starts.  Global across pattern / Part /
bank changes, volatile (power-up = unmuted).  Each held track flips its own state.  While a track key is held [REC] does not
switch GRID REC; without one [REC] is stock.  Toasts REC TRIGS MUTED / UNMUTED / TOGGLED
(mixed), 1.0 s like QUANTIZE_LIVE_REC_TOGGLE's, closed when the last track key is released.
MIDI CC 80: 0 = unmute, 1-127 = mute, on a track's channel (AUTO channel = active track),
gated by AUDIO CC IN; the keys send CC 80 (1 / 0) on each held track's channel, gated by
AUDIO CC OUT -- both exactly like stock's CC 52/53.  A muted track's tab shows two dots
stacked beside its machine letter, on the inner side (right of it on T1-4, left on T5-8).  [TRACK]+[YES]/[NO] and
[FUNC]+[YES]/[NO] stay stock.

SITES (our own disassembly of 1.40C; proofs: reference/handoffs/REC_TRIG_MUTE_SCOPE.md):
  * the base keymaps' [REC] records (T1 0x400bfc3a, T2 0x400c061e): press + release name
    stock's REC handler 0x40048774 -> repointed here; rtm_rec jumps back to 0x40048774 for
    everything but a press with a track key held (so a detour on 0x40048774 itself, e.g.
    STEM REC's UP+REC, still runs).  The [TRACK]-held layer 0x400d164a has no [REC] record;
  * the step handler's recorder-trig test at 0x4009d9a4 (`tst.l %d3` = REC1/2/3 of track
    d7) -- the only producer of recorder events (0x46c7a6c0 has three references);
  * the tab letter renderer 0x4003fed8 (audio mode redraws every letter cell on every UI
    poll): its PICKUP test (0x40040146), where rtm_dots adds the dots before the active-tab
    inversion;
  * the tab mark painter 0x40044804, which runs after it and rewrites the column of T1-4's dots
    (its '!'): its per-track end (0x400448ba), where rtm_mark writes the dots again;
  * the stock CC handler's fall-through for every CC it ignores (0x4000f210);
  * the track-key release handler 0x40083e40, where it clears the key's held bit (0x40083e84).

THE SOURCE is patch_rec_trig_mute.s here, one file for every layout.  The standalone
(tools/build_rec_trig_mute.py) and KYOTI builds reuse three unreachable stock routines for its code; here it
is one DRAM unit octabam places (--defsym OCTABAM_UNIT: a single section, RTM_MASK inside
the unit, the step-handler hook a plain jmp so octabam's nop padding can follow it).

MEASURED: the earlier [TRACK]+[NO]/[YES] form was hardware-confirmed on the author's MKI as
the standalone image and inside KYOTI -- keys, toasts, the edge icons, recording stopping and
resuming; MIDI CC 80 not tried on hardware.  The [TRACK]+[REC] form (toggle + the 1.0 s toast
closed on release) ran on the same MKI inside KYOTI V1.6 on 29 Oct 2026 ("all good").  The
dots beside the tab letter (6 Nov 2026, replacing the "..[]" / "..>" status icons) are checked
pixel by pixel in the emulator, not yet on hardware.  This octabam form (the OCTABAM_UNIT variant) has not been
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
# tab letter renderer: `moveq #4,%d0 ; cmpl %a4,%d0 ; bnes 0x400401c6` -- rtm_dots replays
# the PICKUP test and draws the dots for a muted track
DOTS = 0x40040146
DOTS_STOCK = bytes.fromhex("7004b08c667a")
# stock's mark painter 0x40044804 (after both tab renderers, every UI pass): its per-track end
# `addq.l #1,%d4 ; lea 32(%sp),%sp` -- it rewrites the T1-4 dot column, so rtm_mark writes the
# dots again there (and clears its '!' under them)
MARK = 0x400448ba
MARK_STOCK = bytes.fromhex("52844fef0020")
# CC handler fall-through: `moveq #119,%d6 ; cmp.l %d1,%d6 ; bge 0x4000f274`
CC = 0x4000f210
CC_STOCK = bytes.fromhex("7c77bc816c5e")
# track-key release 0x40083e40: `and.l %d0,0x460fab40` clears the key's held bit -- rtm_trel
# replays it and closes our toast once no track key is held
TREL = 0x40083e84
TREL_STOCK = bytes.fromhex("c1b9460fab40")

# the base keymaps' [REC] records (T1 0x400bfc3a, T2 0x400c061e): press + release fields
REC_FIELDS = (0x400c003c, 0x400c0040, 0x400c0620, 0x400c0624)
REC_STOCK = 0x40048774              # stock [REC]: GRID REC toggle, "REC held"

# ---- the author's oracle -------------------------------------------------------
# tools/build_rec_trig_mute.py builds this on every run, with octabam's own DRAM-unit oracle
# recipe (m68k-elf-as -mcpu=54455 --defsym OCTABAM_UNIT=0x1; ld -Ttext=0x40000000 + the same
# defsym; objcopy -O binary), and refuses if this line no longer matches.
REFERENCE = (0x40000000, "39377c4ed7140925f4d3e5a4f3cd1a14796df3b40901ec7c3abd0426644157b1")


MODULE = Module(
    name="rec-trig-mute",
    key="REC_TRIG_MUTE",
    kind=Kind.CF_PATCH,
    doc="[TRACK]+[REC] mutes/unmutes the held tracks' recorder trigs; MIDI CC 80; "
        "'..' beside a muted track's tab letter.",
    linked=(
        Linked("rtm", os.path.join(_HERE, "patch_rec_trig_mute.s"), dram=True,
               defsyms=(("OCTABAM_UNIT", 1),), reference=REFERENCE),
    ),
    detours=(
        Detour(GATE, GATE_STOCK, "rtm", "rtm_gate",
               "step handler: a muted track's step has no recorder trig", pad_to=10),
        Detour(DOTS, DOTS_STOCK, "rtm", "rtm_dots",
               "tab letter renderer: two dots beside a muted track's letter"),
        Detour(MARK, MARK_STOCK, "rtm", "rtm_mark",
               "tab mark painter: the T1-4 dots again after its column (it runs last)"),
        Detour(CC, CC_STOCK, "rtm", "rtm_cc",
               "CC handler fall-through: CC 80, else stock's compare replayed"),
        Detour(TREL, TREL_STOCK, "rtm", "rtm_trel",
               "track-key release: close our toast once no track key is held", kind="jsr"),
    ),
    symbol_refs=tuple(
        SymbolRef(a, REC_STOCK, "rtm", "rtm_rec", "[REC] keymap record: track held -> toggle")
        for a in REC_FIELDS
    ),
)
