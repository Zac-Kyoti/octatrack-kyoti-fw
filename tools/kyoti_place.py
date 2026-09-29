#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Opt-in cave placement for the combined KYOTI image (tools/build_kyoti.py).

Every finished feature builder links its caves at fixed addresses chosen for a
standalone image.  The combined image needs them elsewhere, so each builder asks
this module for its addresses instead of hardcoding them:

    CAVE_AT = kyoti_place.at("patch_triglock", 0x400d7200)

With KYOTI_PLACE unset (every normal run) `at()` returns the default, so a
standalone build is byte-for-byte what it was.  build_kyoti.py sets KYOTI_PLACE
to a JSON object {key: address-or-flag} and runs the builder in a sandbox copy of
the tree, so nothing it writes lands in out/.

A builder must not treat an override as a licence to skip its own guards: it
still asserts the cave is free in the image it was given and every displaced
byte is stock.  Which zones are acceptable at all is build_kyoti.py's job
(reference/MERGE.md, reference/kb/caves.md).
"""
import json
import os

_PLACE = json.loads(os.environ.get("KYOTI_PLACE") or "{}")


def at(key, default):
    """The address (or flag) for `key`, or `default` when not merging."""
    return _PLACE.get(key, default)


def active():
    """True when a combined build is driving this builder."""
    return bool(_PLACE)
