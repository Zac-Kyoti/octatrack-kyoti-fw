#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
The build gate: everything is WORK IN PROGRESS until the author promotes it.

A WIP build refuses to run unless KYOTI_ALLOW_WIP=1 is set, so nobody flashes an
unfinished image by accident.  A builder is FINAL only while it still builds exactly the
image that was promoted: FINAL below pins each promoted builder to the sha256 of that
image (the patched MAIN OS section, before it is wrapped into a .syx).  Change the
builder or anything it assembles and the image changes, so the build is WIP again until
the author promotes the new one -- which then replaces the old.  A diagnostic variant of
a final builder builds a different image, so it is WIP too.

Two calls in every builder:

    gate(__file__)           first thing: a builder not on the FINAL list is WIP
    seal(__file__, image)    after writing the image, before wrapping it: a FINAL
                             builder whose image no longer matches is WIP

PROMOTION happens only on the author's explicit instruction: build it, put the sha256
that seal() prints into FINAL, and give the feature its entry in README.md.  When the
promoted build is a new builder rather than an update in place, it takes the old one's
FINAL entry and the old builder is deleted.

The gate is a courtesy, not a lock -- this is a public repo.  Read FLASHING.md before you
flash anything, whatever the gate says.
"""
import hashlib
import os
import sys

ALLOW_ENV = "KYOTI_ALLOW_WIP"

# builder -> sha256 of the image it built when the author promoted it.  A builder that
# writes several images maps to {image file name: sha256}, one per promoted image.
FINAL = {
    "build_mute_modes.py":                 "b5e24316e4dc5824657818f26cf1891e02ac26ae9094f101a7703f5beb74d6ba",
    "build_direct_jump_kyoti.py":          "3f26d8de004469052ec9da58967c066b128393dd4a9c4dfc7d7efd0d3696a759",
    "build_sidechain_compressor.py":       "dfafc90cd230f340fd93ecc1f8e130c139fb6128855aca6adbf09cbcedc2d827",
    "build_reload_from_project.py":        "19a3a62ca65de4c27c44d4f07f0b2e25d58b732bb56ed02c91a8e1b98e2676ac",
    "build_repitch_repeat98_kyoti.py":     "3d17b002659023ad5d83cdfd4bef3cca9216401a76da1132598b9ddff7ced2bf",
    "build_quantize_live_rec_toggle.py":   "0832cd9d0b5f804a26c50cf1ed6ce375288635f7c1ec2ad661b0083f80df803f",
    "build_erase_empty_trigless_locks.py": "83690ffbd97ad51281630acc8597f6423715885d2a712915df2edc39bb9b6a1c",
    "build_midi_plays_free_fix.py":        "672158c18630703cc1aadc635d45aeb68549a3237830d5c4a0aeb2d113afad35",
    "build_empty_pattern_led_fix.py":      "737979232995e93dba6778ef10e214a5355a498f54965946127258d186c5be2c",
    "build_bugbuilds.py": {
        "mainos_mute_modes_batch_bugfixes.bin":              "fbdab3b280c1443cb8bb07ac75a6bdfc786a605d3fb9d745c413224b6fe45d7f",
        "mainos_quantize_live_rec_toggle_batch_bugfixes.bin":"a91d4bc6cecb68d9e2926cba9c1d129a537aa506a2450f505838f1040930b088",
        "mainos_sidechain_compressor_batch_bugfixes.bin":    "ebb0355a20ded854acd68b2ad9aecf6aa014842bb61e1969e3b5dfbdccd12974",
        "mainos_erase_empty_trigless_locks_batch_bugfixes.bin":"863afe55f89cf576c1ed3113a15cd91ab7c98a9e03d369502987541d0179a506",
        "mainos_reload_from_project_batch_bugfixes.bin":     "420722edeba797953ca3569d8b15df9711fdc9a779bdec9bb876df8d36c59907",
        "mainos_direct_jump_kyoti_batch_bugfixes.bin":       "fea54f60720e1dc4c615f13783ab8eb3ecd1ec44cb7fc36712dbefbb02eb6a10",
        "mainos_repitch_repeat98_kyoti_batch_bugfixes.bin":  "72e4a40039d540b8f9a2f93207c06dc5119decbee5d2f505053b0b413fc7c79f",
    },
    "build_part_change_carryover_fix.py":  "dd2a7e2ba3328364caa560e431195fd248cbb5d83dce1759de1e7e3effc5febd",
}

_RULE = "  " + "-" * 72


def _allowed():
    return os.environ.get(ALLOW_ENV) == "1"


def _banner(lines, out):
    print(_RULE, file=out)
    for line in lines:
        print(f"  {line}", file=out)
    print(_RULE, file=out)
    out.flush()   # a builder's child processes write straight to the terminal; without
                  # this, a piped run prints the banner after their output instead of first


def _refuse(why, builder):
    print(f"\n  Refusing to build: {why}.\n"
          f"  If you meant it, set {ALLOW_ENV}=1:\n\n"
          f"      {ALLOW_ENV}=1 python3 {os.path.relpath(builder)}\n", file=sys.stderr)
    sys.exit(2)


def gate(builder, note=""):
    """Say whether `builder` is FINAL or WIP; refuse a WIP build without the opt-in.

    `note` is free text shown with a WIP banner -- what is unfinished, specifically.
    Call it at the top of a builder, before it reads the stock image or writes anything.
    """
    name = os.path.basename(builder)
    if name in FINAL:
        _banner([f"{name}  --  FINAL"], sys.stdout)
        print()
        return
    out = sys.stdout if _allowed() else sys.stderr
    _banner([f"{name}  --  WIP, not promoted to final"]
            + [l.strip() for l in note.strip().splitlines()], out)
    if not _allowed():
        _refuse("this build is work in progress, and an image built from it is not\n"
                "  something to flash", builder)
    print()


def seal(builder, image):
    """After a FINAL builder writes its image: is it still the promoted one?

    A build placed at other addresses for the combined image (KYOTI_PLACE set, see
    tools/kyoti_place.py) cannot match its standalone promotion, so it is not checked
    here; the combined builder is gated on its own.
    """
    name = os.path.basename(builder)
    if name not in FINAL or os.environ.get("KYOTI_PLACE"):
        return
    with open(image, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    want = FINAL[name]
    if isinstance(want, dict):
        want = want.get(os.path.basename(image), "(not one of the promoted images)")
    if sha == want:
        print(f"  image matches the promoted FINAL build (sha256 {sha[:16]}...)")
        return
    out = sys.stdout if _allowed() else sys.stderr
    _banner([f"{name}  --  WIP: this is not the promoted build",
             "The builder, or something it assembles, has changed since it was",
             "promoted. It stays WIP until the author promotes it.",
             f"  this build  {sha}",
             f"  promoted    {want}"], out)
    if not _allowed():
        _refuse("the build no longer matches its promoted image", builder)
