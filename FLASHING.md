# Safe flashing guide — OT Kyoti FW

How to flash an OT Kyoti FW image onto your Octatrack, with a full safety net.

> **The behaviour changes are OFF by default.** Straight after flashing, the unit
> behaves like stock firmware apart from the one always-on bug fix below. MUTE
> MODE is switched on from PERSONALIZE; DIRECT JUMP from a front-panel chord.

> **Octatrack MKI or MKII.** Elektron ships one OS 1.40C image for both units and
> the reverse engineering / builds here apply to both; the boot `0x46c8d18c`
> probe adapts the unit-specific details. All hardware testing in this project is
> on a **MKI** the author owns — including the flash that confirmed the Bug-1 fix.

> **The always-on bug fix (no PERSONALIZE switch):** a **Plays-Free MIDI track**
> with **trig quantize = Direct** and the pattern's **scale = Per Track** used to
> **stall after its first step** when manually triggered — step 1's note fired,
> step 2's never did. Root cause: `FUN_4009b5c8` seeded the per-track scale index
> using the *audio* track stride for MIDI tracks, corrupting the step-length
> lookup. Audio tracks were never affected. It is a pure fix — it only changes
> behaviour in that exact broken configuration. See `NOTES.md` "Session 5 part 3"
> / "Session 6"; hardware-confirmed on a MKI 2026-08-28.

> **Guiding principle: learn how to recover BEFORE flashing.** A brick here is
> *soft and recoverable* — the Startup Menu (bootloader) lives in a region that
> the OS update doesn't touch, so you can always return to a good OS over MIDI.
> Read the recovery section first.

---

## 0. What you need (checklist)

- [ ] An **Octatrack** (MKI or MKII).
- [ ] A **5-pin MIDI (DIN) interface** between the computer and the Octatrack's
      MIDI IN. ⚠️ **The MIDI upgrade does NOT work over USB** — it has to be MIDI
      DIN. A USB-MIDI cable or an audio interface with MIDI works. (Or use the
      CF-card path in §3a, which needs no MIDI.)
- [ ] **SysEx Librarian.app** (Mac) or any tool that sends a raw `.syx`.
- [ ] **The build you want** — the `.syx` (MIDI) or `.bin` (CF card) from `out/`.
- [ ] **The official rescue firmware** (essential!):
      `downloads/extracted/OCTATRACK_OS1.40C.syx`.
- [ ] **Stable power** — don't power from a dubious strip; don't move the unit
      during flashing.

---

## 1. Safety net — the recovery path (READ THIS FIRST)

If something goes wrong (a "Z" screen, won't boot, a hang), **DON'T panic**. You
recover like this:

1. Turn off the Octatrack.
2. Holding **[FUNC]** pressed, turn it on → you enter the **STARTUP MENU**.
3. Press **[TRIG 3]** → **MIDI UPGRADE** → "READY TO RECEIVE MIDI UPGRADE…"
   appears.
4. From SysEx Librarian, send the **official rescue OS**
   (`downloads/extracted/OCTATRACK_OS1.40C.syx`).
5. Wait for "PREPARING FLASH" → "UPDATING FLASH". **Don't power off.** You're back
   on the factory OS.

This menu works **even if the OS is corrupt** (it's the bootloader). That is why
the real risk of losing the unit is very low.

> **Also**: [TRIG 2] = EMPTY RESET (resets the battery-backed RAM and clears
> settings, **but NOT the CF card**). Rarely needed, but it's there.

---

## 2. Before flashing — backup

Flashing the OS **does not touch the CF card** (your sets, projects and samples
live there and stay intact). Even so, as a precaution:

- [ ] Back up your CF card to the computer (USB DISK MODE and copy everything), or
      at least the projects that matter.
- [ ] Optional but recommended: create a **RESTORE POINT** of your active project.

---

## 3a. Flash from the CF card — the fast way (recommended)

Manual §8.5.2. Reads the file off the card instead of trickling it over MIDI at
31250 baud, so it takes seconds rather than minutes.

1. Connect the OT over USB, select **USB DISK MODE**, press **[YES]**. The CF card
   appears as a drive.
2. Copy your chosen build's `.bin` (e.g. `out/OCTATRACK_MUTEMODE.bin`) to the
   **ROOT** of the card — not inside any folder.
3. **Eject the card properly**, then leave USB DISK MODE on the OT. Skipping the
   eject can leave the write in cache and the OT reads a truncated file.
4. **PROJECT → OS UPGRADE → [YES]**, confirm the prompt.

The active project is synced to the card automatically before the upgrade.

> This needs a unit that boots. If it does not, use the MIDI path in §3b.

`tools/make_bin.py` builds the `.bin`. Its correctness is not assumed: it
regenerates Elektron's own official `.bin` byte-for-byte from that file's own
container.

---

## 3b. Flash over MIDI — for recovery, or if the card path fails

1. **Connect MIDI**: your interface's MIDI OUT → the Octatrack's **MIDI IN**
   (DIN, not USB).
2. **Open SysEx Librarian**, choose your MIDI interface as the destination.
3. **Drag** your chosen build's `.syx` into the SysEx Librarian list.
4. On the Octatrack: turn it off, hold **[FUNC]** and turn it on → **STARTUP
   MENU**.
5. Press **[TRIG 3]** (MIDI UPGRADE) → **"READY TO RECEIVE MIDI UPGRADE…"**.
6. In SysEx Librarian, select the file and press **Play**. The OT's **[TRIG]**
   lights turn on one by one as it receives. **It takes a while.**
7. When the transfer finishes: **"PREPARING FLASH"** then **"UPDATING FLASH"**.
   - **⚠️ DO NOT POWER OFF OR DISCONNECT** during "…FLASH". Interrupting here
     corrupts the OS (→ "Z" screen).
8. The OT may update the bootstrap after flashing. **Wait** for it to finish or to
   tell you to restart.

> If SysEx Librarian sends too fast and the OT loses sync, lower the send speed in
> *Preferences* (increase "pause between messages", e.g. to 100–300 ms).

---

## 4. Verify the flash and test each feature

An OS upgrade **resets PERSONALIZE**, so any PERSONALIZE-gated feature (MUTE MODE)
is off after a flash until you re-enable it. The Bug-1 fix is always on.

### 4.0  Boot check
The startup screen and **SYSTEM → SYSTEM STATUS → OS VERSION** read `140C_KYOTI`
(the field is fixed at 10 chars; `1.40C_KYOTI` at 11 does not fit). The
`build_trigscale_only.py` fix-only build deliberately keeps the stock `1.40C`
string.

### 4.1  The MIDI manual-trig fix  (always on)

> **Hardware-confirmed (MKI, 2026-08-28.)** The fix-only build was flashed and the
> stall below no longer happens. The steps below re-verify on your own unit.

1. On a **MIDI track**, set **PLAYBACK** so the track is **PLAYS FREE**.
2. Set that MIDI track's **trig quantization to DIRECT**.
3. On the pattern, set **SCALE MODE = PER TRACK** (SCALE SETUP), give the MIDI
   track any per-track length.
4. Put a MIDI note trig on **step 1** and another on **step 2** (different notes,
   e.g. C then C#), MIDI OUT to something you can hear/monitor.
5. **Stop the sequencer.** Press and hold the MIDI track's **[TRIG]** so it plays
   free from step 1.

- **Stock 1.40C (bug):** only the step-1 note (C). It never advances to step 2.
- **Fixed:** C, then C#, then it loops the two-step phrase — like SCALE MODE =
  PATTERN.

6. **Regression checks** (all should behave exactly as on stock):
   - SCALE MODE = PATTERN → still fine.
   - trig quant ≠ Direct → still fine.
   - not Plays Free → still fine.
   - an **audio** track with Plays Free + Direct + Per-Track scale, manually
     trigged → plays and advances normally (audio was never affected).
   - trig modes ONE / ONE2 / HOLD on the MIDI track — all three should be fixed.

> Emulator evidence: `tools/emu_trigbug.py` (`--drift`). On the repro bank the
> corrupted scale index goes 255 → a valid 2 after the patch.

### 4.2  MUTE MODE  (`build_mutemode.py` — `OT`/basic `OT+FX` cut hardware-confirmed; the trig-attack blip on `OT+FX` is a KNOWN, UNFIXED bug — see below before flashing)

> **⚠️ Current status (2026-09-14): the trig-attack blip described below is NOT fixed.
> Do not flash expecting it to be gone.** History: the Session-10 build (softmute V6b)
> was flashed and confirmed working for the basic cut. V7 (adds SOLO) was first flashed
> 2026-09-13 and found the blip. Session 52's `pre_v` hook was believed to fix it
> (isolation-revalidated, described below as fixed) but flashing it changed nothing —
> `pre_v` was root-caused as targeting dead code entirely and removed. Session 53/53-bis
> built two replacements, `mt_trig` and `mt_rebind` (still in `patch_softmute.s`), each
> individually proven correct by direct CPU-side and dynamic instrumentation — **also
> flashed, also zero hardware effect.** Session 55 finally found why, using a genuinely
> DSP-capable emulator (not just CPU-side): both hooks fire and gate exactly as designed
> for a track's first-ever trig, but a **second trig on a track that was already
> muted while playing** — the actual bug scenario — reaches neither hook at all, and
> the DSP-fed voice content restarts in full, byte-identical to unmuted. Root cause is
> narrowed to a specific, not-yet-fully-disassembled code path (`FUN_4000f450`'s reuse
> branch, `0x4000f526` onward — see `NOTES.md` "Session 55 continued") but the actual
> fix has not been written yet. Do not re-flash any `build_mutemode*.py` output
> expecting this specific symptom to be resolved.

1. **PROJECT → PERSONALIZE**, scroll to **MUTE MODE**. It cycles `OT` / `OT+FX`
   (and `DT` on the `build_mutemode_dt.py` build). Default `OT`. The 15/16 stock
   entries above must still show their own values.
2. Set **`OT+FX`**. Put a **delay or reverb** on an audio track, obvious tail.
3. Play the track, then **FUNC + [that track's key]** (also try the MIXER menu /
   QUICK MUTE — same code path):
   - **`OT`:** dead silence instantly — dry *and* the FX tail (stock).
   - **`OT+FX`:** the dry cuts fast and clean; the delay repeats / reverb tail
     **ring out**. A muted track's sequencer trigs make no sound — **specifically
     re-check this: the previous flash left a short attack blip on every trig of a
     muted STATIC or FLEX track; confirm it is now fully gone**, not just shortened.
     Unmute returns the track on its next trig.
4. **Persistence:** power-cycle the unit — MUTE MODE stays where you left it
   (the setter writes the `'ANDY'` battery-SRAM shadow — "Session 19"). An EMPTY
   RESET clears it to factory.
5. Regression: the manual-trig fix still works; other tracks unaffected;
   in `OT` mode SOLO is a stock hard cut.

### 4.3  MUTE MODE `OT+FX` for SOLO  (`wip` `build_mutemode.py`, softmute V7 — flashed 2026-09-13 alongside the `pre_v` bug above, fix not yet reflashed)

With **`OT+FX`** selected and a delay/reverb on two tracks:

1. **SOLO** one track (SOLO mode + its key). The non-soloed tracks' **dry stops**
   fast, but their **FX inserts ring** their tails; their trigs are silent (no
   attack blip, same re-check as §4.2); releasing solo resumes them from the next
   trig.
2. In **`OT`** mode, solo is the stock instant cut of everything else.
3. Solo a track that is **already muted** → it plays (solo overrides mute).

### 4.4  DT mode  (`build_mutemode_dt.py` — flashed 2026-09-13, "does nothing at all"; STILL UNFIXED — see below before flashing)

> **⚠️ Current status (2026-09-14): still unfixed, same root cause as §4.2.** The
> first-ever hardware flash of DT mode showed no audible effect from muting whatsoever.
> DT relies on the same trig-suppression mechanism as `OT+FX` (it has no separate
> dry-cut). Same history as §4.2's callout: `pre_v` (Session 52) targeted dead code and
> was removed; `mt_trig`/`mt_rebind` (Session 53/53-bis, still in `patch_softmute.s`)
> are individually correct but don't reach the actual retrigger path (Session 55). Do
> not re-flash expecting DT to suppress a new trig on an already-muted track yet.

Set **MUTE MODE = DT**. DT is a pure sequencer mute: a voice that is already
sounding keeps playing under its own AMP envelope; only new trigs are suppressed.

1. A one-shot sample, mid-playback, muted → it **follows its own AMP RELEASE**
   (not the `OT+FX` fast declick).
2. A **LOOP** sample with long HOLD/REL, muted → it keeps sounding indefinitely
   while muted; unmute is seamless.
3. **The core thing that was broken: while held, new sequencer trigs on a muted
   STATIC or FLEX track must produce NO sound at all** (not even a blip) — confirm
   this specifically, since this is exactly what "did nothing" before.
4. Solo behaves like the mute (sounding voices ride out).
5. Switch **DT → OT+FX** live while a muted voice is ringing — it should adopt the
   `OT+FX` behaviour on the next mute.

### 4.5  DIRECT JUMP  (`build_directjump_v4.py` — v1/v2/v3 FLASHED 2026-09-14/15, DID NOTHING; root cause found, v4 fixes it, NOT yet reflashed — see below, READ BEFORE FLASHING)

**⚠️ DIRECTJUMP_V3 was flashed and had NO effect whatsoever** — no toast, no
toggle, the combo did literally nothing, on a unit otherwise working normally.
**Root cause found (NOTES.md "Session 60"), and it's stock, structural
behaviour, not a bug in any patch here**: holding **[PTN]** unconditionally
pushes a small stock UI overlay layer (`0x400bf0f2`) whose own `[YES]` record
has a NULL press handler. The runtime key-dispatch table entry for `[YES]`
gets overwritten with that NULL for as long as `[PTN]` is held — v1/v2/v3 all
detour the *stock* `[YES]` handler (`0x4005e4c8`), which that NULLed table
entry never reaches. **This is genuinely dead code while the chord is being
held**, confirmed by running the real, unmodified firmware's own layer-push
code under emulation (`tools/emu_directjump_v4.py`), not just by reasoning
about the disassembly.

**Fix (`build_directjump_v4.py`, `patch_directjump.s` `--defsym DJ_KEYMAP=1`)**:
no detour on `0x4005e4c8` at all. The build instead writes `dj_toggle`'s
address directly into that overlay layer's own `[YES]` record, so the exact
same stock rebuild that used to zero the runtime dispatch slot now points it
at our toggle. Verified two ways: (1) `tools/emu_directjump_v4.py` runs the
real `FUN_4005a044` ([PTN] press) + the real layer-push/table-rebuild code
against both the v3 image (reproduces the dead slot) and the v4 image
(dispatch slot → `dj_toggle`, then actually `jsr`s it and confirms the toggle,
re-checksum, and toast all fire) — the closest thing to a hardware round-trip
this project's emulator harnesses do; (2) a byte-diff assertion that v4
touches exactly v3's cave + the one 4-byte record field, nothing else.

**⚠️ Likely shared root cause, NOT yet fixed**: `patch_reload2.s`'s `rl_yes`
(the `RELOAD FROM PROJECT` `[PTN]`-hold picker's `[YES]` confirm) detours the
*same* `0x4005e4c8` behind the *same* `PTN_MODE` gate — so RELOAD2's
`[PTN]`+`[YES]` flow is very likely equally dead on real hardware for the
identical reason. It just hasn't been flash-tested yet (queued behind
DIRECTJUMP). Worth the same kind of keymap-slot fix before it's ever flashed
standalone (there is no combined build — see `reference/MERGE.md`).

1. Hold **[PTN]** and tap **[YES]** → a transient **"DIRECT JUMP ON"** overlay
   (~0.7 s / ~68 frames), then **OFF** on the next chord. The SELECT PATTERN
   chooser must not pop on the [PTN] release.
2. With DIRECT JUMP **ON**, play a pattern and manually cue another (different
   Part): it should switch on the **next step tick**, keep the **step position**
   (modulo the new pattern's length), and load the new Part at once. A MIDI
   Program Change goes out ~1 step early.
3. The **arranger** and **pattern chains** must be unchanged (DIRECT JUMP bails
   when the arranger is running or a chain is active).
4. Turn it **OFF** → manual pattern changes are stock (end-of-pattern quantised,
   restart at step 1).
5. **[PTN] tapped alone** (no [YES]) still opens SELECT PATTERN normally —
   v4 doesn't touch that path.

> Five further hardware-only unknowns are in `NOTES.md` "Session 15 continued" /
> "Session 21 continued"; `DJ_TOAST_DUR` (default 0x44, ~68 frames) may need one
> tweak after a HW listen. v1/v2/v3 (`build_directjump.py`/`_v2`/`_v3.py`) are
> kept for reference but should not be reflashed — they reproduce the dead combo.

### 4.6  Side-chain compressor  (`build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` — **HARDWARE CONFIRMED, SHIPPING, MKI, 2026-09-20. User considers this build final for now.**)

> **Current state (2026-09-20, supersedes everything below in this section):**
> `KEY FLT` is a **one-pole** tracker (LP/HP/OFF), not the 2-pole Chamberlin
> SVF this section's own body text describes — that redesign landed Session
> 76 and made the whole q=1-vs-q=2 resonance question below moot (a single
> real pole can't resonate at all). `KEY` is now a **list-style chooser**
> (matching LFO TRIG's own UI) reaching **any of the 8 tracks** flat
> (`T1`..`T8`), not just this track's own 4 same-core siblings — the
> cross-core reach (a per-core generation counter + a shared-DSP-window
> publish/foreign-read mechanism, `NOTES.md` "Session 77" ×3) was flashed
> today and the user reports it "seems to be working well": no crash, no
> transport regression, cross-core `KEY` audible and correct. `KEY GAIN` and
> `SC LISTEN`/`MON` are unchanged from what's described below. The build to
> flash going forward is `out/OCTATRACK_OS1.40C_SIDECHAIN3_CROSS.syx`, not a
> plain `SIDECHAIN3` (that name no longer gets built — `build_sidechain3.py`
> itself now produces the CROSS output, since the value semantics genuinely
> changed). The rest of this section is the historical trail that reached
> the *single-core* feature-complete state (Session 55–65) — still useful
> for the register-discipline / transport-safety history, superseded on the
> filter design and the `KEY` range.

`SIDECHAIN3` **donates SPATIALIZER** for DSP code space and removes it from the
FX1/FX2 choosers; a legacy project using SPATIALIZER shows "SPAT" and passes
audio through.

1. On a track with a **COMPRESSOR**, page 2 now has **`KEY`** (after the `RMS`
   gap), then `KFLT`, `KGN`, `MON`. `KEY` = `OFF` / `T1..T4` or `T5..T8` for that
   track's DSP core.
2. Trigger the key track and the compressor track together → the compressor
   ducks in time with the key, even when the key track is muted. **Confirmed
   working 2026-09-14** — needs page-1 threshold/ratio/attack/release tuned by
   ear first (the compressor's own gain-computation chain is untouched by any
   of this project's fixes).
3. `KEY = OFF` → the compressor keys off its own input (stock).
4. **`KFLT` (LP/OFF/HP 2-pole SVF) — damping changed `q=1` -> `q=2` 2026-09-15,
   NOT YET HARDWARE-TESTED.** `KFLT` sits BEFORE the compressor's own
   detector, so this filter shapes both SC LISTEN's audio AND the signal that
   actually drives gain reduction. `q=1` (the prior value) is proven
   UNDERdamped — complex/resonant poles at the upper end of the cutoff
   range — confirmed both by a hardware report (audible ringing on a kick,
   tracking KFLT position, worse away from OFF) and independently by solving
   this loop's own characteristic equation. `q=2` is proven to give REAL
   (non-oscillatory) poles for **every one of the 32 FTAB entries**, not just
   spot-checked ones (NOTES.md Session 65 has the full derivation and the
   worst-case margin). Should now roll off cleanly in whichever direction,
   at the existing slope, with **no resonant peak/ring anywhere in its
   range** — that is the specific thing to listen for on this flash. `KGN`
   (±24 dB into the detector) unaffected, still sounds noticeably better as
   of the Session 55 dirty-state fix.
5. **`MON` (SC LISTEN, monitor the processed key) — transport-safe as of
   2026-09-15 (Sessions 59/61).** No ringing at `KFLT` `OFF` was already
   hardware-confirmed (Session 63) before the q=2 change above; that
   confirmation stands (OFF bypasses KEY FLT entirely, untouched by this
   fix). What's newly at stake on this flash is whether KFLT itself, now
   non-resonant by construction, actually sounds clean through its full
   range — Session 63's "it's just normal filter resonance" verdict was
   correct about the CAUSE but overturned on functional grounds (a resonant
   sidechain key source is a real defect, not just an audition quirk); this
   flash is the fix for that, not a re-confirmation of something already closed.

The sequencer-transport regression this build caused on its first two flashes
(PLAY not starting playback, cycling step LEDs instead) is fixed and
**hardware-confirmed healthy** as of the 2026-09-15 flash — two independent
causes, a register-clobber bug (Session 59) and an uninitialized-Y-memory-slot
hazard in the `moncommit` hook (Session 61). Not touched by the q=2 change
(same `moncommit`/`scdet` register discipline, one extra `sub` inside KEY
FLT's own loop only) — no reason to expect a transport regression from this
flash, but confirm PLAY is healthy first anyway, as always with this build.

> HW test plans: `NOTES.md` "Session 17 continued (8)" and "Session 36"; the
> full MON/KFLT investigation trail is Sessions 55/57/58/59/61/63/65 (58 is
> the dispatcher-level redesign, 59 is the register-clobber transport fix, 61
> is the uninitialized-Y-slot transport fix, 63 diagnosed the ringing as
> ordinary filter resonance — correct diagnosis, but the user overturned the
> "not a bug" conclusion on functional grounds, since this filter also feeds
> the compressor's detector — 65 is the q=2 fix making KEY FLT provably
> non-resonant everywhere in its range).
> Power-cycle after the flash before judging audio — an OS upgrade doesn't clear
> the DSP state RAM (see §6 (a-bis)).

#### 4.6b  Chooser-highlight bug — RESOLVED 2026-09-14, fixed in `build_sidechain3.py`

**Was**: only in the Effect 1 chooser, selecting COMB highlighted COMPRESSOR (the
entry below); selecting COMPRESSOR highlighted LOFI; selecting LOFI highlighted
nothing. No other entry affected, and confirmed NOT reproducible on stock firmware
(ruling out the earlier "copy action" theory — see NOTES.md Session 55 for that
now-superseded trail).

**Root cause (NOTES.md Session 56)**: FX1 and FX2 each have their OWN, separate
id->position table for chooser cursor placement — `0x400d60d0` (FX1) and
`0x400d6150` (FX2, what the build scripts call `ID2POS`) — sitting back to back in
ColdFire data with byte-identical stock values, which is exactly why this was missed
the first time (Session 55 rebuilt only `0x400d6150` when removing SPATIALIZER from
the choosers). FX1's copy was left stale, one position too high for every id past
SPATIALIZER's old slot — matching the symptom exactly, including the total breakdown
at LOFI (whose stale position, 10, doesn't exist in FX1's new 10-entry list at all).

**Fixed**: `build_sidechain2.py`/`build_sidechain3.py` now rebuild both tables
identically. Rebuilt, independently re-verified by reading both tables back out of
the finished binary. **NOT yet reflashed** — flash the current
`out/OCTATRACK_OS1.40C_SIDECHAIN3.syx` and confirm COMB/COMPRESSOR/LOFI all
highlight correctly in the FX1 chooser now.

### 4.7  RELOAD FROM PROJECT  (`build_reload.py` / `build_reload2.py` — emulator only, never flashed)

> Two images. `build_reload2.py` (the SEQ-focused one) = a 3-item picker
> **`TRK SEQ`** / **`PTN SEQ`** / **`PART + PTN SEQ`**, window opens on `TRK SEQ`.
> `build_reload.py` = a 3-item picker **`PTN SEQ`** / **`ALL PARTS`** (all 4
> Parts, stock RELOAD PART x4) / **`PARTS + PTN SEQ`**.  For `build_reload.py`
> substitute `ALL PARTS` where a step below says `TRK SEQ`, and `PARTS + PTN SEQ`
> where it says `PART + PTN SEQ`.  Check the `PART + PTN SEQ` label isn't clipped.
>
> **Session 44 HW checks (both builds):** does holding `[PTN]` ~0.5 s feel right,
> and does a quick tap still open SELECT PATTERN?  Do the arrow keys — and a
> `[TRACK]` key press — reach the picker while the `FUN_4005a0e0` popup is up (if
> not, the fallback is a hook in the event dispatcher `FUN_40061b60`)?

**Hold `[PTN]` ~0.5 s** (while the sequencer is **playing**) opens a picker
**window** — the OS's own hold event, the same one `[PAGE]`-hold uses.
`build_reload2.py`:

    TRK SEQ        -- sequence data of the ONE currently-addressed track (audio
                      track on the audio pages, MIDI track on the MIDI pages):
                      trigs, recorder trigs, trigless trigs/locks, swing/slide,
                      micro-timing, trig conditions, its step count.  Nothing else.
    PTN SEQ        -- the whole active pattern's sequence data.  The pattern's
                      Part ASSIGNMENT is preserved.
    PART + PTN SEQ -- PTN SEQ including the Part link, then that saved Part is
                      applied to the engine (FUN_40009094).

A quick `[PTN]` tap is unchanged (SELECT PATTERN). The window is a **sticky menu
with no timeout** — the **arrow keys** move the highlight; `[YES]` executes it
and closes the window; `[NO]` closes it and runs nothing. While it is open
`[YES]`/`[NO]` do only picker things. All reloads are from the CF card's last
**SAVE BANK** snapshot and do **not** stop playback: the SEQ work rides the
storage task and re-homes through the sequencer's own no-stop reload path.

Setup: a project on the card with **at least one SAVE BANK** done. Pick a bank,
**SAVE BANK** it, then note pattern N's trigs + a Part's filter/level.

1. Play pattern N. On **track 3** edit some trigs / a p-lock. On **track 5** edit
   different trigs. Do **not** SAVE BANK again.
2. Select **track 3**.  Hold `[PTN]` ~0.5 s -> window opens on **`TRK SEQ`**.
   Release `[PTN]` -- the window stays; the SELECT PATTERN chooser must **not**
   pop on release.  A *quick* `[PTN]` tap must still open SELECT PATTERN.
3. `[YES]` -> within ~1 s **track 3** reverts, **no audible gap**; **track 5's
   edits are still there**; toast reads `T3 SEQ`; window closes.
4. Repeat on a **MIDI** track (be on the MIDI pages) -> toast reads `MT<n> SEQ`;
   only that MIDI track reverts.
5. Re-edit.  Hold `[PTN]`, **arrow** to **`PTN SEQ`**, `[YES]` -> the whole
   pattern's sequence reverts; any Part you tweaked is untouched.
6. **Re-assign** pattern N to a different Part.  Hold `[PTN]`, arrow to
   **`PART + PTN SEQ`**, `[YES]` -> the pattern comes back on its **saved** Part.
7. Switch to a **different pattern** you also edited -- its edits must still be
   there (only the pattern/track you reloaded reverts).
8. On a bank **never** SAVE BANK'd, any item shows the stock **"THIS BANK HAS
   NEVER BEEN SAVED! NOTHING TO RELOAD!"** dialog.
9. Open the window and leave it -- it **stays open** (no timeout); `[NO]` closes.
10. Sequencer **stopped** -> holding `[PTN]` does nothing extra.

> **If it misbehaves:** the risk is a storage-task hang (a save/load or the
> reload appears to freeze).  Power-cycle -- it recovers.  Reflash stock 1.40C
> (§5) to fully revert.  The worker writes only pattern N's live slab (`TRK SEQ`:
> only one track's region within it), never disk.
> emu-validated: `emu_reload.py` / `emu_reload2.py` `--combo` (the modal picker),
> `--patched` (the whole-pattern SEQ worker end to end), `--trk` (the per-track
> slice touches nothing else).  Not exercised on real hardware: whether an arrow
> or `[TRACK]` key reaches the picker while the popup is up (fallback: a hook in
> `FUN_40061b60`); `FUN_4008cebc` vs a real card; `FUN_40009094` from the storage
> task while playing (part LED/name refresh); the SEQ discard loop for pattern
> > 0; timing.  Details: `NOTES.md` "Session 42"–"44" + "Session 47".

### 4.8  Bug 2 — pattern with only p-locks reads as empty  (`build_pattern_led.py` — hardware-confirmed, MKI 2026-09-13)

Fixes: a pattern whose only content is p-locks — MIDI-track p-locks, or an
audio trigless lock — used to show its `[PTN]` grid LED unlit ("no pattern
present"), even though real sequence data is there. Root cause: the stock
"does this pattern have content" check scans trig bitmasks but never the
p-lock arrays. Version stays `1.40C` — stock-transparent, always on, no
PERSONALIZE entry.

1. On a pattern with **no trigs anywhere**, put a **p-lock on a MIDI track**
   step (lock a CC/note param with no note trig present) — or on an **audio
   track**, arm a **trigless lock** (a lock with no trig).
2. Look at the pattern grid under `[PTN]`.
   - **Stock (bug):** that pattern's LED is unlit — looks empty.
   - **Fixed:** the LED lights, same as any pattern with real content.
3. Regression: a genuinely empty pattern still shows unlit; a pattern with a
   normal trig still lights normally.

> **Hardware-confirmed (MKI, 2026-09-13):** flashed and working as expected.
>
> Emulator evidence: `emu_pattern_led.py --patched`, full-firmware emulator
> against the factory OT DEMO — MIDI-p-lock-only and audio-trigless-lock-only
> patterns both flip 0→1, an empty pattern stays 0 (no false positive), normal
> trig patterns unaffected. `NOTES.md` "Session 48".

### 4.9  Part params carry over after a pattern→Part change  (`build_partreapply.py` — report #1 FIXED, hardware-confirmed MKI 2026-09-22; one open regression candidate, see below)

Was scoped from three Elektronauts reports for a pattern change that also
switches to a different Part: (1) a track that was **PICKUP** on the old Part
keeps playing its old pickup loop instead of the new Part's **FLEX** sample;
(2) the **recorder** page's SRC/RLEN carries over from the old Part; (3) a REC
SETUP knob tweak on one Part leaks into another Part that never had that
tweak. Version stays `1.40C` — no PERSONALIZE entry, always on.

**Hardware findings (MKI, 2026-09-13 — read this before testing further):**

- **Reports #2 and #3 could not be reliably reproduced on stock.** #2 didn't
  reproduce at all; #3 reproduced once, then stopped manifesting after some
  save action, and no displayed-parameter discrepancy shows on either stock
  or the patched build. Treat those two as **unconfirmed** — the emulator
  evidence for them (below) proves a code-level mechanism exists, not that
  it's what real users actually hit.
- **Report #1 is FIXED and hardware-confirmed (MKI, 2026-09-22).** The 4-pass
  round trip below now plays the new Part's FLEX sample on every pass.
  Precise repro: track 1 = **PICKUP** on Part A (silent), **FLEX** + a
  different sample on Part B. Pattern-A → pattern-B: plays the *correct*
  FLEX sample. Back to pattern-A: fine. Pattern-A → pattern-B **again**:
  **wrong** — track 1 now plays Part A's old PICKUP content under the FLEX
  machine, and stays wrong on every later pass (a one-way latch).
  Root cause: the voice dispatch reads the sample **slot** it hands the
  resolver from a per-track pre-image at `0x8000082f + track*0x48`, byte 0.
  Stock seeds that byte from the Part only when a track **enters** PICKUP
  (`FUN_40001f18`, called from `FUN_400972fc`) and **never when it leaves**,
  so the PICKUP slot `128+track` survives into the new FLEX machine and the
  resolver binds the PICKUP sample faithfully. Pass 1 is clean only because
  the field is still 0; the return to PICKUP sets it, and nothing ever
  clears it — hence the latch. FLEX is affected and STATIC is not because
  FLEX and PICKUP share one arena and one table, differing only in slot.
  **The 2026-09-13 flashed build did not fix this**: stock's own
  entering-PICKUP arm does the kill bit *and* the re-seed together
  (`0x400973b4`-`0x400973e0`), and that build replicated only the kill bit.
  The current source adds the missing re-seed. Full write-up: `NOTES.md`
  "Session 81".

**The build on the unit right now (flashed 2026-09-13) predates the fix** and
is behaviorally identical to stock for report #1 — don't expect the version
you may already have flashed to fix the PICKUP→FLEX symptom. Rebuild from
the current source to get it.

1. Set up 2 patterns linked to 2 different Parts. Track 1: Part A = **PICKUP**
   (not currently playing), Part B = **FLEX** with a sample loaded, STARTS
   SILENT off.
2. Switch pattern A → B → A → B again (a 4-step round trip, not a single
   switch) and trig track 1 after each arrival at B.
   - Stock and the 2026-09-13 build: the **first** A→B is correct; the
     **second** A→B plays Part A's old PICKUP content instead of Part B's
     FLEX sample, and so does every pass after it.
   - **A build from the current source plays Part B's FLEX sample on every
     pass, including the second and later — confirmed on MKI, 2026-09-22.**
3. Reports #2/#3: try the recorder SRC/RLEN and REC SETUP scenarios from the
   original write-up, but don't assume a discrepancy is present — it wasn't
   reproducible in this session's testing.
4. **Open regression candidate (2026-09-22):** after P1→P2→P1, check whether
   Part 1 reads as *edited/unsaved* in the PART menu even though nothing
   changed it. This was seen on the 2026-09-22 build. It is NOT yet known
   whether stock does the same — the entering-PICKUP path is stock's own —
   so if you have a stock or pre-2026-09-22 image handy, run the same round
   trip on it before assuming this build introduced it.

> Emulator evidence: `emu_partswitch.py --repro` vs `--repro --patched` shows
> a clean stock-vs-patched A/B for the recorder-cache / `TRK_PART` / scene /
> morph-guard mechanisms (all flip from "stale" to "correct" only on the
> patched image) — but that A/B does not capture the actual audible bug in
> step 2 above, which needs the repeated round trip and, ultimately, real
> hardware to observe. `NOTES.md` "Session 49", "Session 49 — HANDOFF", and
> "Session 50" (the hardware pass that found this).

### 4.10  QUANTIZE LIVE REC front-panel toggle  (`build_qlrec.py` — hardware-confirmed, MKI 2026-09-13; two cosmetic issues parked)

> **History: the original (Session 46) design HUNG the unit** when flashed —
> a one-shot "persistent" (`dur=0`) toast that never closed, freezing the
> whole panel while the sequencer kept running (recovered cleanly with a
> power-cycle). Root cause, confirmed by real disassembly (`NOTES.md`
> "Session 50"): `dur<=0` registers the notification on a modal window stack
> that the OS's key dispatch almost certainly routes all input to. **The
> Session 50 rewrite** (a periodically re-armed `dur>0`, self-timing call
> instead of one persistent `dur<=0` call) was flashed and confirmed not to
> hang. Six real-use refinements followed (Session 51); one of those
> (double-tap timing) needed two more RE passes (Session 51-bis/-ter) after a
> real logic bug (`G_PEND`) and a wrong-direction tuning guess (`MAX_GAP`)
> were found and corrected. **All of that is now HW-confirmed working**:
> pairing-window timing, toast fade/instant-close, and the ON/OFF label
> polarity. Two purely cosmetic issues are parked, not chased further: a
> rare self-clearing textless-box flash after the toast closes, and the
> PERSONALIZE menu not live-redrawing the row you're already looking at
> (the stored value itself is always correct).

A Digitone-style front-panel toggle for the PERSONALIZE **QUANTIZE LIVE REC**
row (the all-or-nothing live-record quantize — not the per-track TRIG QUANT):
hold **[REC]**, tap **[PLAY]** twice, close together.

1. Hold **[REC]**, tap **[PLAY]** — starts live rec as normal (stock,
   unchanged).
2. Still holding **[REC]**, tap **[PLAY]** again **fairly quickly** — a toast
   reads **"QUANT LIVE REC ON"** (or **OFF**) and the PERSONALIZE value flips;
   the transport is untouched (no live-rec start/stop from this tap). The
   label matches what **PROJECT → PERSONALIZE → QUANTIZE LIVE REC** shows
   checked/unchecked.
3. Double-tap pairing window (`MAX_GAP = 0x10`): a too-slow 2nd tap is
   discarded (no flip) and starts a fresh pairing attempt; a fast pair flips
   on the 2nd tap; a fast 3rd tap right after a successful pair does NOT
   fire again. **HW-confirmed correct.**
4. The toast shows while `[REC]` is held (periodically refreshed
   underneath, no visible flicker) and closes instantly the moment you
   release `[REC]`. **HW-confirmed correct.**
5. Known, parked, cosmetic-only: an occasional small textless square flash
   right after a toast closes (self-clears); the PERSONALIZE row not
   visually updating while you're looking directly at it (re-opening the
   menu always shows the correct value). Neither affects the stored value or
   panel responsiveness — not being chased further unless it starts to
   matter.
6. A 3rd/4th fast `[PLAY]` pair while still holding `[REC]` toggles again
   (cycles on/off/on); releasing `[REC]` always clears the internal state.
7. The PERSONALIZE value survives a power cycle.
8. The panel stays fully responsive throughout, including while the toast is
   showing and right after it closes.

> Emulator evidence: `emu_qlrec.py --patched` — isolation, ALL GOOD including
> the pairing-window logic (fast pair flips, slow pair discards-and-resets,
> `G_PEND` regression coverage, instant-close-on-release, correct label).
> `tools/emu_notify_probe.py` — full-firmware, real function bodies: `dur=0`
> reaches the modal-insert function that caused the original hang;
> `dur=REARM_DUR` (what this build actually uses) and DIRECT JUMP v3's
> known-safe `0x44` both do not. `NOTES.md` "Session 46" (original design),
> "Session 50" (the hang, root cause, rewrite), "Session 51/51-bis/51-ter"
> (refinement, `G_PEND` bug fix, `MAX_GAP` correction). **Hardware-confirmed
> in full** except the two parked cosmetic items above.

### 4.11  Auto-remove an emptied trigless lock  (`build_triglock.py` — **HARDWARE-CONFIRMED, FINAL** — MKI, 2026-09-21)

> **Three earlier TRIGLOCK builds were aimed at the wrong code entirely** and did nothing.
> If any of them is on the unit, flash stock `1.40C` first
> (`downloads/extracted/OCTATRACK_OS1.40C.syx`). The very first one is also unsafe to
> leave on (it could write into arbitrary RAM); the later two were merely inert.

Fixes: a **trigless lock** (a step holding only parameter locks, no audible trig) whose
**last remaining lock is erased** stays lit on the trig row forever.

**How the target was found.** Static analysis put this thread on the `0x40041xxx` /
`0x40062xxx` p-lock cluster for ~50 sessions. A diagnostic firmware that logs into the
bank blob — which a project save serialises to the card, so the trace exports back —
showed that **none of that cluster runs during the gesture**. The real path, measured:

    opcode 8 -> case 0x40061ed4 -> FUN_40041af4 -> FUN_40038874   (audio)

`FUN_40041af4` has no `linkw`, which is why every function-boundary scan missed it.

**Root cause.** `FUN_40038874` *already* scans `#1[step][0..31]` to decide whether a step's
p-lock row has gone empty, and uses that to clear the track's bit from the per-step
bitmap. It simply never also clears the trig-type-layer flag `TRAC+0x10`, which is what
keeps the LED lit.

**The patch** detours `0x40038af2` (6 B). Reaching that instruction *is* stock's own
verdict that the row is empty — the "still has locks" case branches away at `0x40038ad8`
— so the cave holds **no predicate of its own**, and multi-pass behaviour is inherited
rather than reimplemented. It clears `TRAC+0x10`, its `0x1001615e` mirror, and the dirty
flags, guarded so a step owned by any real trig (note/sample, layers A/C, the three
recorder masks) is never touched.

**Emulator validation** — `python3 tools/emu_triglock.py`, driving `FUN_40038874` on the
real `ARTLTEST1` export, stock vs patched:

| check | result |
|---|---|
| erase 1 of 2 — stock keeps the step lit | PASS |
| erase 1 of 2 — **patch also keeps it lit** (multi-pass intact) | PASS |
| erase the last — stock leaves the flag set (**reproduces the hardware bug**) | PASS |
| erase the last — **patch clears the flag** | PASS |
| no other trig layer disturbed | PASS |
| `#1` byte-for-byte identical to stock | PASS |

Unlike the three earlier builds, this run drives the function a hardware trace implicated,
and the stock half reproduces the reported symptom — so the comparison is meaningful
rather than a restatement of an assumption.

**Known limitation**: `[NO]`+knob aimed at a param of an already-empty, deliberately
placed trigless lock removes it. Stock's scan finds the row empty either way and the
pre-erase byte is gone by this point; fixing it needs a second detour inside the param
loop.

**Gesture test after flashing** — bank 1 / pattern 1 / track 1, step 7:

1. Trigless lock with two locks on the PLAYBACK page: PTCH and LEN.
2. Erase **one** → the step must **stay lit**.
3. Erase the **second** → the step must go **dark** and be inert.
4. Regression: ordinary trig with p-locks, erase every lock → the **trig must remain**.
5. Regression: an empty trigless lock placed deliberately must survive a pattern switch
   and a reload (but see the limitation above — do not aim `[NO]`+knob at it).

**Revert**: flash `downloads/extracted/OCTATRACK_OS1.40C.syx`.

## 5. Reverting to the official firmware

Reflash the official one following the **same steps in §3**, sending
`downloads/extracted/OCTATRACK_OS1.40C.syx`. Your CF card and projects are not
affected. Nothing the mods store persists a revert except the PERSONALIZE /
`'ANDY'` block, which an EMPTY RESET clears.

---

## 6. If flashing fails, or the flashed OS misbehaves

**First, always: get back to a known-good OS** — the §1 recovery path works even
from a black/"Z" screen. Then work out what happened.

### (a) The transfer / flash never completed

Symptoms: SysEx Librarian errors or stalls; the TRIG lights stop advancing;
"PREPARING FLASH" never appears; the CF `.bin` path reports `-2` (not a valid OS),
`-3` (length) or `-4` (checksum).

This is almost never the patch — it's the transport. The Kyoti builds differ from
stock by tens to ~1500 bytes and repack through the same checksummed container as
the official file.

- **MIDI:** lower SysEx Librarian's send speed. Use a real 5-pin DIN interface.
  Try another interface/cable.
- **CF card:** re-copy the `.bin` to the card **root**, **eject properly** (a
  cached/truncated write is the usual `-4`), re-seat the card.
- Re-verify the artifact: `elektron-firmware-tool -i <file>.syx` must print
  `checksums : ok`; for the `.bin`, `python3 tools/bin_decode.py <file>.bin` must
  print `✓ COINCIDE`. If either fails, rebuild it.

### (a-bis) It boots, but audio is garbled — **power-cycle first**

An OS upgrade rewrites program memory but does **not** clear the DSP state RAM. An
engine whose warm-up tag is still valid runs on the previous firmware's buffer
contents, so audio can be garbled right after `UPDATING FLASH` — worst on the
delay/reverb. **Turn the unit fully off and on before judging anything.** (Source:
`refs/octabam/docs/FAILURE_MODES.md`.)

### (b) It flashed and finished "UPDATING FLASH", but the OS won't boot / traps / hangs

Now the patched code is suspect. Isolate it:

1. Flash **`build_trigscale_only.py`** (Bug-1 fix on stock). If that boots fine,
   the fault is in the mod you flashed, not the fix. Report which build.
2. If the fix-only build **also** fails to boot → the fix itself is the problem on
   real silicon (it passed the ColdFire emulator, which is not a perfect model).
   Revert to stock and report — this needs a code change, not a reflash.
3. Either way you are never stuck: the §1 rescue path always brings the unit back.

### (c) It boots and runs, but a feature doesn't work

- **Did the flash take?** OS VERSION should read `140C_KYOTI` (fix-only build:
  still `1.40C`, so test by behaviour). PERSONALIZE is reset by every flash — the
  mods are off until you re-enable them.
- **Re-run the exact test** from §4 for that feature.
- **A regression** (something that worked on stock now misbehaves): note the exact
  steps and whether it also happens on the fix-only build. Fix-only-clean points
  at the mod; both-broken points at the Bug-1 fix.

### For a future debugging session (hand this to Claude)

If the MIDI-trig fix is implicated on hardware (case (b).2 or a (c) regression
tied to it):

- The whole fix is `tools/patch_trigscale.s`: an 18-byte detour at `0x4009b6f2`
  (`jmp 0x400d7b00` + 6× `nop`) into a 62-byte cave at `0x400d7b00`. Nothing else.
- Re-check on real-hardware assumptions (not just Unicorn):
  1. **Cave liveness** — the cave clobbers `D0`, `A0`, and (MIDI arm only) `D6`.
     `D0`/`A0` are scratch on both original paths. `D6` was argued dead past
     `0x4009b6d6`; re-verify against the full `FUN_4009b5c8` disasm
     (`out/ghidra/GhidraResolve38_session5.txt`). If `D6` is live, push/pop it
     around the multiply.
  2. **The orphaned bytes** `0x4009b6f8..0x4009b703`. Argued unreachable; if a
     path can reach them, NOP-fill all 18.
  3. **Cave executability** — `0x400d7b00` is inside the same
     `0x400d64da..0x400d7c3c` zero cave that other shipped detours run from.
  4. **ISA** — assembled `-mcpu=5407` (ColdFire V4e), same as every other stub.
  5. **Bisect** — a variant whose cave is just `jmp 0x4009b704` tests the
     trampoline alone, then add the audio arm, then the MIDI arm.
- Harness: `tools/emu_trigbug.py`; `tools/build_trigscale_only.py` rebuilds it.
- Full reasoning: `NOTES.md` "Session 5 part 3" and "Session 6".

---

## Risk notes (honest)

- This firmware is **modified by you, for your own unit, for study purposes.** It
  is not official Elektron firmware and has no support from them.
- Most patches are **validated in a ColdFire emulator** (Unicorn, real image
  bytes) — control flow and DSP frame-word edits, not the audio engine. The
  side-chain DSP runs in dsp56kEmu. **Only the Bug-1 fix and the `OT+FX` soft-mute
  mechanism have run on hardware.** Treat emulator-green as necessary, not
  sufficient, and go in with the recovery net ready (§1, §6).
- The only truly delicate moment is **"UPDATING FLASH"**: don't cut power there.
- Residual risk of a *hard* (unrecoverable) brick: very low — the rescue
  bootloader is not touched in a normal OS update.

---

### Quick file reference

Every Kyoti build lands in `out/` as four files:

```
mainos_*.bin                      the patched MAIN OS section
elek_*.bin                        the rebuilt ELEK container
OCTATRACK_OS1.40C_*.syx           MIDI-DIN upgrade transport
OCTATRACK_*.bin                   CF-card OS UPGRADE transport (faster)
```

| build command | version | contents |
|---|---|---|
| `python3 tools/build_trigscale_only.py` | `1.40C` | Bug-1 fix only, on otherwise-stock 1.40C |
| `python3 tools/build_mutemode.py` | `140C_KYOTI` | Bug-1 fix + MUTE MODE `OT` / `OT+FX` |
| `python3 tools/build_mutemode_dt.py` | `140C_KYOTI` | + the third mode `DT` |
| `python3 tools/build_softmute.py` | `140C_KYOTI` | Bug-1 fix + soft mute **always on**, no menu |
| `python3 tools/build_directjump.py` | `140C_KYOTI` | Bug-1 fix + DIRECT JUMP (`[PTN]`+`[YES]`) |
| `python3 tools/build_directjump_v2.py` | `140C_KYOTI` | DIRECT JUMP with the box-free toast overlay |
| `python3 tools/build_sidechain.py` | `140C_KYOTI` | Bug-1 fix + the COMPRESSOR `KEY` menu param (DSP inert) |
| `python3 tools/build_sidechain2.py` | `140C_KYOTI` | + the side-chain DSP hooks (SPATIALIZER donated) |
| `python3 tools/build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | `140C_KYOTI` | + `KEY FLT` / `KEY GAIN` / `SC LISTEN` in the DSP, `KEY` reaching any of the 8 tracks (cross-core) — **hardware-confirmed, shipping** |
| `python3 tools/build_pattern_led.py` | `1.40C` | Bug 2 fix only: p-lock-only pattern lights the grid LED |
| `python3 tools/build_partreapply.py` | `1.40C` | fix only: Part params fully re-apply on a pattern→Part change |
| `python3 tools/build_qlrec.py` | `140C_KYOTI` | Bug-1 fix + QUANTIZE LIVE REC front-panel toggle |

| File | What it is |
|---|---|
| `downloads/extracted/OCTATRACK_OS1.40C.syx` | **Official rescue OS** — for recovery or reverting. |

Reproducible one-shot for the Bug-1 fix (no assembler needed):

```sh
python3 sysex/apply_patch.py -i <your stock .syx> \
    -p sysex/patches/playsfreefix-r1.json -o OCTATRACK_OS1.40C_PLAYSFREEFIX.syx
```

(Regenerate the JSON from a fresh build with `sysex/gen_patch_json.py`.)
