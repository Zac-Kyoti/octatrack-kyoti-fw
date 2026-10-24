from remix.stock_guard import stock_guard
"""QUANTIZE_LIVE_REC_TOGGLE -- reach the QUANTIZE LIVE REC setting from the front
panel instead of PERSONALIZE.

Hold [REC] and tap [PLAY]: a toast shows the current setting. Tap [PLAY] again
WHILE THAT TOAST IS UP to invert it; tap again to invert it back. Once the toast
has gone (1 s), the next tap just shows the setting again. The first [REC]+[PLAY]
still starts live recording exactly as on stock. This is the all-or-nothing
live-record quantize, not the per-track TRIG QUANT.

No PERSONALIZE menu surgery: the variable, its getter/setter and its power-cycle
persistence are all stock. The module only adds a front-panel gesture that writes
the same word plus its 'ANDY' battery shadow and re-checksums.

TIMING COMES FROM THE OS, NOT FROM US. "Is the toast still up" is read from the
OS's own toast state (the handle 0x460d1e70 / countdown 0x460d1e6c); this module
ticks nothing of its own. That is deliberate: a third detour, `qlr_tick` at 0x400522ca, used to drive the toast from inside
the ENGINE FRAME HANDLER. FUN_4005a2b8 (NOTIFY) and FUN_40056bec (close) both
bottom out in FUN_40000c3c, the kernel post/wake -- legal from a key handler, not
from the engine frame path -- and it hard-crashed a real MKI on 2026-09-25 (dead
controls, loud persistent HF crackle). It also fired far too rarely to time
anything. That site is retired, and the standalone builder asserts it is left
byte-for-byte stock on every build. DO NOT HOOK 0x400522ca.

Nothing is kept in the 0x80006a40+ scratch block either: it sits in the DSP shared
RAM window and does not survive live audio on hardware.

The cave is position-independent, so it may land anywhere the allocator puts it.

MEASURED: hardware-confirmed on the author's MKI: the show-then-invert gesture works
on this version, with the tick hook removed (2026-09-25), and a setting changed with it
survives a power cycle (2026-09-30). The standalone image is tools/build_quantize_live_rec_toggle.py
in the author's repository. See TESTING.md for this version's results.

patch_qlrec.s is the author's file, unchanged (Zac-Kyoti/octatrack-kyoti-fw 3ead7f9): the
"LIVE REC: QUANTIZED" / "LIVE REC: UNQUANTIZED" toasts, the PERSONALIZE redraw after a flip
(only while PERSONALIZE is the open PROJECT page) and the store order that keeps the unit
stock-free are all his. The author's declaration is one floating CavePatch whose emit()
plants the two `jmp` detours and carries the stock instruction bytes it expects at each
site. Here the same cave is one floating Linked unit (`qlr`, linked by the build where it
lands and compared every build with the SHA-256 of the author's 196 bytes at 0x400d7400),
the two `jmp`s are Detours onto its global symbols, and every stock expectation is an
address/length/SHA-256 guard read from the builder's own OS file. No stock bytes are
carried.
"""

import os

from remix.schema import Detour, Kind, Linked, Module

# This module's own directory, relative to the build's cwd (octabam's repo root).
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

# ---- the two hook sites (both `jmp`: the cave replays and rejoins stock) ------
# [PLAY] in the transport handler: its first instruction, the "project ready?" call.
PLAY_HOOK = 0x40061778
# [REC] release: the instruction that clears the held flag 0x460d1726.
RECREL_HOOK = 0x4004883a

# RETIRED, and it must stay stock -- see the note above. Not declared as a claim:
# the site is only lethal to hook from the engine frame path, so another module
# may have a legitimate reason to take it. verify.py reads this guard and refuses
# an image of this module in which the site differs from the original OS.
RETIRED_TICK_HOOK = 0x400522ca
RETIRED_TICK_GUARD = stock_guard(RETIRED_TICK_HOOK, 6, "1eb782bde4b72ae5bad5fe826898c238315df94d4a4e583f7e7949210e3d02fb")

# patch_qlrec.s, m68k-elf-as -mcpu=5407, linked at 0x400d7400: 196 bytes, the author's unit byte for
# byte. It is position independent (its strings are reached PC-relative, stock code by absolute
# address), so the one reference holds wherever it floats.
UNIT_BYTES = 196
RECREL_OFFSET = 0x84                     # qlr_recrel within the unit; qlr_play is at 0
REFERENCE = (0x400d7400, "065cafcb0c3896aad746efd0ce9bf022fb6a6d17a7e593bb7f9e889c2861b9e4")

MODULE = Module(
    name="quantize-live-rec-toggle",
    key="QUANTIZE_LIVE_REC_TOGGLE",
    kind=Kind.CF_PATCH,
    author="Zac-Kyoti", author_url="https://github.com/Zac-Kyoti",
    doc="QUANTIZE LIVE REC from the front panel: hold [REC], tap [PLAY] to see "
        "it, tap again while the toast is up to invert it.",
    linked=(
        Linked("qlr", os.path.join(_HERE, "patch_qlrec.s"), reference=REFERENCE),
    ),
    detours=(
        Detour(PLAY_HOOK, stock_guard(PLAY_HOOK, 6, "163f39714c1f16fb3ec79b74858c4c781336055671dc3ee9016adcf62e72bd64"), "qlr", "qlr_play",
               "[PLAY]: with [REC] held, show QUANTIZE LIVE REC, or invert it while the toast is up"),
        Detour(RECREL_HOOK, stock_guard(RECREL_HOOK, 6, "0022d5dccf16d07cd4fcd66f5ef0e424b016a1394795d993d65e24eeeace7afc"), "qlr", "qlr_recrel",
               "[REC] release: clear the held flag, close the toast"),
    ),
)

assert all(d.kind == "jmp" and d.site != RETIRED_TICK_HOOK for d in MODULE.detours), "0x400522ca must stay stock"
