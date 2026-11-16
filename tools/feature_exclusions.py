# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Feature pairs that must never share an image (the user, 2026-11-07), checked by every builder that
combines named features (build_kyoti.py, feature_image.py).

  CLYPS + RELOAD_FROM_PROJECT   never: Clyps carries its own card reloads (scope §1.8) on the same
                                [PTN] / [BANK] handler sites (0x4005a044, 0x4007af80, 0x4007b3e0) and
                                the same type-0x14 card job.
  CLYPS + DIRECT_JUMP_KYOTI     only as KYOTI's integrated pair: build_kyoti.py's SUPERSEDE makes the
                                shared phase-D site 0x400a1f72 Clyps' and chains DIRECT JUMP's dj_land
                                from it (asserted there). Standalone images never combine.

The single-feature builders cannot be layered onto each other's images either: each refuses any of
its hook sites whose bytes are not stock, and these pairs share sites. octabam / Modwerk: Clyps'
manifest declares the same pairs in `conflicts=` (plus Tim Hastie's DIRECT JUMP) when it is ported.
"""
import sys

EXCLUSIVE = {
    frozenset({"CLYPS", "RELOAD_FROM_PROJECT"}):
        "Clyps carries its own card reloads on the same key-handler sites and card job",
    frozenset({"CLYPS", "DIRECT_JUMP_KYOTI"}):
        "they share the phase-D landing site 0x400a1f72; only KYOTI's integrated pair (SUPERSEDE) is valid",
}


def violations(features, integrated=()):
    """-> [(pair, why)] for every excluded pair in `features` that is not in `integrated`."""
    have = set(features)
    ok = {frozenset(p) for p in integrated}
    return [(tuple(sorted(p)), why) for p, why in EXCLUSIVE.items() if p <= have and p not in ok]


def check(features, integrated=(), who=""):
    """Exit when `features` holds an excluded pair (other than an `integrated` one)."""
    bad = violations(features, integrated)
    if bad:
        sys.exit("\n".join(f"{who}refused: {' + '.join(p)} must never share an image -- {why} "
                           f"(tools/feature_exclusions.py)" for p, why in bad))
