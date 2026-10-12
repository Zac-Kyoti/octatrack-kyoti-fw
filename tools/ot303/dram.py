#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti; the arena geometry is octabam's (tools/remix/arena.py,
# Sam Banks, MIT), measured there and re-asserted here against our own image.
#
# OT-303's DRAM runtime: a reserve of RESERVE_PAGES pages taken off the bottom of the stock audio page
# arena (Flex samples and the track recorders: 14,602 pages of 6,144 B from 0x40a955e0), the way
# octamax 2.0 takes 64 and octabam's platform 1,707. The arena's base literal moves past the reserve
# at its 24 sites and the four geometry words shrink with it, so the OS never touches the reserve
# again (octabam docs/contributing/PLACEMENT.md: the arena clear starts at the new base, the
# boot-time copies follow the literal, the allocator hands out only indexes below the new count).
# tools/ot303/cf/loader.S, appended after the OS image, fills the reserve at boot.
BASE = 0x40A955E0
PAGE = 6144
PAGES = 14602
END = BASE + (PAGES + 1) * PAGE
UNCACHED = 0x08000000
RESERVE_PAGES = 16                    # 96 KiB: the runtime and its data; 0.1 % of the pool
IMAGE_END = 0x4010FDF0                # the byte after the stock OS image: the loader's home
BOOT_SITE = 0x4000050C                # jsr 0x40001e50 (boot continue) -> jsr the loader
BOOT_CONTINUE = 0x40001E50

BASE_SITES = (
    0x4000045C, 0x4000046A, 0x400004C6, 0x400072A6, 0x40007642, 0x4000D5C0,
    0x400254F8, 0x4006C106, 0x40093432, 0x40094A0A, 0x40094A3C, 0x40094A9C,
    0x40095B28, 0x40095BBA, 0x40095C18, 0x40095C78, 0x40095CC2, 0x4009618C,
    0x400963C4, 0x4009700C, 0x4009761E, 0x40097748, 0x40098650,
)
DERIVED_SITES = ((0x40094A62, PAGE),)          # lea base+6144 (page 1)
COUNT_SITE = (0x40096F82, PAGES, "page count")
FILL_SITE = (0x40096FAC, PAGES + 1, "free-list fill limit")
CLEAR_SITE = (0x40097008, (PAGES + 1) * PAGE, "arena clear length")
CAP_SITE = (0x40097126, PAGES, "recorder page cap")

RESERVE = BASE                                  # cached; the runtime is linked here
RESERVE_END = BASE + RESERVE_PAGES * PAGE


def arena_pokes():
    """(operand address, stock 4 bytes, new 4 bytes, note) for the reserve"""
    base = RESERVE_END
    count = (END - base) // PAGE - 1
    out = [(s + 2, BASE.to_bytes(4, "big"), base.to_bytes(4, "big"), "arena base") for s in BASE_SITES]
    out += [(s + 2, (BASE + off).to_bytes(4, "big"), (base + off).to_bytes(4, "big"), f"arena base + {off}")
            for s, off in DERIVED_SITES]
    for (operand, stock, what), new in ((COUNT_SITE, count), (FILL_SITE, count + 1),
                                        (CLEAR_SITE, (count + 1) * PAGE), (CAP_SITE, count)):
        out.append((operand, stock.to_bytes(4, "big"), new.to_bytes(4, "big"), what))
    return out


def boot_poke():
    return (BOOT_SITE + 2, BOOT_CONTINUE.to_bytes(4, "big"), IMAGE_END.to_bytes(4, "big"), "boot site -> the loader")


def x33(data):
    """octabam's rolling hash (loader.S): h = h * 33 + byte, 32 bits"""
    h = 0
    for b in data:
        h = (h * 33 + b) & 0xFFFFFFFF
    return h
