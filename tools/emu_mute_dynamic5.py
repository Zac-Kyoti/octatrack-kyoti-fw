#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Follow-up to emu_mute_dynamic3/4.py: PC-range call tracing around a real trig turned up
almost no `jsr abs.l` activity at all (RTOS task interleaving drowns it out in noise --
28000 traced instructions spanning PRE+POST had only 7 subroutine calls total, none of
them trig_to_voice or FUN_40005178). Tracing code addresses is the wrong instrument here.

Switches to watching DATA instead: FUN_40005178's own body (per the Session-9 Ghidra
decompile) writes exactly one of two "voice command mailbox" locations --
`_DAT_46c7e9fa + track*4` (queued path) or `_DAT_800018de + track*4` (immediate path,
`param_1*4 + -0x7fffe722` == `0x800018de + track*4`). If FUN_40005178 genuinely never
runs for ordinary sequencer trigs (as emu_mute_dynamic.py/2/3/4 all suggest), NEITHER of
these addresses should ever be written for a track that keeps trigging. If they ARE
written by something else entirely, that is the real mechanism. Watches BOTH across the
WHOLE playback window (not a short burst) and cross-references against the known real
trig frames from install_trig_log.

    python3 tools/emu_mute_dynamic5.py [out/mainos_mutemode_dt.bin]
"""
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
IMAGE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/mainos_mutemode_dt.bin")
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn -> "
             "( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )")
import os
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402
import emu_card as ec            # noqa: E402

MAILBOX_A = 0x46c7e9fa      # queued-path voice command mailbox, +track*4
MAILBOX_B = 0x800018de      # immediate-path voice command mailbox, +track*4
FUN_40005178 = 0x40005178


def main():
    img_path = ROOT / IMAGE
    if not img_path.exists():
        sys.exit(f"missing {img_path} -- run tools/build_mutemode_dt.py first")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} saved_bank={saved_bank} final_bank={final_bank} ({elapsed:.0f} ms)")

    writes_a, writes_b, entries = [], [], []

    def mk_hook(log, base):
        def h(u, acc, addr, size, val, d):
            pc = u.reg_read(er.eb.UC_M68K_REG_PC)
            log.append((rt.frame_count, pc, addr - base, val))
        return h
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, mk_hook(writes_a, MAILBOX_A), begin=MAILBOX_A, end=MAILBOX_A + 31)
    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, mk_hook(writes_b, MAILBOX_B), begin=MAILBOX_B, end=MAILBOX_B + 31)

    def on_entry(u, addr, size, ctx):
        entries.append(rt.frame_count)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_entry, begin=FUN_40005178, end=FUN_40005178 + 1)

    rt.install_trig_log()
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print("playing for 6000ms, watching both voice-command mailboxes + FUN_40005178 entry...")
    rt.run(ms=6000)

    print(f"\nreal trig events (install_trig_log), all tracks: {len(rt.live_nibble_log)}")
    for frame, track, val in rt.live_nibble_log:
        print(f"    frame={frame:<6d} track={track} val={val:#04x}")

    print(f"\nFUN_40005178 entered: {len(entries)} times  -> frames: {entries[:20]}")

    print(f"\nMAILBOX_A (0x46c7e9fa+track*4) writes: {len(writes_a)}")
    for frame, pc, off, val in writes_a[:20]:
        print(f"    frame={frame:<6d} pc={pc:#010x} track={off//4} val={val:#010x}")

    print(f"\nMAILBOX_B (0x800018de+track*4) writes: {len(writes_b)}")
    for frame, pc, off, val in writes_b[:20]:
        print(f"    frame={frame:<6d} pc={pc:#010x} track={off//4} val={val:#010x}")

    if not entries and not writes_a and not writes_b:
        print("\n!! FUN_40005178 NEVER runs and NEITHER mailbox is ever written during "
              "ordinary playback -- the whole trig_to_voice/FUN_40005178 mechanism is "
              "unrelated to normal sequencer step-trigs. It must be a manual/live-trig-"
              "only or UI-mute-only path. The real per-step voice dispatch is somewhere "
              "else entirely and needs to be found from scratch.")
    elif entries or writes_a or writes_b:
        print("\n-- FUN_40005178 (or its mailboxes) DOES run during playback -- correlate "
              "the frame numbers above against the real trig frames to see which tracks.")


if __name__ == "__main__":
    main()
