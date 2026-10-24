from remix.stock_guard import stock_guard
"""MUTE_MODES -- what a muted (or soloed-out) audio track does, chosen per unit in
PERSONALIZE -> MUTE MODE:

    OT      stock: an instant post-FX cut
    OTFX    hard dry cut, the track's FX inserts ring their tails out, and the
            sequencer is left alone (trigs keep firing underneath)
    OTFX-T  as OTFX, and new trigs are suppressed
    DT-T    a Digitakt-style sequencer mute: the sounding voice rides its own amp
            envelope out, only new trigs are suppressed

Default OT, so a freshly flashed unit behaves as stock. The setting lives in the free
PERSONALIZE word 0x800000dc and survives power-off: the boot 'ANDY' battery restore is
widened from `pea 0x64` to `pea 0x70` at its three sites so it covers that word.

TWO UNITS. `mm_softmute` (patch_softmute.s) is the mute behaviour: six detours into the
frame builder, the trig dispatch, the fresh-voice bind and the per-trig flag word.
`mm_menu` (patch_mutemode.s) is the PERSONALIZE row: label, getter, setter.

THE MENU. MUTE MODE goes in at index 2, right after PREVIEW WITHOUT FX, as in
tools/build_mute_modes.py: TableGrow(count=16, insert_at=2) relocates each of the three
16-entry stock arrays with MUTE MODE spliced in, and the row count goes 15 -> 16 (MKI),
16 -> 17 (MKII). LED BRIGHTNESS stays the last row and stays MKII-only. Nothing in the
firmware keys off a PERSONALIZE row's position (every reference to the menu's
cursor/scroll/count/row state is inside 0x40068e00..0x40069074, NOTES.md Session 19).

SC_KEY. Beside SIDECHAIN_COMPRESSOR, a muted track that a COMPRESSOR uses as its KEY keeps
feeding it, the way stock mute does (Session 116): mm_softmute's remix.inc carries
`.set SC_KEY,1` when SIDECHAIN_COMPRESSOR is in the remix and is empty otherwise (the source
tests it with `.ifdef`). Its `reference` names the variant: with SC_KEY, the bytes of the
KYOTI V1.0 combined image (tools/build_kyoti.py, --defsym SC_KEY=1) at their address there.

MEASURED. Hardware-confirmed on the author's MKI (tools/build_mute_modes.py, the promoted
standalone image, and the KYOTI V1.0 combined image). Both units, assembled with no
symbols defined (DT_MODE defaults to 1 in the source), are byte-identical to that build
at its addresses -- the `reference` pairs below -- for -mcpu=5407 and 54455 alike; with
SC_KEY, mm_softmute is byte-identical to the KYOTI V1.0 image at 0x400d74e4, and ran on the
author's MKI in an octabam-built image with SIDECHAIN_COMPRESSOR (2026-10-04): a muted KEY
keeps ducking in every MUTE MODE.
"""

import os

from remix.schema import Detour, Kind, Linked, Module, Poke, TableGrow

# This module's own directory, relative to the build's cwd (octabam's repo root):
# "modules/mute-modes" checked out directly, or
# "modules/mute-modes/upstream/octabam-modules/mute-modes" as octabam's submodule of
# Zac-Kyoti/octatrack-kyoti-fw. One manifest serves both layouts.
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

H = bytes.fromhex

SC = "SIDECHAIN_COMPRESSOR"


def _sc_key_inc(modules):
    """remix.inc for mm_softmute: SC_KEY only beside SIDECHAIN_COMPRESSOR."""
    return ".set SC_KEY,1\n" if SC in modules else "| no SIDECHAIN_COMPRESSOR: no SC_KEY\n"


def _softmute_ref(modules):
    """The variant the author ratified for this selection."""
    if SC in modules:       # tools/build_kyoti.py's placement in KYOTI V1.0
        return (0x400d74e4, "8814aa2ca49df775371b17c6c14116494bca7c40febd2dca94c7e90fec7e2009")
    return (0x400d7400, "d56d848e51e96f9561028741a46e509872981fdce6b2e17ee55831d47db5d356")

# The PERSONALIZE pointer arrays (16 u32 each in 1.40C) and the code that names them.
LABELS, GETTERS, SETTERS = 0x400b2a34, 0x400b2a74, 0x400b2ac0
COUNT_AT = 0x40068fb2                    # moveq #15,%d1 in the count function
ANDY_RESTORE_SITES = (0x4001f322, 0x4001f3be, 0x4001fb24)

MODULE = Module(
    name="mute-modes",
    key="MUTE_MODES",
    kind=Kind.CF_PATCH,
    author="Zac-Kyoti", author_url="https://github.com/Zac-Kyoti",
    doc="PERSONALIZE -> MUTE MODE: OT (stock) / OTFX / OTFX-T / DT-T -- dry cut with FX "
        "tails, trig suppression, or a Digitakt-style sequencer mute.",
    linked=(
        # Linked at the standalone image's own addresses by tools/build_mute_modes.py.
        Linked("mm_softmute", os.path.join(_HERE, "patch_softmute.s"),
               include=_sc_key_inc, reference=_softmute_ref),
        Linked("mm_menu", os.path.join(_HERE, "patch_mutemode.s"),
               reference=(0x400d7800,
                          "4c6702aaae1840d9a95a274bd97e252b4bd1e39338c0e50c5257e96060bd4220")),
    ),
    detours=(
        Detour(0x40004dc6, stock_guard(0x40004dc6, 6, "0759b4a7055beab59cdc9d7b8f51bcc27fc8e6b07d38842260ceef916dc33d53"), "mm_softmute", "pre",
               "frame builder: per-frame silenced set, dry cut, release"),
        Detour(0x40006844, stock_guard(0x40006844, 6, "27f17790db914b0847a6bd64cfef8523d1910193c6c550577e389ea506a68b94"), "mm_softmute", "mt_trig",
               "drop a new trig on a silenced track"),
        Detour(0x4000f4dc, stock_guard(0x4000f4dc, 8, "c605d386cc7bbf132d9a1bc10d655c3f8f550c75e0cf51715ac2966015b40068"), "mm_softmute", "mt_rebind",
               "voice rebind on a silenced track", pad_to=8),
        Detour(0x4000d498, stock_guard(0x4000d498, 6, "00dfac25f63401293b216e5ec256e32776a875e1f4d10cf27f31694e95f70308"), "mm_softmute", "dt_trig",
               "trig dispatch (per-machine-type handler call)"),
        Detour(0x40006820, stock_guard(0x40006820, 8, "87faf47c9893d1a9506259f68551bf06eb1ce723ac12cfae49a5b10b8b169fb6"), "mm_softmute", "fresh_bind",
               "fresh voice bind, gated at its single entry", pad_to=8),
        Detour(0x40004c72, stock_guard(0x40004c72, 6, "6314eb6bf2fc2b8a735ece556af833c4937e3c2added6668f6015e33455866d0"), "mm_softmute", "trigflag",
               "per-trig flag bits in the DSP frame word"),
    ),
    tables=(
        TableGrow("PERSONALIZE labels", LABELS, 16, (("mm_menu", "lbl_mutemode"),),
                  ((0x40068efe, LABELS),), insert_at=2),
        TableGrow("PERSONALIZE getters", GETTERS, 16, (("mm_menu", "get_mutemode"),),
                  ((0x40068f0a, GETTERS),), insert_at=2),
        TableGrow("PERSONALIZE setters", SETTERS, 16, (("mm_menu", "set_mutemode"),),
                  ((0x40069022, SETTERS), (0x4006903e, SETTERS), (0x40069056, SETTERS)),
                  insert_at=2),
    ),
    pokes=(
        Poke(COUNT_AT, stock_guard(COUNT_AT, 2, "5dd82fd23ac20130aebe3391a4c9a9fda6ca01bd143223a558ec253b65083dfd"), H("7210"),
             "PERSONALIZE rows 15 -> 16 (MKI), 16 -> 17 (MKII): + MUTE MODE"),
    ) + tuple(
        Poke(site, stock_guard(site, 4, "8c4c50dbddad08d1ae644a694665e608f2bbdb90d7a321fc640e844ae4c149fa"), H("48780070"),
             "ANDY restore pea 0x64 -> 0x70: MUTE MODE (0x800000dc) survives power-off")
        for site in ANDY_RESTORE_SITES
    ),
)
