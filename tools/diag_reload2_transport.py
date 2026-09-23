#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload2_transport -- RELOAD BUSY, with the transport ACTUALLY RUNNING.

WHY THIS EXISTS (Session 83)
----------------------------
Hardware report #6 gave open issue #2 its first crisp discriminator: with the
transport RUNNING, the first TRK SEQ reload works and every later one says
RELOAD BUSY; with the transport STOPPED, reloads work indefinitely.

Every RELOAD2 harness to date is blind to exactly that variable. They all do:

    rt.press_play_live()
    rt.uc.mem_write(erl.TRANSPORT, struct.pack(">I", 1))    # forced flag

i.e. they POKE the transport longword and never actually run the step engine --
`emu_reload.boot_and_load()` attaches with only `tick=True`, omitting the
`ips` / `pit_clock_hz` / `quantum` / `step_quantum` arguments that make the PIT
drive the sequencer. `diag_seq_activity.py` documents the consequence bluntly:
every dynamic run to date reported TRANSPORT=0 and total-fires=0, so no
emulator result about playback-dependent behaviour has ever meant anything.
That is why `diag_reload2_realkey.py 5` reported five byte-identical cycles
while hardware fails on the second reload.

Conversely `diag_seq_activity.py` DOES get a real, measured stepping sequencer
(16/16 tracks advancing) -- but with `0x800065b8` reading 0, so our worker's
`tst.l RUNNING` would take the STOPPED branch there.

Neither configuration exercises the hardware case. This tool is the missing
third one: **real PIT-driven stepping AND `RUNNING` set**, which is the only
state in which `rlj_setflag` arms `RELOAD_NOW` (0x46c8028a, polled once per STEP
at 0x400a2530) while there are real steps to consume it.

HONEST LIMITS -- read before trusting a green result
----------------------------------------------------
* `RUNNING` is still FORCED here, not reached through a real PLAY gesture. What
  is real, and new, is that the step engine is genuinely running underneath it.
  The liveness gate below refuses to report anything if it is not.
* This does not model CF audio streaming contention. If the real mechanism is
  "the storage task is saturated feeding FLEX/STATIC playback", this harness
  will NOT reproduce it, and a green result here is NOT evidence of a fix.
  Treat a green run as "not reproduced here", never as "fixed".

WHAT IT MEASURES, per reload gesture, driven through real `set_key_state`:
  * G_KIND seen by rl_yes_exec AT ENTRY  -- nonzero => the BUSY toast fires
  * rl_job entries                       -- did the posted job actually get run?
  * FUN_40022778 posts                   -- did we post at all?
  * RELOAD_NOW writes                    -- the transport-conditional branch
  * master/per-track STEP movement       -- proof the sequencer kept running

Usage:
  python3 tools/diag_reload2_transport.py [--stopped] [--iters N] [--frames N]
    (default: transport running, 4 iterations -- the hardware repro needs >=3)
"""
import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))

import emu_reload2 as erl2        # noqa: E402
import emu_reload as erl          # noqa: E402

er = erl.er

SET_KEY_STATE = 0x40031734
BANK_CODE, YES_CODE = 0x2F, 0x31
PRESS, RELEASE = 1, 0
STEP_ARR, TICKS_ARR = 0x800064D0, 0x800064F0
MASTER_STEP = 0x800065B6
RUNNING = 0x800065B8
RELOAD_NOW = 0x46C8028A
POST_FN = 0x40022778
FREAD_FN = 0x40016564          # buffered card read -- the streaming-contention proxy
LAYER_HEAD = 0x460D165C


def u32(uc, a):
    return struct.unpack(">I", uc.mem_read(a, 4))[0]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stopped", action="store_true",
                    help="control run: leave RUNNING at 0")
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--frames", type=int, default=1200)
    ap.add_argument("--project", default=None)
    a = ap.parse_args(argv)

    erl.OUR_IMAGE = erl.RELOAD_IMAGE

    # --- attach with the SEQUENCER-LIVE parameters (this is the whole point) ---
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))

    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail)

    proj = a.project or str(erl.DEMO)   # same project every other RELOAD2 harness uses
    card, staged = er.stage_project(proj, "OCTABAM", None)
    r, rt = er.attach(str(erl.RELOAD_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    print(f"boot    : {r.stopped}")
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", staged, run_ms=6000, mount_ms=3000)
    pat = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    rt.seq_select_live(final_bank, pat)
    rt.internal_clock()
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    print(f"load    : mounted={mounted} bank={final_bank} pattern={pat} ({elapsed} ms)")

    # --- instrumentation (hooks BEFORE the flush, per Session 81's own lesson) ---
    counts = {"rl_job": 0, "post": 0, "yes_exec": 0, "fread": 0}
    gkind_at_exec = []
    reloadnow_writes = []

    rl_job = erl2._sym("rl_job")
    rl_yes_exec = erl2._sym("rl_yes_exec")

    rt.uc.hook_add(er.eb.UC_HOOK_CODE,
                   lambda u, ad, sz, x: counts.__setitem__("rl_job", counts["rl_job"] + 1),
                   begin=rl_job, end=rl_job)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE,
                   lambda u, ad, sz, x: counts.__setitem__("post", counts["post"] + 1),
                   begin=POST_FN, end=POST_FN)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE,
                   lambda u, ad, sz, x: counts.__setitem__("fread", counts["fread"] + 1),
                   begin=FREAD_FN, end=FREAD_FN)

    def on_yes_exec(u, ad, sz, x):
        counts["yes_exec"] += 1
        gkind_at_exec.append(u.mem_read(erl.G_KIND_A, 1)[0])

    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_yes_exec, begin=rl_yes_exec, end=rl_yes_exec)

    def on_write(u, access, addr, size, value, x):
        if addr == RELOAD_NOW:
            reloadnow_writes.append(value)

    rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, on_write, begin=RELOAD_NOW, end=RELOAD_NOW + 3)
    rt.uc.mem_write(erl.TOAST_FN, b"\x4e\x75")
    rt.uc.ctl_flush_tb()

    # --- liveness gate: refuse to report anything if the sequencer is frozen ---
    # rt.start_transport_live() is a REAL transport start (diag_seq_activity.py
    # uses it to get 16/16 tracks stepping). Poking 0x800065b8, which is what
    # every other RELOAD2 harness does instead, does not start the step engine.
    def snap():
        return (bytes(rt.uc.mem_read(STEP_ARR, 16)),
                bytes(rt.uc.mem_read(TICKS_ARR, 16)),
                rt.uc.mem_read(MASTER_STEP, 1)[0])

    seen = set()
    s0 = snap()
    if not a.stopped:
        rt.start_transport_live()
        target = rt.frame_count + a.frames
        while rt.frame_count < target:
            rt.run(ms=60)
            seen.add(snap()[0] + snap()[1])
            if len(seen) > 3:
                break
    alive = len(seen) > 1
    playback_freads = counts["fread"]
    running_real = u32(rt.uc, RUNNING)
    print(f"liveness: distinct per-track STEP/TICK snapshots = {len(seen)}  "
          f"master STEP {s0[2]} -> {snap()[2]}  -> sequencer "
          f"{'RUNNING' if alive else 'FROZEN'}")
    print(f"          0x800065b8 (what our worker calls RUNNING) reads "
          f"{running_real:#010x} after a REAL transport start")
    print(f"streaming: buffered card reads (FREAD 0x40016564) during PURE PLAYBACK, "
          f"no reload issued = {playback_freads}")
    if playback_freads == 0:
        print("          ** ZERO. This harness does NOT model CF audio streaming, so it\n"
              "             CANNOT reproduce a storage-task-contention bug. A clean run\n"
              "             below says nothing about the hardware symptom. **")
    if not a.stopped and not alive:
        print("\n  ** ABORT: the step engine is not advancing, so this run cannot say\n"
              "     anything about transport-dependent behaviour. Do not report a result. **")
        return 2

    if a.stopped:
        rt.uc.mem_write(RUNNING, struct.pack(">I", 0))
        print("mode    : CONTROL -- transport never started, RUNNING = 0")
    elif running_real == 0:
        # Worth knowing either way: if a real start leaves this at 0, then our
        # worker's `tst.l RUNNING` takes the STOPPED branch while genuinely
        # playing, and RELOAD_NOW is never armed. Force it so the running branch
        # is at least exercised, but say plainly that it was forced.
        rt.uc.mem_write(RUNNING, struct.pack(">I", 1))
        print("mode    : sequencer live, but a real start left 0x800065b8 at 0 -- "
              "FORCING it to 1 so rlj_setflag's running branch is exercised.\n"
              "          ** That mismatch is itself a finding: see the report below. **")
    else:
        print("mode    : sequencer live AND 0x800065b8 set by the real start "
              "(the configuration no previous harness had)")
    rt.uc.mem_write(erl.CUR_TRACK_G, bytes([3]))
    rt.uc.mem_write(erl.MIDI_MODE_G, b"\x00")

    def key(code, event):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY_STATE, args=(code, event), budget=2_000_000)

    print(f"\n{'it':>3}  {'G_KIND@exec':>11}  {'BUSY?':>5}  {'rl_job':>6}  "
          f"{'posts':>5}  {'G_KIND after':>12}  {'RELOAD_NOW':>10}  freads")
    rows = []
    for i in range(1, a.iters + 1):
        before = dict(counts)
        gk_before = len(gkind_at_exec)
        rn_before = len(reloadnow_writes)

        key(BANK_CODE, PRESS)
        key(YES_CODE, PRESS)      # open the picker (G_SEL defaults to TRK SEQ)
        key(YES_CODE, RELEASE)
        key(YES_CODE, PRESS)      # execute
        key(YES_CODE, RELEASE)
        key(BANK_CODE, RELEASE)
        # let the storage task actually get a turn, with the sequencer running
        for _ in range(120):
            rt.run(ms=60)
            if rt.uc.mem_read(erl.G_KIND_A, 1)[0] == 0 and counts["rl_job"] > before["rl_job"]:
                break

        gk_seen = gkind_at_exec[gk_before] if len(gkind_at_exec) > gk_before else None
        busy = (gk_seen not in (0, None))
        after = rt.uc.mem_read(erl.G_KIND_A, 1)[0]
        rows.append((i, gk_seen, busy, counts["rl_job"] - before["rl_job"],
                     counts["post"] - before["post"], after,
                     reloadnow_writes[rn_before:], counts["fread"] - before["fread"]))
        i_, gk, bz, jb, po, af, rn, fr = rows[-1]
        print(f"{i_:>3}  {str(gk):>11}  {'YES' if bz else 'no':>5}  {jb:>6}  "
              f"{po:>5}  {af:>12}  {str(rn):>10}  {fr}")

    print()
    busy_iters = [r[0] for r in rows if r[2]]
    unserviced = [r[0] for r in rows if r[4] > 0 and r[3] == 0]
    if busy_iters:
        print(f"   REPRODUCED: RELOAD BUSY on iteration(s) {busy_iters} "
              f"(G_KIND was already set when rl_yes_exec ran)")
        if unserviced:
            print(f"   and iteration(s) {unserviced} POSTED a job that rl_job never ran "
                  "-- that is what left G_KIND set")
    else:
        print("   not reproduced here. NOT evidence of a fix -- see HONEST LIMITS "
              "in this file's docstring (no CF streaming contention is modelled).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
