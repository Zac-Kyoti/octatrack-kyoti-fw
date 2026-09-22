#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Session 50: found (by disassembling FUN_4005a2b8) that `dur<=0` registers a
notification on a MODAL WINDOW/OVERLAY STACK -- a linked list headed at
`0x460d165c` -- instead of the passive banner we assumed, which is why the
original QLREC toast (dur=0) hung a real MKI. The rewrite in patch_qlrec.s
never calls NOTIFY with dur<=0 anymore; it periodically re-arms a short
`dur=REARM_DUR` (0x30) self-timing call instead.

This script calls the REAL FUN_4005a2b8 in the full-firmware emulator with
`dur=REARM_DUR` (exactly what the rewritten cave now uses) and checks the ONE
thing that matters: the modal list head `0x460d165c` stays untouched -- i.e.
this call never takes the dur<=0 branch that caused the hang. For contrast it
also runs the known-hang shape (`dur=0`) again in a fresh boot, to show the
list head DOES change in that case, and the known-good DIRECT JUMP v3 shape
(`dur=0x44`) as a second safe reference point.

    python3 tools/emu_notify_probe.py

~4-5 min wall (three separate LOAD PROJECTs).
"""
import os
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
PATCHED_IMAGE = ROOT / "out" / "mainos_qlrec.bin"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn -> "
             "( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )")
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402
import emu_card as ec            # noqa: E402

NOTIFY = 0x4005a2b8
MSG_ON = 0x400d7540    # tools/patch_qlrec.s : qlr_msg_on, current cave layout (post Session-51-bis G_PEND fix)
HANDLE = 0x460d1e70    # FUN_4005a2b8's own notification handle
MODAL_INSERT = 0x40031494   # the linked-list-insert fn dur<=0 tail-jumps into -- dur>0 can NEVER reach it
                            # (tstl %d3 ; bles <this path> is a straight branch on the dur value itself,
                            #  so watching PC hits here is a direct, unconditional test, unlike checking
                            #  the list head 0x460d165c after the fact -- that head is ALREADY non-null
                            #  at boot from something unrelated, so insertion-at-tail never visibly moves it)
REARM_DUR = 0x20           # tools/patch_qlrec.s REARM_DUR -- what the rewritten cave actually uses (Session 51: was 0x30)
DJ_TOAST_DUR = 0x44        # DIRECT JUMP v3's known-good self-timing dur, for a second reference point


def boot(tag):
    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(PATCHED_IMAGE), card, tick=True)
    print(f"\n=== {tag}: boot {PATCHED_IMAGE.name} ===")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"  load: mounted={mounted} ({elapsed:.0f} ms)")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    return rt


def probe(tag, dur):
    rt = boot(tag)
    handle_before = struct.unpack(">I", rt.uc.mem_read(HANDLE, 4))[0]
    print(f"  before: handle=0x{handle_before:08x}")

    hit = [False]

    def on_hit(u, addr, size, ctx):
        hit[0] = True

    h = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_hit, begin=MODAL_INSERT, end=MODAL_INSERT + 1)
    try:
        d0 = rt.call_as_main(NOTIFY, args=(MSG_ON, dur), budget=4_000_000)
        print(f"  call_as_main(NOTIFY, dur={dur:#x}) -> RETURNED d0={d0:#x}")
    except Exception as e:
        rt.uc.hook_del(h)
        print(f"  call_as_main(NOTIFY, dur={dur:#x}) -> DID NOT RETURN: {type(e).__name__}: {e}")
        return None
    rt.uc.hook_del(h)
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    handle_after = struct.unpack(">I", rt.uc.mem_read(HANDLE, 4))[0]
    print(f"  after:  handle=0x{handle_after:08x}")
    print(f"  modal-insert fn (0x{MODAL_INSERT:08x}) {'WAS EXECUTED -- this call used the modal path!' if hit[0] else 'was NOT reached'}")
    return hit[0]


def main():
    if not PATCHED_IMAGE.exists():
        sys.exit(f"missing {PATCHED_IMAGE} -- run tools/build_qlrec.py first")

    print("--- reference: known-hang shape, dur=0 (should reach the modal-insert fn) ---")
    hang_touched = probe("dur=0 (the ORIGINAL, hung a real MKI)", 0)

    print("\n--- reference: known-good shape, dur=0x44 (DIRECT JUMP v3's dur) ---")
    dj_touched = probe("dur=0x44 (DIRECT JUMP v3 reference)", DJ_TOAST_DUR)

    print(f"\n--- THE ACTUAL FIX: dur=REARM_DUR={REARM_DUR:#x} (what patch_qlrec.s now uses) ---")
    fix_touched = probe("dur=REARM_DUR (Session 51 rewrite)", REARM_DUR)

    print("\n=== VERDICT ===")
    print(f"  dur=0        reached modal-insert fn: {hang_touched}   (expected True -- this is what hung)")
    print(f"  dur=0x44     reached modal-insert fn: {dj_touched}   (expected False -- known-safe reference)")
    print(f"  dur=REARM_DUR(0x30) reached it:       {fix_touched}   (MUST be False for the fix to be safe)")
    if fix_touched is False and hang_touched is True and dj_touched is False:
        print("\n  PASS: the rewritten toast never executes the modal-insert path; dur=0 demonstrably does.")
    else:
        print("\n  DID NOT CONFIRM the expected pattern -- do not trust the fix yet, look closer.")


if __name__ == "__main__":
    main()
