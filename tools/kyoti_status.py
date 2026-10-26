#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
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
    "build_direct_jump_kyoti.py":          "3fa14332d95eda55f56de5935afbd988a7179666ae9d8bc2614c1cc7c9f8a896",
    "build_sidechain_compressor.py":       "44465569a6118a9a7936c83d0f728a5f8c81122c42433a7cdaf267206e99f2fc",
    "build_reload_from_project.py":        "439aa3208ace780007139b561b0c2938ae7c4a3cfac3c286c8c691b59d71caae",
    "build_quantize_live_rec_toggle.py":   "2012abd83f75336ddc73925f0a3ebb8de16ed3ea24b4c28d226e35ef99c2a6f4",
    "build_erase_empty_trigless_locks.py": "83690ffbd97ad51281630acc8597f6423715885d2a712915df2edc39bb9b6a1c",
    "build_midi_plays_free_fix.py":        "672158c18630703cc1aadc635d45aeb68549a3237830d5c4a0aeb2d113afad35",
    "build_empty_pattern_led_fix.py":      "0e50306d8c242cf0365f2df3e09998be5db3b92a4cc95d5d17e590d9cc36b266",
    "build_rec_trig_mute.py":              "34f06e293a6f97f0ade3db740273c7f41e06717f3971798c85f1cb362911c804",
    "build_bugbuilds.py": {
        "mainos_mute_modes_batch_bugfixes.bin":              "2c5600dc4dd30812a54ddfec8904f7762593e7c6233638fa2ae40319602ead47",
        "mainos_quantize_live_rec_toggle_batch_bugfixes.bin":"df4a24981ace4a163723ab394bf564c9ccd8b4593ba40c9d5461da36fbd226a4",
        "mainos_sidechain_compressor_batch_bugfixes.bin":    "4febe2e60f3ca36df8bac50e291c99f54450adbce188d0f08c5a954b9f48f917",
        "mainos_erase_empty_trigless_locks_batch_bugfixes.bin":"db348f68a32adcc195208e46f6c964d0a5714ba41c1d8c4f2fad6beb2d122922",
        "mainos_reload_from_project_batch_bugfixes.bin":     "0881b726f3617ebfdc6681e988670cf5c24f4001cae5d3fcc0e6bc8b42944db8",
        "mainos_direct_jump_kyoti_batch_bugfixes.bin":       "2cc151e7f9fa7568eca7d1e50d06ed179ff36ffa28f85fe59ce27295917ca21a",
        "mainos_rec_trig_mute_batch_bugfixes.bin":           "fd65e293657e3caa895064255c7dad76882c21640c6eebdc1cf812074744c658",
        "mainos_blackpyramids_303_batch_bugfixes.bin":       "afc4e27b41a65ae123db54bc693383f32faf8e1f19f9cfd040c57e8ce4e2c5ab",
        "mainos_varispeed_batch_bugfixes.bin":               "c3af514f52feb1c46747736d7a6151b5109f664b2561278f37d01e99d8f10663",
        "mainos_varispeed_emus_batch_bugfixes.bin":          "9e0e3f92088be7f968c2fdc8665b69cfe4c13b19b8229ed5831a297687a509e5",
    },
    "build_kyoti.py": {
        "mainos_kyoti_v1.6.bin":                             "0dda89194db3317f61a6ad7c1d68eb025919918d6362869d39cbf361fe3d9a21",
    },
    "build_blackpyramids_303.py":          "88d49307f481d014b7d5b4c024e918d5b0480c87318eb71798869b300948f62b",
    "build_part_change_carryover_fix.py":  "dd2a7e2ba3328364caa560e431195fd248cbb5d83dce1759de1e7e3effc5febd",
    "build_varispeed.py":                  "ce4f769602d1231ac40c48fde43a00c332a1f7b698fdb9442152864803eff169",
    "build_varispeed_emus.py":             "dbf8cd68cf2180db8924b46317378ccf739a92cb36371de41506b784882affc3",
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
