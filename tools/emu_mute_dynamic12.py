#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Final decisive check on the mt_trig fix. dynamic11 showed mt_trig takes the 'silenced'
branch 100% of the time for the muted track (never 'pass') across the whole run --
which logically guarantees FUN_4000672c (the actual sample-restart, called from deep
inside FUN_40006844's body, well after our early `rts`) never executes for it. This
confirms that directly: hooks FUN_4000672c's own entry, logs the track argument on
every call, across the same real playback. Also explains dynamic9's confusing result:
the arena-rebind writes (+0x04/+0x08) it watched come from an EARLIER, separate,
always-unconditional caller (0x4000f454-ish) that runs regardless of mute state --
harmless bookkeeping, not the audible step -- so their presence for a muted track was
never evidence the fix had failed.

    python3 tools/emu_mute_dynamic12.py [out/mainos_mutemode_dt.bin]
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

MUTE_STATE = 0x80000008
GATE = 0x800000dc
T_MUTED = 0
AMP_RESTART = 0x4000672c   # the actual "restart the sample" call, from inside FUN_40006844


def main():
    img_path = ROOT / IMAGE
    if not img_path.exists():
        sys.exit(f"missing {img_path} -- run tools/build_mutemode_dt.py first")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(img_path), card, tick=True)
    print(f"boot: {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load: mounted={mounted} final_bank={final_bank} ({elapsed:.0f} ms)")

    curbank = rt.uc.mem_read(0x80000002, 1)[0]
    rt.uc.mem_write(0x800065b8, b"\x00\x00\x00\x00")
    rt.run(until=lambda r: r.pc == er.MAIN_SPIN)
    rt.seq_select_live(curbank, 1)
    rt.run(ms=500)

    rt.uc.mem_write(GATE, struct.pack(">I", 1))
    rt.uc.mem_write(MUTE_STATE, struct.pack(">I", 1 << (8 + T_MUTED)))

    calls = []

    def on_call(u, addr, size, ctx):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        track = struct.unpack(">i", u.mem_read(sp + 20, 4))[0]
        calls.append((rt.frame_count, track))
    h = rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_call, begin=AMP_RESTART, end=AMP_RESTART + 1)

    rt.install_trig_log()
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.start_transport_live()
    print(f"playing 6000ms, watching every FUN_4000672c (real sample-restart) call, "
          f"track {T_MUTED+1} muted...")
    rt.run(ms=6000)
    rt.uc.hook_del(h)

    by_track = {}
    for frame, track in calls:
        by_track.setdefault(track, []).append(frame)
    print(f"\nFUN_4000672c calls by track: {{t: count}} = { {t: len(f) for t, f in sorted(by_track.items())} }")
    muted_calls = by_track.get(T_MUTED, [])
    print(f"\nmuted track {T_MUTED+1}: {len(muted_calls)} amp-restart calls (want 0): {muted_calls[:10]}")

    trig_frames_muted = sorted({f for f, tr, v in rt.live_nibble_log if tr == T_MUTED})
    print(f"real trig frames on muted track {T_MUTED+1} (for reference): {trig_frames_muted}")

    print("\n=== VERDICT ===")
    if not muted_calls:
        print(f"  PASS: FUN_4000672c (the real sample-restart) was NEVER called for the muted "
              f"track across {len(trig_frames_muted)} real trigs, while other tracks got "
              f"{sum(len(f) for t, f in by_track.items() if t != T_MUTED)} calls between them. "
              f"The fix works.")
    else:
        print(f"  FAIL: FUN_4000672c WAS called {len(muted_calls)}x for the muted track -- the "
              f"fix is not actually preventing the audible restart.")


if __name__ == "__main__":
    main()
