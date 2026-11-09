"""RELOAD_FROM_PROJECT -- reload one track, or one pattern, from the CF card WITHOUT
stopping the transport.

Stock can only reload a whole bank, and doing so stops the sequencer. Two direct
chords, no modal window and no timeout:

    [PTN]  + [TRACK n]   reload that track's card-saved sequence, Part untouched
    [BANK] + [TRACK n]   the same, and that track's slice of the Part as the project
                         was saved (machine, FX, every page, scene locks, LFO designer);
                         every other track and the rest of the Part are left alone
    [PTN] + [BANK] + trig N  pattern N of the playing bank -- all its tracks and its
                         Part -- as the project was saved; then the OT goes to it

It reloads the pattern that is PLAYING, on an audio or a MIDI track, and never
restarts the sequence or the internal metronome. A stock-style toast confirms when
the reload has FINISHED -- and says so if the trigs did not land.

Deferred by the author's own scoping: whole-bank reload.

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

THE PART SLICE (2026-11-08). [BANK] + [TRACK n] used to run stock's PART RELOAD: the
WHOLE Part, from its SAVE PART copy in RAM, so every other track on that Part reverted
too. It now does what the author's CLYPS card reload does: the worker reads the bank
file's working PART chunk (a direct seek, chunk-by-chunk as the fallback), copies track
n's slice into the Part the pattern links to now, and publishes it for that track alone
(audio: stock's per-track apply 0x40001f18; MIDI: one track of stock's Part apply). The
UI half -- PICKUP setup after a new machine, the page redraw -- runs in the job's doneFn,
which stock calls on the UI task.

THE PATTERN RELOAD (2026-11-08), CLYPS' as well. Neither the [PTN] nor the [BANK] keymap layer
has a record for the other key, so the chord's second key pushes its own layer on top and the
trig goes to whichever came last (the [PTN] layer's trig, 0x40056b2c, is KITS' detour). Two
detours make the chord one state in either order: [PTN]'s press with [BANK] held runs stock's
press, then puts [BANK]'s keymap layer back on top; [BANK]'s trig press is ours while both are
held. Both releases are silent (no SELECT PATTERN, no SELECT BANK), the grid shows [PTN]'s LED
layer. The worker lands the whole slab with its saved Part link and that whole working Part,
applies it when it is sounding, and doneFn cues the pattern as stock's [PTN] + trig does.

QUANTIZED (2026-11-08, the author's request: CLYPS' temp-reload landing for card reloads). The
worker stages the card's data in the unit (a pattern slab + its Part, ~43 KB: why the unit is
48 KB) and, while the transport runs, the sequencer tick lands it: phase D (0x400a2530, where
every path of phase D meets, one site after DIRECT JUMP KYOTI's 0x400a1f72) at the next step
start of the track -- old and new rate, phase-continuous counters -- or, for a pattern, at the
next step all 16 tracks share; the wrap body (0x400a43a0) at a master wrap, and for a reload that
changes the pattern's own length / scale. The slice and the Part go to the engine in the same
tick, per track (stock's whole-Part apply posts a kernel message, so it is left to the UI half).
The UI task's 1/60 s tick (0x40056c28) runs the UI half after the landing, and lands a reload
still pending when the transport stops. Stopped, or the target not playing: at once.

IN DRAM. In octabam this is a Linked(dram=True) unit: octabam's loader unpacks it
into the platform reserve at the bottom of the audio page arena at every boot, and
the eight detours jump there. It moved out of the ROM cave so that every KYOTI module
fits one remix (octabam's floating ROM run is ~4.2 KB; the six need ~6.6 KB). It is
the one that moved because it runs from key chords and the message worker, never on
the per-step tick. Its state still lives in the unit itself, not the DSP window.

MEASURED: hardware-confirmed on the author's MKI from ROM (the standalone image and
KYOTI V1.0), including that the sequencer and the internal metronome keep their phase
(RELOAD_NOW is not armed on any path), and from DRAM in an octabam-built image with all
six KYOTI modules (2026-10-01: both chords, the FINISHED toast, the knob repaint).
The standalone image is tools/build_reload_from_project.py.
"""

import os

from remix.schema import Detour, Kind, Linked, Module

_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

# ---- the eleven hook sites, all `jmp` (the unit replays and rejoins stock) --------
# Three are EIGHT-byte spans: the jmp is six, so one nop follows, or the displaced
# span would be left half-rewritten.
HOOKS = (
    # (site, stock bytes, symbol, span, what)
    (0x40083dc4, "2f02242f0008",     "rl3_ptn_trk",   6, "[CUE] sub-map TRACK, [PTN] held"),
    (0x40040250, "2f02222f0008",     "rl3_bank_trk",  6, "[BANK] + [TRACK n]"),
    (0x4007af42, "487a04c442a7",     "rl3_bank_show", 6, "[BANK] display"),
    (0x4007b3e0, "7002b0b9460e73c6", "rl3_bank_rel",  8, "[BANK] release"),
    (0x40023c62, "71f9460bd910",     "rl_done",       6, "the FINISHED toast"),
    (0x40085864, "2d4afd762f2a0004", "rl_job",        8, "message case 0x14 worker"),
    (0x4005a044, "202f00087201",     "rl3_ptn_key",   6, "[PTN] press with [BANK] held"),
    (0x4007b2fc, "2f0a2f02242f000c", "rl3_bank_trig", 8, "[BANK]-layer trig, [PTN] held"),
    (0x400a2530, "4ab946c8028a",     "rl_tick",       6, "phase D of the sequencer tick: the landing"),
    (0x400a43a0, "201274018082",     "rl_wrap",       6, "the wrap body: a landing at a master wrap"),
    (0x40056c28, "2039460d1e6c",     "rl_uitick",     6, "the UI task's 1/60 s tick: the UI half"),
)

# ---- the author's oracle -------------------------------------------------------
# patch_reload3.s, m68k-elf-as -mcpu=5407 or 54455 (identical bytes; RL_DONE is the
# source's default), linked at 0x400d6500 -- the address the standalone image uses:
# 48224 bytes: ~5 KB of code + the 43 KB staging buffers of the quantized landing (2100 before the
# 8 Nov 2026 Part-slice, pattern and quantized reloads). octabam re-links it there on every build
# and compares.
REFERENCE = (0x400d6500, "fc43e76c73ba2122ec3e7a785c1484109ed99b097a3a5e3d41fbd9b22be2f30e")

MODULE = Module(
    name="reload-from-project",
    key="RELOAD_FROM_PROJECT",
    kind=Kind.CF_PATCH,
    doc="Reload from the card without stopping the transport: [PTN]+[TRACK n] "
        "a track's sequence, [BANK]+[TRACK n] with its machine and effects too, "
        "[PTN]+[BANK]+trig a whole pattern (then the OT goes to it).",
    # Until 2026-11-08 [BANK]+[TRACK n] called stock Part RELOAD (0x4004aab4). Octakit
    # replaces that routine and traps (`illegal`) unless the caller is the menu Part
    # Reload (0x4002dd5c) or FUNC+CUE (0x4005e060), so the pair crashed on the first use.
    # That call is gone, but the slice reload now calls stock's per-track apply
    # 0x40001f18, which Octakit's runtime also names, and the pair has never been run
    # together. Still refused (reference/handoffs/DIRECTJUMP_OCTAKIT_SCOPE.md).
    conflicts=(("OCTAKIT",
                "never run together: [BANK]+[TRACK n] calls stock's per-track Part apply, "
                "which Octakit's runtime also uses (until 2026-11-08 it called the stock "
                "Part reload, which Octakit traps on) -- take one"),),
    linked=(
        Linked("rl3", os.path.join(_HERE, "patch_reload3.s"), dram=True,
               reference=REFERENCE),
    ),
    detours=tuple(
        Detour(site, bytes.fromhex(stock), "rl3", sym, what, pad_to=span if span > 6 else None)
        for site, stock, sym, span, what in HOOKS
    ),
)
