"""ERASE_EMPTY_TRIGLESS_LOCKS -- a stock bug fix.

A trigless lock (a step holding parameter locks but no audible trig) used to stay
lit on the trig row forever once you erased its last remaining lock, even though
the step was now inert. It now disappears. A deliberately empty trigless lock
placed with FUNC + TRIG is left alone.

ROOT CAUSE (static RE + a hardware gesture trace, NOTES.md section 13).
FUN_40038874 is the LIVE erase worker -- reached through opcode 8's case and
FUN_40041af4, and identified by tracing the gesture on the unit rather than by
static guesswork. It already works out that the step's p-lock row has gone empty
and clears the track's bit from the per-step bitmap, but it never clears the
trig-type-layer flag TRAC+0x10, which is what keeps the LED lit. This module adds
only that clear.

The detour site is FUN_40038874's one commit point for "is this step's p-lock row
now empty" (0x40038a5c). An earlier attempt detoured 0x40038af8 instead, whose
second instruction is the enclosing loop's `addql #1,%d7` -- and 0x40038afc is a
branch target from two places, so the six-byte splice would have been jumped into
halfway. The standalone builder keeps that branch-target check
(`assert_no_branch_into`); here the site is simply pinned by its stock bytes.

The cave is position-independent, so it may land anywhere the allocator puts it.

MEASURED: hardware-confirmed on the author's MKI. The standalone image is
tools/build_erase_empty_trigless_locks.py, which deliberately does NOT bump the version string --
one bug fix, stock-transparent.
"""

import os

from remix.schema import CavePatch, Kind, Module

_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

# FUN_40038874's commit point: `moveb %d1,%a0@(0x59,%d2:l)` + `addl %d4,%d0`.
# The cave replays both before its own rts, which lands on 0x40038afe.
HOOK = 0x40038a5c
HOOK_STOCK = bytes.fromhex("11812859d084")

# patch_triglock.s, m68k-elf-as -mcpu=5407, linked at 0x400d7200: 296 bytes,
# sha256 5656b2da0a61719a4d557ca5b6bd8e71.  Position-independent -- verified
# byte-identical when linked at 0x400d7500 and 0x400d6f00 -- so the same bytes are
# the oracle at whatever address the cave lands on.
PINNED = bytes.fromhex(
    "4fefffd048d70fff42801030285952800280000000ff6700010043e800594283"
    "2a039a826700001442851a31380052850285000000ff660000e052837a20ba83"
    "6600ffde224893c42a0b2c05e68e760796860285000000077c01ebae2449d5c3"
    "42851a12ca86660000b042851a2a0008ca86660000a442851a2a0018ca866600"
    "009842851a2a0020ca866600008c42851a2a0028ca866600008042851a2a0030"
    "ca866600007442851a2a0010ca866700006842851a2a0010bd85154500104285"
    "1a39100b14d0203c00008ed84c0058002007223c0000091a4c010800da800685"
    "1001615e2445d5c342851a12ca866700000a42851a12bd851485247946c82456"
    "d5fc0009b3327a012485247c100f859824854eb940027e004cd70fff4fef0030"
    "11812859d0844e75"
)
assert len(PINNED) == 296, len(PINNED)
assert HOOK_STOCK in PINNED                      # the cave replays what it displaced


MODULE = Module(
    name="erase-empty-trigless-locks",
    key="ERASE_EMPTY_TRIGLESS_LOCKS",
    kind=Kind.CF_PATCH,
    doc="Bug fix: a trigless lock whose last parameter lock is erased stops "
        "staying lit on the trig row.",
    cf_patches=(
        CavePatch(
            label="ERASE_EMPTY_TRIGLESS_LOCKS cave",
            cave_addr=None,                      # floats: position independent
            pinned=PINNED,
            source=os.path.join(_HERE, "patch_triglock.s"),
            hook_addr=HOOK,                      # jsr; the cave replays + rts
            hook_stock=HOOK_STOCK,
            reference=lambda addr: PINNED,       # same bytes at any address
            cpu="5407",
            report_note=" (clears the trig-type-layer flag TRAC+0x10 that "
                        "FUN_40038874 leaves set on an emptied trigless lock)",
        ),
    ),
)
