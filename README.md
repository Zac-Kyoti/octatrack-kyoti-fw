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

> **Branches.** The published **`main`** carries six finished features, every one
> flashed and confirmed on MKI hardware: the Bug-1 manual-trig fix, the Bug-2
> pattern-LED fix, **MUTE MODE** (all four modes), **QUANTIZE LIVE REC**, the
> **SIDE-CHAIN COMPRESSOR**, and **trigless-lock auto-remove**. **`wip`** is the
> frontier: all of those, plus a **seventh finished one** — the **part-change
> carryover** fix, hardware-confirmed 2026-09-22/23 but not yet promoted to
> `main` — plus the **Bugbuilds** composites, and the two threads still in
> progress: **DIRECT JUMP** (hardware-confirmed at 1x scales; non-1x scales are
> the open problem) and **RELOAD FROM PROJECT** (RELOAD3, first flash green,
> follow-up fixes unflashed). Per-feature status is in the tables below.

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


### DIRECT JUMP — an Elektron-style immediate pattern change  ·  *hardware-confirmed at 1x scales; non-1x is the open thread*

Toggled by **`[PTN]` + `[YES]`** (a transient "DIRECT JUMP ON/OFF" overlay), no
PERSONALIZE entry. It **deliberately does not persist** — it is a performance
feature, so the unit comes up with it OFF on every power-on (Session 83; the
change was purely subtractive, and the build asserts the ROM seed behind
`DJ_MODE` really is zero). When on, manually cueing a new pattern:

- switches on the **next step tick** instead of quantising to the end of the
  current pattern,
- **stays in master time** — the new pattern resumes at
  `masterStep mod newMasterLen`, and each track at `that mod trackLen`, rather
  than restarting at step 1,
- loads the new **Part immediately**,
- sends the MIDI Program Change ~1 step early.

The arranger and pattern chains are untouched. That position rule is not
invented here: it is the Analog Rytm's own commit arithmetic, ported instruction
for instruction after three flashed builds had each implemented a different
reading of an English sentence (`reference/AR_DIRECT_JUMP.md`; the prose spec is
retired). It is **not** elapsed-time alignment — the two coincide only when the
two patterns' master scales match, which is exactly why every equal-scale test
used to pass and every differing-scale one used to fail.

Current build: `python3 tools/build_directjump_v4.py` → `140C_KYOTI`
(`tools/patch_directjump.s` + a `[PTN]`-held keymap fix). `v1`–`v3` are
superseded — they were dead on hardware, because the stock `[PTN]`-held overlay
swallowed `[YES]`'s dispatch the whole time it was held, until `v4` wrote the
toggle straight into that overlay's own `[YES]` slot.

**Hardware-confirmed (MKI, 2026-09-23, Session 87)**, and this is the baseline
not to regress: tracks and patterns stay in master time through a DIRECT JUMP
switch, patterns land on the correct step between switches, mixed track lengths
in one pattern work together (7 / 12 / 16), and **MASTER LENGTH is respected,
including `INF`**.

**The standing constraint:** all of that is confirmed only with **1x track scales
and a 1x master scale**. Setting either to anything else produces unexpected
results. That is the entire remaining problem, and the next thread — the standing
hypothesis (stock rebuilds position in the *tick* domain while the ported rule is
in the *step* domain, and they agree only at 1x) and the exact regions to
re-derive are written up in
[`reference/handoffs/DIRECTJUMP_SCALES_HANDOFF.md`](reference/handoffs/DIRECTJUMP_SCALES_HANDOFF.md).

Two hardware faults were found and fixed on the way there, both worth recording:
a **lockup** at transport start caused by gating a hook on a global that lives
beyond the boot zero-fill and so held garbage at power-on (the emulator could
never have caught it — Unicorn zero-fills memory, so the gate now poisons that
scratch block before every patched run), and **doubled trigs** caused by writing
a per-track "previous step" array that stock's commit tail deliberately leaves
alone, feeding `0xFF` into the voice dispatcher. Write-up: [`NOTES.md`](NOTES.md)
"Session 15" + "Session 21" + "Session 35" → "Session 60" through "Session 87"
(many parts); emulators and diagnostics `tools/emu_directjump*.py`,
`tools/diag_resume_pos.py`, `tools/diff_stock_vs_patch.py`.

### SIDE-CHAIN COMPRESSOR — external key input for the stock DynamiX compressor  ·  **hardware-confirmed, final**

Adds `KEY` / `KFLT` / `KGN` / `MON` to the COMPRESSOR effect's page 2: pick any
of the eight audio tracks to *drive* the compression on the track the compressor
sits on (classic kick-ducks-the-pad), and it keeps keying even when the key track
is muted. `KEY` reaches **any of the 8 tracks**, flat (`T1`..`T8`) — not just the
four that share the compressor's own DSP core. `KGN` trims the key
(declick-smoothed), `KFLT` is a declicked one-pole filter (below centre LP, above
centre HP, centre = off), and `MON` auditions the filtered key signal instead of
the track.

This is a DSP56300 job, not ColdFire, and it is one build:

```sh
python3 tools/build_sidechain3.py    # -> out/OCTATRACK_SIDECHAIN3_CROSS.{syx,bin}
```

**Hardware-confirmed on MKI, 2026-09-20 — single-core and cross-core both.**
Every track publishes its pre-FX block to a shared ring and the compressor's
detector reads the chosen track's ring; reaching *across* cores adds a per-core
generation counter and a shared-window (`Y:0x30000-0x3FFFF`) publish/foreign-read
mechanism, adapted from octabam's own XBUS cross-core bus design. Emulator-
verified before it was ever flashed: `emu_sc_dsp3.py` (same-core),
`emu_sc_dsp3_xcore.py` (generation counter + cross-core addressing), and a
genuine dual-core run under `tools/dsp56300_xcore`'s `dsp_host_xcore` (lock-step
plus timing-skew fuzz).

**What it costs:** the DSP code space is donated by **SPRING REVERB**, an
FX2-exclusive effect, which is pulled from the FX2 chooser (15 → 14 entries) and
null-stubbed so an older project still referencing it by id stays safe.
**SPATIALIZER is untouched** and remains a normal selectable effect — an earlier
stage of this work donated SPATIALIZER instead, ran out of slack, and was
reverted.

A very mild HP↔OFF filter pop remains (three declick designs tried and
reverted — see `NOTES.md` Session 76's trail); low-ATK/REL "graininess" on a busy
key is filed as research-only, no fix attempted. Neither blocks shipping.
Write-up: [`NOTES.md`](NOTES.md) "Session 17" (+ continued 1–8) → "Session 77"
(×3, the cross-core work); sources `tools/patch_sidechain.s`,
`tools/patch_sc_dsp3.asm`, `tools/sc_tables.py`.

### RELOAD FROM PROJECT — reload a track's sequence from the card, in time  ·  *active WIP; first flash green, follow-up fixes unflashed*

Stock 1.40C can only reload from the card at whole-**bank** granularity, and doing
so **stops the transport**. (An earlier version of these notes said it "glitches
the audio" — that is wrong, and was corrected on hardware: stock simply stops the
sequencer.) What this adds is finer granularity, and doing it *in time with the
master clock, without touching the transport at all*. Adapted from the Digitone's
RELOAD FROM PROJ.

**The picker is gone** (Session 85). Two direct chords — no modal window, no
keymap layer of ours, no arrows, no timeout, no BUSY state:

| chord | what it does |
|---|---|
| **`[PTN]` + `[TRACK n]`** | reload track *n*'s card-saved sequence — audio or MIDI. Everything for that track: regular and recorder trigs, trigless trigs, trigless locks and their locked values, swing/slide, micro-timing, trig conditions, its step count. The other 7 tracks, the pattern length/scale and the pattern→Part link are left alone. **The Part does not change.** Toast `TRK SEQ RELOADED`, and the `[PTN]` release does not raise SELECT PATTERN. |
| **`[BANK]` + `[TRACK n]`** | the same, plus re-apply the saved **Part** — from **RAM, not the card**: the saved copy of the Part currently associated with the pattern, so a Part you saved this session is what comes back. That half is stock's own reload-part routine, so a never-saved Part gets stock's own verdict rather than logic of ours. Two-line toast `TRK SEQ + PART` / `RELOADED`, or the never-saved box alongside the sequence result. |

The sequence always comes from the card's last **SAVE BANK** snapshot
(`bankNN.strd`). An async job on the storage task parses the target out of it
with the firmware's own per-pattern chunk parser, copies it into the live blob,
and refreshes the live cache. No other pattern, no other bank, no disk write, no
confirmation prompt.

**Why a redesign rather than another fix.** Across the whole RELOAD thread the
bug tally was lopsided: ~13 hardware bugs in the picker / keymap / popup
machinery, and **none** in the worker that actually does the reload. Deleting the
modal UI took the build from 10 detours and 2186 cave bytes to 6 and 1500, and it
now *asserts* that it pokes no keymap record at all — every `[PTN]`/`[BANK]`
handler and overlay record is byte-for-byte stock.

**A reload does not touch the clock.** The first RELOAD3 flash restarted both the
track sequence and the internal metronome; the cause was arming stock's
`RELOAD_NOW` flag, which gates a whole-bank **re-home** — a positional operation
that zeroes the master playhead, the same word the metronome's beat flags derive
from. One write explained both symptoms. `RELOAD_NOW` is now armed on no path,
and dropping it costs nothing: the worker's own live-cache refresh already keeps
both trig-data consumers current, and stock re-reads per-track scale from the
blob on every wrap, so a changed step count self-heals within one cycle, in time.

**SELECT BANK moved to the `[BANK]` release**, matching `[PTN]`'s own gesture
shape, and neither chord shows a window on either event. The press still pushes
the `[BANK]` overlay layer, silently — that layer is what remaps the 16 trig keys
to bank-select while `[BANK]` is held, and deferring it along with the window
would have quietly turned hold-`[BANK]`+trig into sequence editing.

Carried over from RELOAD2 because it is proven: the per-track worker slice, the
`.strd` open, and the whole-bank suppression that cut a reload from **6852
buffered card reads to 354**.

Build: `python3 tools/build_reload3.py` → `OCTATRACK_OS1.40C_RELOAD3.{syx,bin}`
(`tools/patch_reload3.s`, 6 detours, 1500 B cave). **First hardware flash
(2026-09-23): both chords execute, no conflicts** — the redesign works. Three
follow-ups came back from that flash (the transport/metronome restart, the
`[BANK]`-release deferral, the two-line Part toast); all three are built and
diagnostic-verified but **not yet reflashed**. Deferred by the user: all-tracks
and whole-bank variants. Still unknown: the root cause of the old stuck-`G_KIND`,
though the redesign leaves no modal state for a lost post to wedge. `RELOAD2`
(the 3-item `[BANK]`+`[YES]` picker) and `RELOAD` (the original) are superseded
and kept only for rollback and reference. Spec and measurements:
[`reference/RELOAD_REDESIGN.md`](reference/RELOAD_REDESIGN.md); write-up
[`NOTES.md`](NOTES.md) "Session 42"–"44" + "Session 47" + "Session 80"–"Session
86" (many parts); diagnostics `tools/diag_reload3_chords.py`,
`diag_reload3_timing.py`, `diag_reload3_bankdefer.py`, and the RELOAD2-era
`emu_reload2.py`.

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


### Part-change carryover — Part params leaking across a pattern→Part change  ·  **2 of 3 reports fixed, hardware-confirmed (MKI)**

Three Elektronauts reports, one family: a pattern change that links a different
Part runs only a partial stock re-apply, so stale Part-2 state can leak into the
newly-linked Part. `tools/patch_partreapply.s`, `python3 tools/build_partreapply.py`
→ `1.40C` (stock-transparent). The thread is **closed**: the two reports that could
be reproduced are fixed and hardware-confirmed. This is the one finished feature
that lives on `wip` only — `main` still carries the older, pre-Session-81 build.

**Report #1 (a FLEX track stuck playing an old PICKUP loop) is fixed and
hardware-confirmed (MKI, 2026-09-22).** The voice dispatch reads the
sample slot it hands the resolver from a per-track pre-image (`0x8000082f +
track*0x48`, byte 0). Stock seeds that byte from the Part only when a track *enters*
PICKUP and never when it *leaves*, so the PICKUP slot (`128+track`) survives into the
new FLEX machine and the resolver faithfully binds the PICKUP sample. That also
explains the one-way latch the hardware showed (first switch clean, every later one
broken) and why FLEX is affected while STATIC is not — FLEX and PICKUP share one
arena and one table, differing only in slot number. Stock's own entering-PICKUP arm
does the kill bit *and* a re-seed call together; the 2026-09-13 build replicated only
the kill bit, which is why it changed nothing. The fix adds the missing re-seed.

**A second, related stock bug was found and fixed the same way: a pattern change
into a PICKUP track spuriously marks its Part edited/unsaved, even when nothing
changed.** Attributed to stock's own entering-PICKUP path (measured identical on
stock and the first patched build, so not something this fix introduced), then
fixed with a second detour that snapshots the Part's edited state before the
switch and restores it after — restoring the *whole* byte, so a genuine edit made
before the switch survives untouched. Hardware-confirmed (MKI, 2026-09-23): the
spurious mark is gone, and a real edit on another Part still shows correctly.

Reports #2/#3 (recorder, REC SETUP) could not be reliably reproduced on stock and
are still treated as unconfirmed; the recorder-cache and scene-morph pieces were
flashed 2026-09-13 and are behaviorally safe. Write-up: [`NOTES.md`](NOTES.md)
"Session 49", "Session 50", "Session 81".

### Composite builds — the bug fixes folded in, and the staged all-in-one

Two ways to combine, both on `wip`.

**Bugbuilds** (`python3 tools/build_bugbuilds.py`) folds all three bug fixes into
each finished *feature* image — MUTEMODE_DT, QLREC, SIDECHAIN3_CROSS and TRIGLOCK,
each plus PARTREAPPLY + PATTERNLED + PLAYSFREEFIX — writing only to
`out/Bugbuilds/`, so the standalone per-feature images are left untouched. It
composes *onto* the finished feature image rather than re-deriving it: SIDE-CHAIN
in particular is never rebuilt, so its DSP payloads, COMPRESSOR descriptor and FX2
chooser edits pass through unchanged and its cave keeps its address. Cave placement
is automatic, and every run asserts an interlock proof on every image — each cave
region all-zero before use, every detour site still holding exact stock bytes, no
branch into a detour site, and a byte-level compositionality check: the composite's
delta against stock is exactly the *disjoint union* of the feature's own delta and
the three fixes' own, with no unattributed bytes. All four images report clean.
`--with-wip` will fold the fixes into DIRECT JUMP and RELOAD3 the same way once
those are finished.

**The single all-in-one image is staged, not built.** `tools/build_merged.py`
stays withdrawn on purpose, so one combined image cannot quietly ship an unfinished
feature; [`reference/MERGE.md`](reference/MERGE.md) is the authoritative allocation
map it will be rebuilt from, re-scanned against true stock on 2026-09-23. That
re-scan found the merge got substantially *simpler*: all 27 detour sites across all
nine mods are distinct with zero byte overlap, the free zone is one contiguous
5986-byte run, and the old `[YES]`-handler collision is **gone** — DIRECT JUMP v4
reaches its toggle through the `[PTN]` keymap overlay and RELOAD3 deleted its
picker, so neither detours `0x4005e4c8` any more (the `[YES]` trampoline and the
`MERGE=1` chaining mechanism are obsolete). Hence two stages:

| | contents | to resolve | headroom |
|---|---|---|---|
| **`KYOTI_V1.0`** | the seven finished, hardware-confirmed mods | none — mechanical repack only | 3196 B (53 %) |
| **`KYOTI_V1.1`** | + DIRECT JUMP v4 + RELOAD3 | two builder-assertion conflicts, both DIRECT-JUMP-vs-someone-else | 652 B (11 %) |

### Hardware-test status — read before you flash

| element | build | on-hardware status (Octatrack MKI) |
|---|---|---|
| Bug 1 manual-trig fix | all | **confirmed** — flashed 2026-08-28, stall gone, no regression |
| Bug 2 p-lock-only pattern shows empty | `build_pattern_led.py` | **confirmed** — flashed 2026-09-13, grid LED lights correctly, no regression |
| Part-change carryover — recorder cache / scene-morph pieces | `build_partreapply.py` | flashed 2026-09-13, behaviorally safe; reports #2/#3 (recorder, REC SETUP) could not be reliably reproduced on stock, treat as unconfirmed |
| ↳ report #1 (PICKUP→FLEX stuck loop) | `build_partreapply.py` | **confirmed fixed** — flashed 2026-09-22, MKI; the 4-pass round trip now plays the FLEX sample on every pass. Stale slot in the per-track pre-image (`0x8000082f + track*0x48`); stock re-seeds it entering PICKUP but never leaving. The 2026-09-13 build did NOT fix it (kill bit copied, re-seed omitted). See `NOTES.md` "Session 81" |
| ↳ spurious Part-edited flag on entering PICKUP | `build_partreapply.py` | **confirmed fixed** — flashed 2026-09-23, MKI; a pattern switch into a PICKUP track no longer marks its Part unsaved, and a genuine edit made before the switch still shows correctly. Found while testing report #1; stock bug, not a regression. See `NOTES.md` "Session 81" |
| **QUANTIZE LIVE REC** front-panel toggle | `build_qlrec.py` | original design hung the unit 2026-09-13; rewrite (periodic `dur>0` re-arm) **HW-confirmed**, no hang; double-tap timing, toast fade/instant-close, and label polarity **all HW-confirmed correct**; 2 cosmetic issues (textless-box flash, PERSONALIZE row not live-redrawing) parked, not chased further |
| **MUTE MODE** — all four modes (`OT` / `OTFX` / `OTFX-T` / `DT-T`), menu, SOLO handling | `build_mutemode_dt.py` | **confirmed, final** — flashed and hardware-tested 2026-09-21, MKI; all four modes and the derived menu index check out |
| ↳ the `'ANDY'`-shadow persistence (survives power cycle) | `build_mutemode_dt.py` | **confirmed** — one persisted word, defaults verified on hardware |
| **DIRECT JUMP** pattern-change mode | `build_directjump_v4.py` | **confirmed at 1x, active WIP beyond it** — flashed 2026-09-23, MKI: master time held through switches, correct landing step, mixed track lengths (7/12/16), MASTER LENGTH respected incl. `INF`, no doubled trigs. **Only with 1x track scales and a 1x master scale**; anything else is unexpected and is the open thread. Earlier `v1`–`v3` were dead on hardware, superseded |
| side-chain compressor (`KEY`/`KFLT`/`KGN`/`MON`, cross-core) | `build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | **confirmed, final** — flashed 2026-09-20, MKI, "seems to be working well"; cross-core `KEY` (any of 8 tracks) included. Donor is SPRING REVERB (pulled from the FX2 list); SPATIALIZER untouched |
| **RELOAD FROM PROJECT** — two direct chords | `build_reload3.py` (`[PTN]`/`[BANK]` + `[TRACK n]`) | **active WIP, first flash green** — flashed 2026-09-23, MKI: both chords execute, no conflicts. Three follow-ups from that flash (reload restarting the sequence + metronome, SELECT BANK on the `[BANK]` release, two-line Part toast) are built and diagnostic-verified but **not yet reflashed**. All-tracks and whole-bank variants deferred |
| **TRIGLESS-LOCK AUTO-REMOVE** | `build_triglock.py` | **confirmed, final** — flashed 2026-09-21, MKI; multi-pass erase, last-lock removal, ordinary trigs untouched, and `FUNC`+`TRIG` placeholders preserved |
| Bugbuild composites (feature + all 3 bug fixes) | `build_bugbuilds.py` → `out/Bugbuilds/` | **not flashed.** Each base feature and each bug fix is individually hardware-confirmed above, and every composite carries a per-run interlock proof (disjoint deltas, stock bytes at every detour site) plus an `emu_pattern_led` pass — but no composite image has been on hardware yet |

`OT` mode is byte-for-byte stock, and every mod is `OFF` by default — DIRECT JUMP
additionally does not persist, so it is OFF again after any power cycle. Everything
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
BUILD_KYOTI.md       roll-your-own build guide (every build_*.py, prerequisites, version strings)
CREDITS.md           lineage and acknowledgements
ARCHITECTURE.md      consolidated architecture (hardware, OS, memory map, container)
COVERAGE.md          what firmware subsystems are mapped vs untouched
NOTES.md             the full chronological reverse-engineering log
FLASHING.md          safe-flashing guide + bootloader recovery net (read before flashing)

reference/kb/         distilled knowledge base (address map, formats, DSP) — ours + external RE
reference/            MERGE.md (the all-in-one allocation map), AR_DIRECT_JUMP.md, RELOAD_REDESIGN.md,
                      EXTERNAL_RESEARCH.md (the mined prior-art repos + workflow), UPSTREAM_INBOX.md
reference/handoffs/   per-thread handoffs for the work still open (DIRECT JUMP scales, RELOAD2)
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
python3 tools/build_qlrec.py                  # one feature -> out/OCTATRACK_*QLREC.{syx,bin}
python3 tools/build_bugbuilds.py              # each finished feature + all 3 bug fixes -> out/Bugbuilds/
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
