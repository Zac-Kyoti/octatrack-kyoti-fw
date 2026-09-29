"""BATCH BUGFIXES -- the three stock Octatrack 1.40C bug fixes, as one module.

All three are fixes to STOCK behaviour: nothing here adds a feature, changes a menu
or touches a setting. Each is independent of the other two; they are bundled because
they are wanted together in practice. (The cost of the bundle: a remix takes all
three or none, and a site conflict on any one of them keeps all three out.)

  BUG 1 -- MIDI PLAYS-FREE TRIG (patch_trigscale.s, `PLAYSFREEFIX`)
    A Plays-Free MIDI track with trig quantize DIRECT and pattern scale PER TRACK
    stalled after its first step on a manual trig. 62 bytes, one 18-byte splice.
    Hardware-confirmed 2026-08-28. Until 2026-09-28 five KYOTI feature builders
    each folded a copy of this into their own standalone image; they no longer do,
    because every copy wrote this same site and the remix ledger refuses that --
    which would have meant no two of those features could share a remix.

  BUG 2 -- EMPTY-PATTERN LED (patch_pattern_led.s, `PATTERNLED`)
    A pattern whose only content is parameter locks -- on a MIDI track, or trigless
    locks on an audio track, with no trig anywhere -- showed as an unused slot, its
    grid LED unlit under [PTN]. 142 bytes, one 6-byte detour.

  BUG 3 -- PART-CHANGE CARRYOVER (patch_partreapply.s, `PARTREAPPLY`)
    After a pattern-triggered Part change, stale per-track state from the old Part
    leaked into the new one. Reported on Elektronauts ("Playback gets carried
    over..."). Two reproducible cases are fixed: a track leaving PICKUP for FLEX
    kept playing the old Part's pickup loop, and a pattern switch into a PICKUP
    track marked that Part edited/unsaved when nothing had changed. 402 bytes, two
    6-byte detours on the same handler.

BUG 3, ROOT CAUSE (static RE + tools/emu_partswitch.py --repro, NOTES.md Session
49/81). The `sys` task's "select Part P" handler at 0x400621a6 -- the site a real
pattern->Part change reaches -- calls FUN_400972fc(newPart, track, oldType) once per
track. For oldType==4 (PICKUP) and newType!=4 that function takes a fast-path branch
that does nothing: no slot rebind, no voice re-trigger. Because PICKUP and FLEX share
one sample arena (0x100b14f0+id*1096; STATIC's is a different arena, which is why a
STATIC machine on the same switch works by accident), the voice's stale SETTINGS
pointer still reads as valid and the FLEX track sounds the old pickup loop. Separately
nothing in the pattern-change path ever republishes the recorder UI cache. The fix
detours the handler's tail, after its existing FUN_400972fc x8 loop, and: republishes
all 8 tracks' recorder records in one 96-byte copy; sets the voice-kill bit for the
PICKUP->notPICKUP transition (stock's own reverse arm already does this); and calls
FUN_40001f18 to re-seed the sample slot, which stock calls on the way INTO PICKUP and
never on the way out. Session 49 copied the kill bit and omitted that re-seed -- it
is the actual fix for the reported case.

⚠️ IF YOUR REMIX INCLUDES DIRECT JUMP, TAKE THIS MODULE WITH IT. DIRECT JUMP changes
the Part by posting stock's own {0x14, part} message, so it reaches the same handler
BUG 3 fixes -- stock path, stock bug included. The two are independent and were
measured as such (Part-change trace, fast-re-cue Program Changes and the whole timing
matrix identical with and without, including a run where every jump changes Part), so
neither needs the other; but DIRECT JUMP gives you many more Part changes to meet the
carryover with.

MEASURED: all three hardware-confirmed on the author's MKI. Standalone images:
tools/build_trigscale_only.py, tools/build_pattern_led.py, tools/build_partreapply.py.
tools/build_bugbuilds.py composes all three onto each finished feature image and
asserts on every run that the composite's changes are the disjoint union of the
feature's and the fixes' own.
"""

import os

from remix.schema import CavePatch, Kind, Module

_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))


def _jmp(target: int) -> bytes:
    return b"\x4e\xf9" + target.to_bytes(4, "big")


def _jsr(target: int) -> bytes:
    return b"\x4e\xb9" + target.to_bytes(4, "big")


# ══════════════ BUG 1: MIDI Plays-Free trig (PLAYSFREEFIX) ══════════════
# 18 bytes are displaced: the jmp is six, then six nops. The cave replays the
# `move.l #0x91a,%d0` it overwrote (it is at offset 6 of the blob).
TS_HOOK = 0x4009b6f2
TS_HOOK_STOCK = bytes.fromhex("203c0000091a4c030800d082204141f00851")
TS_PINNED = bytes.fromhex(
    "7007b0836d18203c0000091a4c030800d082204141f008514ef94009b7042003"
    "51802c3c000008b04c060800d0820680000048f92041d1c04ef94009b704"
)
assert len(TS_PINNED) == 62
assert TS_PINNED[6:12] == TS_HOOK_STOCK[:6]      # the replayed move.l


def ts_emit(addr: int):
    """`jmp`, not the generic installer's `jsr`, over an 18-byte span."""
    return b"", ((TS_HOOK, TS_HOOK_STOCK, _jmp(addr) + b"\x4e\x71" * 6),)


# ══════════════ BUG 2: empty-pattern LED (PATTERNLED) ══════════════
PL_HOOK = 0x4009a464
PL_HOOK_STOCK = bytes.fromhex("2f02202f0008")    # move.l %d2,-(%sp); move.l 8(%sp),%d0
PL_PINNED = bytes.fromhex(
    "2f02202f0008243c00008ed84c020800222f000c243c0009b3404c021800d081"
    "220020010680400e22392040740822482019528066000052200990880c800000"
    "08006500ffec41e8091a53826600ffe020010680400e6ae02040740822482019"
    "528066000024200990880c80000008006500ffec41e808b053826600ffe0202f"
    "00084ef94009a46a241f70014e75"
)
assert len(PL_PINNED) == 142
assert PL_PINNED[:6] == PL_HOOK_STOCK            # the cave opens by replaying them


def pl_emit(addr: int):
    return b"", ((PL_HOOK, PL_HOOK_STOCK, _jmp(addr)),)


# ══════════════ BUG 3: Part-change carryover (PARTREAPPLY) ══════════════
# Both detours are on the SAME stock routine, the "select Part P" handler
# 0x400621a6: the tail (after its FUN_400972fc x8 loop) and the head, where the
# machine-type buffer is snapshotted before that loop dirties it.
PR_TAIL_HOOK = 0x40062216
PR_TAIL_STOCK = bytes.fromhex("4eb9400326a0")    # jsr 0x400326a0
PR_HEAD_HOOK = 0x400621da
PR_HEAD_STOCK = bytes.fromhex("4eb940020898")    # jsr 0x40020898
PR_OFF_CAVE2 = 0x156
PR_BASE = 0x400d7000
PR_PINNED = bytes.fromhex(
    "4fefffc448d77fff42801039100b14cf223c000018b24c010800d0b946c82456"
    "06800008f3822f3c000000602f00487980000c944eb9400208984fef000c7400"
    "163628f749c30c83000000046600009442801039100b14cf223c000018b24c01"
    "0800d0b946c8245606800008eda2d0822040101049c00c800000000467000064"
    "7001e5a812398000184c808113c08000184c428010022f0042801039100b14cf"
    "2f0042801039100b14ce2f004eb940001f184fef000c203c000000a822024c00"
    "1800207c800049d8d1c11028001449c00c8000000004660a2f024eb940006820"
    "588f52820c82000000086600ff5470ff23c0400c0c444eb94003f1b44ab98000"
    "65b8661e42801039100b14cf2f0042801039800000022f004eb9400090944fef"
    "000843f9400d7190101113c0100b145e43f9400d71911011207946c82456d1fc"
    "0009504810804cd77fff4fef003c4eb9400326a04e754fefffc448d77fff1039"
    "100b145e43f9400d71901280207946c82456d1fc00095048101043f9400d7191"
    "12804cd77fff4fef003c4ef9400208980000"
)
assert len(PR_PINNED) == 402


def _pr_rebase(blob: bytes, frm: int, to: int) -> bytes:
    """This cave alone is not position-independent: 4 longwords hold absolute
    addresses inside it. Verified against real m68k-elf-ld output at 0x400d7300
    and 0x400d6d00 -- byte-identical at both."""
    out = bytearray(blob)
    for i in range(0, len(blob) - 3, 2):
        w = int.from_bytes(blob[i:i + 4], "big")
        if frm <= w < frm + len(blob):
            out[i:i + 4] = (w - frm + to).to_bytes(4, "big")
    return bytes(out)


def pr_reference(addr: int) -> bytes:
    return _pr_rebase(PR_PINNED, PR_BASE, addr)


assert sum(1 for i in range(0, len(PR_PINNED) - 3, 2)
           if PR_BASE <= int.from_bytes(PR_PINNED[i:i + 4], "big")
           < PR_BASE + len(PR_PINNED)) == 4


def pr_emit(addr: int):
    """The tail hook goes through hook_addr (a jsr to the cave's base); the head
    hook reaches cave2 and is planted here."""
    return b"", ((PR_HEAD_HOOK, PR_HEAD_STOCK, _jsr(addr + PR_OFF_CAVE2)),)


MODULE = Module(
    name="batch-bugfixes",
    key="BATCH BUGFIXES",
    kind=Kind.CF_PATCH,
    doc="Three stock 1.40C bug fixes in one module: MIDI Plays-Free trig, "
        "empty-pattern LED, and Part-change carryover.",
    cf_patches=(
        CavePatch(
            label="bug 1: MIDI plays-free trig",
            cave_addr=None,
            pinned=TS_PINNED,
            source=os.path.join(_HERE, "patch_trigscale.s"),
            hook_addr=None,                      # jmp over 18 bytes, via emit()
            hook_stock=b"",
            emit=ts_emit,
            reference=lambda addr: TS_PINNED,    # position independent
            cpu="5407",
            report_note=" (PLAYSFREEFIX: Plays-Free MIDI trig with DIRECT quantize "
                        "+ PER TRACK scale; 18-byte splice at 0x4009b6f2)",
        ),
        CavePatch(
            label="bug 2: empty-pattern LED",
            cave_addr=None,
            pinned=PL_PINNED,
            source=os.path.join(_HERE, "patch_pattern_led.s"),
            hook_addr=None,                      # jmp, via emit()
            hook_stock=b"",
            emit=pl_emit,
            reference=lambda addr: PL_PINNED,    # position independent
            cpu="5407",
            report_note=" (PATTERNLED: a pattern holding only p-locks lights its "
                        "grid LED under [PTN])",
        ),
        CavePatch(
            label="bug 3: part-change carryover",
            cave_addr=None,
            pinned=PR_PINNED,
            source=os.path.join(_HERE, "patch_partreapply.s"),
            hook_addr=PR_TAIL_HOOK,              # jsr to the cave base
            hook_stock=PR_TAIL_STOCK,
            emit=pr_emit,                        # + the head hook -> cave2
            reference=pr_reference,
            cpu="5407",
            report_note=" (PARTREAPPLY: recorder cache republished, PICKUP->FLEX "
                        "voice re-seed; tail 0x40062216 + head 0x400621da)",
        ),
    ),
)
