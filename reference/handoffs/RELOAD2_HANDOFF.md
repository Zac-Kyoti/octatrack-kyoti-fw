# RELOAD2 handoff — continue from Session 82

Paste this whole file as your opening prompt in the new session.

---

We are continuing RELOAD2 work on the Octatrack Kyoti firmware project
(`~/Documents/octatrack-kyoti-fw/`, branch `wip`). Read `START_HERE.md` first
(its RELOAD2 row has the full session-by-session history), then
`NOTES.md` "Session 82 — RELOAD2: hardware report #5" (grep
`^## Session 82 .* RELOAD2` — **note the collision: the DIRECT JUMP thread also
has a "Session 82" entry, and it sits EARLIER in the file**, so a bare
`^## Session 82` grep returns both and the first hit is not this one). For the
full thread: `^## Session 80 continued`, `^## Session 81`, and that RELOAD2
Session 82 entry.

## What RELOAD2 is

A feature that reloads sequence data from the CF card without stopping the
transport — `TRK SEQ` (one track), `PTN SEQ` (one pattern), `PART + PTN SEQ`
(pattern + its linked Part). **Stock's own RELOAD BANK (PROJECT menu) already
does exactly the `PART + PTN SEQ` operation** — the user's own framing, and
worth holding onto: we are not inventing a new operation, we're making an
existing stock operation finer-grained and seamless (in time with the master
clock, transport never stopped). Gesture: hold `[BANK]`, tap `[YES]` opens a
sticky picker (arrows = UP/DOWN only, `[YES]` executes, `[NO]` cancels).

Source: `tools/patch_reload2.s` + `tools/build_reload2.py` →
`out/OCTATRACK_RELOAD2.bin` / `.syx`. Currently **9 detours, ~1523 B vs
stock, NOT FLASHED**.

## Current state (as of commit `11e6fb3`)

Session 80 continued (8) gave the picker its own keymap layer (pushed on open,
popped on close) instead of borrowing slots in the `[PTN]`/`[BANK]` overlay
layers — this was the root architectural fix behind most of the routing bugs
below. Session 80 continued (9) then found and fixed two more bugs discovered
via real-key-dispatch testing, and got a definitive hardware answer on a third
issue (it's not ours). Full regression suite is green:
`emu_reload2.py --combo` (27+/27), `emu_reload2_keymap.py`,
`diag_bank_window.py` (incl. `--stress`), `emu_reload2.py --trk`, and 5
consecutive full gestures through real `set_key_state` dispatch
(`diag_reload2_realkey.py 5`) all byte-identical.

Session 81 then found that **the build had been refusing to produce a flashable
image since commit `83ce678`** — a relocation-blind `MANUAL-TRIG FIX DIVERGED`
check `sys.exit()`ing *after* `mainos_reload2.bin` was written but *before* the
`.syx`/CF-card wrap. Every emulator tool loads the pre-abort file, so (8)'s and
(9)'s green regressions were real, but the only actually-flashable files on disk
were three sessions stale. The check is now relocation-aware and all four
artifacts regenerate together. Details: `NOTES.md` "Session 81".

Session 82 flashed that image. **Hardware confirmed (8) and (9): walk-away and
`[BANK]`+`[YES]` reliability both pass, and `RELOAD BUSY` was never seen once**
— strong (not conclusive) evidence that open issue #2 was the
`[YES]`-alone-fires-a-reload family fixed in "(6)"/"(9)". One regression came
back and is now fixed: the arrows worked **exactly once**, then arrows + `[YES]`
+ `[NO]` all died together, because `rl_draw`'s own POPUP2 call tears down the
currently-showing popup by calling `CLOSE_CB` **directly** — and since (9) that
is *our* walk-away hook, so our own redraw unprimed our own picker. Fixed with an
`rl_redraw` re-entrancy flag; new test `diag_reload2_realkey.py --arrows`
reproduced it first and passes now. Details: `NOTES.md` "Session 82".

**The current build (1543 B, 9 detours) has NOT been flashed.** That's the
immediate next step: build (`python3 tools/build_reload2.py` — it should print
`manual-trig fix vs build_trigscale_only.py: identical (cave relocated
0x400d7b00 -> 0x400d7bfc)` and then a `=== wrap ===` section), confirm the
regression suite is green, then ask the user to flash and report back —
particularly on **the arrows**, since that is what this build fixes.

## Open issues, ranked by leverage

1. **The ~1 s stall / stock transport stop.** Root cause is solid and has been
   for several sessions: our worker's job still triggers stock's *full*
   whole-bank RELOAD BANK machinery as a side effect (the doneFn at
   `0x40023bf4` calls through to `0x40023b68`, which re-parses all 16 patterns
   and refreshes the live cache). A naive fix (skip that one call) was tried in
   Session 80 continued (4)/(5): it passed every emulator test on a SINGLE
   reload, then broke `[BANK]`/`[YES]` badly on hardware after "a few" reloads
   — state accumulates across repeated use in a way no single-reload test can
   see. **That fix is reverted and stays reverted.** `tools/diag_reload2_repeat.py`
   exists specifically as the gate for any retry: it drives 5+ consecutive
   `rl_arm_trk` calls and asserts `G_KIND`, `POPUP`, layer depth, and the
   BANK/YES dispatch slots all return to baseline every time. **Do not attempt
   this fix again without that gate passing first**, and ideally also driving
   the retry through real `set_key_state` dispatch (`diag_reload2_realkey.py`),
   not just direct `rl_arm_trk` calls — session (9) showed real-dispatch testing
   catches bugs the direct-call harness structurally cannot see (both of its
   own bugs this session were only visible through real dispatch).

   Session 80 continued (9) also confirmed the Undo/Clear glitch below is in
   the SAME root-cause family as this stall — both are consequences of
   triggering stock's full whole-bank reload for an operation that shouldn't
   need it. Fixing this stall convincingly may fix both at once.

2. **`RELOAD BUSY` toast appears "most of the time".** Root cause still not
   found despite several sessions of attempts. Ruled out and should not be
   re-investigated without new evidence: storage-task-busy-while-CF-streams
   (user explicitly retracted the supporting STATIC-vs-FLEX observation — they
   reload identically), and a single clean reload leaving `G_KIND` stuck (never
   reproduced in any harness across many runs; `G_KIND` always settles to 0).
   The `[YES]`-alone-fires-a-reload family of bugs (fixed in Session 80
   continued (6) and (9)) were plausible contributors to BUSY but never proven
   to be THE cause — ask the user whether BUSY is less frequent on the (9)
   build before investigating further; that's a free data point.

3. **The list UI.** Current picker is a single-line popup, not a real
   multi-item list. User pointed at stock's `[FUNC]+[UP]` list menu as a UI/UX
   reference (not a code reference — that gesture is taken by something else).
   Stock's 12-entry list-table renderer lives near `0x400beb72`; never located
   precisely. Lowest priority, purely cosmetic.

   **USER REQUIREMENT (stated Session 82): the three-option picker window must
   use the system font `F4`.** Recorded verbatim — which font resource/table
   `F4` names in this firmware has NOT been located yet, and no assumption
   should be made about it. Locating `F4` (and how POPUP2 / the list renderer
   select a font at all) is the first RE step whenever this item is picked up;
   do not guess a font pointer.

## Hard-won lessons from this thread (read before touching the code)

These cost real sessions and in a few cases real hardware-flash cycles. Do not
re-derive or re-learn these:

- **The runtime keymap dispatch table (`0x46c7d8de`, 24 B stride) must never be
  written to directly.** Tried once (Session 80 continued (6)) to fix a stale
  slot by writing the table entry back by hand — it desynced the firmware's own
  push/pop bookkeeping so badly that the NEXT `[BANK]` press stopped applying
  its own overlay at all and the layer stack began unwinding on its own. The
  correct pattern is always: push/pop real layer structs through the firmware's
  own `FUN_40031494`/`0x4003146c`, and if a stale dispatch-table value needs to
  be handled, delegate through it (jmp to a saved prior handler) rather than
  overwrite it.

- **Single-reload-clean is not evidence of anything here.** Every "looked fine
  in the emulator, broke on repeated hardware use" failure this thread has had
  came from a test that only drove one reload or one gesture cycle. Any new
  test must drive at least 5 consecutive cycles before its result is trusted.

- **Testing a handler directly (`rl_arm_trk`, `rl_bank_yes`, etc.) is not the
  same as testing through real dispatch.** `set_key_state` (`0x40031734`) is
  the actual per-key dispatcher — it does the runtime-table lookup and manages
  per-key "currently held" bookkeeping that direct-call tests skip entirely.
  Two real bugs this session (the walk-away picker-stays-primed bug, and the
  `rl_bank_press` snapshot corruption) were invisible to every direct-call test
  and only showed up once `diag_reload2_realkey.py` started driving
  `set_key_state` itself. When testing a KEY gesture, always model full
  press/release pairs — a press with no matching release is not a gesture any
  physical button can produce, and firmware bookkeeping that depends on the
  release will misbehave in ways that look like a real bug but are a test
  artifact (this cost one full false-alarm report to the user this session).

- **`objdump -D -b binary -m m68k:cfv4e --adjust-vma=<addr>` is the right tool
  for reading unfamiliar firmware code — use it from the start.** Several
  address/mapping errors this session (an inverted arrow-key pairing reported
  to the user twice, a mislocated function entry point that was actually
  mid-instruction) came from hand-decoding raw hex bytes instead of using
  objdump. When identifying a new function or checking a call's exact
  arguments, disassemble it properly first.

- **Do not infer facts the user didn't state.** The arrow-pairing bug happened
  twice in a row because a hardware report stating only "DOWN doesn't work" was
  read as implying "UP works," and that unstated inference anchored a wrong
  conclusion. When a report names one specific symptom, fix exactly that and
  verify the rest — don't assume the unstated parts.

- **Cave space is the binding constraint now — check it BEFORE designing.**
  Measured free zone: stock is zero `0x400d7400..0x400d7c3b` and `0xff` from
  `0x400d7c3c` (= `FREE_END`). `patch_trigscale` (62 B) now sits at the very top,
  `0x400d7bfc`, and **cannot move again**, so `patch_reload2`'s hard ceiling is
  **2044 B — and it is at 2036. Eight bytes left.** The cave address is also an
  ALIGNMENT constraint, not just an offset: `0x400d7bfe` was tried first and the
  source's own `.align` padded the blob 62 -> 64 B and tripped the free-zone
  assert. Keep it 4-byte aligned. **The list UI cannot fit** — it needs a second
  cave or another free region surveyed first.

- **A green suite does not mean a current flashable image.** `build_reload2.py`
  writes `out/mainos_reload2.bin` (what every emulator tool loads) *before* its
  validation checks, and wraps the `.syx`/CF-card images *after* them. A check
  that fails therefore leaves the tests passing on fresh bytes while the only
  files a human can flash stay stale — silently, for three sessions, in Session
  81's case. When a handoff says "build, test, flash", check the **mtime of the
  artifact you would actually flash** against the commits it should contain.
  The test results cannot tell you this, by construction.

- **The MAIN_OS section base is `0x40000400`, not `0x40000000`.** Indexing
  `out/raw/section_3_MAIN_OS.bin` with the wrong base shifts every address by
  `0x400` and makes two builds patching the same site look like they patch
  different ones.

- **Unicorn test-harness gotchas, both cost real time this session:**
  `ctl_flush_tb()` must be called AFTER `hook_add`, not before — cached
  translation blocks are not retroactively re-instrumented for a new hook, and
  this silently produces false "nothing happened" negatives. And draining a
  reload until `G_KIND == 0` is NOT the same as draining until it's actually
  finished — `G_KIND` clears at `rl_job`'s entry, long before stock's slower
  downstream work (deserializing, live-cache refresh) completes; drain on a
  more specific completion signal (e.g. a parse-count reaching its full
  expected value) instead.

## Available diagnostic tools (all in `tools/`)

- `emu_reload2.py --combo` / `--trk` — fast, direct-call regression suite.
- `emu_reload2_keymap.py` — layer push/rebuild correctness on the real stock
  layer mechanism (still direct-call for the driving side).
- `diag_bank_window.py` [`--stress`] — the `[BANK]` popup/layer lifecycle,
  measured against real stock behavior.
- `diag_reload2_realkey.py [N | --no-cancel | --trig | --walk-away | --arrows]` — drives
  the REAL `set_key_state` dispatcher, the only harness that has ever caught
  the routing-class bugs in this thread. Use this first for anything involving
  key gestures. `--arrows` (Session 82) opens the picker and drives four arrow
  taps plus a final `[YES]`, checking `G_MENU`, `G_SEL`, layer linkage and the
  live YES dispatch slot after every key — `--combo` cannot see arrow bugs of
  this class at all, because it calls the arrow handlers directly with no layer
  ever pushed, which leaves the `CLOSE_CB` hook inert.
- `diag_reload2_repeat.py [N]` — the multi-reload gate for the worker/job path
  (direct `rl_arm_trk` calls, N consecutive, checks for state drift).
- `diag_reload2_deser.py` — traces the storage-task job path past the point
  older tests used to halt at; this is what originally found the whole-bank
  reload side effect.
- `diag_reload2_undo.py` — the Clear/Undo investigation tool; the query-based
  check inside it has unverified args (see its own docstring) and should not be
  trusted on its own, but its memory-write-watch mode is solid once given
  enough drain time.

All of these are full-RTOS-emulator tools (boot + real card load), each taking
several minutes of wall-clock time. Always run them in the background and wait
for the notification rather than polling.
