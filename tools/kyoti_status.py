#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build status tiers -- what a builder tells you before it runs, and what it refuses.

There is one branch in this repo and it carries every build, finished or not, so the
tier a build is in has to be visible at the moment someone runs it -- not only in
README.md.  Each build_*.py declares one tier by calling status() right after its
imports:

    FINAL    flashed on the author's MKI and working.  One line, then it builds.
    PREVIEW  incomplete, but safe to try and useful on hardware as far as it goes.
             Prints what is unfinished, then builds.
    WIP      the author's own flash-and-measure loop: expected to be wrong, and
             changing between commits.  REFUSES to build unless the environment
             has KYOTI_ALLOW_WIP=1.

The WIP gate is a courtesy, not a lock -- this is a public repo and anyone can delete
the call.  It is here so that nobody flashes a diagnostic build by accident, and so
"which of these is finished?" is answered where the question actually comes up.

Read FLASHING.md before you flash any of them, whatever the tier says.
"""
import os
import sys

FINAL = "FINAL"
PREVIEW = "PREVIEW"
WIP = "WIP"

ALLOW_ENV = "KYOTI_ALLOW_WIP"

_RULE = "  " + "-" * 72

_HEADLINE = {
    FINAL: "FINAL -- hardware-confirmed on the author's MKI",
    PREVIEW: "PREVIEW -- incomplete, buildable on purpose",
    WIP: "WIP -- work in progress, expected to be wrong",
}


def status(tier, name, note=""):
    """Announce `name`'s tier; for WIP, refuse unless the caller opted in.

    `note` is free text -- say what is unfinished, in the specific.  Called for its
    side effects (printing, and sys.exit for a gated WIP build), so it goes at the
    top of a builder, before it reads the stock image or writes anything.
    """
    if tier not in _HEADLINE:
        raise ValueError(f"unknown tier {tier!r}")

    allowed = tier != WIP or os.environ.get(ALLOW_ENV) == "1"
    out = sys.stdout if allowed else sys.stderr

    print(_RULE, file=out)
    print(f"  {name}  --  {_HEADLINE[tier]}", file=out)
    for line in note.strip().splitlines():
        print(f"  {line.strip()}", file=out)
    print(_RULE, file=out)

    if not allowed:
        print(
            f"\n  Refusing to build: this one is not finished, and an image built from\n"
            f"  it is not something to flash.  If you meant it, set {ALLOW_ENV}=1:\n\n"
            f"      {ALLOW_ENV}=1 python3 {os.path.relpath(sys.argv[0])}\n",
            file=sys.stderr,
        )
        sys.exit(2)

    print(file=out)
