```
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
▐░░  O T   K Y O T I   F W   ·   custom Octatrack firmware  ░░▌
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
```

# OT Kyoti FW

**A custom firmware for the Elektron Octatrack (OS 1.40C) — a hardware-confirmed
MIDI bug fix and a set of feature modifications / enhancements, built from a
reverse-engineering study of the stock OS.**

Everything here is **educational**. You bring your own copy of the official OS;
the tools analyze it and, if you ask, produce a modified image byte-for-byte
reproducibly from *your* copy. No `.bin` / `.syx` is ever distributed — only the
tools to roll your own.

This project began as a fork of
[`mxldyn/octamax`](https://github.com/mxldyn/octamax) by Maxolydian and is built
on its method and infrastructure — the container / update-chain analysis, the
guarded binary-patch build pipeline, the code-cave detour technique, and the
flashing procedure. Full lineage and acknowledgements:
[`CREDITS.md`](CREDITS.md).

---

## ⚠️ Warning — read before doing anything

**This is for personal study.** Updating an Elektron unit with anything other
than official firmware is risky: it puts the warranty in question and can leave
the unit needing the bootloader recovery path. Static analysis of the public OS
is harmless; *writing* a non-official OS to real hardware is not. Nothing here is
endorsed by, supported by, or affiliated with Elektron. If you flash a modified
OS you do so entirely at your own risk. If in doubt, don't flash — just read,
disassemble, and learn.

Elektron ships **one OS 1.40C image for the Octatrack MKI and MKII**; the boot
`0x46c8d18c` probe adapts the unit-specific details. All hardware testing in this
project is on an Octatrack **MKI** the author owns — including the flash that
confirmed the Bug-1 fix.

---

## What this firmware does

> **Branches.** The published **`main`** carries the finished work: the Bug-1
> manual-trig fix, the Bug-2 pattern-LED fix, **MUTE MODE** (all four modes),
> **QUANTIZE LIVE REC**, the **SIDE-CHAIN COMPRESSOR**, and **trigless-lock
> auto-remove** — every one of them flashed and confirmed on MKI hardware.
> **`wip`** is the frontier: it carries all of the above plus the work that is
> still in progress — **DIRECT JUMP**, **RELOAD FROM PROJECT**, and the
> **part-change carryover** fix, each with real open bugs. Per-feature status is
> in the tables below.

### Bug 1 — Plays-Free MIDI manual-trig stall  ·  **fixed, hardware-confirmed (MKI)**

A Plays-Free MIDI track with trig quantize *Direct* and pattern scale *Per Track*
stalled after its first step on a manual trig: `FUN_4009b5c8` seeded the
per-track scale index with the **audio**-track stride for MIDI tracks. Fixed with
a 6-byte detour into a code cave (`tools/patch_trigscale.s`). Flashed to a real
Octatrack MKI (2026-08-28) — the stall is gone, no regression. Write-up:
[`NOTES.md`](NOTES.md) "Session 5–7"; emulator `tools/emu_trigbug.py`.

### Bug 2 — a pattern with only parameter locks reads as empty  ·  **fixed, hardware-confirmed (MKI)**

A pattern whose only content is p-locks — parameter locks on a **MIDI track**, or
**trigless locks** on an audio track, with no trig anywhere — showed as an unused
slot: its grid LED stayed unlit under `[PTN]`. The stock "does this pattern have
content" predicate (`FUN_4009a464`, which drives the pattern-grid LEDs and the
"does this bank have content" check) scans each track's trig masks but never its
p-lock array. Fixed with a 6-byte detour into a code cave that, when no trig is
found on any track, scans the 16 p-lock arrays (8 audio + 8 MIDI) for a locked
value: `tools/patch_pattern_led.s`, `python3 tools/build_pattern_led.py` →
`OCTATRACK_OS1.40C_PATTERNLED.{syx,bin}` (version stays `1.40C`, base = stock
only). Validated in the full-firmware emulator (`tools/emu_pattern_led.py`): stock
reproduces the bug, patched lights the LED, a genuinely empty pattern still reads
empty. Write-up: [`NOTES.md`](NOTES.md) "Session 48". **Flashed to the MKI
(2026-09-13) — confirmed working, no regression.**

### MUTE MODE — a PERSONALIZE toggle for audio-track mute behaviour  ·  **final, hardware-confirmed (MKI)**

Off by default (`MUTE MODE = OT`), so a freshly flashed unit is stock until you opt in.
The choice lives in the checksummed `'ANDY'` battery-SRAM block, so it survives a power
cycle.

| mode | effect |
|---|---|
| **OT** | stock behaviour, byte-for-byte |
| **OTFX** | hard dry cut, FX inserts ring their tails, and **the sequencer is left alone** — trigs keep firing and voices keep restarting underneath, so unmuting picks up exactly where the pattern would have been |
| **OTFX-T** | the same dry cut and ringing FX tails, but a *trig*-mute: new trigs stay suppressed until you unmute |
| **DT-T** | pure sequencer mute, Digitakt-style — a sounding voice rides out its own amp envelope and its FX ring, and only *new* trigs are suppressed |

Menu order is OT / OTFX / OTFX-T / DT-T, increasing "stickiness". That is deliberately not
the internal GATE order: the modes are tested as a chain, so a mode's position in it is its
per-frame instruction count, and reordering would silently cost `OTFX-T` its bit-identity
with stock. **One** persisted word holds the mode and the menu index is derived from it, so
the menu and the running firmware cannot disagree — an earlier two-word design did exactly
that on a unit upgrading from an older build.

Sources: `tools/patch_mutemode.s`, `tools/patch_softmute.s`; the four-mode image is
`python3 tools/build_mutemode_dt.py` (both stubs assembled `--defsym DT_MODE=1`) —
plain `build_mutemode.py` is the older two-value `OT` / `OT+FX` build; emulators `tools/emu_mutemode.py`, `tools/emu_mute.py`,
`tools/emu_solo.py`, `tools/emu_dt.py`; write-ups [`NOTES.md`](NOTES.md) "Session 9–12"
and "Session 57–58" (many parts).

**SOLO follows MUTE MODE too.** A track silenced because another track is soloed takes the
same treatment as a manual mute; stock's own hard-cut path was found to run unopposed here
and is now closed off.

**`CUE MUTES TRK` intentionally stays a hard cut** in every mode. That PERSONALIZE option
ORs the cue bits into the mute positions after this project's hook runs, and is left
untouched by design — a decision, not a gap.


### DIRECT JUMP — an Elektron-style immediate pattern change  ·  *active WIP, partly hardware-confirmed*

Toggled by **`[PTN]` + `[YES]`** (a transient "DIRECT JUMP ON/OFF" overlay), no
PERSONALIZE entry. When on, manually cueing a new pattern:

- switches on the **next step tick** instead of quantising to the end of the
  current pattern,
- keeps the **playhead step position** (the new pattern resumes where the old
  one was, modulo its length) rather than restarting at step 1 — **still open,
  see below**,
- loads the new **Part immediately**,
- sends the MIDI Program Change ~1 step early.

The arranger and pattern chains are untouched. Current build:
`python3 tools/build_directjump_v4.py` → `140C_KYOTI` (`tools/patch_directjump.s`
+ a `[PTN]`-held keymap fix). The toggle's **reachability and switch timing are
hardware-confirmed**: earlier `v1`–`v3` builds were dead on hardware — the stock
`[PTN]`-held overlay swallowed `[YES]`'s dispatch the whole time it was held, so
the detour never ran at all — until `v4` fixed it by writing the toggle straight
into that overlay's own `[YES]` slot. A crash found along the way
(`EXCEPTION VEC:04`) was also root-caused and fixed. **Still open:** with DIRECT
JUMP on, a manual pattern change currently restarts the new pattern at step 1
instead of keeping the playhead position; the root cause was mechanically proven
2026-09-20 (a spurious extra write into the sequencer's table-arm state on
commit), but the fix is not yet built or flashed. Write-up:
[`NOTES.md`](NOTES.md) "Session 15" + "Session 21" + "Session 35" → "Session 60"
through "Session 79" (many parts); emulator `tools/emu_directjump.py` /
`tools/emu_directjump_v4.py` / `tools/emu_directjump_dynamic.py`.

### SIDE-CHAIN COMPRESSOR — external key input for the stock DynamiX compressor  ·  **hardware-confirmed, shipping**

Adds `KEY` / `KEY FLT` / `KEY GAIN` / `SC LISTEN` to the COMPRESSOR effect's
page 2: pick any of the eight audio tracks to *drive* the compression on the
track the compressor sits on (classic kick-ducks-the-pad), and it keeps keying
even when the key track is muted. `KEY` reaches **any of the 8 tracks**, flat
(`T1`..`T8`) — not just the four tracks that share the compressor's own DSP
core, since the cross-core extension (below) shipped 2026-09-20.

This is a DSP56300 job, not ColdFire. Built in stages:

| build | contents | state |
|---|---|---|
| `build_sidechain.py` | the `KEY` menu parameter only; the DSP is untouched, so it does nothing audible | menu + dynamic `T1..T8` formatter **emulator-verified** |
| `build_sidechain2.py` | + the DSP hooks: every track publishes its pre-FX block to a shared ring, and the compressor's detector reads the chosen track's ring. **SPATIALIZER is donated** for the code space and removed from the FX menu. | hooks **emulator-verified** under dsp56kEmu |
| `build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | + `KEY GAIN` (declick-smoothed) + `KEY FLT` (one-pole LP/HP/OFF, declicked) + `SC LISTEN`/`MON`, all over a donated SPRING REVERB; **plus cross-core `KEY`** — a per-core generation counter and a shared-window (`Y:0x30000-0x3FFFF`) publish/foreign-read mechanism (adapted from octabam's own XBUS cross-core bus design) let the compressor key off any of the 8 tracks, not just its own core's 4 | **HARDWARE CONFIRMED on MKI, 2026-09-20** — single-core and cross-core both. Emulator-verified first: `emu_sc_dsp3.py` (same-core), `emu_sc_dsp3_xcore.py` (generation counter + cross-core addressing), and a genuine dual-core run under `tools/dsp56300_xcore`'s `dsp_host_xcore` (lock-step + timing-skew fuzz) |

A very mild HP↔OFF filter pop remains (three declick designs tried and
reverted — see `NOTES.md` Session 76's trail); low-ATK/REL "graininess" on a
busy key is filed as research-only, no fix attempted. Neither blocks
shipping. Write-up: [`NOTES.md`](NOTES.md) "Session 17" (+ continued 1–8) →
"Session 77" (×3, the cross-core work); DSP source `tools/patch_sc_dsp.asm` /
`patch_sc_dsp3.asm`; emulators `tools/emu_sidechain.py`, `tools/emu_sc_dsp.py`,
`tools/emu_sc_dsp3.py`, `tools/emu_sc_dsp3_xcore.py`.

### RELOAD FROM PROJECT — reload a pattern from the CF card without stopping playback  ·  *active WIP, partly hardware-confirmed*

Stock 1.40C can only reload from the card at whole-**bank** granularity, and doing
so **stops the transport**. (An earlier version of these notes said it "glitches
the audio" — that is wrong, and was corrected on hardware: stock simply stops the
sequencer.) Stock's RELOAD BANK is in fact exactly the `PART + PTN SEQ` operation
this feature offers; what is being added is finer granularity plus doing it *in
time with the master clock, without stopping the transport*. Adapted from the
Digitone's RELOAD FROM PROJ.

**Hold `[BANK]` and tap `[YES]`** opens a picker window (the gesture moved off
`[PTN]`, which was triple-booked; `[PTN]` is byte-for-byte stock in this build) —
a quick `[BANK]` tap is
unchanged. The **arrow keys** move the highlight; **`[YES]`** executes it and
closes the window; **`[NO]`** closes it and runs nothing. Like every stock menu
it has **no timeout** — it stays until you answer it. While it is open
`[YES]`/`[NO]` act only on the picker. All items reload from the card's last
**SAVE BANK** snapshot:

Current build (`tools/patch_reload2.s`, `python3 tools/build_reload2.py` →
`OCTATRACK_OS1.40C_RELOAD2.{syx,bin}`) — the window opens with **TRK SEQ**
highlighted, so `[PTN]`-hold then `[YES]` is a complete gesture:

| item | what it does |
|---|---|
| **TRK SEQ** | the sequence data of the **one currently-addressed track** — audio track if you are on the audio pages, MIDI track if on the MIDI pages. Everything for that track (regular + recorder trigs, trigless trigs, trigless locks and their locked values, swing/slide, micro-timing, trig conditions, its step count). The other 7 tracks, the pattern length/scale, and the pattern→Part link are all left alone. |
| **PTN SEQ** | the whole active pattern's sequence data — all 8 audio + all 8 MIDI tracks + length + scale. The pattern's Part **assignment is preserved** (a sequence reload never re-points the pattern at a different Part). |
| **PART + PTN SEQ** | faithful restore: PTN SEQ *including* the Part link, then that saved Part is made current on the engine. The pattern comes back exactly as the card has it. |

An earlier 3-item build (**PTN SEQ** / **ALL PARTS** / **PARTS + PTN SEQ**, no
per-track option) predates the hardening below and isn't maintained going
forward — historical only, see `NOTES.md`.

An async job on the storage task parses the target pattern from `bankNN.strd`
with the firmware's own per-pattern chunk parser, copies it into the live blob, and
fires the sequencer's own no-stop reload flag. No other pattern, no other bank, no
disk write. Guards are the stock ones: a never-saved bank shows *"THIS BANK HAS
NEVER BEEN SAVED! NOTHING TO RELOAD!"*. No confirmation prompt.

Six hooks (the `[PTN]` key handler for the hold, the `[NO]` and `[YES]` handlers,
two arrow key handlers, and the storage task's bank-reload case). **First hardware
flash (2026-09-20) found 3 real bugs**: the `[YES]`/`[NO]` handlers could be
unreachable while still physically holding `[PTN]` (the same overlay issue DIRECT
JUMP hit — fixed and dynamically verified against the real keymap code); a
`RUNNING`-transport gate that turned out not to be load-bearing (dropped, so the
picker now works whether the transport is running or stopped); and a case where,
after one successful reload, holding `[PTN]` again stopped opening the picker at
all with no recovery (fixed by removing the flawed gate rather than chasing its
exact root cause). **These fixes are built and emulator-verified but not yet
reflashed.** A real fix for the reload's own timing (an audible gap and a reset to
step 1 rather than the playhead position — comparable in scope to DIRECT JUMP's own
playhead work) and a proper multi-item list-style picker UI are both deferred.
Write-up: [`NOTES.md`](NOTES.md) "Session 42"–"44" + "Session 47" + "Session 80"
(+ continued); emulator `tools/emu_reload.py` / `emu_reload2.py` — `--combo` (the
whole picker, single-stepped), `--patched` (the whole-pattern SEQ worker end to
end), and `--trk` (per-track slice: only the addressed track reverts) pass. Still
hardware-only: the parse against a real CF card, `FUN_40009094` from the storage
task while playing, and the reload's seamless-timing feel.

A **power move** — hold `[PTN]` + tap a `[TRACK]` key for immediate per-track
reload, no picker — is scoped but not built (the chord is free; it needs a
track-key-handler hook).

### QUANTIZE LIVE REC — a front-panel toggle for the live-record quantize  ·  *hardware-confirmed; two cosmetic issues parked*

The all-or-nothing **QUANTIZE LIVE REC** (the PERSONALIZE row — *not* the
per-track 50 % TRIG QUANT in the TRACK TRIG MENU) has no shortcut. This adds one,
Digitone-style: **hold `[REC]`, tap `[PLAY]` twice, close together** to toggle
it, with a "QUANT LIVE REC ON / OFF" toast that shows while `[REC]` is held and
closes instantly on release. The first `[REC]` + `[PLAY]` still starts live
recording exactly as on stock; a second tap only flips the setting if it lands
within a short pairing window of the first, otherwise it's discarded and
starts a fresh pairing attempt. The setting is a stock PERSONALIZE word already
inside the battery-backed `'ANDY'` block, so the toggle survives a power cycle
with no extra plumbing. Three detours, one cave: `tools/patch_qlrec.s`,
`python3 tools/build_qlrec.py` → `140C_KYOTI`.

**Flashed and hung the MKI (2026-09-13, original design):** it opened the
toast with a one-shot `dur=0` ("persistent, no timer") call and never closed
it — the whole front panel stopped responding to any key (sequencer kept
running — a clean power-cycle recovered it, no corruption). Root cause found
by disassembling `FUN_4005a2b8`: `dur=0` doesn't produce a passive banner — it
tail-jumps into a linked-list-insert function (`FUN_40031494`, list head
`0x460d165c`) that is structurally a **modal window/overlay stack**, a path
the project's other (HW-confirmed-safe) toasts never touch since they all use
a self-timing `dur>0`.

**Rewritten and reflashed — no hang.** The toast is a **periodically re-armed
`dur>0`** call: a per-frame hook (`qlr_tick`, detour of `0x400522ca`, the same
site DIRECT JUMP v2 uses for its own toast countdown) re-issues the same
self-timing call every `REARM_INTERVAL` ticks while `[REC]` stays held, always
before the previous one could expire. Dynamically confirmed off the modal path
in the emulator (`tools/emu_notify_probe.py`) *and* HW-confirmed by actually
flashing it.

**Six real-use refinements** came back from that flash, all now HW-confirmed
or deliberately parked. The double-tap requires the two taps to land within a
pairing window of each other (a too-slow pair is discarded, not flipped, and
starts a fresh attempt); the toast fade time was shortened; it closes
instantly on `[REC]` release instead of fading (safe now that `dur` is never
`<=0`, unlike the design that hung); the ON/OFF label was found to be
backwards relative to what the PERSONALIZE menu actually shows checked, now
fixed. The pairing window itself needed two more passes after real hardware
use turned up a genuine logic bug (a fast tap right after a successful flip
could pair with the flip itself) and a wrong-direction tuning guess along the
way — both since corrected and confirmed. Two items are deliberately left
parked rather than chased further: a rare, self-clearing cosmetic glitch (a
small textless box briefly appears where the toast was after it closes), and
the PERSONALIZE menu not visually refreshing while you're already looking at
the row it just changed (the stored value is correct — it reads right next
time you open the menu). Write-up: [`NOTES.md`](NOTES.md) "Session 46"
(original design), "Session 50" (the hang, root cause, and rewrite), "Session
51/51-bis/51-ter" (refinement pass, logic-bug fix, tuning correction). **All
of the above is HW-confirmed** except the two parked cosmetic items.

### TRIGLESS-LOCK AUTO-REMOVE — drop an emptied trigless lock  ·  **fixed, hardware-confirmed (MKI)**

A **trigless lock** is a step that carries parameter locks but no audible trig. Erase
its last remaining lock and stock leaves it lit on the trig row forever — the step is
inert but still looks like it holds something.

The handler had been mis-identified for about fifty sessions. Static analysis pointed at
the `0x40041xxx`/`0x40062xxx` p-lock cluster, and three builds aimed there did nothing on
hardware. What settled it was a **diagnostic firmware that traces itself on the unit**:
it logs into the bank blob, which a project save serialises to the card, so the trace
exports back off the machine. That showed none of the suspected message opcodes occur
during the gesture at all. The real path is `opcode 8` → `0x40061ed4` → `FUN_40041af4`
(no `linkw`, which is why every function-boundary scan missed it) → `FUN_40038874`.

Stock already works out that a step's p-lock row has gone empty — it just applies that
only to the per-step stored-p-lock bitmap and never to the trig-type-layer flag that
lights the LED. The fix adds only the missing half.

The detour sits on the **erase store** rather than on stock's emptiness verdict, so that
an empty trigless lock placed deliberately with `FUNC`+`TRIG` is never mistaken for one
that just lost its last lock: it fires only when the param being erased *was* actually
locked and every other param in the row is already clear. That matters because LIVE REC
erases as the playhead passes — holding `[NO]` and sweeping a knob across a pattern would
otherwise have silently removed placeholders the playhead crossed.

`tools/patch_triglock.s`, `python3 tools/build_triglock.py` → `1.40C` (stock-transparent,
one hunk + cave). Validated against **real hardware-exported projects**, stock vs patched,
including a real `FUNC`+`TRIG`-style empty placeholder, then **confirmed on hardware
(MKI, 2026-09-21)**: multi-pass erase, last-lock removal, ordinary trigs untouched, and
`FUNC`+`TRIG` placeholders left alone. Write-up: [`NOTES.md`](NOTES.md) "Session 13" +
"Session 78" (continued, many parts).

**Known ambiguity, pre-existing in stock:** a parameter whose legal range includes 255
stores as the same `0xFF` that means "not locked", so stock itself cannot tell such a lock
from an absent one. The LED is already wrong for that case today, patched or not.


### Part-change carryover — Part params leaking across a pattern→Part change  ·  *active WIP, partly hardware-confirmed*

Three Elektronauts reports, one family: a pattern change that links a different
Part runs only a partial stock re-apply, so stale Part-2 state can leak into the
newly-linked Part. `tools/patch_partreapply.s`, `python3 tools/build_partreapply.py`
→ `1.40C` (stock-transparent).

**Report #1 (a FLEX track stuck playing an old PICKUP loop) is now root-caused and
fixed in the emulator — awaiting a hardware test.** The voice dispatch reads the
sample slot it hands the resolver from a per-track pre-image (`0x8000082f +
track*0x48`, byte 0). Stock seeds that byte from the Part only when a track *enters*
PICKUP and never when it *leaves*, so the PICKUP slot (`128+track`) survives into the
new FLEX machine and the resolver faithfully binds the PICKUP sample. That also
explains the one-way latch the hardware showed (first switch clean, every later one
broken) and why FLEX is affected while STATIC is not — FLEX and PICKUP share one
arena and one table, differing only in slot number. Stock's own entering-PICKUP arm
does the kill bit *and* a re-seed call together; the 2026-09-13 build replicated only
the kill bit, which is why it changed nothing. The fix adds the missing re-seed.

Reports #2/#3 (recorder, REC SETUP) could not be reliably reproduced on stock and
are still treated as unconfirmed; the recorder-cache and scene-morph pieces were
flashed 2026-09-13 and are behaviorally safe. Write-up: [`NOTES.md`](NOTES.md)
"Session 49", "Session 50", "Session 81".

### Hardware-test status — read before you flash

| element | build | on-hardware status (Octatrack MKI) |
|---|---|---|
| Bug 1 manual-trig fix | all | **confirmed** — flashed 2026-08-28, stall gone, no regression |
| Bug 2 p-lock-only pattern shows empty | `build_pattern_led.py` | **confirmed** — flashed 2026-09-13, grid LED lights correctly, no regression |
| Part-change carryover — recorder cache / scene-morph pieces | `build_partreapply.py` | flashed 2026-09-13, behaviorally safe; reports #2/#3 (recorder, REC SETUP) could not be reliably reproduced on stock, treat as unconfirmed |
| ↳ report #1 (PICKUP→FLEX stuck loop) | `build_partreapply.py` | **root-caused and fixed, emulator-validated, NOT yet flashed** — stale slot in the per-track pre-image (`0x8000082f + track*0x48`); stock re-seeds it entering PICKUP but never leaving. Stock/patched A/B clean in emu; the 2026-09-13 build did NOT fix it (kill bit copied, re-seed omitted). See `NOTES.md` "Session 81" |
| **QUANTIZE LIVE REC** front-panel toggle | `build_qlrec.py` | original design hung the unit 2026-09-13; rewrite (periodic `dur>0` re-arm) **HW-confirmed**, no hang; double-tap timing, toast fade/instant-close, and label polarity **all HW-confirmed correct**; 2 cosmetic issues (textless-box flash, PERSONALIZE row not live-redrawing) parked, not chased further |
| **MUTE MODE** — all four modes (`OT` / `OTFX` / `OTFX-T` / `DT-T`), menu, SOLO handling | `build_mutemode_dt.py` | **confirmed, final** — flashed and hardware-tested 2026-09-21, MKI; all four modes and the derived menu index check out |
| ↳ the `'ANDY'`-shadow persistence (survives power cycle) | `build_mutemode_dt.py` | **confirmed** — one persisted word, defaults verified on hardware |
| **DIRECT JUMP** pattern-change mode | `build_directjump_v4.py` | **active WIP, partly hardware-confirmed** — toggle reachability and switch timing confirmed working on hardware (earlier `v1`–`v3` were dead on hardware, superseded); the playhead-preserving behaviour (currently resets to step 1) is root-caused but **not yet fixed** |
| side-chain compressor (`KEY`/`KEY FLT`/`KEY GAIN`/`SC LISTEN`, cross-core) | `build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | **confirmed, final for now** — flashed 2026-09-20, MKI, "seems to be working well"; cross-core `KEY` (any of 8 tracks) included |
| **RELOAD FROM PROJECT** — modal picker | `build_reload2.py` (TRK SEQ / PTN SEQ / PART + PTN SEQ) | **active WIP, partly hardware-confirmed** — first flash (2026-09-20) found 3 real bugs, 2 fixed (a `[PTN]`-held reachability issue and a permanent picker lockout) but **not yet reflashed**; the reload's own timing (audible gap / step-1 reset) and a real list-style picker UI are deferred |
| **TRIGLESS-LOCK AUTO-REMOVE** | `build_triglock.py` | **confirmed, final** — flashed 2026-09-21, MKI; multi-pass erase, last-lock removal, ordinary trigs untouched, and `FUNC`+`TRIG` placeholders preserved |

`OT` mode is byte-for-byte stock, and every mod is `OFF` by default. Everything
above is validated primarily in a ColdFire emulator (Unicorn, real image bytes —
RELOAD in a full-firmware emulator with a mounted card) and the side-chain DSP in
dsp56kEmu — control-flow and frame-word edits, not a guarantee of how anything
*sounds*; items marked hardware-confirmed above have also been flashed and
listened to on a real MKI. Flash at your own risk; keep the official `.syx` on
hand ([`FLASHING.md`](FLASHING.md)).

---

## What has been investigated

Verified against the official **OS 1.40C** — from the firmware's own checksums,
byte-exact decompilation, or direct disassembly. This is the reverse-engineering
foundation the firmware changes are built on. Consolidated write-ups:
[`ARCHITECTURE.md`](ARCHITECTURE.md); the address-keyed knowledge base:
[`reference/kb/`](reference/kb/); chronological log: [`NOTES.md`](NOTES.md);
mapped-vs-untouched: [`COVERAGE.md`](COVERAGE.md).

### Hardware
- **CPU:** Freescale/NXP **ColdFire** (likely MCF5445x, 32-bit, big-endian,
  ~266 MHz) — a 68000-family core, *not* ARM. The firmware drives the on-chip
  ATA controller in the MBAR region (`0xFC04_51xx`) characteristic of the MCF5445x.
- **Audio DSP:** Freescale **DSP56xxx** (DSP56721, two cores — tracks 1–4 / 5–8),
  confirmed by the 24-bit word size the boot loader uses uploading the DSP
  program 3 bytes at a time.
- **Storage:** **CompactFlash** (FAT16/32) over the ColdFire's on-chip ATA
  controller, reached through the FlexBus.

### Firmware format and update chain
Elektron ships a ZIP with **two transports of the same OS** — a `.bin` and a
`.syx` — both wrapping the same compressed container:

```
.bin  = [ELUP hdr][seed] + XOR-feedback( [len] + ELEK( aPLib( MAIN OS ) ) ) + checksum
.syx  = SysEx 7-bit(              ELEK( aPLib( MAIN OS ) )              )
```

- **ELUP layer** (`.bin` only): XOR obfuscation with feedback plus an additive
  checksum. Reimplemented in `tools/make_bin.py` / `tools/bin_decode.py`,
  validated by regenerating Elektron's own official `.bin` byte-for-byte.
- **ELEK layer:** a proprietary container whose payload is compressed with
  **aPLib**; it decompresses to the **MAIN OS** (1,112,560 bytes, base `0x40000400`).
- **No cryptographic signature** on any layer — the OS is analyzable and, with
  recalculated checksums, rebuildable. That is *why* the format can be repacked;
  it is not a security bypass.
- The updater validates the OS (`FUN_4007f748`) with explicit error codes:
  `-2` not a valid OS · `-3` length · `-4` checksum · `-5` version string
  `<"0156"` · `-6` no downgrade. (`-5` is a version floor, not a unit-model gate.)

### Operating system
- A **proprietary preemptive microkernel** (banner `ElektronOctatrack DPS-1` —
  not MQX/ThreadX/VxWorks). Task Control Blocks, per-priority ready queues,
  context switch via `TRAP #0`, blocking message queues, a time slice driven by
  the ColdFire PIT timer (`0xFC08_0000`).
- The same message-queue pattern unifies the firmware: the ATA "async queues" and
  the audio "voice mailboxes" *are* kernel message queues.

### Audio engine and sequencer
- 8 track voices in the `0x80000000` shared-RAM window (base `0x800049d8`,
  stride `0xA8`).
- Control path: a sequencer trig writes a voice mailbox → a control-rate frame
  builder assembles a parameter frame into a **double buffer** → handshake to the
  **DSP56xxx** over MMIO at `0x20000000`, which does the real-time synthesis.
- Work split: **ColdFire = control** (RTOS, sequencer, parameter assembly);
  **DSP = signal** (playback, time-stretch, filters, FX).

---

## Repository layout

```
START_HERE.md        onboarding + current frontier (read first)
README.md            this — what the firmware is, and lineage
BUILD_KYOTI.md       roll-your-own build guide (Bug 1 & 2 fixes, MUTE MODE, DIRECT JUMP, side-chain, RELOAD, QUANTIZE LIVE REC)
CREDITS.md           lineage and acknowledgements
ARCHITECTURE.md      consolidated architecture (hardware, OS, memory map, container)
COVERAGE.md          what firmware subsystems are mapped vs untouched
NOTES.md             the full chronological reverse-engineering log
FLASHING.md          safe-flashing guide + bootloader recovery net (read before flashing)

reference/kb/         distilled knowledge base (address map, formats, DSP) — ours + external RE
reference/            EXTERNAL_RESEARCH.md (the mined prior-art repos + workflow), UPSTREAM_INBOX.md
reference/upstream-notes.md   inherited octamax mod-design notes (not part of this firmware)
refs/                MANIFEST.{toml,lock} tracked; the clone cache under it is git-ignored
sysex/               the Bug-1 fix as JSON hunks + a no-assembler applier
tools/               build scripts, ColdFire patch sources, Unicorn + DSP56300 emulators, packers
tools/attic/         inherited octamax mod patch sources — kept for RE cross-reference, not built here
tools/refs/          sync.py / whatsnew.py — clone + track the external-RE repos
tools/ghidra/        Ghidra headless helpers; attic/ = one-shot probe scripts (provenance)
fetch-os.sh          download + extract the official OS
analyze.sh           entropy + binwalk + strings + container unpack -> out/
setup.sh             clone/patch/build elektron-firmware-tool into vendor/
disasm.sh            radare2 disassembly (m68k BE, base wired)
```

Downloaded Elektron binaries and generated images (`downloads/`, `out/`,
`vendor/*.bin`, `*.syx`, `*.bin`, `*.pdf`) are **git-ignored on purpose** — none
are redistributed.

Maxolydian's own octamax behaviour mods (lazy Part transitions, no BANK/PTN
countdown, arp key-scales, LED/encoder "dirty" indicators, boot branding) are
**not** part of any OT Kyoti FW build. Their patch sources live in
[`tools/attic/`](tools/attic/) for reverse-engineering cross-reference; see
[`CREDITS.md`](CREDITS.md).

---

## Building

See **[`BUILD_KYOTI.md`](BUILD_KYOTI.md)** for the full walkthrough. In short:

```sh
./fetch-os.sh && ./analyze.sh && ./setup.sh   # one-time: bring your own OS 1.40C + tools
python3 tools/build_qlrec.py                  # -> out/OCTATRACK_*QLREC.{syx,bin}
```

Every build is a guarded binary patch: it asserts the stock bytes at each splice,
verifies the code caves, derives detour targets from the linker symbol table, and
round-trips through `elektron-firmware-tool`. It aborts before writing if the
stock file is wrong, already patched, or the checksum is off.

---

## Legality (not legal advice)

- Static analysis of the publicly distributed OS carries **zero risk to the
  hardware** and is the point of this project.
- EU: Directive 2009/24/EC Art. 5 (observe/study/test a program you lawfully use)
  and Art. 6 (decompilation for interoperability). Elektron's EULA may contain
  anti-RE clauses — a contractual matter separate from copyright.
- Private and educational use is low-risk. Redistributing modified binaries is a
  different question; this repo deliberately redistributes **no** Elektron binary.

---

*OT Kyoti FW is an independent, unofficial, educational project derived from
`mxldyn/octamax`. "Elektron" and "Octatrack" are trademarks of Elektron Music
Machines MAV AB, used here only to identify the hardware under study. Not
affiliated with or endorsed by Elektron.*
