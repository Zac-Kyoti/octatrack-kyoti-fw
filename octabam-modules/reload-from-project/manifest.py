"""RELOAD_FROM_PROJECT -- reload ONE track's sequence from the CF card WITHOUT
stopping the transport.

Stock can only reload a whole bank, and doing so stops the sequencer. Two direct
chords, no modal window and no timeout:

    [PTN]  + [TRACK n]   reload that track's card-saved sequence, Part untouched
    [BANK] + [TRACK n]   the same, and re-apply the saved Part

It reloads the pattern that is PLAYING, on an audio or a MIDI track, and never
restarts the sequence or the internal metronome. A stock-style toast confirms when
the reload has FINISHED -- and says so if the trigs did not land.

Deferred by the author's own scoping: all-tracks and whole-bank reload.

HOW IT GOT HERE. An earlier design (RELOAD2) put a modal picker window on a
[PTN]-hold with arrow navigation; it needed ten detours and a keymap-layer poke,
and that poke was the mechanism behind a slot collision with DIRECT JUMP and
several routing bugs. This is the Session 85 redesign: six detours, two plain
chords, and NEITHER chord site pokes a keymap layer record. Full RE and design
rationale: patch_reload3.s's own header; dynamic proof against the real stock
layer-push code: NOTES.md Session 85.

⚠️ NO PRIVATE STATE IN THE DSP WINDOW. RELOAD_FROM_PROJECT's request bytes used to live at
0x80006a54-55, in the 0x80006a40+ scratch block. On hardware they were overwritten
between the chord and the worker: it reloaded MIDI track 6 instead of audio track 1
and cheerfully said RELOADED (Session 98). Everything now lives in the cave, and the
standalone builder refuses any reference into 0x80006a40..0x80006abf.

The worker itself (message case 0x14, rl_job) is stock's own; this module hooks it
rather than reimplementing it.

IN DRAM. In octabam this is a Linked(dram=True) unit: octabam's loader unpacks it
into the platform reserve at the bottom of the audio page arena at every boot, and
the six detours jump there. It moved out of the ROM cave so that every KYOTI module
fits one remix (octabam's floating ROM run is ~4.2 KB; the six need ~6.6 KB). It is
the one that moved because it runs from key chords and the message worker, never on
the per-step tick. Its state still lives in the unit itself, not the DSP window.

MEASURED: hardware-confirmed on the author's MKI from ROM (the standalone image and
KYOTI V1.0), including that the sequencer and the internal metronome keep their phase
(RELOAD_NOW is not armed on any path). Not yet run from DRAM on hardware.
The standalone image is tools/build_reload_from_project.py.
"""

import os

from remix.schema import Detour, Kind, Linked, Module

_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

# ---- the six hook sites, all `jmp` (the unit replays and rejoins stock) --------
# Two are EIGHT-byte spans: the jmp is six, so one nop follows, or the displaced
# span would be left half-rewritten.
HOOKS = (
    # (site, stock bytes, symbol, span, what)
    (0x40083dc4, "2f02242f0008",     "rl3_ptn_trk",   6, "[PTN] + [TRACK n]"),
    (0x40040250, "2f02222f0008",     "rl3_bank_trk",  6, "[BANK] + [TRACK n]"),
    (0x4007af42, "487a04c442a7",     "rl3_bank_show", 6, "[BANK] display"),
    (0x4007b3e0, "7002b0b9460e73c6", "rl3_bank_rel",  8, "[BANK] release"),
    (0x40023c62, "71f9460bd910",     "rl_done",       6, "the FINISHED toast"),
    (0x40085864, "2d4afd762f2a0004", "rl_job",        8, "message case 0x14 worker"),
)

# ---- the author's oracle -------------------------------------------------------
# patch_reload3.s, m68k-elf-as -mcpu=5407 or 54455 (identical bytes; RL_DONE is the
# source's default), linked at 0x400d6500 -- the address the standalone,
# hardware-confirmed image uses: 2088 bytes. octabam re-links it there on every build
# and compares.
REFERENCE = (0x400d6500, "ef22237d38c24966e8bd5353a8cb05b020a33a655925e8fe90ee6f84d5e819c4")

MODULE = Module(
    name="reload-from-project",
    key="RELOAD_FROM_PROJECT",
    kind=Kind.CF_PATCH,
    doc="Reload one track's sequence from the card without stopping the "
        "transport: [PTN]+[TRACK n], or [BANK]+[TRACK n] to re-apply the Part.",
    linked=(
        Linked("rl3", os.path.join(_HERE, "patch_reload3.s"), dram=True,
               reference=REFERENCE),
    ),
    detours=tuple(
        Detour(site, bytes.fromhex(stock), "rl3", sym, what, pad_to=span if span > 6 else None)
        for site, stock, sym, span, what in HOOKS
    ),
)
