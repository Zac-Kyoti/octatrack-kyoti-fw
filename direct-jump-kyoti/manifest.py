"""DIRECT JUMP (KYOTI) -- an optional immediate pattern change, toggled from the
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

STATE, AND THE ONE THING THAT CAN BREAK IT. One word, DJ_MODE = 0x800000d8
(0 = OFF/stock, 1 = ON). DIRECT JUMP is a performance feature and must come up OFF
at every power-on; that is guaranteed by two stock facts, not by this module's
code: the boot 'ANDY' battery restore (`pea 0x64` at 0x4001f322 / 0x4001f3be /
0x4001fb24) covers 0x80000070..0x800000d3 and so never reaches 0x800000d8, and
the boot re-image seeds 0x800000d8 from 0x401087cc, which is 0 in stock.

⚠️ MUTE MODE BREAKS THE FIRST FACT (reference/MERGE.md, blocker B1). It widens
that restore to `pea 0x70` so its own word 0x800000dc survives power-off -- and
the widened span 0x80000070..0x800000df SWEEPS 0x800000d8. With both in one
image, DJ_MODE would be restored from a battery word nothing maintains, and
DIRECT JUMP could come up ON. The two words differ (d8 vs dc); the RANGE is the
collision. (An earlier revision of this docstring said the two do not collide on
SRAM. That compared the words and missed the range. It was wrong.)

So this module CLAIMS those four sites below, as assert-only pokes (expect ==
write). Octabam's ledger checks every module's pokes against every other's, so a
remix that pairs this module with anything rewriting them -- MUTE MODE's widening
-- is REFUSED at the ledger instead of shipping a unit that can power on with
DIRECT JUMP enabled. The real fix is the source option DJ_MODE_IN_CAVE (branch
kyoti-v1, `4ed4720`), which moves the word into the cave -- re-loaded from flash
at every boot, so OFF by construction -- after which these claims can go.

MEASURED. Hardware-confirmed on the author's MKI 2026-09-27/28: the clock-locked
timing and the Part change. Emulator-verified only (ot_emu, real image bytes):
Program Change on fast re-cues, START SILENT, trig-condition reset, MIDI tracks.
Standalone image and version string: tools/build_directjump_v7.py -> 140C_KDJ7.

PLAYSFREEFIX is deliberately NOT part of this module. The standalone builder
folds the manual-trig fix (patch_trigscale) into its own image, but as a module
that fix is its own contribution -- five KYOTI feature builders each carry a copy
of it and all write the same site 0x4009b6f2, which the ledger would refuse.
"""

import os

from remix.schema import CavePatch, Kind, Module

# This module's own directory, relative to the build's cwd (octabam's repo
# root): "modules/direct-jump-kyoti" checked out directly, and
# "modules/direct-jump-kyoti/upstream/direct-jump-kyoti" as octabam's submodule
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
OFF_LAND = 0x088
OFF_NOFA = 0x3f6
OFF_PTNREL = 0x416
CAVE_LEN = 0x7bc

DJ_TOAST_DUR = 0x44                                    # toast frames, --defsym

# patch_directjump_v7.s assembled with m68k-elf-as -mcpu=5407 (--defsym
# DJ_TOAST_DUR=0x44) and linked at 0x400d7000 -- the address the standalone,
# hardware-confirmed V7.0.1 image uses. sha256 34635ad57f25f7337eefa307ad5e234e.
# These bytes ARE the contract: the build links the source at the address the
# cave lands on and refuses if the result differs from reference(addr).
PIN_BASE = 0x400d7000
PINNED = bytes.fromhex(
    "7001b0af00086600005e2039460d17425380660000524ab9460d1aec66000048"
    "4ab9460e5cd06600003e2039800000d80a800000000102800000000123c08000"
    "00d841fa00344a80670441fa001c487800442f084eb94005a2b8508f700123c0"
    "460d173e4e754e75444952454354204a554d50204f4e0000444952454354204a"
    "554d50204f4646004fefffc448d77fff7001b0b9800065b8670842b9400d7788"
    "600652b9400d77884ab9800000d8670000847001b0b9800065b8660000784ab9"
    "460d1aec6600006e4ab98000654666000064103a06ae6700007e0c000003660e"
    "610006484239400d7782600001ae0c000001660001a61039800065c0b03a0688"
    "660c1039800065bfb03a067d67104239800066874239400d77826000003a1039"
    "800066870c000001660001706100017c60000168103a064c0c00000166064239"
    "800066874239400d778270ff13c0400d7783600001461039800065c00c00ffff"
    "67e2b039800065be66501039800065bfb039800065bd6642103a06090c00ffff"
    "6700ffc2b039800065be660e103a05f7b039800065bd6700ffac700010398000"
    "65be2f0070001039800065bd2f004eb94009e884508f6000ff8c1039800065c0"
    "b03a05c1660c1039800065bfb03a05b767341039800065c013c0400d77831039"
    "800065bf13c0400d778570001039800065c02f0070001039800065bf2f004eb9"
    "4009e884508f4a39800066876e00008c70001039800065bf72001239800065c0"
    "6100033c610003582e3a055e0687000000007c002007d086610004524a806d12"
    "223a055624004c4120024c012800b082670e52860c86000000786dd86000003c"
    "1039800065c013c0400d77861039800065bf13c0400d77872206528113c18000"
    "66870c810000000166086100001e6000000a700113c0400d77824cd77fff4fef"
    "003c1039800066874e751039800065be13c0800065c11039800065bd13c08000"
    "65c21039800065c013c0800065be1039800065bf13c0800065bd700010398000"
    "65bd223c0009b3404c01080072001239800065be243c00008ed84c021800d081"
    "45f9400e21e0d5c0610002742e3a047a06870000000023c7400d778c263a0472"
    "2007d0835380223a046c670c24004c4120024c012800908228004c43400423c4"
    "800066382a009a83528541f98000651643f98000653647fa044449fa04507c10"
    "7200121b20054c4100007400141c7202b2826e0e22004c4210014c0218009081"
    "6002700030c04219538666d46100031e42798000662642798000668042798000"
    "66824279800066841039800065bd13c0400d81684879400d81674879460d17ae"
    "4eb940000c3c508f610000681039800065be13c0400d816c4879400d816b4879"
    "460d17ae4eb940000c3c508f700213c0400d77824e75103a038a0c000002660e"
    "700313c0400d77824a3a037a4e754a398000002a4e754ab9460d1e7067087001"
    "23c0460d1e6c4879400bf0f24ef94004341e223c00008e571032180013c0400d"
    "816a4879400d81694879460d17ae4eb940000c3c508f780376532c3c0000091a"
    "610000ce23c446c7fa8020394610757c23c0800019e41039800065bd13c046c7"
    "ff40223c00008e571032180013c046c7ff627803263c000048fb2c3c000008b0"
    "6100008e23c446c7a1207a004a3980001860661610398000002808000000670a"
    "4ab946104ca867027a012039461075644a85660606800000313823c046c76aa6"
    "700123c046c76a222039461075644a8567080480000041a06006048000001068"
    "23c046c76aaa1039800065bd13c046c7a850223c00008e571032180013c046c7"
    "a9344878ffff4eb9400a539c588f4e757a0810323800671a0c000001670e0c00"
    "ffff660e4a398000004f67067001eba88880d68652857010b08566d64e75243c"
    "0009b3404c020800243c00008ed84c021800d08145f9400e21e0d5c04e7541f9"
    "400aba50203c00008e551e32080072004a07661c203c00008e54123208002630"
    "1c00203c00008e53780018320800601e203c00008e521232080026301c00203c"
    "00008e503832080048c46e02780023c3400d779020044c03080023c0400d7794"
    "2a0347fa01b849fa01c44bf98000663e7c007008b0866f12203c0000091a4c06"
    "0800068000000050601420065180223c000008b04c0108000680000048f843f2"
    "08004a2900046708720012356800601672004a07660c203c00008e5412320800"
    "60041229000124301c0016c24a07660418c4600218d1200522024a8167142600"
    "4c4130034c013800908326002001220360e84c4050054c02580052867010b086"
    "6600ff7023c5400d77984e75263a0102d0835380223a00fe670c24004c412002"
    "4c0128009082908352804e752a394610757c41f98000190443f946c7e99847f9"
    "46c7fe44612c41f98000198443f946c7faa447f946c7fe8c61182a3946107564"
    "41f946c76a2643f946c769c047f946c77be27c00780070001033680009006718"
    "2204e789d28624301c0094856b0a42b11c0009801780680052847003b08466d6"
    "52867008b08666cc4e7541f9400aba50700010398000663d26300c007a00223a"
    "0054670c92835281b2ba00426e027a0143f98000663e45f9800065d37c007200"
    "4a85671070001031680022300c0092836a0272001581680052867010b08666de"
    "4e7500ff00ffffff000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000"
)
assert len(PINNED) == CAVE_LEN, len(PINNED)


def _rebase(blob: bytes, frm: int, to: int) -> bytes:
    """The cave is NOT position-independent: 17 longwords hold absolute
    addresses of its own state block (dj_state .. dj_obs_h). Relocating is
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
           if PIN_BASE <= int.from_bytes(PINNED[i:i + 4], "big") < PIN_BASE + CAVE_LEN) == 17


# ---- power-on OFF: the stock facts it rests on, CLAIMED (see STATE above) -------
# Assert-only: each writes back exactly what it expects. Their job is to put these
# addresses in the ledger under this module's name, so a module that rewrites any
# of them is refused rather than silently letting DJ_MODE survive a power cycle.
#
# They are returned from emit(), NOT declared as Module.pokes, and that is load-
# bearing: remix/ledger.py checks a plain Module.poke against caves, hook sites and
# emit() pokes, but never against ANOTHER module's plain poke -- so as Module.pokes
# these claims would not collide with a MUTE MODE port that declares its widening
# the same way. As emit() pokes they are checked against every poke of every kind
# (measured against the real ledger, both shapes of widening refused).
ANDY_RESTORE_SITES = (0x4001f322, 0x4001f3be, 0x4001fb24)
ANDY_RESTORE_STOCK = bytes.fromhex("48780064")          # pea 0x64: ends at 0x800000d3
DJ_MODE_SEED = 0x401087cc                                # boot re-image source for 0x800000d8
POWER_ON_OFF = tuple(
    (site, ANDY_RESTORE_STOCK, ANDY_RESTORE_STOCK) for site in ANDY_RESTORE_SITES
) + ((DJ_MODE_SEED, bytes(4), bytes(4)),)


def _jsr(target: int) -> bytes:
    return b"\x4e\xb9" + target.to_bytes(4, "big")


def _jmp(target: int) -> bytes:
    return b"\x4e\xf9" + target.to_bytes(4, "big")


def emit(addr: int):
    """The source is the only truth for the bytes (b""). All three detours and
    the keymap pointer depend on where the cave lands; each site is fixed, so
    the ledger sees them all by name. The four power-on-OFF claims ride along
    here rather than in Module.pokes -- see POWER_ON_OFF for why."""
    return b"", (
        (LAND_HOOK, LAND_HOOK_STOCK, _jsr(addr + OFF_LAND)),
        (NOFA_HOOK, NOFA_HOOK_STOCK, _jsr(addr + OFF_NOFA)),
        (PTNREL_HOOK, PTNREL_HOOK_STOCK, _jmp(addr + OFF_PTNREL)),
        (PTN_LAYER_YES_PRESS, bytes(4), (addr + OFF_TOGGLE).to_bytes(4, "big")),
    ) + POWER_ON_OFF


MODULE = Module(
    name="direct-jump-kyoti",
    key="DIRECT JUMP KYOTI",
    kind=Kind.CF_PATCH,
    doc="Clock-locked DIRECT JUMP ([PTN]+[YES]): a cued pattern lands on the "
        "next step exactly where it would be had it played since START.",
    cf_patches=(
        CavePatch(
            label="direct jump kyoti cave",
            cave_addr=None,                  # floats; 17 self-refs are rebased
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
