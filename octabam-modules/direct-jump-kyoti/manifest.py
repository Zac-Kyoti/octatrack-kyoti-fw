"""DIRECT_JUMP_KYOTI -- an optional immediate pattern change, toggled from the
front panel with [PTN] + [YES] (a toast confirms; it comes up OFF at every
power-on, so a unit that never enables it behaves exactly as stock).

A cued pattern takes over on the NEXT STEP instead of waiting for the current
one to finish, and the landing is LOCKED TO THE MASTER CLOCK: the new pattern
plays exactly where it would be had it been running since START, whatever its
track lengths, scales or master settings -- never shifted by a step, never a
fraction of a step off, and its first trig always wins. START SILENT and the Part's
pattern-wide settings (scenes, the Part itself) change as on a stock pattern change; each
track's own Part settings reach the engine with that track's first sounding trig of the new
pattern (V7.2), so a sound still ringing from the old pattern never takes the new
settings; trig conditions stand where the new pattern's would, had it played since START
(V7.0.2), and the last MIDI
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

MEASURED. Hardware-confirmed on the author's MKI: the clock-locked timing and the Part
change, from the ROM cave (2026-09-27/28) and from DRAM in an octabam-built image with
all six KYOTI modules (2026-10-01; also OFF at power-on, the PTN+YES toggle, OFF again
after a power cycle). Emulator-verified only (ot_emu, real image bytes):
Program Change on fast re-cues, MIDI tracks, START SILENT (identical to a stock
pattern change in the emulator) and V7.0.2's trig conditions (equal to a never-switched
reference run at every tick, tools/cmp_reflock.py --cond; not flashed).
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

# ---- the four hook sites -----------------------------------------------------
# Phase D of the tick handler: the countdown read this cave arms.
LAND_HOOK = 0x400a1f72
LAND_HOOK_STOCK = bytes.fromhex("103980006687")        # move.b (0x80006687).l,%d0
# The MIDI START a jump must not send.
NOFA_HOOK = 0x400a221c
NOFA_HOOK_STOCK = bytes.fromhex("4a398000002a")        # tst.b (0x8000002a).l
# [PTN] release: the chooser must not open when [PTN]+[YES] was the gesture.
PTNREL_HOOK = 0x40043418
PTNREL_HOOK_STOCK = bytes.fromhex("4879400bf0f2")      # pea 0x400bf0f2
# V7.2: the light Part apply's LFO AUTO CHANGE test -- the one apply after a jump skips its
# per-track part (each track's publish brings it at that track's first sounding trig).
LFOQ_HOOK = 0x40009ebe
LFOQ_HOOK_STOCK = bytes.fromhex("4a3980000050")        # tst.b (0x80000050).l

# The [PTN]-held keymap layer (0x400bf0f2): the 26-byte record for YES (key code
# 0x31) is all-NULL in stock, so the press slot is a free function pointer.
PTN_LAYER_YES = 0x400bf0be
PTN_LAYER_YES_STOCK = bytes([0x31, 0x00]) + bytes(24)
PTN_LAYER_YES_PRESS = PTN_LAYER_YES + 2                # the u32 press handler

# ---- the author's oracle -------------------------------------------------------
# patch_directjump_v7.s, m68k-elf-as -mcpu=5407 or 54455 (identical bytes), no symbols
# (DJ_MODE in the unit and DJ_TOAST_DUR = 0x44 are the source's defaults), linked at
# 0x400d6d38. octabam re-links it there on every build and compares. V7.0.1 (2026 B,
# a0f48090...) was byte for byte the DIRECT JUMP code of the KYOTI V1.0 image the author
# flashed on 2026-09-30; V7.0.2 (2188 B, WIP 2026-11-13: dj_cond, the trig conditions of a
# never-switched pattern instead of COND_RESET(-1)) and V7.1 (2262 B, WIP 2026-11-13: a jump lands one
# tick before the boundary, ahead 2, like Clyps CL26) and V7.1.1 (2610 B: an armed cue is never taken by
# stock's wrap-change) and V7.2 (3808 B: each track's Part at its first sounding trig, with LFO AUTO
# CHANGE on; a waiting track whose sequence has no sample trig publishes at once) and V7.2.2 (3846 B: the
# tracks a jump's switch will silence are released with stock's note-off first) are not flashed yet.
REFERENCE = (0x400d6d38, "688978daa1ed86c0a0874404e859ee781fbfbed7808be33c2f862beb3e373011")

MODULE = Module(
    name="direct-jump-kyoti",
    key="DIRECT_JUMP_KYOTI",
    kind=Kind.CF_PATCH,
    doc="Clock-locked DIRECT JUMP ([PTN]+[YES]): a cued pattern lands on the "
        "next step exactly where it would be had it played since START.",
    # Tim Hastie's DIRECT JUMP (modules/direct-jump) shares no address with this one,
    # but both change WHEN a cued pattern takes over; untested together.
    # Octakit shares no byte either, but wraps stock's switch block (0x400a4568..0x400a4856)
    # in a checked Kit transaction that this landing's hand-off bypasses: reported to crash
    # the unit. Refused until a bridge exists (reference/handoffs/DIRECTJUMP_OCTAKIT_SCOPE.md).
    conflicts=(("DIRECT JUMP",
                "both change when a cued pattern takes over (CHAIN AFTER = DIRECT vs "
                "[PTN]+[YES]); never tested together -- take one"),
               ("OCTAKIT",
                "a jump changes the pattern and Part outside Octakit's Kit transaction, and "
                "the pair is reported to crash the unit; refused until a bridge exists -- "
                "take one"),),
    # DIRECT JUMP reads each track's live scale byte. Stock's per-track scale seed for a MIDI
    # track can leave garbage there (BATCH_BUGFIXES bug 1, MIDI_PLAYS_FREE_FIX), so every
    # DIRECT JUMP image carries the fix; the source also guards every step-length lookup
    # (Sam Banks' static review, octabam #561).
    requires=("BATCH_BUGFIXES",),
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
        Detour(LFOQ_HOOK, LFOQ_HOOK_STOCK, "dj7", "dj_lfoq",
               "light Part apply: per-track part deferred to each track's first trig", kind="jsr"),
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
