"""QUANTIZE LIVE REC TOGGLE -- reach the QUANTIZE LIVE REC setting from the front
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
ticks nothing of its own. That is deliberate and it is the whole story of Session
93: a third detour, `qlr_tick` at 0x400522ca, used to drive the toast from inside
the ENGINE FRAME HANDLER. FUN_4005a2b8 (NOTIFY) and FUN_40056bec (close) both
bottom out in FUN_40000c3c, the kernel post/wake -- legal from a key handler, not
from the engine frame path -- and it hard-crashed a real MKI on 2026-09-25 (dead
controls, loud persistent HF crackle). It also fired far too rarely to time
anything. That site is retired, and the standalone builder asserts it is left
byte-for-byte stock on every build. ⚠️ DO NOT HOOK 0x400522ca.

Nothing is kept in the 0x80006a40+ scratch block either: it sits in the DSP shared
RAM window and does not survive live audio on hardware.

The cave is position-independent, so it may land anywhere the allocator puts it.

MEASURED: hardware-confirmed on the author's MKI, after the Session 93 crash was
found and the tick hook removed. The standalone image is tools/build_qlrec.py.
"""

import os

from remix.schema import CavePatch, Kind, Module

_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

# ---- the two hook sites (both `jmp`: the cave replays and rejoins stock) ------
# [PLAY] in the transport handler.
PLAY_HOOK = 0x40061778
PLAY_HOOK_STOCK = bytes.fromhex("4eb94009b5c0")        # jsr 0x4009b5c0
# [REC] release: clears the held flag 0x460d1726.
RECREL_HOOK = 0x4004883a
RECREL_HOOK_STOCK = bytes.fromhex("42b9460d1726")      # clr.l (0x460d1726).l

# RETIRED, and it must stay stock -- see the note above. Not declared as a claim:
# the site is only lethal to hook from the engine frame path, so another module
# may have a legitimate reason to take it.
RETIRED_TICK_HOOK = 0x400522ca
RETIRED_TICK_STOCK = bytes.fromhex("45f946c7dfba")

# ---- cave layout -------------------------------------------------------------
OFF_PLAY = 0x0
OFF_RECREL = 0x74

# patch_qlrec.s, m68k-elf-as -mcpu=5407, linked at 0x400d7400: 176 bytes,
# sha256 52c26af67443e470147844a52009d09f.  Position-independent -- verified
# byte-identical at 0x400d7700 and 0x400d7100.
PINNED = bytes.fromhex(
    "4ab9460d1726670000604ab9460d1e70670000046004600000262039800000ac"
    "0a800000000102800000000123c0800000ac23c0100fff3c4eb94001f23c2039"
    "800000ac41fa00444a80670441fa004e4878003c2f084eb94005a2b8508f4ab9"
    "460d172a67024e754eb94009b5c04ef94006177e42b9460d17264ab9460d1e70"
    "67064eb940056bec4e755155414e54204c49564520524543204f4e005155414e"
    "54204c49564520524543204f46460000"
)
assert len(PINNED) == 176, len(PINNED)
assert PINNED[OFF_PLAY:OFF_PLAY + 6] == bytes.fromhex("4ab9460d1726")   # qlr_play: REC held?


def _jmp(target: int) -> bytes:
    return b"\x4e\xf9" + target.to_bytes(4, "big")


def emit(addr: int):
    """The source is the only truth for the bytes (b""). Both detours are `jmp`,
    not the generic installer's `jsr`, so they are planted here."""
    return b"", (
        (PLAY_HOOK, PLAY_HOOK_STOCK, _jmp(addr + OFF_PLAY)),
        (RECREL_HOOK, RECREL_HOOK_STOCK, _jmp(addr + OFF_RECREL)),
    )


MODULE = Module(
    name="quantize-live-rec-toggle",
    key="QLREC TOGGLE",
    kind=Kind.CF_PATCH,
    doc="QUANTIZE LIVE REC from the front panel: hold [REC], tap [PLAY] to see "
        "it, tap again while the toast is up to invert it.",
    cf_patches=(
        CavePatch(
            label="qlrec toggle cave",
            cave_addr=None,                      # floats: position independent
            pinned=PINNED,
            source=os.path.join(_HERE, "patch_qlrec.s"),
            hook_addr=None,                      # both detours are jmp, via emit()
            hook_stock=b"",
            emit=emit,
            reference=lambda addr: PINNED,       # same bytes at any address
            cpu="5407",
            report_note=" (2 jmp detours: [PLAY] 0x40061778, [REC] release "
                        "0x4004883a; toast state read from the OS, no tick hook)",
        ),
    ),
)
