# Safe flashing guide — OT Kyoti FW

How to flash an OT Kyoti FW image onto your Octatrack, with a full safety net.

> **The behaviour changes are OFF by default.** Straight after flashing, the unit
> behaves like stock firmware apart from the always-on bug fixes. MUTE MODE and
> QUANTIZE LIVE REC live in PERSONALIZE (QUANTIZE LIVE REC also gets a front-panel
> shortcut); DIRECT JUMP is a front-panel chord and comes up OFF on every power-on.
> RELOAD FROM PROJECT adds two chords that do nothing until you press them. The
> three bug fixes — the MIDI Plays-Free trig stall, the p-lock-only pattern LED,
> and the Part-change carryover — are always on, since a bug fix has nothing to
> opt into.

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

### 4.2  MUTE MODE  (`build_mutemode_dt.py` — **HARDWARE-CONFIRMED, FINAL**, all four modes, MKI 2026-09-21)

> **History worth knowing before you read old notes.** For about a dozen sessions
> this feature had a hardware-only bug: a trig-attack blip on an already-muted
> track, and a DT mode that "did nothing at all". Three separate fixes (`pre_v`,
> then `mt_trig`/`mt_rebind`) each passed CPU-side emulation and each changed
> nothing on hardware. Session 55 found why with a DSP-capable emulator: the hooks
> fire correctly for a track's *first* trig, but a second trig on a track already
> muted while playing reached neither. Sessions 57–58 root-caused and closed it,
> and the SOLO path (which stock's own hard cut was running unopposed) with it.
> **All four modes are now confirmed on hardware.** `build_mutemode.py` is the
> older two-value `OT` / `OT+FX` build, kept for comparison — do not flash it
> expecting the four-mode menu.

1. **PROJECT → PERSONALIZE**, scroll to **MUTE MODE**. It cycles
   **`OT` / `OTFX` / `OTFX-T` / `DT-T`**, in that order, default **`OT`**. The
   15/16 stock entries above must still show their own values. The menu index is
   *derived* from the one persisted word, so the menu and the running firmware
   cannot disagree.
2. Put a **delay or reverb** insert on an audio track, obvious tail. Play it, then
   **FUNC + [that track's key]** (also try the MIXER menu / QUICK MUTE — same code
   path):
   - **`OT`** — dead silence instantly, dry *and* FX tail. Byte-for-byte stock.
   - **`OTFX`** — the dry cuts fast and clean, the FX insert **rings its tail**,
     and the **sequencer is left alone**: trigs keep firing and voices keep
     restarting underneath, so unmuting picks up exactly where the pattern would
     have been. No attack blip.
   - **`OTFX-T`** — the same dry cut and ringing tail, but a **trig-mute**: new
     trigs stay suppressed until you unmute.
   - **`DT-T`** — pure sequencer mute, Digitakt-style: a sounding voice rides out
     its **own AMP envelope** and its FX ring, and only *new* trigs are suppressed.
3. **The specific thing that used to be broken:** in `OTFX-T` and `DT-T`, a new
   sequencer trig on a track that is **already muted while playing** must produce
   **no sound at all** — not even a blip. This is the case three earlier builds
   failed.
4. **SOLO follows the selected mode.** With a delay/reverb on two tracks, solo one:
   in `OTFX`/`OTFX-T`/`DT-T` the non-soloed tracks get the same treatment as a
   manual mute (dry stops, FX rings); in `OT` solo is the stock instant cut.
   Soloing a track that is already muted plays it (solo overrides mute).
5. **`CUE MUTES TRK` intentionally stays a hard cut in every mode** — that
   PERSONALIZE option ORs the cue bits in after this project's hook runs, and is
   left untouched by design. Not a bug.
6. **Persistence:** power-cycle — MUTE MODE stays where you left it (one word in
   the `'ANDY'` battery-SRAM shadow). An EMPTY RESET clears it to factory.
7. Regression: the manual-trig fix still works; other tracks unaffected.

### 4.3  DIRECT JUMP  (`build_directjump_v4.py` — **hardware-confirmed at 1x scales**, MKI 2026-09-23; non-1x scales are a known open problem)
> **⚠️ Read this before flashing.** The **1x** behaviour below is hardware-confirmed
> (2026-09-23). **Non-1x track and master scales were broken, were root-caused and
> fixed on 2026-09-24, and that fix has NOT been on hardware** — Hook P was reading
> the master step once and using it as every track's step index, which is only
> correct when master and track share a ticks-per-step. The fix is bit-identical to
> the confirmed build at 1x, so flashing it should not risk the baseline, but the
> non-1x behaviour itself is unverified: **treat §4.3 step 10 as the thing to test.**
>
> **Also still open, and NOT explained by that fix:** a report that which steps get
> visited depends on what trigs are on the grid, and that the LEDs and the audio
> disagree about the position. No measured write path reads trig data, so this is a
> separate mechanism. If you see it, it is a known unknown, not a new regression.
>
> **`v1`–`v3` are dead on hardware and must not be reflashed.** Holding `[PTN]`
> pushes a stock UI overlay whose `[YES]` record has a NULL press handler, which
> overwrites the runtime dispatch slot for as long as `[PTN]` is held — so their
> detour on the stock `[YES]` handler (`0x4005e4c8`) was genuinely unreachable.
> `v4` writes `dj_toggle` straight into that overlay's own `[YES]` record instead.
> Two other hardware faults were found and fixed along the way: a **lockup at
> transport start** (a hook gated on a global living beyond the boot zero-fill, so
> garbage at power-on) and **doubled trigs** (writing a per-track "previous step"
> array that stock's commit tail deliberately leaves alone).

1. Hold **[PTN]** and tap **[YES]** → a transient **"DIRECT JUMP ON"** overlay
   (~0.7 s), then **OFF** on the next chord. The SELECT PATTERN chooser must not
   pop on the `[PTN]` release.
2. **It does not persist.** Power-cycle → DIRECT JUMP is **OFF** again. That is
   deliberate: it is a performance toggle.
3. With DIRECT JUMP **ON**, play a pattern and manually cue another (different
   Part): it switches on the **next step tick**, loads the new Part at once, and a
   MIDI Program Change goes out ~1 step early.
4. **The behaviour to verify, all at 1x:**
   - tracks and patterns stay in **master time** through the switch — check
     against the metronome, it must not drift or re-anchor to your keypress;
   - the new pattern lands on the **correct step**;
   - **mixed track lengths** in one pattern work together — try 7, 12 and 16;
   - **MASTER LENGTH is respected**, including **`INF`**;
   - existing trigs sound **once**, not doubled.
5. The **arranger** and **pattern chains** must be unchanged (DIRECT JUMP bails
   when the arranger is running or a chain is active).
6. Turn it **OFF** → manual pattern changes are stock again (end-of-pattern
   quantised, restart at step 1).
7. **[PTN] tapped alone** (no `[YES]`) still opens SELECT PATTERN normally.
8. **Non-1x scales — the unverified part.** Set a **track scale** to something
   other than 1x (say 2x on one track, 1x on the rest) and repeat step 4; then set
   the **master scale** to 2x and repeat again. Each track must land on its own
   correct step and stay in master time, exactly as the 1x case does. This is the
   2026-09-24 fix and it has never been heard on hardware.
9. Watch for the open report while you are there: do the **LEDs and the audio agree**
   about where the playhead is, and does changing *which trigs are on the grid* change
   which steps get visited? Both would be the unexplained issue in the callout above.

> Still not validated: the non-1x fix on hardware (above), two patterns with
> differing MASTER LENGTHs (no fixture), and per-track sub-step phase at a mid-cycle
> commit. Detail: `NOTES.md` "Session 60"–"Session 88".

### 4.4  Side-chain compressor  (`build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` — **HARDWARE-CONFIRMED, FINAL**, MKI 2026-09-20, single-core and cross-core both)

> **What this section used to be.** It carried a long historical trail — a 2-pole
> Chamberlin SVF with a `q=1` vs `q=2` damping question, a SPATIALIZER donor, an
> FX1 chooser-highlight bug, and a `SIDECHAIN3` image name. All four are obsolete:
> the filter was redesigned as a **one-pole** (a single real pole cannot resonate,
> so the damping question is moot), the donor is now **SPRING REVERB**, the chooser
> bug is fixed, and the only image built is `OCTATRACK_SIDECHAIN3_CROSS`. The trail
> lives in `NOTES.md` "Session 17" (+1–8) → "Session 77" (×3).

Adds four parameters to the **COMPRESSOR** effect's **page 2**, next to `RMS`:

    KEY     OFF / T1..T8 -- which track drives the compression. Any of the 8,
                            flat, not just this track's own DSP-core siblings.
    KFLT    one-pole filter on the key signal: below centre = LP, above = HP,
            centre = off. Sits BEFORE the detector, so it shapes both what MON
            auditions and what actually drives gain reduction.
    KGN     key trim into the detector, declick-smoothed, bipolar, centre = unity.
    MON     audition the filtered key signal instead of the track.

**What it costs:** **SPRING REVERB** is removed from the **FX2** chooser (15 → 14
entries) to donate its DSP code space, and its descriptor is null-stubbed so an
older project that still references it by id stays safe. **SPATIALIZER is
untouched** and remains a normal selectable effect.

1. **Boot check** — the FX2 chooser has **14** entries and no SPRING REVERB; the
   **FX1** chooser is untouched. SPATIALIZER is present and selectable in both.
   Every other effect must highlight **the effect you actually picked** (an earlier
   build had FX1's id→position table one slot out past the removed effect).
2. Put a **kick on T1**, and a **pad + COMPRESSOR on T2**. On T2's FX page 2 set
   **`KEY = T1`** → the pad **ducks on every kick**. Sweep `THRS`/`RAT` to confirm
   it is the compressor responding, not something else.
3. **`KEY = OFF`** → the compressor keys off its own input again (stock behaviour).
4. **Mute T1** → the pad **must keep ducking**. Keying is deliberately independent
   of the mute state.
5. **Cross-core** — the tracks are split across two DSP cores (1–4 and 5–8). Put
   the compressor on a track in **one** core and set `KEY` to a track in the
   **other** (e.g. compressor on T2, `KEY = T5`): ducking must be identical in feel
   and timing to a same-core pair. This is the part that needed a per-core
   generation counter and a shared DSP window; it is confirmed, but it is the first
   thing to re-check on any rebuild.
6. **`KFLT`** — sweep it. It should roll off cleanly in either direction with **no
   resonant peak or ring anywhere in its range**. With `KFLT` left of centre the
   compressor stops responding to the key's highs; right of centre, to its lows.
7. **`KGN`** — trim the key into the detector; more gain, more ducking. It should
   move smoothly, with no zipper noise or clicks.
8. **`MON = ON`** → you hear the filtered key signal itself. Useful for dialling
   `KFLT` by ear. Turn it back off.
9. **Regression:** the transport must be unaffected (start/stop/record), other
   effects unchanged, and no crash or audio dropout after several minutes with a
   cross-core `KEY` active.

> **Known open, deliberately left alone:** a very mild pop when `KFLT` crosses
> between **HP and OFF** — three separate hardware-tested declick designs each
> failed or regressed, so do not re-attempt without a fundamentally different
> approach (`NOTES.md` Session 76's trail). Also filed as research-only: a slight
> "graininess" at very low `ATK`/`REL` on a busy key. Neither blocks use.
>
> Not emulable, so this list is genuinely hardware-only: `dsp_host` cannot run the
> stock compressor end to end, so the *gain-reduction response* to `KEY`/`KFLT`/
> `KGN` is only ever verified by ear. The emulators verify the data transforms
> feeding it, which is a different claim.
### 4.5  RELOAD FROM PROJECT  (`build_reload3.py` — **hardware-confirmed, final**, MKI 2026-09-25)

> **The picker is gone.** RELOAD3 replaced the modal window with two direct
> chords. `build_reload2.py` (the `[BANK]`+`[YES]` 3-item picker) and
> `build_reload.py` (the original) are **superseded** and kept only for rollback —
> do not flash them. Across the whole thread the bug tally was ~13 hardware bugs in
> the picker / keymap / popup machinery and **none** in the worker that does the
> reload, which is what drove the redesign.
>
> **Final.** Flashed 2026-09-23 and 2026-09-24 (both chords execute; reloads "quick and
> on-time"), and again 2026-09-25 after the last bug was fixed: the sequence sometimes
> did not come back while the toast still said RELOADED. An on-screen diagnostic build
> (`build_reload3.py --diag`) showed the reload had read its own request -- which
> track, audio or MIDI -- from a RAM block the unit overwrites, so it reloaded a
> different (MIDI) track. The request now lives in the patch's own memory and the user
> reported every reload issue resolved. The message is drawn when the reload has
> **finished**, not when the chord is recognised, and is a stock-style block toast (a
> titled card was tried and rejected).

The two gestures, both reading from the CF card's last **SAVE BANK** snapshot,
neither stopping or disturbing the transport:

    [PTN]  + [TRACK n]   reload track n's saved sequence. The Part does not change.
                         Audio or MIDI track. Everything for that track: regular
                         and recorder trigs, trigless trigs, trigless locks and
                         their locked values, swing/slide, micro-timing, trig
                         conditions, its step count. The other 7 tracks, the
                         pattern length/scale and the pattern->Part link are left
                         alone. Toast: TRK SEQ RELOADED.

    [BANK] + [TRACK n]   the same, plus re-apply the saved Part -- from RAM, not
                         the card: the saved copy of the Part currently associated
                         with the pattern. Two-line toast: TRK SEQ + PART
                         / RELOADED.  A never-saved Part instead gets
                         TRK SEQ RELOADED / SAVE PART FIRST! -- stock's own
                         wording, and the sequence still reloaded.

Setup: a project on the card with **at least one SAVE BANK** done. Pick a bank,
**SAVE BANK** it, then note pattern N's trigs.

1. Play pattern N. On **track 3** edit some trigs / a p-lock. On **track 5** edit
   different trigs. Do **not** SAVE BANK again.
2. **`[PTN]` + `[TRACK 3]`** → track 3 reverts; **track 5's edits are still
   there**; the toast `TRK SEQ RELOADED` appears. The
   SELECT PATTERN chooser must **not** pop on the `[PTN]` release.
3. **The toast must dismiss itself** in about a second, with **no `OK` prompt
   to answer and no countdown dots**. If it sits there waiting for a keypress, that
   is the exact regression this design removed — the emulator cannot drive the
   popup tick, so this is hardware-only.
4. **The timing is the point** — during and after the reload, the track, the
   pattern and the **internal metronome** must all stay in undisturbed time. No
   restart to step 1, no metronome jump, no audible gap. This is
   a regression check; test it deliberately.
5. Repeat on a **MIDI** track → only that MIDI track reverts.
6. Try **track 1** and **track 8** specifically — the keycode→index arithmetic is
   right at both ends, but it is worth confirming on the unit.
7. **`[BANK]` + `[TRACK n]`** → the same, and the Part is restored too. The
   `[BANK]` release must **not** raise SELECT BANK after the chord.
8. **A plain `[TRACK]` tap with no modifier must still just select the track** —
   that handler is detoured, so this is the regression that matters most.
9. **A plain `[BANK]` tap** must still open SELECT BANK — now on the **release**,
   matching how `[PTN]` behaves. Tap again to dismiss. And **hold `[BANK]` + tap a
   trig** must still pick a bank, *not* edit the sequence: that overlay layer is
   pushed on the press, and breaking it is the silent failure mode this design was
   most at risk of.
10. On a bank **never** SAVE BANK'd, you get stock's own **"THIS BANK HAS NEVER
   BEEN SAVED! NOTHING TO RELOAD!"**. With a **never-saved Part**, the `[BANK]`
   chord reports that too, alongside the sequence result — the sequence still
   reloaded.
11. Reload the **same track repeatedly**, 5+ times, and confirm nothing
    accumulates — no wedged UI, no lost gesture. (The old picker's failure mode was
    "works once, then never again".)

> **If it misbehaves:** the risk is a storage-task hang (a save/load or the reload
> appears to freeze). Power-cycle — it recovers. Reflash stock 1.40C (§5) to fully
> revert. The worker writes only the live blob, never disk. Still hardware-only:
> the parse against a real CF card, and the reload's seamless-timing *feel*.
> Detail: `NOTES.md` "Session 42"–"44" + "Session 47" + "Session 80"–"Session 98";
> spec `reference/RELOAD_REDESIGN.md`.
### 4.6  Bug 2 — pattern with only p-locks reads as empty  (`build_pattern_led.py` — hardware-confirmed, MKI 2026-09-13)

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

### 4.7  Part params carry over after a pattern→Part change  (`build_partreapply.py` — report #1 FIXED and a second stock bug (spurious Part-edited flag) FIXED, both hardware-confirmed MKI 2026-09-22/23)

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
4. **Second bug, found and fixed — hardware-confirmed (MKI, 2026-09-23):** stock
   itself marks a Part edited/unsaved on a switch into a PICKUP track, even when
   nothing changed (attributed to stock's own entering-PICKUP path — measured
   identical on stock and the first patched build). Fixed with a second detour
   that snapshots the Part's edited-state bytes before the switch and restores
   them after, so a genuine edit made before the round trip is not lost. Check:
   P1→P2→P1 no longer marks Part 1 edited; a real edit made to a *different*
   Part beforehand still shows edited afterward — both confirmed on hardware.

> Emulator evidence: `emu_partswitch.py --repro` vs `--repro --patched` shows
> a clean stock-vs-patched A/B for the recorder-cache / `TRK_PART` / scene /
> morph-guard mechanisms (all flip from "stale" to "correct" only on the
> patched image) — but that A/B does not capture the actual audible bug in
> step 2 above, which needs the repeated round trip and, ultimately, real
> hardware to observe. `NOTES.md` "Session 49", "Session 49 — HANDOFF", and
> "Session 50" (the hardware pass that found this).

### 4.8  QUANTIZE LIVE REC front-panel toggle  (`build_qlrec.py` — **hardware-confirmed working**, MKI 2026-09-25; two cosmetic issues parked)

> **History: three flashes, three different failures.** Worth reading before
> touching this patch, because two of them were caused by reasoning that looked
> sound and was checked in.
>
> 1. **HUNG the unit** (Session 46 design, flashed 2026-09-13). A "persistent"
>    `dur<=0` toast that never closed, freezing the panel while the sequencer kept
>    running; a power-cycle recovered it. `dur<=0` tail-jumps into the modal
>    window/overlay stack the OS routes input to.
> 2. **CRASHED the unit** (flashed 2026-09-25): dead controls plus a loud
>    persistent HF crackle. The toast's life was being counted by a detour of
>    `0x400522ca`, called a safe "per-control-frame tick" in our own notes since
>    Session 21. It is not: that is the **engine frame handler**, and both
>    `FUN_4005a2b8` (notify) and `FUN_40056bec` (close) bottom out in
>    `FUN_40000c3c`, the **kernel post/wake**, which marks a blocked task runnable
>    and pokes the ready-list head. Legal from a key handler, not from there. ⚠️
>    **That crash was already latent in the Session 51 build this document used to
>    call "hardware-confirmed, final"** — it armed the hook only after a successful
>    double-tap, so it was rare, not absent. The detour is deleted and the build now
>    asserts `0x400522ca` stays byte-for-byte stock.
> 3. **Never flipped at all** (the rewrite after that). Its one private scratch word
>    at `0x80006a60` does not survive between key presses on the unit, while
>    persisting indefinitely in the emulator, which does not run the DSP/audio path.
>    A diagnostic build that named the failing condition **on screen**
>    (`build_qlrec_diag.py`) settled it in one flash, after static analysis and
>    emulation had both reported success.
>
> **The shipping patch keeps no state of its own.** The flip window *is* the toast,
> because both are the same thing: stock's own notification handle `0x460d1e70`.
> 176 B, two detours, zero scratch. Two cosmetic issues are parked, not chased: a
> rare self-clearing textless-box flash after the toast closes, and the PERSONALIZE
> row not live-redrawing while you are looking at it (the stored value is always
> correct).

A Digitone-style front-panel toggle for the PERSONALIZE **QUANTIZE LIVE REC**
row (the all-or-nothing live-record quantize — not the per-track TRIG QUANT):
hold **[REC]** and tap **[PLAY]**, then tap **[PLAY]** again while the toast is up.

1. Hold **[REC]**, tap **[PLAY]** — starts live rec as normal (stock, unchanged),
   and a toast shows the **current** QUANTIZE LIVE REC setting.
2. Still holding **[REC]**, tap **[PLAY]** again **while that toast is still on
   screen** — the setting inverts and the toast re-opens on the new value. Tap
   again, still within the toast, and it inverts back. The transport is untouched
   by these taps.
3. **Let the toast go (1 s) and tap again** — it only *shows* the setting, no flip.
   The window and the toast are the same object, so what you see is the gate.
4. The label must match what **PROJECT → PERSONALIZE → QUANTIZE LIVE REC** shows,
   and the toast must close instantly the moment you release **[REC]**.
5. **The gesture is deliberately not exclusive:** with no state of its own, *any*
   toast on screen arms the flip, stock's included. Stock issues no notification on
   the live-rec path, so this is rare, and when it happens the toast shows the new
   value rather than changing it silently. Accepted trade-off, asserted in the
   harness — not a bug to report.
6. **Watch for the two failures this patch has had on hardware** (§history above):
   the panel going dead or an HF crackle (the crash), and a tap that shows the toast
   but never inverts the value (the gate). Either means stop and re-read the history
   note, not retune a timing constant.
7. The PERSONALIZE value survives a power cycle.
8. The panel stays fully responsive throughout, including while the toast is showing
   and right after it closes. `LIVE_DUR` (`python3 tools/build_qlrec.py [VERSTR]
   [LIVE_DUR]`, default `0x3c`) is the toast's life *and* the flip window, in units
   of 1/60 s — so `0x3c` is 1.000 s and stock's own house value `0x30` is 0.8 s.

> Emulator evidence, and what it is worth: `emu_qlrec.py` — 60 checks, ALL GOOD,
> including the reported bug as an explicit case, a guard that the retired
> `0x400522ca` hook appears nowhere in the image, and a guard that the cave
> references no `0x8000xxxx` address except stock's own setting word. **All three of
> this patch's hardware failures happened while the emulator was green**, which is
> the standing lesson: route A proves the logic, never the machine.
> `tools/emu_notify_probe.py` — full-firmware, real function bodies: `dur=0` reaches
> the modal-insert function behind the original hang; the durations this build uses
> do not. `NOTES.md` "Session 46" (original design), "Session 50" (the hang),
> "Session 51" (refinements), "Sessions 92-96" (the crash, the dead gate, and the
> stateless rewrite that works).

### 4.9  Auto-remove an emptied trigless lock  (`build_triglock.py` — **HARDWARE-CONFIRMED, FINAL** — MKI, 2026-09-21)

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
- Every patch is **validated in a ColdFire emulator** (Unicorn, real image bytes)
  — control flow and DSP frame-word edits, not the audio engine; the side-chain DSP
  runs in dsp56kEmu. That is necessary, not sufficient: this project has shipped
  emulator-green builds that locked the unit up, did nothing at all, or doubled
  every trig. **What has actually been on hardware is listed per feature in §4 and
  in `README.md`'s hardware-test status table** — read one of them before you
  flash, and go in with the recovery net ready (§1, §6).
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
| `python3 tools/build_trigscale_only.py` | `1.40C` | Bug-1 fix only (MIDI Plays-Free trig stall), on otherwise-stock 1.40C |
| `python3 tools/build_pattern_led.py` | `1.40C` | Bug-2 fix only: a p-lock-only pattern lights its grid LED |
| `python3 tools/build_partreapply.py` | `1.40C` | fix only: Part params fully re-apply on a pattern→Part change |
| `python3 tools/build_mutemode_dt.py` | `140C_KYOTI` | Bug-1 fix + **MUTE MODE**, all four modes (`OT` / `OTFX` / `OTFX-T` / `DT-T`) — the shipping MUTE MODE build |
| `python3 tools/build_qlrec.py [VERSTR] [LIVE_DUR]` | `140C_KYOTI` | Bug-1 fix + QUANTIZE LIVE REC front-panel toggle, toast-gated — **hardware-confirmed working** (2026-09-25) |
| `python3 tools/build_sidechain3.py` → `OCTATRACK_SIDECHAIN3_CROSS` | `140C_KYOTI` | Bug-1 fix + the full **SIDE-CHAIN COMPRESSOR** (`KEY` / `KFLT` / `KGN` / `MON`, `KEY` reaching any of the 8 tracks, cross-core) |
| `python3 tools/build_triglock.py` | `1.40C` | fix only: auto-remove an emptied trigless lock |
| `python3 tools/build_directjump_v4.py` | `140C_KYOTI` | Bug-1 fix + **DIRECT JUMP** (`[PTN]`+`[YES]`) — *confirmed at 1x scales only* |
| `python3 tools/build_reload3.py` | `140C_KYOTI` | Bug-1 fix + **RELOAD FROM PROJECT**, two chords (`[PTN]`/`[BANK]` + `[TRACK n]`) — **hardware-confirmed, final** (2026-09-25) |
| `python3 tools/build_bugbuilds.py` | per-image | each finished feature **with all three bug fixes folded in** → `out/Bugbuilds/` |

Superseded, kept only for rollback and reference — **do not flash**:
`build_mutemode.py` / `build_mutemode_new.py` / `build_softmute.py` (pre-four-mode),
`build_directjump.py` / `_v2` / `_v3` (dead on hardware),
`build_reload.py` / `build_reload2.py` (the picker designs),
`build_sidechain.py` / `build_sidechain2.py` (intermediate stages).

| File | What it is |
|---|---|
| `downloads/extracted/OCTATRACK_OS1.40C.syx` | **Official rescue OS** — for recovery or reverting. |

Reproducible one-shot for the Bug-1 fix (no assembler needed):

```sh
python3 sysex/apply_patch.py -i <your stock .syx> \
    -p sysex/patches/playsfreefix-r1.json -o OCTATRACK_OS1.40C_PLAYSFREEFIX.syx
```

(Regenerate the JSON from a fresh build with `sysex/gen_patch_json.py`.)
