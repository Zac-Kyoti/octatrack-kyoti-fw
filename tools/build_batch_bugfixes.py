#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
BATCH_BUGFIXES: the three stock-bug fixes in one image (MIDI_PLAYS_FREE_FIX + EMPTY_PATTERN_LED_FIX +
PART_CHANGE_CARRYOVER_FIX) -> out/BATCH_BUGFIXES/OCTATRACK_OS1.40C_BATCH_BUGFIXES.syx (+ .bin).
Composed by tools/feature_image.py (gate() hands off there); every feature image carries the same three.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kyoti_status import gate                  # noqa: E402

gate(__file__)
