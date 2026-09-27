#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build status tiers -- what a builder tells you before it runs, and what it refuses.

There is one branch in this repo and it carries every build, finished or not, so the
tier a build is in has to be visible at the moment someone runs it -- not only in
README.md.  Each build_*.py declares one tier by calling status() right after its
imports:

    FINAL       flashed on the author's MKI and working.  One line, then it builds.
    PREVIEW     incomplete, but safe to try and useful on hardware as far as it goes.
                Prints what is unfinished, then builds.
    WIP         the author's own flash-and-measure loop: expected to be wrong, and
                changing between commits.  REFUSES to build unless the environment
                has KYOTI_ALLOW_WIP=1.
    SUPERSEDED  a dead end or an intermediate stage, kept only so its reasoning and
                its measurements stay readable.  Something else does this better, or
                it never worked.  REFUSES to build unless KYOTI_ALLOW_SUPERSEDED=1,
                and says what replaced it.

The gates are a courtesy, not a lock -- this is a public repo and anyone can delete the
call.  They are here so that nobody flashes a diagnostic or an abandoned build by
accident, and so "which of these is finished?" is answered where the question actually
comes up: at the moment someone runs one of nearly thirty builders.

Read FLASHING.md before you flash any of them, whatever the tier says.
"""
import os
import sys

FINAL = "FINAL"
PREVIEW = "PREVIEW"
WIP = "WIP"
SUPERSEDED = "SUPERSEDED"

ALLOW_ENV = "KYOTI_ALLOW_WIP"
ALLOW_SUPERSEDED_ENV = "KYOTI_ALLOW_SUPERSEDED"

# Which environment variable opts in to a gated tier.  A tier absent from this map is
# never gated.  Deliberately two names, not one: the incantation for "I know this is
# unfinished" should not also unlock "this one was abandoned".
_GATE_ENV = {WIP: ALLOW_ENV, SUPERSEDED: ALLOW_SUPERSEDED_ENV}

_RULE = "  " + "-" * 72

_HEADLINE = {
    FINAL: "FINAL -- hardware-confirmed on the author's MKI",
    PREVIEW: "PREVIEW -- incomplete, buildable on purpose",
    WIP: "WIP -- work in progress, expected to be wrong",
    SUPERSEDED: "SUPERSEDED -- a dead end, kept for its reasoning only",
}

_REFUSAL = {
    WIP: "this one is not finished, and an image built from it is not something\n"
         "  to flash",
    SUPERSEDED: "this one was abandoned or replaced, so building it gets you a worse\n"
                "  image than the build that replaced it -- and some of these never\n"
                "  worked on hardware at all",
}


def status(tier, name, note=""):
    """Announce `name`'s tier, and refuse to continue if that tier is gated.

    `note` is free text -- say what is unfinished, or what replaced this, in the
    specific.  Called for its side effects (printing, and sys.exit on a gated tier),
    so it goes at the top of a builder, before it reads the stock image or writes
    anything.
    """
    if tier not in _HEADLINE:
        raise ValueError(f"unknown tier {tier!r}")

    gate = _GATE_ENV.get(tier)
    allowed = gate is None or os.environ.get(gate) == "1"
    out = sys.stdout if allowed else sys.stderr

    print(_RULE, file=out)
    print(f"  {name}  --  {_HEADLINE[tier]}", file=out)
    for line in note.strip().splitlines():
        print(f"  {line.strip()}", file=out)
    print(_RULE, file=out)
    out.flush()   # a builder's own child processes write straight to the terminal; without
                  # this, a piped run prints the banner after their output instead of first

    if not allowed:
        print(
            f"\n  Refusing to build: {_REFUSAL[tier]}.\n"
            f"  If you meant it, set {gate}=1:\n\n"
            f"      {gate}=1 python3 {os.path.relpath(sys.argv[0])}\n",
            file=sys.stderr,
        )
        sys.exit(2)

    print(file=out)
    out.flush()
