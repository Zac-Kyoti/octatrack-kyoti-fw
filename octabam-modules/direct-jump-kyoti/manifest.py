"""DIRECT_JUMP_KYOTI -- an optional immediate pattern change, toggled from the
front panel with [PTN] + [YES] (a toast confirms; it comes up OFF at every
power-on, so a unit that never enables it behaves exactly as stock).

A cued pattern takes over on the NEXT STEP instead of waiting for the current
one to finish, and the landing is LOCKED TO THE MASTER CLOCK: the new pattern
plays exactly where it would be had it been running since START, whatever its
track lengths, scales or master settings -- never shifted by a step, never a
fraction of a step off, and its first trig always wins. The Part, START SILENT
and trig conditions change as on a stock pattern change, and the last MIDI
Program Change sent always names the pattern that plays. The arranger and
pattern chains are untouched. (The Analog Rytm's own DIRECT JUMP, by contrast,
lands shifted or fractional whenever lengths or scales differ; that difference
is what V6.4 froze as the OT<->AR parity build and V7 moved past.)

HOW IT LANDS. OT already has a synchronous re-landing as stock code, behind the
countdown byte 0x80006687 in phase D of its tick handler. V7 therefore adds no
new sequencer mechanism: it arms that countdown and prepares the snapshot on the
landing tick (ACT<-PEND, master step, per-track step/counter), suppresses the
MIDI START (0xFA) a jump must not send, and owns the [PTN]-held [YES] key.
The pattern-boundary body, the rebuild loops and every per-track counter are
STOCK. Design: reference/handoffs/DIRECTJUMP_V7_DESIGN.md; the sequencer bugs
found on the way: reference/OT_SEQUENCER_BUGS.md.

STATE. One word, DJ_MODE (0 = OFF/stock, 1 = ON), kept INSIDE the code unit -- the
source's default (DJ_MODE_IN_CAVE); only the standalone builder asks for the old
0x800000d8 word, with DJ_MODE_IN_RAM=1. DIRECT JUMP is a performance feature and must
come up OFF at every power-on. In octabam the unit is a Linked(dram=True) unit that
octabam's loader unpacks into the platform reserve at every boot, so the word starts at
0 by construction; no battery restore can reach it.

That is what makes it safe next to MUTE_MODES, which widens the boot 'ANDY' restore
(`pea 0x64` -> `pea 0x70` at 0x4001f322 / 0x4001f3be / 0x4001fb24) so its own word
0x800000dc survives power-off. The widened span 0x80000070..0x800000df sweeps
0x800000d8 -- where DJ_MODE lived before, and where the standalone builder still keeps
it (reference/MERGE.md, blocker B1).

IN DRAM. octabam's floating ROM run (~4.2 KB with stock effects in the chooser) cannot
hold every KYOTI module, so this unit and RELOAD_FROM_PROJECT live in DRAM. The DRAM
reserve is the same cached SDRAM the OS image runs from, so the tick-path code runs at
the same speed; what DRAM adds is the dependency on octabam's loader at boot.

MEASURED. Hardware-confirmed on the author's MKI 2026-09-27/28 (from the ROM cave):
the clock-locked timing and the Part change. Not yet run from DRAM on hardware. Emulator-verified only (ot_emu, real image bytes):
Program Change on fast re-cues, MIDI tracks, START SILENT and the trig-condition
reset (the last two identical to a stock pattern change in the emulator).
Standalone image and version string: tools/build_direct_jump_kyoti.py -> 140C_KDJ7.
"""

import os

from remix.schema import Detour, Keep, Kind, Linked, Module, SymbolRef

# This module's own directory, relative to the build's cwd (octabam's repo
# root): "modules/direct-jump-kyoti" checked out directly, and
# "modules/direct-jump-kyoti/upstream/octabam-modules/direct-jump-kyoti" as octabam's submodule
# of Zac-Kyoti/octatrack-kyoti-fw. The source path below is built from it, so
# one manifest serves both layouts.
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

# ---- the three hook sites ----------------------------------------------------
# Phase D of the tick handler: the countdown read this cave arms.
LAND_HOOK = 0x400a1f72
LAND_HOOK_STOCK = bytes.fromhex("103980006687")        # move.b (0x80006687).l,%d0
# The MIDI START a jump must not send.
NOFA_HOOK = 0x400a221c
NOFA_HOOK_STOCK = bytes.fromhex("4a398000002a")        # tst.b (0x8000002a).l
# [PTN] release: the chooser must not open when [PTN]+[YES] was the gesture.
PTNREL_HOOK = 0x40043418
PTNREL_HOOK_STOCK = bytes.fromhex("4879400bf0f2")      # pea 0x400bf0f2

# The [PTN]-held keymap layer (0x400bf0f2): the 26-byte record for YES (key code
# 0x31) is all-NULL in stock, so the press slot is a free function pointer.
PTN_LAYER_YES = 0x400bf0be
PTN_LAYER_YES_STOCK = bytes([0x31, 0x00]) + bytes(24)
PTN_LAYER_YES_PRESS = PTN_LAYER_YES + 2                # the u32 press handler

# ---- the author's oracle -------------------------------------------------------
# patch_directjump_v7.s, m68k-elf-as -mcpu=5407 or 54455 (identical bytes), no symbols
# (DJ_MODE in the unit and DJ_TOAST_DUR = 0x44 are the source's defaults), linked at
# 0x400d6d38: byte for byte the DIRECT JUMP code of the promoted KYOTI V1.0 image the
# author flashed (syx 576756fd...). octabam re-links it there on every build and compares.
REFERENCE = (0x400d6d38, "b86e3c3255674ceff539423ad45f3c747649be5b6615fd2cf95ee98f310b070e")

MODULE = Module(
    name="direct-jump-kyoti",
    key="DIRECT_JUMP_KYOTI",
    kind=Kind.CF_PATCH,
    doc="Clock-locked DIRECT JUMP ([PTN]+[YES]): a cued pattern lands on the "
        "next step exactly where it would be had it played since START.",
    # Tim Hastie's DIRECT JUMP (modules/direct-jump) shares no address with this one,
    # but both change WHEN a cued pattern takes over; untested together.
    conflicts=(("DIRECT JUMP",
                "both change when a cued pattern takes over (CHAIN AFTER = DIRECT vs "
                "[PTN]+[YES]); never tested together -- take one"),),
    linked=(
        Linked("dj7", os.path.join(_HERE, "patch_directjump_v7.s"), dram=True,
               reference=REFERENCE),
    ),
    detours=(
        Detour(LAND_HOOK, LAND_HOOK_STOCK, "dj7", "dj_land",
               "phase-D countdown read: arm the stock re-landing", kind="jsr"),
        Detour(NOFA_HOOK, NOFA_HOOK_STOCK, "dj7", "dj_nofa",
               "no MIDI START (0xFA) on a jump", kind="jsr"),
        Detour(PTNREL_HOOK, PTNREL_HOOK_STOCK, "dj7", "dj_ptnrel",
               "[PTN] release: keep the chooser shut after [PTN]+[YES]"),
    ),
    symbol_refs=(
        SymbolRef(PTN_LAYER_YES_PRESS, 0, "dj7", "dj_toggle",
                  "[PTN]-layer YES press handler (all-NULL record in stock)"),
    ),
    # The rest of that 26-byte record stays stock: its key code, and the 20 bytes after
    # the press pointer. Another module writing into it is refused by the ledger.
    keeps=(
        Keep(PTN_LAYER_YES, PTN_LAYER_YES_STOCK[:2], "[PTN]-layer record: key code YES"),
        Keep(PTN_LAYER_YES_PRESS + 4, PTN_LAYER_YES_STOCK[6:],
             "[PTN]-layer YES record after the press slot"),
    ),
)
