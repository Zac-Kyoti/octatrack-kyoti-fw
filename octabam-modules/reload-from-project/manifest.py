"""RELOAD_FROM_PROJECT -- reload ONE track's sequence from the CF card WITHOUT
stopping the transport.

Stock can only reload a whole bank, and doing so stops the sequencer. Two direct
chords, no modal window and no timeout:

    [PTN]  + [TRACK n]   reload that track's card-saved sequence, Part untouched
    [BANK] + [TRACK n]   the same, and re-apply the saved Part

It reloads the pattern that is PLAYING, on an audio or a MIDI track, and never
restarts the sequence or the internal metronome. A stock-style toast confirms when
the reload has FINISHED -- and says so if the trigs did not land.

Deferred by the author's own scoping: all-tracks and whole-bank reload.

HOW IT GOT HERE. An earlier design (RELOAD2) put a modal picker window on a
[PTN]-hold with arrow navigation; it needed ten detours and a keymap-layer poke,
and that poke was the mechanism behind a slot collision with DIRECT JUMP and
several routing bugs. This is the Session 85 redesign: six detours, two plain
chords, and NEITHER chord site pokes a keymap layer record. Full RE and design
rationale: patch_reload3.s's own header; dynamic proof against the real stock
layer-push code: NOTES.md Session 85.

⚠️ NO PRIVATE STATE IN THE DSP WINDOW. RELOAD_FROM_PROJECT's request bytes used to live at
0x80006a54-55, in the 0x80006a40+ scratch block. On hardware they were overwritten
between the chord and the worker: it reloaded MIDI track 6 instead of audio track 1
and cheerfully said RELOADED (Session 98). Everything now lives in the cave, and the
standalone builder refuses any reference into 0x80006a40..0x80006abf.

The worker itself (message case 0x14, rl_job) is stock's own; this module hooks it
rather than reimplementing it.

MEASURED: hardware-confirmed on the author's MKI, including that the sequencer and
the internal metronome keep their phase (RELOAD_NOW is not armed on any path).
The standalone image is tools/build_reload_from_project.py.
"""

import os

from remix.schema import CavePatch, Kind, Module

_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

# ---- the six hook sites, all `jmp` (the cave replays and rejoins stock) -------
# Two are EIGHT-byte spans: the jmp is six, so one nop follows, or the displaced
# span would be left half-rewritten.
HOOKS = (
    # (site, stock bytes, symbol, span)
    (0x40083dc4, "2f02242f0008",     "rl3_ptn_trk",   6),   # [PTN]  + [TRACK n]
    (0x40040250, "2f02222f0008",     "rl3_bank_trk",  6),   # [BANK] + [TRACK n]
    (0x4007af42, "487a04c442a7",     "rl3_bank_show", 6),   # [BANK] display
    (0x4007b3e0, "7002b0b9460e73c6", "rl3_bank_rel",  8),   # [BANK] release
    (0x40023c62, "71f9460bd910",     "rl_done",       6),   # the FINISHED toast
    (0x40085864, "2d4afd762f2a0004", "rl_job",        8),   # message case 0x14 worker
)

# ---- cave layout: offsets of the six entry points, from m68k-elf-nm -----------
OFF = {
    "rl3_ptn_trk": 0x0,
    "rl3_bank_trk": 0x22,
    "rl3_bank_show": 0x206,
    "rl3_bank_rel": 0x248,
    "rl_done": 0x36e,
    "rl_job": 0x42a,
}
CAVE_LEN = 0x838

# patch_reload3.s, m68k-elf-as -mcpu=5407 (RL_DONE is the source's default), linked at
# 0x400d6500 -- the address the standalone, hardware-confirmed image uses.
# 2104 bytes, sha256 bd02dd428559e27abea093612326aed0.
PIN_BASE = 0x400d6500
PINNED = bytes.fromhex(
    "7001b0af00086600000e7000102f0007610000904e752f02242f00084ef94008"
    "3dca7001b0af00086600006c4ab946c7dd3e670c7000102f0007610000664e75"
    "4ab946c7dd566700004e7000102f00070480000000102f007000103980000003"
    "2f004eb94004aab4588f4a80670a700213c0400d6c1c6008700313c0400d6c1c"
    "700113c0400d6c36201f4eba028642b9460e73c24e752f02222f00084ef94004"
    "02560480000000102f00700113c0400d6c1c201f4eba025c70ff23c0460d173e"
    "4e75487800302f084eb94005a2b8508f4e754fefffd848d73cfc286f002c2e2f"
    "00304ab9460d1e7067064eb940056bec7c007a00ba876c162005e58820740800"
    "610000dcb0866f022c00528560e606860000000f200753802200e78890810680"
    "000000122800487940056bec4878000a42a742a72f042f064eb94005829c4fef"
    "00184a806700008e23c0460d1e7026404879400ba86242a72f142f0b4eb94005"
    "70084fef0010260b0683000000247401b4876c0000502002e58824740800204a"
    "6100005c220692806a027200e28120022a00e78890852a0404850000000b9a80"
    "2f0a2f3cffffffff2f052f012f034879400ba8624eb940012bd84fef00185282"
    "6000ffae700123c046c7c72c703023c0460d1e6c4cd73cfc4fef00284e752f08"
    "2f3cffffffff4879400ba8624eb940012f304fef000c4e75487800022f084eba"
    "fed2508f4e754a3a052c66284879400cff144eb940031494588f4879400cff28"
    "4eb94007e760588f42a74eb94007e998588f4e754239400d6c3448794007b408"
    "42a74ef94007af484a3a04ec670e4239400d6c364eb94007b4084e754ab9460e"
    "73c666344ab9460e73c2661e2039460d1e5c670e203c4007b408b0b9460d1e60"
    "67164eb94007b408600e700113c0400d6c344eb94007af307002b0b9460e73c6"
    "4ef94007b3e854524b205345512052454c4f41444544000054524b2053455120"
    "2b2050415254000052454c4f4144454400000000400d67dc400d67ec53455120"
    "52454c4f4144204c4f5354004e4f5420524553544f5245442100400d67a6400b"
    "41bb400d67b8400d67c8700010398000000002800000000713c0400d6c167000"
    "1039800000126702700113c0400d6c171039800065be13c0400d6c15700313c0"
    "400d6c1470001039800065bd7201e1a92f014eb940022778588f4e7554256420"
    "534551004d5425642053455100004a3a03a8660e3039460bd91048c04ef94002"
    "3c684239400d6c184a3a03986700005070001039800065bd223c0009b3404c01"
    "0800207c400e21e0d1c070001039800065be223c00008ed84c010800d1c0d1fa"
    "035e43fa0360741010181219b0016606538266f46008700413c0400d6c1c4239"
    "400d6c227000103a033467384239400d6c1c53806726538067185380670a41fa"
    "fed46100fdf4601c41fafef06100fdea601241fafeee6100fde0600841fafe88"
    "4ebafca04ef940023c762d4afd762f007000103a02e0670e0c80000000036312"
    "4239400d6c14201f2f2a00044ef94008586c201f600000024fefffd848d73cfc"
    "7a001a3a02b17000103a02aa23c0400d6c104239400d6c144239400d6c183039"
    "460fab5c33c0400d6c3c4eba02144a806a0670f4600001e22f3c00000016487a"
    "0360487a031c4eb9400165644fef000c4a806f0001dc7c001c3a035ae18e7000"
    "103a03538c8078002f064879460aff60487a02ee4eb94008cebc4fef000c4a80"
    "6b0001ae5284b8856fde487a02d44eb94001677c588f70001039800065bd223c"
    "0009b3404c010800287c400e21e0d9c02005223c00008ed84c010800d9c02e3a"
    "01f07003b087670000742a4cdbfc00008e577000101523c0400d6c382f3c0000"
    "8ed84879460aff602f0c4eb9400208984fef000c2a4cdbfc00008e577001b087"
    "660a203a01d41a80600000ea7600161502830000000313c38000000370001039"
    "800065bd2f032f004eb940009094508f700123c046c7c72c600000ba7000103a"
    "01760280000000074a3a016d6614223c0000091a4c0108002400263c0000091a"
    "6018223c000008b04c0108000680000048d02400263c000008b02f03203c460a"
    "ff60d0822f00200cd0822f004eb9400208984fef000c207c460aff60d1c243fa"
    "0124701012d8538066fa23c2400d6c1e700113c0400d6c22204cd1fc00008e55"
    "4a106630227c460aff60d3fc00008e53204cd1fc00008e531011108010290001"
    "1140000112398000663db001670613c08000663d700123c046c7c72c700113c0"
    "400d6c1870001039800065bd2f004eb94000faf0588f7001323a00c233c1460f"
    "ab5c4cd73cfc4fef00284ef9400858a8487a012e4eb94001677c588f70ff60d8"
    "4fefffd848d73cfc42a742a74eb940025230508f72001239800065bd52812f01"
    "2f002f3c400b86d8487a00764eb940013a084fef001041fa00e8701042985380"
    "66fa2f3c000070004879460a8f604879400b3289487a004a487a00c64eb94001"
    "68644fef00144cd73cfc4fef00284e7500000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000"
)
assert len(PINNED) == CAVE_LEN, len(PINNED)


def _rebase(blob: bytes, frm: int, to: int) -> bytes:
    """The cave is NOT position-independent: 29 longwords hold absolute addresses
    inside it (its own state and tables -- this module keeps everything in the
    cave by design, see the Session 98 note above). Relocating is rebasing
    exactly those. Verified against real m68k-elf-ld output at 0x400d6800 and
    0x400d6c00 -- byte-identical at both."""
    out = bytearray(blob)
    for i in range(0, len(blob) - 3, 2):
        w = int.from_bytes(blob[i:i + 4], "big")
        if frm <= w < frm + len(blob):
            out[i:i + 4] = (w - frm + to).to_bytes(4, "big")
    return bytes(out)


def reference(addr: int) -> bytes:
    """The ratified bytes AT `addr`; this cave floats."""
    return _rebase(PINNED, PIN_BASE, addr)


assert sum(1 for i in range(0, CAVE_LEN - 3, 2)
           if PIN_BASE <= int.from_bytes(PINNED[i:i + 4], "big") < PIN_BASE + CAVE_LEN) == 29


def emit(addr: int):
    """The source is the only truth for the bytes (b""). All six detours are `jmp`,
    so none can go through the generic installer's `jsr`; an eight-byte span gets
    the jmp plus one nop."""
    pokes = []
    for site, stock, sym, span in HOOKS:
        jmp = b"\x4e\xf9" + (addr + OFF[sym]).to_bytes(4, "big")
        pokes.append((site, bytes.fromhex(stock), jmp + b"\x4e\x71" * ((span - 6) // 2)))
    return b"", tuple(pokes)


MODULE = Module(
    name="reload-from-project",
    key="RELOAD_FROM_PROJECT",
    kind=Kind.CF_PATCH,
    doc="Reload one track's sequence from the card without stopping the "
        "transport: [PTN]+[TRACK n], or [BANK]+[TRACK n] to re-apply the Part.",
    cf_patches=(
        CavePatch(
            label="RELOAD_FROM_PROJECT cave",
            cave_addr=None,                  # floats; 29 self-refs are rebased
            pinned=PINNED,
            source=os.path.join(_HERE, "patch_reload3.s"),
            hook_addr=None,                  # six jmp detours, all via emit()
            hook_stock=b"",
            emit=emit,
            reference=reference,
            cpu="5407",
            report_note=" (2 chords: [PTN]/[BANK] + [TRACK n]; 6 jmp detours, "
                        "two of them 8-byte spans; stock's own 0x14 worker)",
        ),
    ),
)
