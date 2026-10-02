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

STATE. One word, DJ_MODE (0 = OFF/stock, 1 = ON), kept INSIDE the cave -- the
source's default (DJ_MODE_IN_CAVE); only the standalone builder asks for the old
0x800000d8 word, with DJ_MODE_IN_RAM=1. It has to be the default: octabam's
CavePatch.defsyms reach the LINKER (ld --defsym), and `.ifdef` is decided by the
assembler, so a defsym cannot select it. DIRECT JUMP is a performance feature and must come up
OFF at every power-on: the cave is part of the OS image, re-loaded from flash at every
boot, so the word starts at 0 by construction -- no battery restore can reach it.

That is what makes it safe next to MUTE_MODES, which widens the boot 'ANDY' restore
(`pea 0x64` -> `pea 0x70` at 0x4001f322 / 0x4001f3be / 0x4001fb24) so its own word
0x800000dc survives power-off. The widened span 0x80000070..0x800000df sweeps
0x800000d8 -- where DJ_MODE lived before this module took DJ_MODE_IN_CAVE, and where
the standalone builder still keeps it (reference/MERGE.md, blocker B1). The KYOTI V1.0
combined image, flashed on the author's MKI, carries exactly this cave.

MEASURED. Hardware-confirmed on the author's MKI 2026-09-27/28: the clock-locked
timing and the Part change. Emulator-verified only (ot_emu, real image bytes):
Program Change on fast re-cues, MIDI tracks, START SILENT and the trig-condition
reset (the last two identical to a stock pattern change in the emulator).
Standalone image and version string: tools/build_direct_jump_kyoti.py -> 140C_KDJ7.
"""

import os

from remix.schema import CavePatch, Kind, Module

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

# ---- cave layout ------------------------------------------------------------
# Offsets of the four entry points within the linked cave, read from
# m68k-elf-nm. dj_toggle is the cave's first byte, so the primary hook is NOT
# the cave base and every detour is planted by emit() instead of hook_addr.
OFF_TOGGLE = 0x000
OFF_LAND = 0x086
OFF_NOFA = 0x3f2
OFF_PTNREL = 0x412
CAVE_LEN = 0x7bc

DJ_TOAST_DUR = 0x44                                    # toast frames, --defsym

# patch_directjump_v7.s assembled with m68k-elf-as -mcpu=5407 (no symbols: DJ_MODE in
# the cave is the default) and linked at 0x400d7000 with --defsym DJ_TOAST_DUR=0x44 -- the
# standalone V7.0.1 address. Rebased to 0x400d6d38 these are byte-for-byte the
# DIRECT JUMP cave of the promoted KYOTI V1.0 image. sha256 a2010a6b9c40c7c95377c82ca70a7fa4.
# These bytes ARE the contract: the build links the source at the address the
# cave lands on and refuses if the result differs from reference(addr).
PIN_BASE = 0x400d7000
PINNED = bytes.fromhex(
    "7001b0af00086600005c2039460d17425380660000504ab9460d1aec66000046"
    "4ab9460e5cd06600003c203a07580a800000000102800000000123c0400d7784"
    "41fa00344a80670441fa001c487800442f084eb94005a2b8508f700123c0460d"
    "173e4e754e75444952454354204a554d50204f4e0000444952454354204a554d"
    "50204f4646004fefffc448d77fff7001b0b9800065b8670842b9400d77886006"
    "52b9400d77884aba06dc670000847001b0b9800065b8660000784ab9460d1aec"
    "6600006e4ab98000654666000064103a06ae6700007e0c000003660e61000648"
    "4239400d777e600001ae0c000001660001a61039800065c0b03a0688660c1039"
    "800065bfb03a067d67104239800066874239400d777e6000003a103980006687"
    "0c000001660001706100017c60000168103a064c0c0000016606423980006687"
    "4239400d777e70ff13c0400d777f600001461039800065c00c00ffff67e2b039"
    "800065be66501039800065bfb039800065bd6642103a06090c00ffff6700ffc2"
    "b039800065be660e103a05f7b039800065bd6700ffac70001039800065be2f00"
    "70001039800065bd2f004eb94009e884508f6000ff8c1039800065c0b03a05c1"
    "660c1039800065bfb03a05b767341039800065c013c0400d777f1039800065bf"
    "13c0400d778170001039800065c02f0070001039800065bf2f004eb94009e884"
    "508f4a39800066876e00008c70001039800065bf72001239800065c06100033c"
    "610003582e3a05620687000000007c002007d086610004524a806d12223a055a"
    "24004c4120024c012800b082670e52860c86000000786dd86000003c10398000"
    "65c013c0400d77821039800065bf13c0400d77832206528113c1800066870c81"
    "0000000166086100001e6000000a700113c0400d777e4cd77fff4fef003c1039"
    "800066874e751039800065be13c0800065c11039800065bd13c0800065c21039"
    "800065c013c0800065be1039800065bf13c0800065bd70001039800065bd223c"
    "0009b3404c01080072001239800065be243c00008ed84c021800d08145f9400e"
    "21e0d5c0610002742e3a047e06870000000023c7400d778c263a04762007d083"
    "5380223a0470670c24004c4120024c012800908228004c43400423c480006638"
    "2a009a83528541f98000651643f98000653647fa044849fa04547c107200121b"
    "20054c4100007400141c7202b2826e0e22004c4210014c021800908160027000"
    "30c04219538666d46100031e4279800066264279800066804279800066824279"
    "800066841039800065bd13c0400d81684879400d81674879460d17ae4eb94000"
    "0c3c508f610000681039800065be13c0400d816c4879400d816b4879460d17ae"
    "4eb940000c3c508f700213c0400d777e4e75103a038a0c000002660e700313c0"
    "400d777e4a3a037a4e754a398000002a4e754ab9460d1e706708700123c0460d"
    "1e6c4879400bf0f24ef94004341e223c00008e571032180013c0400d816a4879"
    "400d81694879460d17ae4eb940000c3c508f780376532c3c0000091a610000ce"
    "23c446c7fa8020394610757c23c0800019e41039800065bd13c046c7ff40223c"
    "00008e571032180013c046c7ff627803263c000048fb2c3c000008b06100008e"
    "23c446c7a1207a004a3980001860661610398000002808000000670a4ab94610"
    "4ca867027a012039461075644a85660606800000313823c046c76aa6700123c0"
    "46c76a222039461075644a8567080480000041a0600604800000106823c046c7"
    "6aaa1039800065bd13c046c7a850223c00008e571032180013c046c7a9344878"
    "ffff4eb9400a539c588f4e757a0810323800671a0c000001670e0c00ffff660e"
    "4a398000004f67067001eba88880d68652857010b08566d64e75243c0009b340"
    "4c020800243c00008ed84c021800d08145f9400e21e0d5c04e7541f9400aba50"
    "203c00008e551e32080072004a07661c203c00008e541232080026301c00203c"
    "00008e53780018320800601e203c00008e521232080026301c00203c00008e50"
    "3832080048c46e02780023c3400d779020044c03080023c0400d77942a0347fa"
    "01bc49fa01c84bf98000663e7c007008b0866f12203c0000091a4c0608000680"
    "00000050601420065180223c000008b04c0108000680000048f843f208004a29"
    "00046708720012356800601672004a07660c203c00008e541232080060041229"
    "000124301c0016c24a07660418c4600218d1200522024a81671426004c413003"
    "4c013800908326002001220360e84c4050054c02580052867010b0866600ff70"
    "23c5400d77984e75263a0106d0835380223a0102670c24004c4120024c012800"
    "9082908352804e752a394610757c41f98000190443f946c7e99847f946c7fe44"
    "612c41f98000198443f946c7faa447f946c7fe8c61182a394610756441f946c7"
    "6a2643f946c769c047f946c77be27c007800700010336800090067182204e789"
    "d28624301c0094856b0a42b11c0009801780680052847003b08466d652867008"
    "b08666cc4e7541f9400aba50700010398000663d26300c007a00223a0058670c"
    "92835281b2ba00466e027a0143f98000663e45f9800065d37c0072004a856710"
    "70001031680022300c0092836a0272001581680052867010b08666de4e7500ff"
    "00ffffff00000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000"
)
assert len(PINNED) == CAVE_LEN, len(PINNED)


def _rebase(blob: bytes, frm: int, to: int) -> bytes:
    """The cave is NOT position-independent: 18 longwords hold absolute
    addresses of its own state block (dj_state .. dj_obs_h, and DJ_MODE). Relocating is
    rebasing exactly those: every u32 on a 2-byte boundary whose value lands
    inside the cave. Verified against real m68k-elf-ld output at 0x400d7300
    and 0x400d6500 -- byte-identical at both."""
    out = bytearray(blob)
    for i in range(0, len(blob) - 3, 2):
        w = int.from_bytes(blob[i:i + 4], "big")
        if frm <= w < frm + len(blob):
            out[i:i + 4] = (w - frm + to).to_bytes(4, "big")
    return bytes(out)


def reference(addr: int) -> bytes:
    """The ratified bytes AT `addr` -- this cave floats, so there is no single
    fixed `pinned` for the build to hold the re-assembly against."""
    return _rebase(PINNED, PIN_BASE, addr)


assert sum(1 for i in range(0, CAVE_LEN - 3, 2)
           if PIN_BASE <= int.from_bytes(PINNED[i:i + 4], "big") < PIN_BASE + CAVE_LEN) == 18


def _jsr(target: int) -> bytes:
    return b"\x4e\xb9" + target.to_bytes(4, "big")


def _jmp(target: int) -> bytes:
    return b"\x4e\xf9" + target.to_bytes(4, "big")


def emit(addr: int):
    """The source is the only truth for the bytes (b""). All three detours and
    the keymap pointer depend on where the cave lands; each site is fixed, so
    the ledger sees them all by name."""
    return b"", (
        (LAND_HOOK, LAND_HOOK_STOCK, _jsr(addr + OFF_LAND)),
        (NOFA_HOOK, NOFA_HOOK_STOCK, _jsr(addr + OFF_NOFA)),
        (PTNREL_HOOK, PTNREL_HOOK_STOCK, _jmp(addr + OFF_PTNREL)),
        (PTN_LAYER_YES_PRESS, bytes(4), (addr + OFF_TOGGLE).to_bytes(4, "big")),
    )


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
    cf_patches=(
        CavePatch(
            label="DIRECT_JUMP_KYOTI cave",
            cave_addr=None,                  # floats; 18 self-refs are rebased
            pinned=PINNED,
            source=os.path.join(_HERE, "patch_directjump_v7.s"),
            hook_addr=None,                  # entry is not the cave base
            hook_stock=b"",
            emit=emit,
            reference=reference,
            defsyms=(("DJ_TOAST_DUR", DJ_TOAST_DUR),),
            cpu="5407",
            report_note=" ([PTN]+[YES] toggles; 3 detours: phase-D countdown "
                        "0x400a1f72, MIDI START 0x400a221c, [PTN] release "
                        "0x40043418; + the PTN-layer YES press slot)",
        ),
    ),
)
