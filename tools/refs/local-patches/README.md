# `tools/refs/local-patches/`

`refs/*` is **gitignored** — the clones under `refs/` are a disposable cache, so any edit
made inside one is outside version control and dies with the next sync, reset, or
re-clone. This directory is the durable home for those edits: it lives in **our** repo, so
a patch committed here survives all of that.

`tools/refs/sync.py` writes into this directory automatically (see `sync_one()`), in two
cases:

| file | what it captures |
|---|---|
| `<name>-local.patch` | **uncommitted** working-tree edits found in `refs/<name>` before it is reset |
| `<name>-local-commits.patch` | **committed** work in `refs/<name>` that is not reachable from the sync target |

Nothing here is re-applied automatically. `sync.py` prints the exact `git -C refs/<name>
apply …` command; re-applying is a deliberate act.

**Commit the patches you care about.** A patch sitting here untracked is no safer than the
clone it came from — `git clean -fdx` removes both.

## ⚠️ `octabam-emu-samplebank-map.patch` is REQUIRED, not optional

Without it the emulator **cannot boot this repo's firmware images at all**: the post-PR#360
(more-correct EMAC) boot branch reaches a stock ~10.8 MB zero-fill at `0x4f502c10`, which
no other mapping covers, and Unicorn aborts with `UC_ERR_WRITE_UNMAPPED` partway through
`gate_m6a()`. Project mount then DMAs card sectors into the same bank at `0x4ece3000`.
A/B tested upstream:

```
refs/octabam tools/emu/emu_rtos.py @ 111fd76 (the MANIFEST.lock pin)  -> BOOT FAILED
                                   + this patch                       -> BOOT OK
```

Verified 2026-09-25: it **applies cleanly to the pinned commit `111fd76`**, so
re-application is mechanical.

It currently also exists as commit `d5b84fb` on the local branch `emu/map-audio-sdram`
inside `refs/octabam`. **Do not rely on that branch.** `sync.py`'s `checkout --detach`
moves off it; before Session 92 that happened silently, because the old dirty-check saw
only uncommitted edits and a committed fix left a clean tree. The branch ref survives, so
nothing looks lost — the clone just quietly stops carrying the fix. That gap is now closed
(`sync.py` exports unreachable commits as `-local-commits.patch` and prints the re-apply
command), but the patch committed here is the thing that actually guarantees recovery.

`MANIFEST.lock` deliberately still pins `111fd76` rather than `d5b84fb`: `d5b84fb` exists
only in this local clone and is not on `origin`, so pinning it would break any fresh clone.
The pin stays upstream-resolvable and this patch goes on top.

One staleness note: the patch's own inline comment says "`tools/emu_reload.py` grows pages
the same way". That is no longer true — Session 92 retired our duplicate pager, because
octabam's own hook is registered first and takes every fault, making ours dead code (and
it had a real defect: it swallowed an overlapping-`mem_map` error and returned "handled"
anyway). The comment is left alone so the patch keeps applying byte-for-byte.

## The three emulator-speed patches (Session 101, 2026-09-25)

Added after measuring where route A's 121-143x slowdown actually goes. The
microbenchmark behind the numbers below is `Unicorn 2.1.4 m68k TCG on arm64`:
**154-252 MIPS with no hooks** — i.e. the CPU core is *faster* than the OT's own
ColdFire, and every bit of the slowdown is harness tax, not emulation cost.

| patch | what it changes | measured |
|---|---|---|
| `octabam-emu-writehook.patch` | `boot()` installs an **unbounded** `UC_HOOK_MEM_WRITE` whose Python lambda fires on every store in the address space, and never removes it — so it rides through every RTOS run. Its only two readers are boot's own stall loop and `_run_until`. Now: boot keeps it and `hook_del`s it on the way out; `_run_until` installs its own, lazily, at the first mid-way burst. | the hook alone: **154 → 21 MIPS (7.3x)** on store-dense code. End to end on `emu_pattern_led.py`: **217.9 s → 183.8 s**, output byte-identical |
| `octabam-emu-exact-clock-native.patch` | `exact_clock()` counted retired instructions with a **global per-instruction Python `UC_HOOK_CODE`** — recomputing a number Unicorn already keeps in C (`uc->emu_counter`, maintained by its own internal count hook on every burst started with `count > 0`, which is every burst `step()` starts). Adds `tools/patches/unicorn_emu_counter.patch` (one appended `uc_ctl` enum value + one read case) and reads it instead. Also adds `instrs_quantum` / `bursts_short` so the clock's mis-billing is reported rather than assumed. | **correct, but NO measurable speedup — see below.** The hook alone benchmarks at 92 → 3.2 MIPS (28x) on straight-line code; end to end on `--sequencer --frames 40` it bought nothing (178.6 s before, 188.4 s after, within host-load noise) |
| `octabam-ot-emu-steps.patch` | adds `--steps FILE` to the C++ port (`tools/emu/ot_emu`): a line-oriented step list run after the load at main's spin, so a diagnostic that is dozens of interleaved `call_as_main` + poke + read steps becomes ONE native run. Verbs: `ptr`/`set`/`spin`/`call`/`poke`/`copy`/`peek`/`echo`, plus the transport — `frame on\|off`, `iclock`, `seq BANK,PAT`, `transport`, `triglog`, `trigs`, `coverage`, `frames N [ADDR,LEN=HEX]` (run N frames, or stop early once memory matches: a bind phase with a ceiling). The caller parses `step ` records and owns the assertions. | `emu_pattern_led.py` → `tools/port_pattern_led.py`: **183.8 s → 16.7 s (11x)**, identical `blob` and all six assertions, stock and patched. `diff_flex_static.py` → `tools/port_diff_flex_static.py`: **75 s** for three full transport runs, against route A's ~8–12 min estimate for a run it never completed |

### Why `exact_clock` native made no difference, and what that means

Three runs of one scenario (`--sequencer --internal-clock --frames 40`), same project:

| run | libunicorn | counter | wall | mis-billing | short bursts |
|---|---|---|---|---|---|
| baseline | old | Python hook | 178.6 s | 1.366x | 56,843 of 270,588 |
| `OCTA_EXACT_VERIFY=1` | new | both | 194.7 s | 1.000x | **0** of 211,179 |
| production | new | `uc_ctl` read | 188.4 s | 1.365x | 56,842 of 270,619 |

**The counter swap is proven correct**, and by better evidence than the verify
mode gives: baseline and production agree to four significant figures on every
metric — 610,430,552 vs 610,484,760 instructions executed (0.01%), 1.366x vs
1.365x, 56,843 vs 56,842 short bursts — across *two different libraries and two
different counting mechanisms*. Two independent paths, one accounting.

**☠ `OCTA_EXACT_VERIFY=1` perturbs what it measures.** Installing the global
Python hook changes the burst structure itself: 211,179 bursts instead of
270,619, and not one of them stops short. So verify mode proves the two counters
agree *in verify mode*, which is not production's configuration. Use the
cross-run agreement above as the real check; treat a verify-mode `RtosFault` as
a red flag but its burst statistics as an artefact of the measurement.

**And the mis-billing is real: 1.365x, reproducibly.** `exact_clock()` earns its
keep — an earlier idea to gate it on `self.frame` was wrong twice over (all 63
transport diags set `rt.frame = True` by attribute, and the correction is needed
regardless).

**Why no speedup, and the lesson for route A.** Unicorn's fast path is lost as
soon as *any* code hook covers the code being executed, and route A installs
**435** of them at the EMAC macload sites no matter what. Removing one more
global hook cannot restore a fast path that 435 site hooks have already given
up. The same effect caps the write-hook patch at 16% end to end against a 7.3x
microbenchmark. **Route A's cost is structural** — hook-instrumented emulation
driving a Python-side machine model — so it will not be micro-optimised into
speed. The instrument to reach for is the C++ port (`--steps`, 11x measured),
not a faster route A.

### ☠ Two hazards found the hard way while building these (2026-09-25)

**1. `build_unicorn.sh` installed the new library with a plain `cp`, over the
live file.** That keeps the inode and rewrites its pages in place; macOS then
fails page validation against the ad-hoc signature it cached for that path and
SIGKILLs (`Killed: 9`) every process that loads it -- the script's own EMAC
self-test included. It looks exactly like a broken build: three rebuilds here
were blamed on the `emu_counter` patch before the identical bytes at a *fresh
path* loaded fine. `octabam-emu-exact-clock-native.patch` adds an `rm -f` before
the `cp`. `rm` is the safe order, not the risky one: the inode lives until the
last mapping drops, so a process already running keeps the copy it mapped.
This is also, almost certainly, what this file's own pre-existing note about
"an x86_64 build that crashed on its first emu_start" was really describing.

**2. `refs/octabam` and its one `libunicorn.2.dylib` are shared by every Claude
session open on this repo.** A second session was mid-`diag_reload3_*` run
against that clone while these rebuilds happened, and short-lived Python
processes in other chats were killed by hazard 1. **Before rebuilding the
library, check for other live runs** -- `pgrep -f 'tools/(diag_|emu_|port_)'` --
and prefer `LIBUNICORN_PATH=<a private dir>` to test a new build without
touching the shared one at all.

⚠️ **`unicorn_emu_counter.patch` needs a Unicorn rebuild to take effect**, and
`build_unicorn.sh` only applies it if the exact-clock patch above is in place:

```
( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )
```

`exact_clock()` falls back to the old Python hook on a libunicorn without the
ctl, so a missed rebuild is slow, never wrong. To re-establish the equality
after a Unicorn bump, run any transport diag with `OCTA_EXACT_VERIFY=1`: that
keeps both counters and raises `RtosFault` on the first burst where they differ.

The `--steps` verb list lives in a comment at the executor in `main.cpp`. After
re-applying that patch, rebuild the port: `cmake --build refs/octabam/out/emu`.
