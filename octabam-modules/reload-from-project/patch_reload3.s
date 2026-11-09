| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| patch_reload3.s -- RELOAD, redesigned around direct chords (Session 85).
|
| Supersedes patch_reload2.s, which is kept for rollback and reference. The picker
| is GONE: hardware report #8 was "very inconsistent, hard to understand what is
| happening where and when", and the bug tally explains why -- ~13 bugs in the
| picker/keymap/popup machinery and essentially none in the worker that does the
| reload. So there is no modal window, no keymap layer of our own, no popup-slot
| sharing, no walk-away detection, no arrows, and no BUSY state.
|
|   [PTN]  + [TRACK n] -> reload that track's CF-saved sequence. Part untouched.
|   [BANK] + [TRACK n] -> the same, PLUS that track's slice of the Part as the project
|                         was saved on the card (2026-11-08, CLYPS' card reload; it used
|                         to re-apply the WHOLE Part from its SAVE PART copy in RAM).
|
| Carried over unchanged because it is proven: rl_job's per-track slice, rl_arm_trk,
| rl_openstrd, and the whole-bank suppression (rl_done + the FUN_4000faf0 live
| refresh) that cut a reload from 6852 buffered card reads to 354.
|
| Full rationale, measurements and open risks: reference/RELOAD_REDESIGN.md

| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| patch_reload2 -- "RELOAD FROM PROJECT", scaled-down / SEQ-focused variant
| (NOTES.md "Session 43" / "44" / "47").
|
| A trimmed sibling of patch_reload.s (which is SEQ / ALL PARTS / WHOLE PATTERN).
| patch_reload2.s is a separate image (build_reload2.py -> OCTATRACK_OS1.40C_RELOAD2.*)
| with a 3-item picker:
|
|   TRK SEQ        -- reload the SEQUENCE DATA of the ONE currently-addressed track
|                     (audio track if you are on the AUDIO pages, MIDI track if you
|                     are on the MIDI pages -- read from 0x80000000 / 0x80000012).
|                     Everything for that track: regular trigs, recorder trigs,
|                     trigless trigs, trigless locks + their p-lock values, swing/
|                     slide, micro-timing, trig conditions, that track's step
|                     count.  Nothing else -- the other 7 tracks, the pattern
|                     length/scale, and the pattern->Part link are all untouched.
|   PTN SEQ        -- reload the WHOLE active pattern's sequence data (all 8 audio
|                     + all 8 MIDI tracks + length + scale + trig conditions +
|                     micro-timing) from bankNN.strd, seamlessly.  The pattern's
|                     Part ASSIGNMENT is preserved (masked out of the copy) -- a
|                     sequence reload must not silently re-point the pattern at a
|                     different Part.
|   PART + PTN SEQ -- faithful restore: PTN SEQ *including* the pattern->Part link,
|                     then make that saved Part current on the engine
|                     (FUN_40009094).  Puts the pattern back exactly as the card
|                     has it -- assignment and all.  The Part's own parameters
|                     come from its live slot (= its saved state unless you SAVE
|                     PART'd it since; matches the stock "reload part" convention).
|
| ---- UX (Session 44 -- OT-native) ----
|   Hold [PTN] ~0.5 s   opens a sticky picker window (the OS's own hold event, as
|                       [PAGE]-hold uses).  The window opens with TRK SEQ already
|                       highlighted, so the most common (least destructive) action
|                       is [PTN]-hold then [YES] -- no arrow keys.  A quick [PTN]
|                       tap is unchanged -- SELECT PATTERN.
|   arrow keys          move the highlight  (UP/RIGHT = prev, DOWN/LEFT = next,
|                       wrapping)  TRK SEQ / PTN SEQ / PART + PTN SEQ.
|   [YES]               execute the highlight, close the window.
|   [NO]                close the window, execute nothing.
|
|   No timeout -- like every stock OS menu, the window stays until you answer it
|   with [YES] or [NO].  While it is open [YES]/[NO] act ONLY on the picker.
|
|   MERGE NOTE (DJ + RELOAD2):  DIRECT JUMP is [PTN]+[YES].  RELOAD2 no longer
|   touches [PTN]+[YES] at all -- rl_yes here only acts while G_MENU==1, and the
|   entry gesture is the hold, so the two features share no chord.  See
|   reference/MERGE.md for the trampoline (build_merged.py: --defsym MERGE=1).
|
|   POWER MOVE (not built -- kept open).  Hold [PTN] + tap a [TRACK] key = TRK SEQ
|   on that track immediately, no picker.  The chord IS available: the track keys
|   are keycodes 0x10..0x17 (handler dispatch 0x40040250 -> FUN_40083ab4 mute),
|   and NO stock handler reads the "[PTN] held" flag 0x460d1742.  To add it: detour
|   the track-key handler, and when 0x460d1742 != 0 -> load d0 = keycode-0x10,
|   set 0x80000000 = d0 (so the currently-addressed track is that one), jsr
|   rl_arm_trk, set 0x460d173e = 1 (swallow SELECT PATTERN on the [PTN] release),
|   and rts (swallow -- do NOT also mute).  rl_arm_trk is factored out for exactly
|   this.  Deferred: it needs its own displaced-byte guard + a HW check that the
|   track key reaches that handler and that swallowing the mute is harmless.
|
| ---- ⚠️ Session 60's flag, FIXED here (Session ??) ----
| Session 60 (NOTES.md), while root-causing why DIRECT JUMP v1-v3 did NOTHING on
| hardware, flagged that `rl_yes` (the detour @ 0x4005e4c8 below) sits on the exact
| same dead hook: [PTN] press unconditionally pushes a UI overlay keymap layer
| (26-byte records @ 0x400bf0f2, one per key) that OVERWRITES the runtime dispatch
| table's YES slot for as long as [PTN] stays physically held -- the layer's own
| YES record has press=NULL, so the slot goes to 0 and the real handler this
| detour lives inside (0x4005e4c8) is never entered AT ALL while the chord is
| held. DIRECT JUMP's whole gesture ([PTN]+[YES], pressed together) hits this on
| every attempt, which is why it was flashed and did nothing; fixed there
| (build_directjump_v4.py, --defsym DJ_KEYMAP=1) by writing the handler straight
| into that dead slot instead of detouring 0x4005e4c8.
|
| RELOAD2's UX is different -- YES/NO are meant to answer a STICKY, no-timeout
| picker that's designed to be navigated AFTER releasing [PTN] (that's the whole
| point of "sticky": you don't have to keep it held) -- so the *existing*
| 0x4005e4c8 / 0x4005e25c detours are NOT dead in general, only for the narrower
| case of a user who presses YES/NO while STILL physically holding [PTN] down
| (plausible: DIRECT JUMP's own combo trains users to expect exactly that
| gesture, and nothing stops someone from doing it here too, intentionally or
| out of habit). Dumping the actual stock table (`out/raw/section_3_MAIN_OS.bin`
| @ 0x400bef04..0x400bf0d8) confirms both keys are affected while [PTN] is held,
| for two different reasons:
|   YES (code 0x31, record @ 0x400bf0be): press = NULL, exactly DIRECT JUMP's bug.
|   NO  (code 0x32, record @ 0x400bf0a4): press = 0x40056aa8 -- NOT null, but that
|     function's entire body is `cmp.l 0x460d1742,d0(==2) ; bne rts` -- i.e. it
|     does something only when PTN_MODE reads the literal value 2, which our
|     [PTN]-hold-for-the-picker case never produces (PTN_MODE is 0/1 throughout
|     the press-hold-release cycle per Session 44's own RE of FUN_4005a044) -- so
|     in every case this project's own [PTN]-held gesture can produce, it is
|     already an unconditional no-op, safe to shadow.
| Arrow keys (codes 0x34/0x21/0x33/0x20) have NO record in that table at all, so
| they are NOT swallowed by this layer and need no fix.
|
| Fix (same shape as DJ_KEYMAP, applied to both slots): `rl_yes_ptnheld` /
| `rl_no_ptnheld` are poked directly into the two dead/no-op press fields by the
| build script (not a code detour -- see build_reload2.py). Each replays the
| exact same G_MENU/POPUP gate `rl_yes`/`rl_no` already use and, when it applies,
| `bsr`s the now-shared `rl_yes_exec` / `rl_no_exec` body (factored out of the
| original inline code so both entry points -- the keymap slot AND the original
| 0x4005e4c8/0x4005e25c detour -- drive identical logic). When it does NOT apply
| (menu closed): `rl_yes_ptnheld` just `rts`s (stock's own NULL slot did nothing);
| `rl_no_ptnheld` `jmp`s the original `NO_PTNHELD_STOCK` (0x40056aa8) so whatever
| conditional behaviour that function has for a PTN_MODE this project's gesture
| never produces is preserved byte-for-byte, not just assumed harmless.
| The ORIGINAL 0x4005e4c8/0x4005e25c detours are UNCHANGED and still needed --
| they're what answers the picker once the user has let go of [PTN], which is
| the documented, no-timeout, common case.
| RL_DONE (rl_done, below) is in every shipped build, so it is the default here: octabam's
| CavePatch.defsyms reach the LINKER (ld --defsym), and `.ifdef` is decided by the
| assembler. Define RL_NO_DONE to build without it.
    .ifndef RL_NO_DONE
    .ifndef RL_DONE
    .equ RL_DONE, 1
    .endif
    .endif

    .equ PTN_LAYER_YES,     0x400bf0be   | [PTN]-held layer record, code 0x31 (YES);
                                        | press field @ +2. Stock: NULL.
    .equ PTN_LAYER_NO,      0x400bf0a4   | [PTN]-held layer record, code 0x32 (NO);
                                        | press field @ +2. Stock: 0x40056aa8.
    .equ NO_PTNHELD_STOCK,  0x40056aa8   | that record's stock press handler (see above --
                                        | an unconditional no-op for every PTN_MODE value
                                        | this project's own [PTN]-hold gesture produces)

| Stock 1.40C only reloads from the card at whole-BANK granularity, and doing so
| glitches the audio (FUN_400a10c8 pre-step + FUN_400238a4 re-sync -- both
| HW-observed).  This is per-pattern / per-track and seamless: the file work rides
| the async storage task and the active pattern re-homes through FUN_400a1eea's
| own no-stop reload block (0x46c8028a); the Part apply is FUN_40009094
| ("apply a Part by event"), which parts-switching during playback already uses.
|
| ---- state (volatile scratch, no persistence needed -- one-shot actions) ----
|   ===== Session 98: the request bytes live IN THE CAVE now, not at 0x80006a50-55. =====
|   HARDWARE-PROVEN, by the RL3DG diagnostic toast (handoff section 10): with trigs on steps
|   1,3,...,15 the chord armed track 1 / audio (C 0000) and the worker read track 6 / MIDI
|   back from 0x80006a54-55 (W 005B). It reloaded MIDI track 6, the verify checked that
|   slice and passed, and the toast said RELOADED while the edited track kept playing.
|   The block is inside the DSP shared-RAM window and is overwritten at runtime on the unit
|   (the same finding QUANTIZE_LIVE_REC_TOGGLE paid for, Sessions 94-96); the emulator never overwrites it.
|   The value followed the pattern content (0x55 mask bytes, 0x55 & 7 = 5), which is why a
|   single-trig test on track 1 read back zeros = track 1 and looked correct by accident.
|   G_KIND being clobbered was just as possible: a stray 1..3 would have hijacked the next
|   stock RELOAD BANK job. All six bytes are now labels in this cave's data (see rl_kind),
|   the region rl_own / rl_msg / rl_vsnap already live in and that the RL3DG toast proved
|   survives on hardware. build_reload_from_project.py asserts no 0x80006a40..0x80006abf reference
|   remains in the blob. G_MENU / G_SEL are picker-era and unused, and are gone.

|   ---- stock symbols ----
    .equ PTN_USED,  0x460d173e          | set 1 to suppress SELECT PATTERN on [PTN] release
    .equ PTN_MODE,  0x460d1ab2          | stock: "[PTN] was not already in SELECT mode"
    .equ POPUP,     0x460e5cd0          | != 0 -> a blocking FUN_4006d57c dialog is up
    .equ ARR_ACT,   0x460d1aec          | arranger active
    .equ RUNNING,   0x800065b8          | transport state -- LONGWORD (=1 playing)
    .equ ACT_PAT,   0x800065be          | sequencer's active pattern (byte)
|   ===== Session 92: PLAY_BANK is ACT_PAT's partner; CUR_BANK is NOT. =====
|   Hardware report #14: "the sequence data does not always reload reliably. Most of the
|   time it does. Occasionally the toast will show 'reloaded', but the sequence is not
|   actually restored."  The reload was aimed with a MISMATCHED (bank, pattern) pair.
|   MEASURED -- all three writers of 0x800065bd set it in the same breath as ACT_PAT:
|       0x400a05f6  the direct goto          65bd=bank, 65be=pattern, + queued mirrors
|       0x400a40aa  the boundary latch       gated on BOTH queued values being != -1
|       0x400a44dc  the second latch site    identically gated
|   so (PLAY_BANK, ACT_PAT) always describes ONE pattern -- the one being played -- and
|   both move only when the sequencer says so. CUR_BANK (0x80000002) has no such pairing:
|   it is written at 0x400622b8 (a UI path, alongside LIVE_REFRESH and the cached blob
|   base 0x46c82456) and at 0x40087d26 (clamped 0..15, project load). Pairing it with
|   ACT_PAT could name a slab that nothing is reading -- so the .strd was read, the slab
|   was rewritten, LIVE_REFRESH ran, our success toast appeared, and not one byte of what
|   the user could hear had changed. Intermittent exactly as reported: harmless while you
|   stay in one bank.
|   Every reload-TARGETING site below uses PLAY_BANK. CUR_BANK is deliberately left
|   defined but unused, so a future site cannot reach for it by habit.
    .equ PLAY_BANK, 0x800065bd          | the bank being PLAYED -- pair this with ACT_PAT
    .equ CUR_BANK,  0x80000002          | UI-side bank; NOT ACT_PAT's partner (see above)
    .equ CUR_PART,  0x80000003          | the Part the sounding pattern is assigned to (byte)
    .equ CUR_TRACK, 0x80000000          | UI-selected track (byte 0..7 ; mirror 0x100b14cc)
    .equ MIDI_MODE, 0x80000012          | LONG, != 0 -> the MIDI pages are up (track index means MIDI track)
    .equ RELOAD_NOW,0x46c8028a          | step engine polls this at 0x400a2530
    .equ POPUP2,    0x4005a0e0          | FUN_4005a0e0(text) -- bare text box, no timeout
    .equ CLOSE_CB,  0x40056bc0          | FUN_40056bc0 -- close the 0x460d1e64 popup
    .equ TOAST,     0x4005a2b8          | FUN_4005a2b8(text, dur) -- the "PART %d RELOADED" toast
    .equ PARTAPPLY, 0x40009094          | FUN_40009094(bank, part) -- apply a Part by event (parts-switch path)
    .equ RDRAW,     0x46c7c72c          | screen redraw dirty flag (set to 1)
    .equ PART_RFRSH, 0x4005e0a8         | Session 120: the tail of stock's Part-reload shortcut
                                        | (key 0x2a, FUN_4005e038): RDRAW = 1, then its UI refresh
|   ===== Session 98: the DIAG build (--defsym RL_DIAG=1, tools/build_reload_from_project.py --diag) =====
|   reference/handoffs/RELOAD3_SEQFAIL_HANDOFF.md section 4. On hardware a [PTN]+[TRACK n]
|   reload frequently leaves the EDITED sequence playing while the toast says RELOADED and
|   the self-verify in rl_done stays silent. Every intermediate the harness can measure
|   passes, so the only instrument left is the toast itself: this build replaces every
|   success message with four lines of the raw bytes and indices the worker actually used,
|   captured into OUR CAVE at the moment each was read (never into SCRATCH, which is inside
|   stock's 64 KB OPEN_BUF window and is one of the suspects).
|   NOTHING UNDER TEST MOVES: SCRATCH, OPEN_BUF, the 0x80006a50 scratch bytes, the job flow
|   and the verify are exactly the flashed build's. Only cave-side captures are added.
|     line 0  P pppppppp S ssssssss   P = live slab bytes BEFORE the copy (= what was
|                                     playing / edited), S = rl_vsnap (SCRATCH after copy)
|     line 1  L llllllll K kkkkkkkk   L = live slab at doneFn (what the verify compared),
|                                     K = the 0x1001614e live-cache copy at doneFn
|     line 2  C bptm W bptm D bp      bank/pattern/track/midi as the CHORD armed them, as
|                                     the WORKER read them from 0x80006a5x, and PLAY_BANK/
|                                     ACT_PAT as DONEFN saw them. One hex digit each.
|     line 3  Mn Vn Kn R rr           M = message code armed (1 TRK/2 TRK+PART/3 SAVE
|                                     FIRST/4 LOST), V = verify (0 not armed/1 pass/2
|                                     fail), K = G_KIND as the worker read it, R = low
|                                     byte of the LAST PARSEPAT return.
|   Reading it (section 4 of the handoff):  P==S==L -> SCRATCH held the edited data and
|   both copy and verify were vacuous (hypothesis A).  P!=S, S==L -> the copy landed in
|   the blob the verify reads; playback reads elsewhere (C).  C!=W -> the 0x80006a5x
|   scratch was clobbered between chord and worker (kb/caves.md, Sessions 94-96).  Two
|   chords in a row with no edit in between: toast 1's L vs toast 2's P settles (B).
    .ifdef RL_DIAG
    .equ LIVE_CACHE, 0x1001614e         | LIVE_REFRESH's destination: bank's 16 slabs
    .equ DIAG_DUR,   0x168              | 6 s at the measured ~60 Hz tick -- long enough
                                        | to read four lines of hex; diag build only
    .endif

|   ---- [BANK]-held overlay layer (Session 80 continued (2)) ----
|   [BANK] press 0x4007af80 pushes layer struct 0x400cff14 (records @ 0x400cff34)
|   through the same FUN_40031494 push+rebuild [PTN] uses; [BANK] release
|   0x4007b3e0 pops it (0x4003146c @ 0x4007b40e).  Record 17 = code 0x31 (YES)
|   @ 0x400d00ee, press field @ 0x400d00f0, stock value NULL -- the dead slot
|   build_reload2.py pokes rl_bank_yes into.
    .equ BANK_LAYER_YES, 0x400d00ee     | code 0x31 record in the [BANK]-held layer
|   Session 80 continued (3) -- deferring the SELECT BANK window to the release.
|   MEASURED on stock by tools/diag_bank_window.py (do not re-derive by reading):
|     * [BANK] press SHOWS the window (FUN_40059f8c, dur 0xf0, onClose 0x4007b408)
|       and THEN pushes the overlay layer.
|     * [BANK] RELEASE pops NOTHING -- zero teardown calls, layer still live.
|       The WINDOW owns the LAYER: onClose 0x4007b408 is the only thing that pops
|       it, so the layer's lifetime is the window's, exactly as stock [PTN] does.
|     * Calling 0x4007b408 directly pops the layer cleanly and restores the YES
|       dispatch slot to 0x4005e4c8 -- that is stock [PTN]'s own "swallow" route
|       (its release calls teardown 0x40043418 directly when 0x460d173e is set).
|   So the window may NOT simply be suppressed: something must still run teardown
|   exactly once, or the [BANK] overlay strands on the dispatch table forever.
|   Session 80 continued (6): MEASURED through the real key dispatcher
|   (tools/diag_reload2_realkey.py, set_key_state 0x40031734 -> the runtime
|   table). After [BANK] release the overlay layer IS correctly popped
|   (BANKlayer=popped) and the NO slot IS restored (0x4007b25c -> the underlying
|   handler) -- but the YES slot KEEPS pointing at rl_bank_yes. The asymmetry
|   names the cause: NO's record has a non-NULL press in stock, YES's is NULL,
|   and the pop's table rebuild does not restore a slot that was NULL in stock.
|   Our poke therefore OUTLIVES the layer, and [YES] on its own then opens the
|   reload picker for the rest of the session -- confirmed: "[YES] alone ->
|   G_MENU=1" with no [BANK] held, and stock [YES] is gone.
|   So save the slot's pre-push value and put it back on release ourselves
|   rather than trusting the rebuild. Restoring it to the UNDERLYING handler is
|   also exactly what the sticky picker wants: that handler is 0x4005e4c8, which
|   rl_yes detours and which answers an open picker after [BANK] is released.
    .equ LAYER_PUSH,     0x40031494     | FUN_40031494(struct) -> link + rebuild
    .equ LAYER_POP,      0x4003146c     | (struct) -> unlink + rebuild
    .equ CLOSECB_RESUME, 0x40056bc6     | resume after the displaced tst.l 0x460d1e64
                                        | (lands exactly on CLOSE_CB's own beqs)
    .equ BANK_HELD_FLAG, 0x46c7dd56     | is_key_held([BANK]) = 0x46c7d8ee + 0x2f*24
    .equ YES_DISPATCH,   0x46c7dd76     | runtime dispatch table, YES press slot
                                        | = 0x46c7d8de + 0x31*24
    .equ BANK_SHOW,      0x4007af42     | press tail: pea onClose ; clr.l -(sp)  (6 B displaced)
    .equ BANK_PRESS_RES, 0x4007af48     | resume AFTER the 2 displaced insns -- stock's
                                        | own SELECT BANK window show is left intact
    .equ BANK_TEARDOWN,  0x4007b408     | window onClose -> pops the overlay layer
|   Session 91: the SHOW_WIN popup slot and the onClose pointer stock's own dismiss
|   follows. MEASURED writers: 0x460d1e5c is written ONLY at 0x40059fe4 and 0x460d1e60
|   ONLY at 0x4005a006 -- both inside SHOW_WIN. So stock's dismiss (0x40056a70) runs an
|   onClose only if a window was actually SHOWN through SHOW_WIN; it bails at 0x40056a76
|   otherwise. This is what the POPUP guard below used to get wrong.
    .equ WIN_SLOT,       0x460d1e5c     | the SHOW_WIN popup handle
    .equ WIN_ONCLOSE,    0x460d1e60     | the onClose 0x40056a70 jumps to, if any
    .equ BANK_TEXT,      0x400b7302     | "SELECT BANK"
    .equ BANK_SEL,       0x460e73c6     | trig handler sets it -> its own "bank N" toast is up
    .equ SHOW_WIN,       0x40059f8c     | FUN_40059f8c(text, dur, flag, onClose)
    .equ BANK_COMMIT,    0x460e73c2     | [BANK] release: !=0 -> commit path
                                        | (0x40031200); 0 -> 0x40056a70 dismiss.
                                        | rl_bank_yes clears it (INFERRED, see there)

|   [PTN] key handler FUN_4005a044.  RETIRED in Session 80 continued (2) -- the
|   entry gesture moved to [BANK]+[YES], so rl_ptn and its detour are gone and
|   PTN_USED / the hold tail are no longer referenced.  Addresses kept for the
|   record only.
|   .equ PTN_HOLD_H,  0x4005a044
|   .equ PTN_RESUME,  0x4005a04a
|   .equ PTN_HOLDTAIL,0x4005a0d2

|   [NO] handler @ 0x4005e25c.  Detour replaces `move.l 8(sp),d0 ; beq.s 0x4005e276` (6 B).
    .equ NO_REL,    0x4005e276          | event 0 -> stock release cleanup
    .equ NO_PRESS,  0x4005e262          | press/hold path after the displaced 2 insns

|   [YES] handler @ 0x4005e4c8.  Detour replaces `move.l 4(sp),d1 ; move.l 8(sp),d0` (8 B).
    .equ YES_RESUME,0x4005e4d0

|   Session 80 continued (4): the type-0x14 doneFn's SUCCESS path.
    .equ LIVE_REFRESH, 0x4000faf0       | FUN_4000faf0(bank) "make bank current":
                                        | memcpy(0x1001614e, blob+bank*0x9b340, 0x8ed80)
                                        | + parts -> 0x100a4ece. RAM->RAM, no card.
    .equ MASK_SAVED,   0x460bd910       | the bank mask, stashed by FUN_40022778 at buf-2
    .equ DONE_RESUME,  0x40023c68       | resume after the displaced mvz.w (move.l d0,-(sp))
    .equ DONE_EPILOG,  0x40023c76       | doneFn epilogue: move.l (sp)+,d2 ; movea.l (sp)+,a2 ; rts

    .equ JOB_POST,  0x40022778          | FUN_40022778(mask) -> post the type-0x14 storage job
    .equ JOB14_EXIT,0x400858a8          | 0x14 case: tst.l d0 ; ... ; done-dance ; -> dequeue loop
    .equ JOB14_ORIG,0x4008586c          | 0x14 case: resume after the displaced 2 insns

|   arrow keys -- keycodes 0x34 (UP) / 0x21 (RIGHT) -> ARROW_A ; 0x33 (DOWN) /
|   0x20 (LEFT) -> ARROW_B.  Verified against the 26-byte keymap tables
|   (T1 0x400bfc10 / T2 0x400c01f4) + octabam MAINMENU.md sec 7 (HW-tested).
|   Session 80 continued (6): the picker takes UP/DOWN ONLY (user's explicit
|   request: "I don't want the left/right arrows to operate on the RELOAD2
|   options selector at all. I just want up/down"). Both handlers are SHARED by
|   two keycodes each, so the detours must test the code, not just the handler.
|
|   ** KB CORRECTION, hardware-derived. ** reference/kb/memory-map.md said
|   UP 0x34 + RIGHT 0x21 -> 0x4004b970 and DOWN 0x33 + LEFT 0x20 -> 0x400491a0
|   (confidence C, cross-checked against octabam -- which is MKII-oriented; this
|   project is MKI-only). That pairing is WRONG. A build gating 0x4004b970 on
|   0x34 and 0x400491a0 on 0x33 was flashed: UP worked, **DOWN did not**. If the
|   KB pairing held, 0x33 IS down and the gate would have passed it, so the
|   report falsifies it. The correct pairing is the one the handlers' own shape
|   implies anyway:
|     0x4004b970 = UP 0x34 + DOWN 0x21   -- the VERTICAL pair, which is exactly
|                  why stock special-cases its two codes at 0x4004b9d6
|     0x400491a0 = LEFT 0x20 + RIGHT 0x33 -- horizontal; this wrapper never even
|                  examines the keycode, treating both identically
|   So rl_arr_a owns both vertical directions and rl_arr_b owns neither.
|   They are also mapped for press AND release AND hold (with auto-repeat on all
|   four keys), so the original detours moved the selection on the release too --
|   one physical tap stepped it TWICE, plus once per repeat tick. --combo only
|   ever drove event=1, so it never caught that. Both are now gated on
|   event==press, and LEFT/RIGHT are swallowed while the picker is open so the
|   window stays put rather than letting stock arrow navigation move off it
|   (which is what "strange visual glitches and move away from the option
|   window" was). Picker closed -> every arrow falls through to stock untouched.
|   ** CORRECTED AGAIN, Session 80 continued (7). ** Hardware: "the arrow keys
|   L/R work, but U/D do not. This should be reversed." So 0x4004b970 (0x34 +
|   0x21) is the LEFT/RIGHT pair and 0x400491a0 (0x33 + 0x20) is UP/DOWN -- the
|   opposite of "(6)". My "(6)" reasoning rested on an INFERENCE I had no right
|   to make: the user reported only that DOWN did not work, and I read that as
|   "UP works" to anchor 0x34 = UP. It did not say that.
|   Which of 0x33 / 0x20 is UP vs DOWN is still unverified -- the 0x400491a0
|   wrapper never examines the keycode, so nothing in the firmware distinguishes
|   them. 0x33 is assigned prev/UP here; if the picker steps the wrong way, swap
|   these two lines and nothing else.
    .equ UP_CODE,       0x33
    .equ DOWN_CODE,     0x20
    .equ ARROW_A_H,     0x4004b970      | UP / RIGHT handler
    .equ ARROW_A_RESUME,0x4004b978      | after `lea -12(sp),sp ; movem.l d2-d3/a2,(sp)`
    .equ ARROW_B_H,     0x400491a0      | DOWN / LEFT handler
    .equ ARROW_B_RESUME,0x400491a6      | after `move.l d2,-(sp) ; movea.l 8(sp),a0`

    .equ PROJDIR,   0x40025230          | (0,0) -> char* "<set>/<project>"
    .equ SPRINTF,   0x40013a08
    .equ FOPEN,     0x40016864          | (fh, path, mode, buf, size) buffered open, d0<0 = fail
    .equ FREAD,     0x40016564          | (fh, buf, count) buffered read
    .equ FCLOSE,    0x4001677c          | (fh)
    .equ PARSEPAT,  0x4008cebc          | (fh, destSlab, verWord) parse one PTRN chunk
    .equ FWMEMCPY,  0x40020898          | (dst, src, len)
    .equ FMT_STRD,  0x400b86d8          | "%s/bank%02d.strd"
    .equ MODE_R,    0x400b3289          | "r"
    .equ OPEN_BUF,  0x460a8f60          | the storage task's 64 KB buffer (idle while we hold the task)
    .equ SCRATCH,   0x460aff60          | = OPEN_BUF + 0x7000 ; 0x8ed8 B pattern scratch
    .equ CKSUM,     0x460fab5c          | the deserialiser's rolling checksum (word)
    .equ BLOB,      0x400e21e0
    .equ BANKSTRIDE,0x9b340
    .equ PATSTRIDE, 0x8ed8

|   RAM pattern-slab geometry (blob-relative), from FUN_4009a670 (the load-time
|   bounds clamp -- walks 8 audio tracks stride 0x91a, then 8 MIDI stride 0x8b0,
|   then the pattern fields; NOTES.md L1067):
    .equ TRAC_A,     0x91a              | audio track stride (track t at slab + t*0x91a)
    .equ MIDI_BASE,  0x48d0             | MIDI region base (= 8 * 0x91a)
    .equ TRAC_M,     0x8b0              | MIDI track stride (MIDI track t at slab + 0x48d0 + t*0x8b0)
    .equ PAT_PART,   0x8e57             | pattern->Part link, 1 byte [0..3]
|   Session 89 -- the pattern-level scale trailer. Offsets CONFIRMED against stock's own
|   load-time clamp FUN_4009a670: +0x8e53 is clamped to 2..64 (a STEP COUNT, 0x4009aada)
|   and +0x8e54 to 0..6 (a SCALE INDEX, 0x4009ab06); +0x8e55 is the scale-MODE flag the
|   step engine tests at 0x400a2720 to decide whether per-track scale applies.
    .equ PAT_LEN,    0x8e53             | pattern LENGTH in steps (governs in NORMAL mode)
    .equ PAT_SCALE,  0x8e54             | pattern SCALE index    (governs in NORMAL mode)
    .equ PAT_SMODE,  0x8e55             | 0 = NORMAL, != 0 = PER TRACK
|   The LIVE master-scale cache. ** Not refreshed per wrap. ** Stock writes it only from
|   transport start/stop (0x4009beec/0x4009bf54), the whole-bank re-home
|   (0x400a272e/0x400a2764) and the pattern-switch commit tail (0x400a4220). In NORMAL
|   mode it is sourced from +0x8e54, in PER TRACK mode from the MASTER scale +0x8e52.
    .equ SCALE_IX,   0x8000663d         | live MASTER scale index (byte)

|   ---- 2026-11-08: [BANK] + [TRACK n] = the track's sequence + ITS Part slice, from the card ----
|   The same reload CLYPS does (tools/clyps/clyps_reload.s in the trkseq worktree, scope §1.8, the
|   user 2026-10-30): never the whole Part (that reverted every other track on it), and never the
|   SAVE PART copy in RAM, but the bank file's WORKING Part chunk -- the Part as the project was
|   saved. Stock's bank reader 0x4008e0c0..0x4008e2c0 reads the 16 PTRN chunks, then the 4 working
|   PART chunks (0x4008be2c) into bank +0x8ed80, then the 4 SAVE PART copies (+0x9504a).
    .equ PARSEPRT,   0x4008be2c         | (fh, part, i, ver): parse one PART chunk
    .equ LLSEEK,     0x46c8243e         | -> the card filesystem's seek (id, byte offset)
    .equ PART_OFF,   0x8ed80            | a bank's 4 working Parts, after its 16 slabs
    .equ PARTSZ,     0x18b2
    .equ PEDIT,      0x95048            | bank + : byte, bit p = Part p edited
    .equ PSAVECPY,   0x9504a            | bank + part * PARTSZ: the SAVE PART copies
    .equ PSAVED,     0x9b312            | bank + part: != 0 = the Part has a SAVE PART copy
    .equ BDIRTY,     0x9b332            | bank + : long 1 = the bank has changed
    .equ DIRTY2,     0x100f8598         | long 1 (stock's TRACK PASTE sets it with the two above)
    .equ UI_BANK,    0x80000002         | the bank the SRAM mirror and the screen show
    .equ TRK_APPLY,  0x40001f18         | (bank, part, t): one audio track's Part values -> the engine
                                        | (C, our reading: a5 = bank, fp = part, d6 = t)
    .equ ENG_RESTART,0x8000184c         | byte, bit t: restart the voice (stock's machine edit 0x400973b4)
    .equ PICKUP_SET, 0x40097290         | stock's PICKUP setup after a machine change (UI context;
                                        | stock's machine edit calls it first, 0x400973b0)
    .equ MENG,       0x46c76dc0         | 8 x 68 B: a MIDI track's page values (32) + setup (36)
    .equ MDES,       0x46c7738c         | 24 x 16 B: the MIDI LFOs' designer waves
    .equ MSLP,       0x46c7750c         | 24 x u16: ... their slopes
    .equ MBANK,      0x8000666e         | byte[8] bank / [8+m] Part the MIDI track's values came from
    .equ MZERO,      0x8000664e         | long[8], cleared by stock's apply
    .equ RQ_TRKSEQ,  3                  | G_KIND: the track's sequence
    .equ RQ_TRKFULL, 4                  | G_KIND: the track's sequence + its Part slice
    .equ RQ_PTN,     5                  | rl_req: a whole pattern + its whole Part
    .equ RQ_STAGE,   5                  | G_KIND: a staging job (the generation says what for)
|   ---- 2026-11-08 (2): [PTN] + [BANK] + trig N = pattern N of the playing bank from the card ----
|   CLYPS' pattern reload (scope §1.8, built CLYPP; "the OT goes to it", 2026-11-06), outside Clyps.
|   MEASURED keymaps (stock 1.40C): the [PTN] layer (struct 0x400bf0f2, records 0x400bef04) maps
|   trigs 0..15 -> 0x40056b2c (pattern pick; octabam's KITS detours it), NO, YES; the [BANK] layer
|   (0x400cff14, records 0x400cff34) maps trigs 0..15 -> 0x4007b2fc (bank pick), NO, YES. Neither has
|   a record for the other key, so the chord's second key reaches its own base handler and pushes
|   its layer ON TOP -- the trig then goes to whichever was pressed last. This patch makes the chord
|   one state in either order: [BANK]'s keymap layer on top (its trig press is ours while both are
|   held), [PTN]'s LED layer on top (the grid shows the patterns, as Clyps' chord does), and both
|   releases silent (PTN_CONSUMED: [PTN]'s release only tears down, 0x4005a0be; rl3_bank_used:
|   ours tears [BANK] down, no SELECT BANK).
    .equ PTN_KEY_RES,  0x4005a04a       | [PTN] handler after `move.l 8(sp),d0 ; moveq #1,d1`
    .equ BANK_TRIG_RES,0x4007b304       | [BANK]-layer trig press after its 8-byte prologue
    .equ PTN_LEDL,     0x400bebfe       | [PTN]'s LED layer (0x4004346c pushes it with its keymap)
    .equ LED_POP,      0x4007e81c       | (layer): unlink it, wherever it is in the list
    .equ PAT_MSCALE,   0x8e52           | the MASTER scale (PER TRACK mode's source of SCALE_IX)
    .equ PAT_MLEN,     0x8e50           | u16: the master length (0xffff = INF)
|   ---- 2026-11-08 (3): the landing (CLYPS' cl_land / cl_wrap / cl_uitick equates, measured there) ----
    .equ TICK_GATE,    0x46107568       | != 0: this ISR slice is not a tick (0x400a1f68)
    .equ MASTER_STEP,  0x800065b2       | u16: the master step, ++ at each master tick 0
    .equ TICK_CTR,     0x800065b6       | byte: master ticks within the step
    .equ LEN_TBL,      0x400aba50       | long[scale]: ticks per step (2 = 1x = 6)
    .equ STEP_ARR,     0x800064d0       | byte[16]: per-track step (audio 0..7, MIDI 8..15)
    .equ STEPM1_ARR,   0x800064e0       | byte[16]: per-track step - 1 (mod len)
    .equ TICKS_ARR,    0x800064f0       | byte[16]: per-track ticks within the step
    .equ TSCALE_ARR,   0x8000663e       | byte[16]: per-track scale cache
    .equ PEND_BANK,    0x800065bf
    .equ PEND_PAT,     0x800065c0
    .equ TICK_RES,     0x400a2536       | after `tst.l 0x46c8028a` (stock's beq.w follows)
    .equ WRAP_RES,     0x400a43a6       | after the wrap body's first three instructions
    .equ UITICK_RES,   0x40056c2e       | after `move.l 0x460d1e6c,%d0` (stock's beq follows)

    .equ CHAIN_OFF,    0x4009a404       | stock [PTN] + trig's steps (0x40056b2c..): chain off,
    .equ PAT_CUE,      0x400a1030       | (bank, pattern): the cue (running: pending; stopped: at once)

    .equ N_ITEMS,     3

|   ---- merged-firmware [YES] chaining (build_merged.py only) ----
|   Standalone, patch_reload2 owns the YES handler detour @ 0x4005e4c8 and its
|   "not the picker" path replays the displaced prologue -> stock.  In a combined
|   build DIRECT JUMP also wants that handler ([PTN]+[YES] toggle), so the single
|   detour goes to rl_yes and rl_yes hands "not the picker" on to dj_toggle
|   instead.  dj_toggle sees the stack exactly as the stock handler would (0=ret,
|   4=keycode, 8=event -- rl_yes has not disturbed it on this path) and either
|   handles the combo or replays the prologue itself -> 0x4005e4d0.  build_merged.py
|   passes  --defsym MERGE=1 --defsym MERGE_DJ_TOGGLE=<dj_toggle abs addr>.
    .ifdef MERGE
    .equ DJ_TOGGLE, MERGE_DJ_TOGGLE
    .endif

    .text

| ================= Session 85: the chord redesign =================
| Measured, see reference/RELOAD_REDESIGN.md. Both detour sites open with the
| same 6-byte prologue and take a 6-byte jmp with no padding.
    .equ PTN_TRK_H,      0x40083dc4     | TRACK handler at the site all 8 stock refs
    .equ PTN_TRK_RES,    0x40083dca     | point at. Those refs live in CUE's held-
                                        | modifier sub-map table (0x400bf122, from
                                        | CUE key 0x2a's sub-map 0x400bf2a0) -- NOT a
                                        | [PTN] overlay. [PTN] never redirects TRACK
                                        | keys here (Session 85); [CUE]+[TRACK] does.
                                        | So arriving here is NOT uniquely a reload
                                        | chord: gate on the panel PTN held bit.
    .equ KROWS,          0x46100b18     | panel matrix held rows; code = row*8+bit
    .equ KPTN,           0x2e           | PATTERN: row 5, bit 6
    .equ TRK_BASE_H,     0x40040250     | base TRACK handler ([BANK] does NOT override
    .equ TRK_BASE_RES,   0x40040256     | track keys, so the chord lands here)
    .equ PTN_HELD_FLAG,  0x46c7dd3e     | is_key_held([PTN]) = 0x46c7d8ee + 0x2e*24.
                                        | MEASURED (diag_reload3_chords.py): a [PTN]
                                        | press sets this to 1, but the [PTN] OVERLAY
                                        | never redirects the TRACK keys -- the dispatch
                                        | slot stays on the base handler through press,
                                        | 20 frames of hold, and an explicit HOLD event.
                                        | So the chord cannot rely on 0x40083dc4 being
                                        | reached; the base handler tests this flag
                                        | instead, the same way the [BANK] chord does.
    .equ PTN_CONSUMED,   0x460d173e     | stock's "a [PTN]-held action consumed the
                                        | gesture" flag. Its release path does
                                        | `tstl 0x460d173e ; bne -> skip SELECT PATTERN`
                                        | (0x4005a088). Stock writes -1 at 0x40056b44.
    .equ PART_RELOAD,    0x4004aab4     | stock Part RELOAD. RETURNS 0 when the Part has
                                        | never been saved (stock then toasts SAVE PART
                                        | FIRST!), non-zero when it reloaded the saved
                                        | version. Decoded from stock's own caller at
                                        | 0x4005e05a.
    .equ STOCK_SAVEFIRST, 0x400b41bb    | stock's "SAVE PART FIRST!" -- reuse its wording
    .equ MLNOTIFY,       0x4006d57c     | FUN_4006d57c(title, nlines, lines[], 0, 0) --
                                        | stock's TITLED, SELF-DISMISSING multi-line box.
                                        | Height is 7*nlines+27 and it arms a 40-frame
                                        | countdown at 0x460e5e20, so it goes away on its
                                        | own (the "0.5 s or less" the spec asks for).
                                        | Stock uses it for exactly this class of message:
                                        | "THIS BANK HAS NEVER / BEEN SAVED! / NOTHING TO
                                        | RELOAD!" under the title "RELOAD BANK"
                                        | (0x40023c20). ** It opens with
                                        | `tstl 0x460e5cd0 ; bne -> bail`, i.e. it REFUSES
                                        | to draw while a popup is up -- which is exactly
                                        | the [BANK] chord's situation, since SELECT BANK
                                        | opens on press. Hence BANK_WIN_CLOSE below. **
    .equ BANK_WIN_CLOSE, 0x4007b408     | SELECT BANK's own onClose. MEASURED in Session 80
                                        | continued (3): the window OWNS the [BANK] keymap
                                        | layer, and calling this directly pops the layer
                                        | and restores the YES slot. Exactly one teardown
                                        | must run on every path.
|   ---- Session 86: SELECT BANK moves from the PRESS to the RELEASE ----
|   Hardware report #9 item 2: "A BANK tap still brings up SELECT BANK countdown on
|   press, not release. I want it on release, like PTN does."
|   MEASURED layout (do not re-derive by reading):
|     0x4007af80  the [BANK] PRESS handler. Computes BANK_COMMIT = (0x460e73bc == 0)
|                 -- so it is a TOGGLE -- then `bras 0x4007af30`.
|     0x4007af30  a SHARED tail, reached from that bras and NOTHING ELSE (grepped the
|                 whole image). It clears BANK_SEL / 0x460e73b8 / 0x460e73bc, shows
|                 the window (SHOW_WIN, dur 0xf0, onClose 0x4007b408), pushes the
|                 [BANK] overlay layer, makes two more UI calls, then
|                 `lea 28(sp),sp ; rts` -- it cleans up exactly what it pushed.
|     0x4007b3e0  the RELEASE handler: BANK_SEL==2 or BANK_COMMIT==0 -> dismiss
|                 (0x40056a70), else commit (0x460e73bc=1 then 0x40031200, which is
|                 just 0x460d1e4c=1 -- a popup-CONFIRM flag, NOT a bank change).
|                 That commit is what makes stock's window STICKY after the release.
|   So the whole gesture is: press shows, release makes it stick, next tap dismisses.
|   Time-shifting only the SHOW preserves that state machine exactly, and two measured
|   facts make it safe rather than hopeful:
|     * LAYER_PUSH (0x40031494) is IDEMPOTENT -- it rts's if the struct is already the
|       list head (0x400314b4) or anywhere in the list (0x400314b8), so replaying the
|       tail can never double-link the overlay.
|     * LAYER_POP (0x4003146c) walks the list and simply finds nothing if the struct
|       was never linked, so a teardown on a window that never opened is harmless.
|   ** Session 80 continued (3)/(7) tried this and it failed on hardware. The
|   difference now is that the previous attempt carried the picker, its own keymap
|   layer and a poked YES slot; this build pokes no layer record at all, so the only
|   moving part left is the show itself. Still the riskiest item in this build. **
|   ---- Session 89: a TALLER, MULTI-LINE version of stock's own BLOCK toast ----
|   Report #11 reverted Session 88's card: "I want the toasts to NOT be in cards. I want
|   them to be in the form of the previously used larger block toasts. But we need
|   1) TRK SEQ + PART, RELOADED and 2) TRK SEQ RELOADED, SAVE PART FIRST! each on two
|   lines (enlarge toast vertical size)."
|
|   Decoded stock TOAST (FUN_4005a2b8) -- the block toast in question:
|     width  = measured text width + 15          (0x4005a2f2)
|     height = 0x12                              (0x4005a2ee)
|     style  = 0xa   <- the BLOCK look. 4 is the card look Session 88 used.
|     slot     0x460d1e70, its OWN, separate from SHOW_WIN's 0x460d1e5c
|     countdown 0x460d1e6c = dur                 (0x4005a328)
|     dismiss  0x40056bec                        (also its onClose)
|     one line, centred at y = height-11, drawn by FUN_40057008
|
|   Two measured properties of that slot matter, and both are why this is the safer
|   mechanism of the two:
|     * its tick (0x40056c28) reads the countdown DIRECTLY -- `tstl 0x460d1e6c ; beq
|       rts` -- with NO enabling flag. The SHOW_WIN slot's tick is gated on CD_FLAG at
|       0x40056abe, and clearing that by mistake is exactly what would have left Session
|       88's card on screen forever. No such trap exists here.
|     * the countdown DOTS come from 0x40037cc8, which reads the SHOW_WIN slot ONLY.
|       Nothing on the toast path can reach it, so a block toast cannot show dots --
|       which is what report #11 also asked for ("not have countdown dots anywhere").
|   Stock has no multi-line block toast to borrow: the only other 0x4005a2b8-alike
|   (0x4005a160) is a sprintf wrapper with the same 0x12 height and a single line.
    .equ TOAST_SLOT,     0x460d1e70     | the toast's own window handle
    .equ TOAST_CD,       0x460d1e6c     | its countdown; set it and it self-dismisses
    .equ TOAST_DISMISS,  0x40056bec     | tears the toast down (also its onClose)
    .equ TOAST_H1,       0x12           | stock's height for ONE line
    .equ TOAST_STYLE,    0xa            | the BLOCK look (4 would be the card)
    .equ FONT_TOAST,     0x400ba862     | the font stock measures AND draws the toast in
    .equ WIN_NEW,        0x4005829c     | (w,h,x,y,style,onClose) -> handle
    .equ WIN_DRAW1,      0x40057008     | (handle, text, top, font): clears the window
                                        | and centres `text` at y = height-11
    .equ DRAWTEXT,       0x40012bd8     | (font, winptr, x, y, len, text)
    .equ TEXTW,          0x40012f30     | (font, maxlen, text) -> pixel width
    .equ BANK_LAYER,     0x400cff14     | the [BANK] overlay keymap layer struct
    .equ BANK_UI_A,      0x4007e760     | the two UI calls the press tail makes AFTER
    .equ BANK_UI_A_ARG,  0x400cff28     | LAYER_PUSH; BANK_WIN_CLOSE pairs them with
    .equ BANK_UI_B,      0x4007e998     | 0x4007e81c.
|   ** Checked, because the opening tap calls BANK_UI_A TWICE -- once in our press
|   replication and once when the release replays the tail -- while 0x4007e81c runs only
|   once in the teardown. That is safe: 0x4007e760 is the SAME idempotent linked-list
|   push shape as LAYER_PUSH, on head 0x460e7624. It early-exits to 0x4007e810 when the
|   struct is already the head (0x4007e780) or already in the list (0x4007e788), so the
|   second call is a no-op, and 0x4007e81c's single unlink is therefore correctly paired.
|   Every list this deferral touches is idempotent-push / safe-pop; that is what makes
|   replaying stock's tail legitimate rather than lucky. **
    .equ BANK_SHOW_TAIL, 0x4007af30     | stock's own show sequence, replayed on release
    .equ BANK_REL_RES,   0x4007b3e8     | release handler, past the 2 displaced insns
                                        | (lands on its own beq, so the cmp must stand)
|   Session 90, hardware report #13: "the toasts need to be visible a little longer.
|   Whatever the next higher value used in stock OT is (still less than 1 second)."
|   MEASURED across every stock FUN_4005a2b8 call site: 0x30 x87, 0x44 x3, 0x5a x2,
|   0x60 x7, 0x78 x1. So 0x30 is not merely the next value up from our 0x18 -- it is
|   stock's overwhelmingly standard toast duration. (0x18 was never a stock value at
|   all; an earlier note in this file claimed it was "stock's duration for this
|   family", which the measurement disproves.) At the UI tick rate 0x30 lands close to
|   0.8 s, inside the "less than 1 second" the report asks for; the next stock step up,
|   0x44, would be past it.
    .equ TOAST_DUR,      0x30           | 48 ticks -- stock's standard toast duration
                                        | (0x4005e09c). RELOAD2 used 0x44; this is the
                                        | "OT standard" the spec asks for.

| ================= [PTN] + [TRACK n] -- reload that track's CF-saved sequence =================
| The Part is NOT touched. Toast "TRK SEQ RELOADED".
| Releasing [PTN] afterwards must not raise SELECT PATTERN -- achieved with stock's
| OWN mechanism rather than a detour on the [PTN] handler: set PTN_CONSUMED, which
| stock's release path already tests and skips the window on.
| Displaces 6 B: move.l %d2,-(%sp) ; move.l 8(%sp),%d2
|
| 16 Oct 2026: the eight stock refs to this site are CUE's sub-map TRACK slots
| (0x400bf122), not a [PTN] overlay. Without a PTN held gate, [CUE]+[TRACK n]
| reloaded and toasted "TRK SEQ RELOADED". [PTN]+[TRACK] still mostly arrives
| through rl3_bank_trk (base TRACK + PTN_HELD_FLAG); this site stays as a
| secondary route for any context that does land here with PTN held.
    .global rl3_ptn_trk
rl3_ptn_trk:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0                 | event == press ?
    bne.w   r3p_stock
    move.b  KROWS+(KPTN>>3),%d0        | panel row for PTN (not the key-cache
    btst    #(KPTN&7),%d0              | field: that is sticky for sub-map keys)
    beq.w   r3p_stock                  | [CUE]+[TRACK] (etc.): stock, no reload
    moveq   #0,%d0
    move.b  7(%sp),%d0                 | low byte of the keycode long at 4(sp)
    bsr.w   rl3_do_ptn
    rts                                | swallow: stock's [PTN]+[TRACK] does nothing
                                       | observable on hardware (user-confirmed)
r3p_stock:
    move.l  %d2,-(%sp)                 | displaced original
    move.l  8(%sp),%d2                 | displaced original (reads the pre-push 4(sp))
    jmp     PTN_TRK_RES

| ============ 2026-11-08 (2): the [PTN] + [BANK] chord ============
| [PTN] key handler 0x4005a044 (press, release, hold), replaces 6 B: move.l 8(sp),%d0 ; moveq #1,%d1.
| Only a PRESS with [BANK] already held (and nothing picked under it, BANK_SEL 0) is ours: stock's
| press runs as usual (it pushes [PTN]'s layers ON TOP), then [BANK]'s keymap layer goes back on top
| and rl3_chord marks the gesture. Everything else is stock, byte for byte.
    .global rl3_ptn_key
rl3_ptn_key:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0
    bne.b   r3k_stock                  | release / hold: stock
    tst.l   BANK_HELD_FLAG
    beq.b   r3k_stock
    tst.l   BANK_SEL
    bne.b   r3k_stock                  | a bank picked under [BANK]: stock's state, leave it
    move.l  8(%sp),-(%sp)              | event
    move.l  8(%sp),-(%sp)              | code
    bsr.b   r3k_stock                  | stock's own press (it ends in jmp 0x40027de4 -> rts here)
    addq.l  #8,%sp
    pea     BANK_LAYER
    jsr     LAYER_POP
    addq.l  #4,%sp
    pea     BANK_LAYER
    jsr     LAYER_PUSH                 | [BANK]'s trigs on top again
    addq.l  #4,%sp
    bsr.w   rl3_chord
    rts
r3k_stock:
    move.l  8(%sp),%d0                 | displaced
    moveq   #1,%d1                     | displaced
    jmp     PTN_KEY_RES

| rl3_chord: the chord is complete (its second key's press). Both releases silent, the grid on the
| patterns. UI task; d0/d1/a0/a1 only.
rl3_chord:
    moveq   #-1,%d0
    move.l  %d0,PTN_CONSUMED           | [PTN]'s release: teardown only (stock's -1, 0x40056b44)
    moveq   #1,%d0
    move.b  %d0,rl3_bank_used          | [BANK]'s release: ours, teardown only
    clr.l   BANK_COMMIT
    pea     PTN_LEDL
    jsr     LED_POP
    addq.l  #4,%sp
    pea     PTN_LEDL
    jsr     BANK_UI_A                  | 0x4007e760: [PTN]'s LED layer on top
    addq.l  #4,%sp
    clr.l   -(%sp)
    jsr     BANK_UI_B                  | 0x4007e998(0): repaint the grid
    addq.l  #4,%sp
    rts

| [BANK]-layer trig press 0x4007b2fc, replaces 8 B: move.l %a2,-(%sp) ; move.l %d2,-(%sp) ;
| move.l 12(%sp),%d2. With [PTN] held too (and no bank picked): reload pattern N, swallow. Its
| release 0x4007b434 does nothing while BANK_SEL != 2, so swallowing the press is the whole of it.
    .global rl3_bank_trig
rl3_bank_trig:
    tst.l   PTN_HELD_FLAG
    beq.b   r3t_stock
    tst.l   BANK_HELD_FLAG
    beq.b   r3t_stock
    tst.l   BANK_SEL
    bne.b   r3t_stock
    moveq   #0,%d0
    move.b  7(%sp),%d0
    andi.l  #15,%d0
    bsr.w   rl3_do_pat
    rts
r3t_stock:
    move.l  %a2,-(%sp)                 | displaced
    move.l  %d2,-(%sp)                 | displaced
    move.l  12(%sp),%d2                | displaced
    jmp     BANK_TRIG_RES

| rl3_do_pat (d0 = N): arm the pattern reload and post the job (Session 93: the message first).
| Not with the arranger running, nor over a blocking dialog (CLYPS' gate), nor while a request of
| ours is still waiting for the worker (G_KIND != 0: a second post would overwrite it).
rl3_do_pat:
    tst.l   ARR_ACT
    bne.w   r3d_out
    tst.l   POPUP
    bne.w   r3d_out
|   2026-11-08 (3): through rl_req -- a new generation; the toast is chosen when it lands
    moveq   #RQ_PTN,%d1
    jsr     rl_req
r3d_out:
    rts

| ============ [BANK] + [TRACK n] -- the sequence PLUS the track's Part slice, from the card ============
| Toast "TRK FULL" / "RELOADED FROM PROJ" (2026-11-08; see r3b_try_bank).
| Displaces 6 B: move.l %d2,-(%sp) ; move.l 8(%sp),%d1
    .global rl3_bank_trk
rl3_bank_trk:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0                 | event == press ?
    bne.w   r3b_stock
|   Session 85: BOTH chords are tested here, because the [PTN] overlay was measured
|   NOT to redirect the TRACK keys (see PTN_HELD_FLAG). This is the [PTN]+[TRACK]
|   route. rl3_ptn_trk (0x40083dc4) is [CUE]'s sub-map TRACK handler, not [PTN]'s
|   (16 Oct 2026); it reloads only when [PTN] is held too, through the same body.
    tst.l   PTN_HELD_FLAG
    beq.b   r3b_try_bank
|   2026-11-08 (2): with BOTH modifiers held a TRACK key reloads nothing -- it changes the track, as
|   stock (CLYPS' exclusive modifiers, the user 2026-10-30)
    tst.l   BANK_HELD_FLAG
    bne.w   r3b_stock
    moveq   #0,%d0
    move.b  7(%sp),%d0
    bsr.w   rl3_do_ptn
    rts
r3b_try_bank:
    tst.l   BANK_HELD_FLAG
    beq.w   r3b_stock                  | neither modifier -> ordinary track select
|   ===== 2026-11-08: the sequence AND this track's Part slice, from the CARD, in one job. =====
|   Until now this chord ran stock's PART RELOAD (0x4004aab4) here and then a sequence job: that
|   put back the WHOLE Part, from its SAVE PART copy in RAM ("SAVE PART FIRST!" when there was
|   none), so every other track on the Part reverted too. The user asked for what CLYPS' card
|   reload does (scope §1.8, 2026-10-30): track n's sequence + track n's slice of the Part (machine,
|   FX, levels, every page, scene locks, LFO designer) as the PROJECT was saved -- the working Part
|   chunk of the bank file. Every other track, and the rest of the Part, untouched. The whole job
|   runs in the worker (rl_full); the UI half (PICKUP setup, the page redraw) in rl_done.
|   Session 93's rule still holds: the message is armed BEFORE the job is posted, the post LAST.
|   d2 belongs to stock's caller on this path (we rts): only d0/d1.
    moveq   #1,%d0
    move.b  %d0,rl3_bank_used          | claim the [BANK] release: rl3_bank_rel swallows
                                       | it AND runs the overlay teardown there, so the
                                       | teardown happens exactly once, on the release.
    moveq   #0,%d0
    move.b  7(%sp),%d0
    subi.l  #0x10,%d0                  | TRACK keycodes 0x10..0x17 -> index 0..7
    moveq   #RQ_TRKFULL,%d1
    jsr     rl3_arm_n                  | the request (rl_req); the toast when it lands
r3b_done:
|   Belt and braces for the release. rl3_bank_used above is what actually swallows it;
|   clearing BANK_COMMIT means that even if that flag were somehow missed, the release
|   takes stock's DISMISS path rather than showing a window (rl3_bank_rel only shows
|   when BANK_COMMIT is set). Session 86: SELECT BANK no longer opens on the PRESS at
|   all, so there is nothing left to flash before the chord completes.
    clr.l   BANK_COMMIT
    rts
r3b_stock:
    move.l  %d2,-(%sp)                 | displaced original
    move.l  8(%sp),%d1                 | displaced original (reads the pre-push 4(sp))
    jmp     TRK_BASE_RES

| ---- rl3_do_ptn: d0 = TRACK keycode. The [PTN]+[TRACK] body, shared by both routes ----
| Reloads that track's sequence, leaves the Part alone, and sets stock's own
| "gesture consumed" flag so stock's [PTN] release path skips SELECT PATTERN.
rl3_do_ptn:
    subi.l  #0x10,%d0                  | TRACK keycodes are 0x10..0x17 -> index 0..7
|   2026-11-08 (3): the message is no longer armed here -- rl_follow chooses it from what landed
    moveq   #RQ_TRKSEQ,%d1
    jsr     rl3_arm_n                  | the request (rl_req)
    move.l  #-1,%d0
    move.l  %d0,PTN_CONSUMED           | same value stock writes at 0x40056b44
|   Session 88 item 4: this used to be the big block TOAST (FUN_4005a2b8). It is now
|   the same card as the [BANK] message, at the user's request, so both reload
|   messages look alike.
    rts

| ---- rl3_toast2(lines[], nlines) -- the SAME block toast, but taller, multi-line ----
| Stock has no multi-line block toast (checked: the only other 0x4005a2b8-alike at
| 0x4005a160 is a sprintf wrapper with the same 0x12 height and one line), so this
| rebuilds it from the parts stock's own toast uses, changing only the height and the
| number of centred lines:
|
|   stock TOAST  : WIN_NEW(textw+15, 0x12,            0,0, 0xa, TOAST_DISMISS)
|   rl3_toast2   : WIN_NEW(maxw+15,  0x12 + 7*(n-1),  0,0, 0xa, TOAST_DISMISS)
|
| Same style (0xa = the block look), same font, same margin, same slot (0x460d1e70),
| same dismiss, same countdown. The LAST line is drawn by stock's own WIN_DRAW1, which
| clears the window and centres the text at y = height-11 -- i.e. exactly where a
| one-line toast puts it -- and earlier lines are stacked 7 px above with the same
| centring maths. So a 1-line call is indistinguishable from stock, and a 2-line call
| is stock's toast grown upward by one row.
| No OK prompt (no keymap layer is pushed) and no countdown dots (those belong to the
| SHOW_WIN slot's 0x40037cc8, which is never involved here).
rl3_toast2:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)      | 40 B saved; ret at 40(sp), args at 44/48
    move.l  44(%sp),%a4                | a4 = lines[]
    move.l  48(%sp),%d7                | d7 = nlines
|   Replace a toast already on screen, exactly as stock TOAST does at 0x4005a2c4.
    tst.l   TOAST_SLOT
    beq.b   rt2_noprev
    jsr     TOAST_DISMISS
rt2_noprev:
|   --- width = widest line + 15 (stock's own margin, 0x4005a2f2) ---
    moveq   #0,%d6
    moveq   #0,%d5
rt2_wloop:
    cmp.l   %d7,%d5
    bge.b   rt2_wdone
    move.l  %d5,%d0
    lsl.l   #2,%d0
    move.l  (%a4,%d0.l),%a0
    bsr.w   rt2_measure
    cmp.l   %d6,%d0
    ble.b   rt2_wnext
    move.l  %d0,%d6
rt2_wnext:
    addq.l  #1,%d5
    bra.b   rt2_wloop
rt2_wdone:
    addi.l  #15,%d6
|   --- height = 0x12 + 7*(n-1): stock's height, one extra row per extra line ---
    move.l  %d7,%d0
    subq.l  #1,%d0
    move.l  %d0,%d1
    lsl.l   #3,%d0
    sub.l   %d1,%d0                    | 7*(n-1)
    addi.l  #TOAST_H1,%d0
    move.l  %d0,%d4                    | d4 = height
    pea     TOAST_DISMISS
    pea     TOAST_STYLE
    clr.l   -(%sp)
    clr.l   -(%sp)
    move.l  %d4,-(%sp)
    move.l  %d6,-(%sp)
    jsr     WIN_NEW
    lea     24(%sp),%sp
    tst.l   %d0
    beq.w   rt2_out                    | no slot free -- say nothing rather than fault
    move.l  %d0,TOAST_SLOT
    move.l  %d0,%a3                    | a3 = handle
|   --- line 0 through stock's own path: clears the box and centres it at y = h-11 ---
|   ** Line ORDER. y counts UP from the bottom, so line 0 must take the HIGHEST y. **
|   That is settled by stock's own three-line message, whose reading order is fixed --
|   "THIS BANK HAS NEVER" / "BEEN SAVED!" / "NOTHING TO RELOAD!" (0x40023c20): MLNOTIFY
|   draws line i at H-17-7i, so line 0 has the greatest y and is the top line. An
|   earlier version of this routine drew line 0 LAST, at the lowest y, which would have
|   printed "RELOADED" above "TRK SEQ + PART".
|   So line 0 goes at h-11 -- exactly where a one-line toast puts its text -- and each
|   later line sits 7 px lower. For n=1 that is stock's geometry unchanged.
    pea     FONT_TOAST
    clr.l   -(%sp)
    move.l  (%a4),-(%sp)               | lines[0]
    move.l  %a3,-(%sp)
    jsr     WIN_DRAW1                  | FUN_40057008(handle, text, 0, font)
    lea     16(%sp),%sp
|   --- lines 1..n-1, each 7 px lower, same centring maths ---
    move.l  %a3,%d3
    addi.l  #36,%d3                    | d3 = winptr, as stock passes to DRAWTEXT
    moveq   #1,%d2
rt2_dloop:
    cmp.l   %d7,%d2
    bge.w   rt2_done                   | n==1 -> nothing extra to draw
    move.l  %d2,%d0
    lsl.l   #2,%d0
    move.l  (%a4,%d0.l),%a2
    move.l  %a2,%a0
    bsr.w   rt2_measure
    move.l  %d6,%d1
    sub.l   %d0,%d1
    bpl.b   rt2_xok
    moveq   #0,%d1                     | wider than the box -- clamp left
rt2_xok:
    asr.l   #1,%d1                     | x = (boxwidth - textwidth)/2  -> centred
    move.l  %d2,%d0
    move.l  %d0,%d5
    lsl.l   #3,%d0
    sub.l   %d5,%d0                    | 7*i
    move.l  %d4,%d5
    subi.l  #11,%d5
    sub.l   %d0,%d5                    | y = height-11 - 7*i  (line 0 highest, so on top)
    move.l  %a2,-(%sp)
    move.l  #-1,-(%sp)
    move.l  %d5,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %d3,-(%sp)
    pea     FONT_TOAST
    jsr     DRAWTEXT                   | FUN_40012bd8(font, winptr, x, y, len, text)
    lea     24(%sp),%sp
    addq.l  #1,%d2
    bra.w   rt2_dloop
rt2_done:
    moveq   #1,%d0
    move.l  %d0,RDRAW
    .ifdef RL_DIAG
    move.l  #DIAG_DUR,%d0              | diag build: hold the hex on screen for 6 s
    .else
    move.l  #TOAST_DUR,%d0
    .endif
    move.l  %d0,TOAST_CD               | stock's toast countdown. NO gate flag on this
                                       | one (0x40056c28 tests it directly), and no
                                       | dots -- unlike the SHOW_WIN slot's timer.
rt2_out:
    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    rts

| a0 = text -> d0 = raw pixel width. Clobbers d0/d1/a0/a1 only.
rt2_measure:
    move.l  %a0,-(%sp)
    move.l  #-1,-(%sp)
    pea     FONT_TOAST
    jsr     TEXTW                      | FUN_40012f30(font, maxlen, text)
    lea     12(%sp),%sp
    rts

| ---- rl3_show2: a0 = lines[], always 2 lines ----
| ** Push order matters and got it wrong once. ** rl3_toast2's first argument is
| lines[], so lines[] must be pushed LAST (it ends up at the lower address). Pushing
| a0 first put the literal 2 in a4 and a pointer in the line COUNT, which faulted
| immediately (UC_ERR_READ_UNMAPPED, caught by diag_reload3_toast.py).
rl3_show2:
    pea     2                          | nlines  (second arg -> higher address)
    move.l  %a0,-(%sp)                 | lines[] (first arg  -> lower address)
    jsr     rl3_toast2
    addq.l  #8,%sp
    rts

| ============ Session 120: the Part-reload UI refresh ============
| Hardware (OBKYOTI6): after [BANK] + [TRACK n] the Part's values were live and audible but
| the knobs still showed their pre-reload positions until a page press or a transport stop.
| PART_RELOAD (FUN_4004aab4) changes the values only. Stock's own Part-reload shortcut
| (key 0x2a -> FUN_4005e038, the same key-handler context as this chord) follows it with
| a toast and then, from 0x4005e0a8: RDRAW = 1; pea -1; FUN_4004d948, FUN_40032208,
| FUN_4004d640, FUN_400486cc, FUN_4006dbe8, FUN_40077b00, FUN_4002f2f8; lea 12(sp),sp;
| unlk fp; rts. We run THAT code, not a copy: `link fp,#-8` gives it the frame it expects
| (its lea 12 pops its own -1 plus our 8 bytes, so sp is back at fp before unlk, with
| nothing below sp at any point), and its unlk/rts return here. 2026-11-08: called from rl_done
| (the UI task, after a [BANK] + [TRACK n] slice landed), no longer from the chord. The calls are C
| functions: d2-d7 and a2-a6 survive; the caller needs none of d0/d1/a0/a1 afterwards.
rl3_part_refresh:
    link.w  %fp,#-8
    jmp     PART_RFRSH

| ============ SELECT BANK: shown on RELEASE, not on PRESS ============
| Gate spliced into stock's shared show tail at 0x4007af42. A [BANK] PRESS reaches it
| with the gate CLOSED and simply returns, so no window and no overlay layer. The
| release below opens the gate for exactly one pass and then calls the very same tail,
| so what the user sees is stock's own window, stock's own duration, stock's own
| teardown -- just one event later. Displaces 6 B: pea %pc@(0x4007b408) ; clr.l -(%sp)
    .global rl3_bank_show
rl3_bank_show:
    tst.b   rl3_showing
    bne.b   r3s_do
|   ===== PRESS: defer the WINDOW, but still push the overlay LAYER. =====
|   ** This is the whole reason the Session 80 attempt failed, and it is not a
|   cosmetic detail. ** The [BANK] overlay is what remaps the 16 TRIG keys to
|   bank-select while [BANK] is held -- that IS the "hold [BANK], tap a trig to pick a
|   bank" gesture. Skipping the tail wholesale (which is what deferring the window
|   naively does) leaves the trigs on their BASE handler 0x40060ce0, so holding [BANK]
|   and tapping a trig would EDIT THE SEQUENCE instead of changing bank -- silent and
|   destructive.
|   Stock [PTN] is the existence proof for the shape the user asked for: its press
|   pushes its overlay and shows NOTHING, and SELECT PATTERN appears on the release.
|   So mirror that exactly -- push the layer, skip only SHOW_WIN.
|   Nothing has been pushed on the stack at this point (the tail's three clears push
|   nothing and the handler has no prologue), so we replicate the tail's post-window
|   remainder with balanced cleanup of our own and return.
    pea     BANK_LAYER
    jsr     LAYER_PUSH                 | idempotent (0x400314b4/0x400314b8), so the
    addq.l  #4,%sp                     | release's replay of the tail cannot double-link
    pea     BANK_UI_A_ARG
    jsr     BANK_UI_A
    addq.l  #4,%sp
    clr.l   -(%sp)
    jsr     BANK_UI_B
    addq.l  #4,%sp
|   2026-11-08 (2): [PTN] already held -> the chord ([BANK]'s layer is on top already)
    tst.l   PTN_HELD_FLAG
    beq.b   r3s_out
    bsr.w   rl3_chord
r3s_out:
    rts
r3s_do:
    clr.b   rl3_showing                | one-shot -- re-close behind us immediately
    pea     BANK_TEARDOWN              | displaced (was pc-relative; same value)
    clr.l   -(%sp)                     | displaced
    jmp     BANK_PRESS_RES

| [BANK] RELEASE. Displaces 8 B: moveq #2,%d0 ; cmp.l 0x460e73c6,%d0
|
| ** This is not an invented shape -- it is stock [PTN]'s own release, transplanted. **
| Stock's [PTN] release (0x4005a084..0x4005a0ca) reads:
|     tstl 0x460d173e          | was the gesture consumed?
|     bnes -> 0x4005a0be       |   yes: clrl PTN_MODE ; jsr 0x40043418  <- teardown
|                              |        called DIRECTLY, and NO window is shown
|     ...                      |   no:  pea 0x40043418 (teardown as onClose)
|     jsr 0x40059f8c           |        SHOW_WIN -- i.e. the window opens on the RELEASE
| So stock already does, for [PTN], exactly the two things this build needs for [BANK]:
| the show lives on the release, and the consumed path calls the teardown itself rather
| than relying on a window that was never opened. Every branch below is that same
| structure with [BANK]'s own teardown (BANK_WIN_CLOSE) substituted. That is also why
| the user's "like PTN does" was the right instinct: the mechanism was already there.
    .global rl3_bank_rel
rl3_bank_rel:
    tst.b   rl3_bank_used
    beq.b   r3r_notours
    clr.b   rl3_bank_used              | our chord owned this gesture: swallow it whole
|   No window was ever shown, so nothing else will pop the overlay the press pushed.
|   Do it here -- this is the same measured teardown, and it balances BANK_UI_A.
    jsr     BANK_WIN_CLOSE
    rts                                | -- no SELECT BANK, no countdown, nothing
r3r_notours:
|   ===== Hardware report #14: a pick during the hold must cancel the release show. =====
|   Gesture: hold [BANK], tap a trig to pick a bank, tap a trig to pick a pattern,
|   release [BANK] -- and SELECT BANK appeared with its countdown. Obviously wrong: the
|   prompt asks for something the user has already supplied, and it lands on top of the
|   window the pick itself put up.
|   MEASURED at the [BANK]-overlay trig handler 0x4007b2fc. BANK_SEL is that gesture's
|   own progress counter, and it is the only state that distinguishes "nothing picked"
|   from "picked":
|       0  nothing picked yet   -- the show tail 0x4007af30 clears it on every press
|       1  a BANK was picked    -- set at 0x4007b276, together with BANK_COMMIT=1 at
|                                  0x4007b33c, and a "SELECT PATTERN IN BANK x" window
|                                  of its own (SHOW_WIN at 0x4007b2b0, onClose 0x4007b408)
|       2  a PATTERN was picked -- set at 0x4007b3d2 at the end of the pattern branch
|   Stock's release (0x4007b3e0) opens with exactly this test -- cmpl BANK_SEL,#2 then
|   beq to DISMISS -- BEFORE it looks at BANK_COMMIT. Our release inverted that order, so
|   BANK_COMMIT (set by the pick itself, or by the hold handler at 0x4007af24) sent us to
|   r3r_show and the pick was never noticed. Restoring stock's ordering is the whole fix.
|
|   Both non-zero values want stock's own tail, which is why this branches there rather
|   than handling them:
|     * 2 -> our displaced compare below succeeds and BANK_REL_RES's beq takes the
|            DISMISS path (0x40056a70), closing the pick's window and running ITS onClose
|            (0x4007b408) -- the same teardown, so the overlay is popped exactly once.
|     * 1 -> falls past the compare to stock's BANK_COMMIT test, which sets the sticky
|            flag and keeps the overlay live so a pattern can still be picked after the
|            release. That is stock's untimed window, unchanged.
|   Note this also covers the un-reported half: releasing after picking only a bank would
|   have drawn SELECT BANK over "SELECT PATTERN IN BANK x". Both are gone with one test.
    tst.l   BANK_SEL
    bne.b   r3r_stock                  | something was picked during the hold: stock's
                                       | own release logic already does the right thing
    tst.l   BANK_COMMIT
    bne.b   r3r_show
|   ===== Session 91: this guard used to test the WRONG VARIABLE. =====
|   Toggle-OFF tap: no window of ours to open, but the PRESS pushed the [BANK] trig
|   overlay, so somebody has to pop it. The old code skipped its own teardown whenever
|   POPUP (0x460e5cd0) was non-zero, "because stock's own dismiss will run onClose".
|   Both halves of that were wrong:
|     * POPUP is MLNOTIFY's OWN handle. It says nothing about whether stock's dismiss
|       will run an onClose -- that depends on the SHOW_WIN slot, a different subsystem.
|     * stock's dismiss (0x40056a70) bails immediately at 0x40056a76 when WIN_SLOT is
|       zero, and WIN_SLOT/WIN_ONCLOSE are written ONLY inside SHOW_WIN (0x40059fe4 /
|       0x4005a006). Our press deliberately shows no window, so in the case the guard
|       was aimed at, nothing called the teardown at all and the overlay stranded --
|       leaving the trig keys meaning "pick a bank" until something else rebuilt the
|       keymap. That is octalab's documented failure mode.
|   ** And it IS reachable, which I first argued it was not. ** The near-miss argument
|   was "BANK_COMMIT==0 implies 0x460e73bc was set, which implies a window had been
|   shown, so WIN_SLOT would be non-zero anyway". Wrong: 0x460e73bc has a writer at
|   0x4007b2b6, in the bank-select/trig handler, with no SHOW_WIN involved -- so the
|   sticky flag can be set with the slot empty. Measured, not reasoned.
|
|   So test what actually decides it: is a window in the slot, and is ITS onClose our
|   teardown? Only then may we leave the job to stock and avoid a double teardown
|   (0x4007e81c would otherwise run twice against one 0x4007e760).
    move.l  WIN_SLOT,%d0
    beq.b   r3r_pop                    | nothing in the slot -> nobody else will do it
    move.l  #BANK_TEARDOWN,%d0
    cmp.l   WIN_ONCLOSE,%d0
    beq.b   r3r_stock                  | stock's dismiss will run OUR teardown -> let it
r3r_pop:
    jsr     BANK_WIN_CLOSE             | the measured teardown: pops the layer and
    bra.b   r3r_stock                  | balances BANK_UI_A with 0x4007e81c
r3r_show:
    moveq   #1,%d0
    move.b  %d0,rl3_showing            | open the gate for exactly one pass
    jsr     BANK_SHOW_TAIL             | jsr, not bsr: the tail is ~0x27000 away, far
                                       | outside bsr.w range. It ends lea 28(sp),sp/rts
                                       | and cleans up exactly its own pushes. From here
                                       | the WINDOW owns the layer again, as in stock.
r3r_stock:
    moveq   #2,%d0                     | displaced #1
    cmp.l   BANK_SEL,%d0               | displaced #2 -- must stand, BANK_REL_RES is
                                       | stock's own beq on this very compare
    jmp     BANK_REL_RES

    .align 2
|   2026-11-08: CLYPS' card-reload toasts (the user, 2026-10-30 / 11-02: two lines, no track
|   number; "RELOADED FROM PROJECT" is 123 px, wider than a toast line holds, so PROJ). The old
|   "TRK SEQ RELOADED" / "TRK SEQ + PART" / "RELOADED" / "SAVE PART FIRST!" set is gone with the
|   RAM Part reload.
rl3_lines_seq:
    .long   rl3_s_seq                  | 1 = [PTN]  + [TRACK n]
    .long   rl3_s_proj
rl3_lines_full:
    .long   rl3_s_full                 | 2 = [BANK] + [TRACK n]
    .long   rl3_s_proj
|   Session 93: shown when the verify in rld_skip finds the copy did not hold. Two lines
|   so it cannot be mistaken for the success message at a glance.
rl3_lines_lost:
    .long   rl3_msg_lost1              | 4
    .long   rl3_msg_lost2
|   2026-11-08: [BANK] + [TRACK n] read the sequence but not the Part chunk (a card error after
|   the sequence had landed): say exactly that.
rl3_lines_nopart:
    .long   rl3_s_seqonly              | 5
    .long   rl3_s_nopart
rl3_lines_ptn:
    .long   rl3_pline                  | 6 = "PATTERN A05" / "RELOADED FROM PROJ"
    .long   rl3_s_proj
rl3_lines_ptnnp:
    .long   rl3_pline                  | 7 = "PATTERN A05" / "PART NOT READ!"
    .long   rl3_s_nopart
rl3_msgtab:
    .long   rl3_lines_seq, rl3_lines_full, rl3_lines_lost, rl3_lines_lost
    .long   rl3_lines_nopart, rl3_lines_ptn, rl3_lines_ptnnp
rl3_s_seq:
    .asciz  "TRK SEQ"
rl3_s_full:
    .asciz  "TRK FULL"
rl3_s_proj:
    .asciz  "RELOADED FROM PROJ"
rl3_msg_lost1:
    .asciz  "SEQ RELOAD LOST"
rl3_msg_lost2:
    .asciz  "NOT RESTORED!"
rl3_s_seqonly:
    .asciz  "TRK SEQ RELOADED"
rl3_s_nopart:
    .asciz  "PART NOT READ!"
rl3_fmt_ptn:
    .asciz  "PATTERN %c%02d"
    .align 2
rl3_pline:
    .space  24

| ---- rl_arm_trk: arm a TRK SEQ reload of the currently-addressed track ----
| Reads CUR_TRACK (0x80000000) + MIDI_MODE (0x80000012), sets G_TRK / G_TMIDI /
| G_PAT / G_KIND=3, posts FUN_40022778(1<<curbank).  Clobbers d0/d1 only
| (preserves d2 -- rl_yes still needs G_SEL there).  Also the entry point for the
| (unbuilt) [PTN]+[TRACK] power move.
    .global rl_arm_trk
rl_arm_trk:
    moveq   #0,%d0
    move.b  CUR_TRACK,%d0
    moveq   #RQ_TRKSEQ,%d1
|   Session 85: the chord design knows WHICH track from the keycode, so it enters
|   here with the index already in d0 instead of reading the UI-selected track.
|   Everything below is the proven rl_arm_trk tail; 2026-11-08: d1 = the kind (RQ_TRKSEQ /
|   RQ_TRKFULL), written to G_KIND below exactly where the fixed 3 used to be.
    .global rl3_arm_n
rl3_arm_n:
|   2026-11-08 (3): d0 = the track key 0..7, d1 = the kind -> rl_req (the MIDI side: tracks 8..15)
    andi.l  #7,%d0
    tst.l   MIDI_MODE                  | a LONG (2026-10-25: a byte read saw its high byte, always 0)
    beq.b   rat_aud
    addq.l  #8,%d0
rat_aud:
    jmp     rl_req

| ===== suppress the stock WHOLE-BANK reload our own job would otherwise cause =====
| Session 80 continued (4). MEASURED by tools/diag_reload2_deser.py on the real
| storage task -- this is not a static read:
|
|   rl_job -> parse_pattern (our 1 slice) -> JOB14_EXIT -> job_doneFn
|     -> 0x400a69e0 -> WHOLE_BANK_DESER (from 0x40090730)
|     -> PUSH_LAYER 0x400d0bc4 ("RELOADING BANK") -> parse_pattern x16 -> POP_LAYER
|
| The type-0x14 job IS stock's RELOAD BANK, and its doneFn (0x40023bf4) performs
| the real reload: 16 pattern parses straight off the card, no matter what our
| worker did. So every RELOAD2 action was followed by a full bank reload -- the
| "just under a second" stall and the sequencer restart the user reported (issue
| #2), and the reason the per-track slice was only nominally per-track:
| everything else in the bank reverted a moment later too.
|
| ** FINDING THE RIGHT CALL TOOK TWO TRIES -- the first was wrong. ** doneFn
| opens with `bsr.w 0x40022e04` ; `jsr 0x40080844` (0x40023c00/0x40023c04), and
| 0x40080844 looks like "reload the bank" -- the 0x400d0bc4 overlay push/pop sit
| at 0x4008092c / 0x4008086a, numerically right inside it. Detouring that site
| changed NOTHING: the trace came back byte-identical, with our hook entered and
| the flag consumed. The counters gave it away -- 0x40022e04 and 0x40080844 each
| ran TWICE, and the reload is in the SECOND pair, reached from the SUCCESS path:
|
|   0x40023c0e  bge.s 0x40023c62          ; result >= 0
|   0x40023c62  mvz.w 0x460bd910,d0       ; the bank mask (stashed at buf-2)
|   0x40023c68  move.l d0,-(sp) ; pea 0x100f8378
|   0x40023c70  bsr.w 0x40023b68          ; <-- THE reload
|
| "Numerically near 0x40080844" is not "inside 0x40080844", and that assumption
| cost a full emulator run. Suppress the success path instead: with the flag set,
| jump straight to doneFn's own epilogue, so 0x40023b68 never runs.
|
| The 0x400d0bc4 overlay's push AND pop both live inside the suppressed subtree
| (measured: balance 0), so skipping it leaves the keymap layer stack balanced --
| the layer is simply never pushed.
|
| ** The flag is a ONE-SHOT, set only by rl_job on the path that handled OUR job,
| so a genuine stock RELOAD BANK the user asks for is never suppressed. **

| ** BACKED OUT in Session 80 continued (5); RE-ENABLED in Session 83. **
|
| Session 83 rationale for the retry -- this is NOT a blind repeat. "(5)"'s three
| hardware symptoms were: [BANK]+[YES] "hardly ever executes", [YES] "almost
| always" RELOAD BUSY, and stock [BANK] dying after a few attempts. The first two
| are now known to have had INDEPENDENT causes that have since been found and
| fixed on their own: "(6)" fixed [YES] being swallowed while [BANK] was still
| held (that IS the "hardly ever executes" report), and "(8)"/"(9)" fixed the
| layer-routing and walk-away bugs that left the picker primed and the YES slot
| shadowed. So the build "(5)" condemned carried at least two confounders that no
| longer exist, and the evidence that rl_done itself was the culprit -- "the
| previous flash was clean and only these two changes were added" -- is much
| weaker than it looked, because those confounders were present in BOTH flashes
| and are exactly the kind of bug that worsens with repeated use.
| Session 83 additionally measured what this suppression is worth: ONE reload
| costs 6852 buffered card reads (diag_reload2_transport.py), essentially all of
| it this whole-bank re-read.
| The "(5)" gate still applies and is not optional: diag_reload2_repeat.py driving
| 5+ consecutive reloads, plus real set_key_state dispatch. A single clean reload
| remains worthless evidence here.
| Hardware: the flash carrying rl_done + the LIVE_REFRESH call broke things badly
| -- [BANK]+[YES] "hardly ever executes", [YES] "almost always" gives RELOAD
| BUSY, and **stock [BANK] single-press stops working entirely after a few
| reload attempts**. The immediately PREVIOUS flash (same file minus these two
| changes) was hardware-confirmed clean, so one of them is the cause. Skipping
| 0x40023b68 evidently drops bookkeeping the job/window machinery needs -- the
| emulator measured the layer stack staying balanced and G_KIND clearing on a
| SINGLE reload, so whatever accumulates does so across REPEATED use, which no
| test here covers yet. Do not re-enable without a multi-reload test.
| Assemble with --defsym RL_DONE=1 to bring it back for investigation.
    .ifdef RL_DONE
    .global rl_done
rl_done:
    tst.b   rl_own
    bne.b   rld_skip
    moveq   #0,%d0                     | displaced mvz.w 0x460bd910,d0 (stock word 71f9:
    move.w  MASK_SAVED,%d0             | ZERO-extend), same 8 bytes as the old move.w + ext.l,
|   which sign-extended: bank 16's mask 0x8000 reached FUN_40023b68 as 0xffff8000. Harmless
|   (it keeps only the low word, move.w %d3,0x460bdfc6) but not stock's value; found by Sam
|   Banks' static review (octabam #561), corrected 2026-10-08.
    jmp     DONE_RESUME
rld_skip:
    clr.b   rl_own                     | one-shot: consume it
|   2026-11-08 (3): the job read and staged; when it also LANDED (stopped, or not the playing
|   pattern) the UI half runs now; armed, the UI tick runs it after the landing (rl_uitick)
    tst.b   rl_post
    beq.b   rld_out
    bsr.w   rl_follow
rld_out:
    jmp     DONE_EPILOG                | skip the whole-bank reload entirely

| rl_pline: rl3_pline = "PATTERN A05" (the target's bank and pattern). Uses d0-d1/a0-a1.
rl_pline:
    moveq   #0,%d0
    move.b  rl_tpat,%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)                 | pattern 1..16
    moveq   #0,%d0
    move.b  rl_tbank,%d0
    addi.l  #'A',%d0
    move.l  %d0,-(%sp)                 | its bank's letter
    pea     rl3_fmt_ptn
    pea     rl3_pline
    jsr     SPRINTF
    lea     16(%sp),%sp
    rts

| ================= rl_follow: the UI half of a landed reload (UI task) =================
| From doneFn (rl_done) or the UI tick (rl_uitick), once rl_post says a landing happened: the
| Session 93 verify (track reloads), the message, the edited mark, the SRAM mirror, a changed Part
| link's whole-Part apply, the PICKUP setup and page redraw, the pattern switch. Then the next
| request may come (rl_busy). Keeps d2-d7/a2-a6.
rl_follow:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)
|   what landed since the last UI half (the tick may land more meanwhile: read and clear masked)
    move.w  %sr,%d0
    move.w  %d0,-(%sp)
    ori.l   #0x0700,%d0
    move.w  %d0,%sr
    clr.b   rl_post
    move.w  rl_ldm,%d3
    clr.w   rl_ldm
    move.w  rl_ldf,%d4
    clr.w   rl_ldf
    move.b  rl_dp,%d5
    clr.b   rl_dp
    move.w  (%sp)+,%d0
    move.w  %d0,%sr
|   the message: a pattern "PATTERN A05", tracks with a slice "TRK FULL", else "TRK SEQ"; line 2
|   "RELOADED FROM PROJ" ("PART NOT READ!" when the Part chunk was not read)
    moveq   #0,%d2
    tst.b   %d5
    beq.b   ff_t
    bsr.w   rl_pline
    moveq   #6,%d2
    tst.b   rl_nopart
    beq.b   ff_m
    moveq   #7,%d2
    bra.b   ff_m
ff_t:
    tst.w   %d3
    beq.b   ff_m                       | nothing landed: no message
    moveq   #1,%d2
    tst.w   %d4
    beq.b   ff_m
    moveq   #2,%d2
    tst.b   rl_nopart
    beq.b   ff_m
    moveq   #5,%d2
ff_m:
    move.b  %d2,rl_msg

    .ifdef RL_DIAG
    clr.b   rl_dv                      | DIAG: verify result 0 = not armed
    .endif
|   ===== verify the copy still holds, and SAY SO if it does not =====
|   This runs in doneFn, after the worker. If the 16 trig-mask bytes at the destination
|   no longer match what we parsed, the reload was undone (or never landed) and the user
|   must not be told RELOADED. Overriding rl_msg to 4 makes the two cases visibly
|   different ON HARDWARE, which is the only place this bug appears: every emulator run
|   restores correctly (6/6 on the user's own empty->reload->LED test, 8/8 [PTN], 4/4
|   [BANK]), and the harness cannot fail a card read, stream audio off the card, or drive
|   the firmware's own edit path.
    tst.b   rl_varm
    beq.w   rld_noverify               | nothing stashed (kind 1/2) -> nothing to check
|   Recompute the destination from the state the SEQUENCER is using RIGHT NOW, rather
|   than trusting the pointer the worker used. If the worker aimed at a stale bank or
|   pattern, the bytes IT wrote would match its own snapshot and a naive check would pass
|   while the user still heard the edited sequence. Comparing against the live slab asks
|   the question that actually matters: does what is playing now hold the CF-saved trigs?
    moveq   #0,%d0
    move.b  rl_tbank,%d0               | 2026-11-08 (3): the reload's own target (it may have landed
    move.l  #BANKSTRIDE,%d1            | on a pattern that has stopped playing since)
    muls.l  %d1,%d0
    move.l  #BLOB,%a0
    add.l   %d0,%a0
    moveq   #0,%d0
    move.b  rl_tpat,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    add.l   %d0,%a0
    add.l   rl_voff,%a0                | a0 = the LIVE track record, as of now
    .ifdef RL_DIAG
|   DIAG: the four bytes the verify is about to compare, the same four in the live-cache
|   copy LIVE_REFRESH filled, and the (bank, pattern) doneFn is using. a0 is preserved.
    move.l  %a0,%d2                    | keep a0 intact for the verify below
    lea     rl_dlive,%a1
    move.b  (%a0)+,(%a1)+
    move.b  (%a0)+,(%a1)+
    move.b  (%a0)+,(%a1)+
    move.b  (%a0)+,(%a1)+
    move.l  %d2,%a0
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    add.l   rl_voff,%d0
    add.l   #LIVE_CACHE,%d0
    move.l  %d0,%a1                    | a1 = the same record in the live cache
    move.b  (%a1)+,%d0
    move.b  %d0,rl_dcache
    move.b  (%a1)+,%d0
    move.b  %d0,rl_dcache+1
    move.b  (%a1)+,%d0
    move.b  %d0,rl_dcache+2
    move.b  (%a1)+,%d0
    move.b  %d0,rl_dcache+3
    move.b  PLAY_BANK,%d0
    move.b  %d0,rl_dd+0
    move.b  ACT_PAT,%d0
    move.b  %d0,rl_dd+1
    moveq   #1,%d0
    move.b  %d0,rl_dv                  | 1 = armed, assume pass; rld_vbad overrides
    .endif
    lea     rl_vsnap,%a1
    moveq   #16,%d2
rld_vloop:
    move.b  (%a0)+,%d0
    move.b  (%a1)+,%d1
    cmp.b   %d1,%d0
    bne.b   rld_vbad
    subq.l  #1,%d2
    bne.b   rld_vloop
    bra.b   rld_noverify
rld_vbad:
    .ifdef RL_DIAG
    moveq   #2,%d0
    move.b  %d0,rl_dv                  | DIAG: 2 = the verify FAILED
    .endif
    moveq   #4,%d0
    move.b  %d0,rl_msg                 | override -> "SEQ RELOAD LOST"
rld_noverify:
    clr.b   rl_varm                    | one-shot, like rl_own and rl_msg
|   ===== Session 93: the message is shown HERE, not at chord time. =====
|   Hardware report #14 item 1: "the toast will show 'reloaded', but the sequence is not
|   actually restored." The toast was OPTIMISTIC BY CONSTRUCTION -- the key handler drew
|   it the instant the chord was recognised, before the job had even been dequeued, so it
|   could never reflect an outcome. It said RELOADED whatever happened.
|   This point is reached ONLY on the success path: stock's doneFn tests our result code
|   and, when it is negative, shows its OWN error toast and never gets here (0x40023c0e's
|   bge is what gates it), and rl_own is set only by rlj_setflag after the copy has
|   actually happened. So a message drawn here means the worker ran AND succeeded.
|   That makes the two failure shapes distinguishable on hardware, which no test in this
|   repo can do -- the harness cannot fail a card read, cannot stream audio off the card,
|   and cannot drive the firmware's own edit path (measured: all four edit strategies
|   from Session 84 still move zero bytes):
|       no toast / stock's error  -> the worker FAILED  (card I/O, the open or the parse)
|       toast but no change       -> the worker SUCCEEDED and something downstream lost it
|   Register safety: DONE_EPILOG (0x40023c76) is only `movel (sp)+,d2 ; moveal (sp)+,a2 ;
|   rts`, so it restores d2/a2 off the stack and cares about nothing else. The calls below
|   are stack-balanced and touch only scratch registers, so jumping there afterwards is
|   exactly as safe as jumping there directly.
    moveq   #0,%d0
    move.b  rl_msg,%d0
    beq.b   rld_nomsg                  | 0 = nothing armed (not our chord) -> silent
    clr.b   rl_msg                     | one-shot, like rl_own
    .ifdef RL_DIAG
    move.b  %d0,rl_ldm                  | DIAG: which message WOULD have been shown
    bsr.w   rl3_diag_show              | ... and show the bytes instead, every time
    bra.b   rld_nomsg
    .endif
    lea     rl3_msgtab-4,%a0           | 1..7 -> its two lines
    lsl.l   #2,%d0
    movea.l (%a0,%d0.l),%a0
rld_show:
    bsr.w   rl3_show2
rld_nomsg:
|   ===== 2026-11-08: the UI half of a [BANK] + [TRACK n] Part slice (rl_full set rl_pfull). =====
|   MEASURED: this doneFn runs on the UI TASK -- the storage loop posts it to the UI queue
|   0x460d17ae as message 0x2b (0x40084110) and the UI loop's case 0x2b (0x40062454) calls it.
|   So what stock's own machine edit (0x400973b0) and CLYPS' UI tail do after a slice landed is
|   legal here: the PICKUP setup for a new audio machine, then the Part-reload page redraw
|   (rl3_part_refresh, Session 120) so the knobs show the reloaded values at once. Both read the
|   UI bank, so only when the reloaded bank is the one on screen (CLYPS' cl_postpart rule).
|   The data (the slice, the engine, the edited mark, the SRAM mirror) is already done.
|   the Part's edited mark (it follows its SAVE PART copy), then the SRAM mirror of the bank (stock's
|   0x4000faf0: slabs, Parts, the edited byte) -- after the landing, so the mirror holds what plays
    tst.b   rl_pfull
    beq.b   rld_lv
    moveq   #0,%d0
    move.b  rl_tbank,%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a5
    adda.l  %d0,%a5                    | a5 = the bank
    moveq   #0,%d0
    move.b  rl_tpat,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l %a5,%a0
    adda.l  %d0,%a0
    adda.l  #PAT_PART,%a0
    moveq   #0,%d2
    move.b  (%a0),%d2
    andi.l  #3,%d2                     | d2 = the Part the target links to
    bsr.w   rl_partp                   | a3 = it
    bsr.w   rl_pmark
rld_lv:
    moveq   #0,%d0
    move.b  rl_tbank,%d0               | the bank written
    move.l  %d0,-(%sp)
    jsr     LIVE_REFRESH               | FUN_4000faf0(bank): RAM->RAM, no card
    addq.l  #4,%sp
|   the playing pattern's Part link changed under it: stock's whole-Part apply too (UI context: it
|   posts a kernel message, which the tick may not)
    tst.b   rl_lnk
    beq.b   rld_pf
    clr.b   rl_lnk
    moveq   #0,%d0
    move.b  CUR_PART,%d0
    move.l  %d0,-(%sp)
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     PARTAPPLY                  | FUN_40009094(bank, part)
    addq.l  #8,%sp
rld_pf:
    moveq   #1,%d0
    move.l  %d0,RDRAW                  | Session 93: repaint after the data has landed
    tst.b   rl_pfull
    beq.b   rld_epi
    clr.b   rl_pfull
    move.b  rl_mch,%d0
    clr.b   rl_mch
    move.b  PLAY_BANK,%d1
    cmp.b   UI_BANK,%d1
    bne.b   rld_epi                    | another bank than the UI's: nothing on screen
    tst.b   %d0
    beq.b   rld_ref
    jsr     PICKUP_SET                 | a new machine: stock's PICKUP setup, once
rld_ref:
    bsr.w   rl3_part_refresh
rld_epi:
|   2026-11-08 (2): a pattern reload -- the OT goes to that pattern, as CLYPS' cl_ptnswitch (and stock's
|   [PTN] + trig, 0x40056b2c..0x40056b8c, without its window teardown): the chain off, the cue
|   (running: a pending change; stopped: at once), then stock's refreshes. Its own pattern: nothing.
    move.b  rl_ptngo,%d0
    beq.b   rlf_out
    clr.b   rl_ptngo
    andi.l  #15,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    cmp.l   %d0,%d1
    beq.b   rlf_out
    move.l  %d0,-(%sp)                 | N (the cue's second argument)
    jsr     CHAIN_OFF
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     PAT_CUE                    | 0x400a1030(bank, N)
    jsr     0x400418e0                 | stock's refreshes after it (0x40056b6e..0x40056b8c)
    pea     -1
    jsr     0x40083bc0
    jsr     0x40032208
    jsr     0x400486cc
    jsr     0x4004b528
    jsr     0x4004b08c
    lea     12(%sp),%sp
rlf_out:
|   nothing pending, nothing reading: the staged data expires (the next chord reads the card again)
    move.w  %sr,%d0
    move.w  %d0,-(%sp)
    ori.l   #0x0700,%d0
    move.w  %d0,%sr
    tst.b   rl_arm
    bne.b   rlf_x
    tst.b   rl_jobq
    bne.b   rlf_x
    tst.b   G_KIND
    bne.b   rlf_x
    clr.b   rq_act
    clr.b   st_ok
rlf_x:
    move.w  (%sp)+,%d0
    move.w  %d0,%sr
    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    rts

    .endif

| ================= the SEQ worker -- jmp detour @ the type-0x14 case 0x40085864 =================
| replaces 8 bytes: move.l %a2,%fp@(-650) ; move.l %a2@(4),%sp@-
|
| G_KIND on entry:  3 = TRK SEQ  (RQ_TRKSEQ: one track's region only)
|                   4 = TRK FULL (RQ_TRKFULL: the same, then that track's slice of the card's
|                       working Part -- rl_full)
| 2026-11-08: the picker-era kinds 1 (PTN SEQ) and 2 (PART + PTN SEQ) are gone; no chord has armed
| them since Session 85.

    .global rl_job
rl_job:
    move.l  %a2,-650(%fp)              | displaced #1 -- stash msg for both exit paths
|   Session 84: validate the kind, do not just test for non-zero. The dispatch
|   below has cases for 3 (TRK) and 1 (PTN SEQ) and sends EVERYTHING ELSE down the
|   PART+PTN path, so a G_KIND of, say, 200 would run a full slab copy plus a Part
|   apply -- and would also claim (via rl_own) a stock whole-bank reload the user
|   asked for. Out-of-range means the flag is not a request we made, so hand the
|   job to stock AND clear it, which self-heals the BUSY guard at the same time.
|   d0 is saved/restored because JOB14_ORIG is stock code we must not surprise;
|   only the two displaced instructions may touch registers here.
    move.l  %d0,-(%sp)
    moveq   #0,%d0
    move.b  G_KIND,%d0
    beq.b   rlj_notours                | 0 = genuinely not ours
    cmpi.l  #RQ_TRKSEQ,%d0
    bcs.b   rlj_drop
    cmpi.l  #RQ_PTN,%d0
    bls.b   rlj_isours                 | 3..5 = a request we made
rlj_drop:
    clr.b   G_KIND                     | garbage -> drop it, let stock have the job
rlj_notours:
    move.l  (%sp)+,%d0
    move.l  %a2@(4),-(%sp)            | displaced #2
    jmp     JOB14_ORIG                | not ours -> stock: jsr 0x40084094
rlj_isours:
    move.l  (%sp)+,%d0
    bra.w   rlj_ours                   | .w: rlj_ours is out of byte-branch range

rlj_ours:
|   2026-11-08 (3): the job STAGES one generation's target -- the saved slab and the working Part it
|   links to -- and hands it to rl_stdone, which arms (or, stopped, lands) what the generation wants.
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)
    clr.b   G_KIND                     | consume now -- a re-entrant real RELOAD BANK must NOT see it
    moveq   #1,%d0
    move.b  %d0,rl_jobq                | running (rl_req: a chord of this generation waits for it)
    move.b  rl_gen,%d0
    move.b  %d0,rl_jgen
    move.b  rq_bank,%d0
    move.b  %d0,rl_tbank
    moveq   #0,%d5
    move.b  rq_pat,%d5                 | d5 = the target pattern P
    move.b  %d5,rl_tpat
    .ifdef RL_DIAG
    move.b  %d5,rl_dw+1                | DIAG: pattern as the WORKER read it
    .endif
    .ifdef RL_DONE
    clr.b   rl_own                     | Session 90: set only on success
    .endif
    move.w  CKSUM,%d0
    move.w  %d0,rl_cksum
    jsr     rl_openstrd                | -> d0 = open result (fh in rl_fh)
    tst.l   %d0
    bpl.b   rlj_opened
    moveq   #-12,%d0                   | ENOENT -> stock "THIS BANK HAS NEVER BEEN SAVED!"
    bra.w   rlj_fail0
rlj_opened:
    move.l  #22,-(%sp)                 | 22-byte header
    pea     rl_hdrbuf
    pea     rl_fh
    jsr     FREAD
    lea     12(%sp),%sp
    tst.l   %d0
    ble.w   rlj_readfail
    moveq   #0,%d6
    move.b  rl_hdrbuf+0x14,%d6
    lsl.l   #8,%d6
    moveq   #0,%d0
    move.b  rl_hdrbuf+0x15,%d0
    or.l    %d0,%d6                    | d6 = version word
    moveq   #0,%d4                     | i
rlj_ploop:
    move.l  %d6,-(%sp)
    pea     SCRATCH
    pea     rl_fh
    jsr     PARSEPAT                   | FUN_4008cebc(fh, SCRATCH, verWord)
    lea     12(%sp),%sp
    .ifdef RL_DIAG
    move.b  %d0,rl_dr                  | DIAG: low byte of the last parse's return
    .endif
    tst.l   %d0
    bmi.w   rlj_readfail
    addq.l  #1,%d4
    cmp.l   %d5,%d4
    ble.b   rlj_ploop                  | parse patterns 0..P (0..P-1 discarded)
    bsr.w   rl_live                    | a0 = the live slab of P
    movea.l %a0,%a4
|   the bytes the bank file never holds keep their live values (stock parses into the live slab):
|   each audio record's +0x899 and the slab tail +0x8e5c.. (CLYPS gate X)
    movea.l #SCRATCH,%a0
    move.l  #0x899,%d0
rlj_ns:
    move.b  (%a4,%d0.l),%d1
    move.b  %d1,(%a0,%d0.l)
    addi.l  #TRAC_A,%d0
    cmpi.l  #8*TRAC_A,%d0
    bcs.b   rlj_ns
    move.l  #0x8e5c,%d0
rlj_nt:
    move.b  (%a4,%d0.l),%d1
    move.b  %d1,(%a0,%d0.l)
    addq.l  #1,%d0
    cmpi.l  #PATSTRIDE,%d0
    bcs.b   rlj_nt
|   the tick must not land from RQ_SLAB while it is rewritten (a later chord of an older generation
|   may still be pending): nothing pending of an older one survives rq_fresh, and this generation's
|   tracks arm only in rl_stdone
    move.l  #PATSTRIDE,-(%sp)
    pea     SCRATCH
    pea     RQ_SLAB
    jsr     FWMEMCPY                   | the saved pattern, staged
    lea     12(%sp),%sp
    clr.b   rl_nopart
    moveq   #0,%d3
    move.b  RQ_SLAB+PAT_PART,%d3
    andi.l  #3,%d3                     | the Part the SAVED pattern links to
    bsr.w   rl_rdpart                  | -> RQ_PART; the file closed on every path
    tst.l   %d0
    bpl.b   rlj_staged
    moveq   #1,%d0
    move.b  %d0,rl_nopart              | the sequences land, the Part does not
rlj_staged:
    move.b  rq_ptn,%d0
    beq.b   rlj_arm
    move.l  %d5,%d0
    ori.l   #0x80,%d0
    move.b  %d0,rl_ptngo               | rl_follow: the OT goes to it (nothing if it already plays)
rlj_arm:
    move.b  rl_jgen,%d0
    bsr.w   rl_stdone                  | arm (playing) or land now (stopped / not playing)
    .global rlj_setflag        | exported so tests can hook the real success point
rlj_setflag:
    .ifdef RL_DONE
    moveq   #1,%d0
    move.b  %d0,rl_own                 | Session 90: the job has succeeded -- doneFn's bank reload is ours
    .endif
rlj_ok:
    moveq   #1,%d0
rlj_exit:
    move.w  rl_cksum,%d1
    move.w  %d1,CKSUM
    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    jmp     JOB14_EXIT

rlj_readfail:
    pea     rl_fh
    jsr     FCLOSE
    addq.l  #4,%sp
    moveq   #-1,%d0
rlj_fail0:
|   stock's doneFn shows its error and rl_done never runs: this generation's request is over
    clr.b   rl_jobq
    move.b  rl_jgen,%d1
    cmp.b   rl_gen,%d1
    bne.b   rlj_exit
    clr.b   rq_act
    bra.b   rlj_exit

    .global rl_openstrd
rl_openstrd:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)

    clr.l   -(%sp)
    clr.l   -(%sp)
    jsr     PROJDIR                    | d0 = char* project dir
    addq.l  #8,%sp

    moveq   #0,%d1
    move.b  rl_tbank,%d1               | the job's target bank (2026-11-08 (3): its generation's)
    addq.l  #1,%d1
    move.l  %d1,-(%sp)                 | bank number (1-based)
    move.l  %d0,-(%sp)                 | project dir
    move.l  #FMT_STRD,-(%sp)
    pea     rl_pathbuf
    jsr     SPRINTF                    | sprintf(rl_pathbuf, "%s/bank%02d.strd", dir, bank)
    lea     16(%sp),%sp

    lea     rl_fh,%a0                  | zero the 64-byte handle struct
    moveq   #16,%d0
rlo_zero:
    clr.l   (%a0)+
    subq.l  #1,%d0
    bne.b   rlo_zero

    move.l  #0x7000,-(%sp)             | open buffer size (28 KB of OPEN_BUF)
    pea     OPEN_BUF
    pea     MODE_R
    pea     rl_pathbuf
    pea     rl_fh
    jsr     FOPEN                      | FUN_40016864(fh, path, "r", buf, size)
    lea     20(%sp),%sp

    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    rts

| ================= 2026-11-08 (3): the request, the staging and the landing =================
| The user (2026-11-08): card reloads land like CLYPS' temp reload -- a track at its next step start,
| in phase, its Part slice in the same tick; a pattern at the next step all its tracks share; a reload
| that changes the pattern's own length / scale on the next step too, every track re-phased to where
| the saved pattern would be since the master cycle began. Several chords before a landing all count:
| per track, the latest kind wins; a pattern reload, or a reload of another pattern, replaces them.
|
| THE REQUEST (rl_req, UI task). A "generation" is one target (bank, pattern) and what is wanted of it
| (rq_ptn: the whole pattern; rq_seqm / rq_fullm: tracks, sequence only / with their slice). A new
| target -- or a pattern reload -- starts a new generation and drops whatever was pending. The card is
| read ONCE per generation, by one storage job (G_KIND = RQ_STAGE): the whole saved slab and the
| working Part it links to, into RQ_SLAB / RQ_PART. A chord for a track of a generation already staged
| arms that track at once; one whose job is queued or running for this generation is taken by it when
| it ends. A job is posted only when none is queued (G_KIND == 0): a second post of stock's one message
| would reach the 0x14 case with G_KIND already consumed and run stock's whole-bank reload.
| THE LANDING (rl_tick in phase D, rl_wrap at a master wrap, rl_uitick when stopped; rl_landall /
| rl_landtrk / rl_put): see rl_tick. THE UI HALF (rl_follow) after each landing.
| Shared with the sequencer ISR: rl_lm / rl_lf / rl_lp / rl_arm -- the task side changes them with
| interrupts masked.

| rl_req (d0 = track 0..15, or the pattern 0..15 for RQ_PTN; d1 = RQ_TRKSEQ / RQ_TRKFULL / RQ_PTN).
| UI task. Keeps d2-d7/a2-a6.
rl_req:
    lea     -16(%sp),%sp
    movem.l %d2-%d5,(%sp)
    move.l  %d0,%d5                    | d5 = t / pattern
    move.l  %d1,%d4                    | d4 = kind
    move.w  %sr,%d0
    move.w  %d0,-(%sp)
    ori.l   #0x0700,%d0
    move.w  %d0,%sr                    | the tick must not see half a request
    moveq   #0,%d2
    move.b  PLAY_BANK,%d2              | d2 = the bank
    cmpi.l  #RQ_PTN,%d4
    bne.b   rq_trk
    move.l  %d5,%d3                    | d3 = pattern N
    bsr.w   rq_fresh
    moveq   #1,%d0
    move.b  %d0,rq_ptn
    bra.b   rq_post
rq_trk:
    moveq   #0,%d3
    move.b  ACT_PAT,%d3                | a track reload aims at the playing pattern
    tst.b   rq_act
    beq.b   rq_new
    cmp.b   rq_bank,%d2
    bne.b   rq_new
    cmp.b   rq_pat,%d3
    bne.b   rq_new
    tst.b   rq_ptn
    bne.w   rq_none                    | the whole pattern is already on its way: it brings this track
    bra.b   rq_add
rq_new:
    bsr.w   rq_fresh
rq_add:
    moveq   #1,%d1
    lsl.l   %d5,%d1                    | d1 = the track's bit
    move.w  rq_fullm,%d0
    cmpi.l  #RQ_TRKFULL,%d4
    beq.b   rq_f
    not.l   %d1
    and.l   %d1,%d0                    | the latest kind wins: a SEQ after a FULL is a SEQ
    not.l   %d1
    bra.b   rq_fw
rq_f:
    or.l    %d1,%d0
rq_fw:
    move.w  %d0,rq_fullm
    move.w  rq_seqm,%d0
    or.l    %d1,%d0
    move.w  %d0,rq_seqm                | rq_seqm = every track wanted (rq_fullm the FULL ones)
    tst.b   st_ok
    beq.b   rq_post
|   staged for this generation already: the track is armed now (the tick lands it, or the UI tick
|   when stopped)
    move.w  rl_lm,%d0
    or.l    %d1,%d0
    move.w  %d0,rl_lm
    move.w  rq_fullm,%d0
    move.w  %d0,rl_lf
    moveq   #1,%d0
    move.b  %d0,rl_arm
    bra.b   rq_none
rq_post:
    tst.b   G_KIND
    bne.b   rq_none                    | a job is queued: it takes the request as it stands then
    tst.b   rl_jobq
    beq.b   rq_p2
    move.b  rl_jgen,%d0
    cmp.b   rl_gen,%d0
    beq.b   rq_none                    | running for this generation: it arms the request at its end
rq_p2:
    moveq   #RQ_STAGE,%d0
    move.b  %d0,G_KIND
    moveq   #1,%d5                     | post below, with interrupts back on
    bra.b   rq_sr
rq_none:
    moveq   #0,%d5
rq_sr:
    move.w  (%sp)+,%d0
    move.w  %d0,%sr
    tst.l   %d5
    beq.b   rq_out
    moveq   #1,%d1
    lsl.l   %d2,%d1
    move.l  %d1,-(%sp)
    jsr     JOB_POST                   | FUN_40022778(1 << the bank)
    addq.l  #4,%sp
rq_out:
    movem.l (%sp),%d2-%d5
    lea     16(%sp),%sp
    rts
| rq_fresh (d2 = bank, d3 = pattern): a new generation -- whatever was pending is dropped
rq_fresh:
    move.b  rl_gen,%d0
    addq.l  #1,%d0
    move.b  %d0,rl_gen
    moveq   #1,%d0
    move.b  %d0,rq_act
    move.b  %d2,rq_bank
    move.b  %d3,rq_pat
    clr.b   rq_ptn
    clr.w   rq_seqm
    clr.w   rq_fullm
    clr.w   rl_lm
    clr.w   rl_lf
    clr.b   rl_lp
    clr.b   rl_arm
    clr.b   st_ok
    rts

| rl_stdone (the worker, at the end of a staging job): arm what the generation wants, or land it now
| (stopped, or the target not playing). d0 = the job's generation. Masks interrupts itself.
rl_stdone:
    move.l  %d2,-(%sp)
    move.w  %sr,%d1
    move.w  %d1,-(%sp)
    move.l  %d1,%d2
    ori.l   #0x0700,%d2
    move.w  %d2,%sr
    clr.b   rl_jobq
    cmp.b   rl_gen,%d0
    bne.b   sd_out                     | a newer generation: its own job is queued -- drop this one
    moveq   #1,%d0
    move.b  %d0,st_ok
    move.w  rq_seqm,%d0
    move.w  %d0,rl_lm
    move.w  rq_fullm,%d0
    move.w  %d0,rl_lf
    move.b  rq_ptn,%d0
    move.b  %d0,rl_lp
    moveq   #1,%d0
    move.b  %d0,rl_arm
    tst.l   RUNNING
    beq.b   sd_now
    move.b  rl_tpat,%d0
    cmp.b   ACT_PAT,%d0
    bne.b   sd_now
    move.b  rl_tbank,%d0
    cmp.b   PLAY_BANK,%d0
    beq.b   sd_out                     | playing: the tick lands it
sd_now:
    bsr.w   rl_landall                 | stopped / not playing: no phase to keep
sd_out:
    move.w  (%sp)+,%d1
    move.w  %d1,%sr
    move.l  (%sp)+,%d2
    rts

| rl_landall: land everything pending now, data only (no counters: the caller sets them, stock
| re-homes, or nothing plays). Any context; a task context calls it with interrupts masked.
rl_landall:
    lea     -12(%sp),%sp
    movem.l %d0-%d2,(%sp)
    tst.b   rl_lp
    beq.b   la2_t
    moveq   #1,%d0
    move.b  %d0,rl_dp                  | the UI half: a pattern landed
    moveq   #RQ_PTN,%d0
    bsr.w   rl_put
    bra.b   la2_done
la2_t:
    moveq   #0,%d2
la2_l:
    move.w  rl_lm,%d1
    btst    %d2,%d1
    beq.b   la2_n
    move.l  %d2,%d0
    bsr.w   rl_landtrk
la2_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   la2_l
la2_done:
    clr.w   rl_lm
    clr.b   rl_lp
    clr.b   rl_arm
    movem.l (%sp),%d0-%d2
    lea     12(%sp),%sp
    rts


| rl_landtrk (d0 = t): land one pending track -- its record (and slice when FULL) -- and note it for
| the UI half (rl_ldm / rl_ldf). Clears its pending bit. Keeps every register.
rl_landtrk:
    lea     -12(%sp),%sp
    movem.l %d0-%d2,(%sp)
    move.l  %d0,%d2                    | d2 = t
    move.b  %d2,rl_t
    moveq   #RQ_TRKSEQ,%d0
    move.w  rl_lf,%d1
    btst    %d2,%d1
    beq.b   lt2_k
    moveq   #RQ_TRKFULL,%d0
lt2_k:
    bsr.w   rl_put
    moveq   #1,%d1
    lsl.l   %d2,%d1                    | d1 = its bit
    move.w  rl_ldm,%d0
    or.l    %d1,%d0
    move.w  %d0,rl_ldm                  | landed
    move.w  rl_lf,%d0
    and.l   %d1,%d0
    beq.b   lt2_s
    move.w  rl_ldf,%d0
    or.l    %d1,%d0
    move.w  %d0,rl_ldf                  | ... with its slice
lt2_s:
    not.l   %d1
    move.w  rl_lm,%d0
    and.l   %d1,%d0
    move.w  %d0,rl_lm                  | no longer pending
    movem.l (%sp),%d0-%d2
    lea     12(%sp),%sp
    rts

| rl_live -> a0 = the live target slab (rl_tbank, rl_tpat). Uses d0-d1.
rl_live:
    moveq   #0,%d0
    move.b  rl_tbank,%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a0
    adda.l  %d0,%a0
    moveq   #0,%d0
    move.b  rl_tpat,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    adda.l  %d0,%a0
    rts

| rl_ctr (d4 = t, d7 = t0): t's counters, phase-continuous, from its rate in the live target slab
| (after its landing): STEP = (t0 / tps + 1) mod len, STEP-1, TICKS = t0 mod tps, its scale cache.
| Uses d0-d3/d5/a0-a1 (the tick saved every register).
rl_ctr:
    bsr.w   rl_live
    move.l  %d4,%d0
    bsr.w   rl_rate                    | d0 = tps, d1 = len, d2 = scale
    move.l  %d2,%d3                    | d3 = its scale
    move.l  %d0,%d5                    | d5 = its tps
    move.l  %d7,%d0
    divu.l  %d5,%d0                    | t0 / tps
    addq.l  #1,%d0
    remu.l  %d1,%d2:%d0                | d2 = STEP
    lea     STEP_ARR,%a0
    move.b  %d2,(%a0,%d4.l)
    add.l   %d1,%d2
    subq.l  #1,%d2
    remu.l  %d1,%d0:%d2                | d0 = (STEP + len - 1) mod len
    lea     STEPM1_ARR,%a0
    move.b  %d0,(%a0,%d4.l)
    move.l  %d7,%d0
    remu.l  %d5,%d2:%d0                | d2 = t0 mod tps (0 at a step start)
    lea     TICKS_ARR,%a0
    move.b  %d2,(%a0,%d4.l)
    lea     TSCALE_ARR,%a0
    move.b  %d3,(%a0,%d4.l)
    rts

| rl_mrate (a0 = a slab) -> d0 = the master's ticks per step, d1 = the master length (0 = INF),
| d2 = its scale index: NORMAL the pattern's length / scale (+0x8e53 / +0x8e54), PER TRACK the
| master's (+0x8e50 u16, 0xffff = INF / +0x8e52). Uses a0-a1.
rl_mrate:
    movea.l %a0,%a1
    adda.l  #PAT_MLEN,%a1
    tst.b   PAT_SMODE-PAT_MLEN(%a1)
    bne.b   mr2_pt
    moveq   #0,%d1
    move.b  PAT_LEN-PAT_MLEN(%a1),%d1
    moveq   #0,%d2
    move.b  PAT_SCALE-PAT_MLEN(%a1),%d2
    bra.b   mr2_t
mr2_pt:
    moveq   #0,%d1
    move.w  (%a1),%d1
    cmpi.l  #0xffff,%d1
    bne.b   mr2_l
    moveq   #0,%d1                     | INF
mr2_l:
    moveq   #0,%d2
    move.b  PAT_MSCALE-PAT_MLEN(%a1),%d2
mr2_t:
    move.l  %d2,%d0
    bra.w   rl_tps

| rl_wclass -> d0 = 1 when the pending landing changes the pattern's own rate -- then every track and
| the master are re-phased (rl_rephase): a pattern whose trailer +0x8e50..55 differs from the live
| one, or (NORMAL mode) track reloads, which bring the pattern's length / scale with them.
| Uses d1/a0-a1.
rl_wclass:
    bsr.w   rl_live
    adda.l  #PAT_MLEN,%a0
    movea.l #RQ_SLAB+PAT_MLEN,%a1
    moveq   #6,%d1
    tst.b   rl_lp
    bne.b   wc2_c
    tst.b   PAT_SMODE-PAT_MLEN(%a0)
    bne.b   wc2_no                     | PER TRACK: a track's own rate lands per track
    addq.l  #3,%a0
    addq.l  #3,%a1
    moveq   #2,%d1                     | NORMAL: the pattern's length / scale
wc2_c:
    move.b  (%a0)+,%d0
    cmp.b   (%a1)+,%d0
    bne.b   wc2_yes
    subq.l  #1,%d1
    bne.b   wc2_c
wc2_no:
    moveq   #0,%d0
    rts
wc2_yes:
    moveq   #1,%d0
    rts

| rl_rephase (d7 = t0, after the landing): the pattern's own rate changed, so the master and every
| track go where the SAVED pattern would be had it played since this master cycle began: master
| step = (t0 / tps_M) mod its length + 1, its tick = t0 mod tps_M, the master scale cache; every
| track as rl_ctr. Uses d0-d5/a0-a2.
rl_rephase:
    bsr.w   rl_live
    movea.l %a0,%a2                    | a2 = the live target slab (now the saved pattern)
    bsr.w   rl_mrate                   | d0 = tps_M, d1 = master length (0 = INF), d2 = its scale
    move.b  %d2,SCALE_IX
    move.l  %d0,%d5
    move.l  %d7,%d3
    divu.l  %d5,%d3                    | d3 = master steps since the cycle began
    tst.l   %d1
    beq.b   rp3_inf
    remu.l  %d1,%d0:%d3
    move.l  %d0,%d3                    | ... within its length
rp3_inf:
    addq.l  #1,%d3
    move.w  %d3,MASTER_STEP
    move.l  %d7,%d0
    remu.l  %d5,%d2:%d0
    move.b  %d2,TICK_CTR               | 0 at a step start
    moveq   #0,%d4
rp3_l:
    bsr.w   rl_ctr
    addq.l  #1,%d4
    cmpi.l  #16,%d4
    bne.b   rp3_l
    rts

| rl_ready (d4 = t, d7 = t0) -> d0 = 1 when t starts a step at t0 at its old rate (its scale cache)
| and at its new one (RQ_SLAB). Uses d0-d2/a0-a1.
rl_ready:
    lea     TSCALE_ARR,%a0
    moveq   #0,%d0
    move.b  (%a0,%d4.l),%d0
    bsr.w   rl_tps
    move.l  %d7,%d1
    remu.l  %d0,%d2:%d1
    tst.l   %d2
    bne.b   ry2_no
    movea.l #RQ_SLAB,%a0
    move.l  %d4,%d0
    bsr.w   rl_rate
    move.l  %d7,%d1
    remu.l  %d0,%d2:%d1
    tst.l   %d2
    bne.b   ry2_no
    moveq   #1,%d0
    rts
ry2_no:
    moveq   #0,%d0
    rts

| ================= rl_tick: phase D of the sequencer tick, 0x400a2530 =================
| Replaces `tst.l 0x46c8028a` (6 B; stock's beq.w follows on its flags, so the replay comes LAST).
| Every path of phase D converges here -- the tick gate's skip (0x400a1f6e), DIRECT JUMP's landing
| countdown (0x400a1f72, DIRECT JUMP KYOTI's site) and the count-in -- before the per-track
| scheduler (phase E, 0x400a2982): CLYPS' landing point (scope §3.4), one site later. Slices that
| are not a tick (0x46107568 != 0) pass straight through.
| The rule is CLYPS' (measured on the A4..A8 oracles): t0 = (MASTER_STEP - 1) * tps_M + TICK_CTR.
|   * a pending track lands on the first tick that starts a step of its old AND its new rate, then
|     plays phase-continuous (rl_ctr) -- each track on its own;
|   * a pattern lands all 16 on the first such tick they share (and the master's, when its rate
|     changes), then every track's counters;
|   * a landing that changes the pattern's own length / scale (rl_wclass) waits for the tick that is a
|     step start of every track and the master, old and new, and re-phases them all (rl_rephase).
| A target that no longer plays lands at once, data only. The master's first tick is rl_wrap's.
    .global rl_tick
rl_tick:
    tst.b   rl_arm
    beq.w   rt3_out                    | nothing armed: one byte test per tick
    tst.l   TICK_GATE
    bne.w   rt3_out
    tst.l   RUNNING
    beq.w   rt3_out                    | stopped: the UI tick lands it
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    move.b  rl_tpat,%d0
    cmp.b   ACT_PAT,%d0
    bne.w   rt3_off
    move.b  rl_tbank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.w   rt3_off
    moveq   #0,%d0
    move.b  SCALE_IX,%d0
    bsr.w   rl_tps
    move.l  %d0,%d5                    | d5 = tps_M
    moveq   #0,%d3
    move.w  MASTER_STEP,%d3
    tst.l   %d3
    beq.w   rt3_done                   | no master step yet (transport start)
    moveq   #0,%d1
    move.b  TICK_CTR,%d1
    move.l  %d3,%d0
    subq.l  #1,%d0
    muls.l  %d5,%d0
    add.l   %d1,%d0
    move.l  %d0,%d7                    | d7 = t0
    beq.w   rt3_done                   | the master's first tick: rl_wrap has landed it
    bsr.w   rl_wclass
    move.l  %d0,%d6                    | d6 = 1: the pattern's own rate changes
    tst.b   rl_lp
    bne.b   rt3_all
    tst.l   %d6
    bne.b   rt3_all
|   ---- tracks, each on its own step ----
    moveq   #0,%d4
rt3_tl:
    move.w  rl_lm,%d0
    btst    %d4,%d0
    beq.b   rt3_tn
    bsr.w   rl_ready
    tst.l   %d0
    beq.b   rt3_tn
    move.l  %d4,%d0
    bsr.w   rl_landtrk
    bsr.w   rl_ctr
    moveq   #1,%d0
    move.b  %d0,rl_post
rt3_tn:
    addq.l  #1,%d4
    cmpi.l  #16,%d4
    bne.b   rt3_tl
    tst.w   rl_lm
    bne.w   rt3_done
    clr.b   rl_arm
    bra.w   rt3_done
|   ---- everything together: a pattern, or a change of the pattern's own rate ----
|   2026-11-08 (4), the user: a reload of the pattern you are ON is not a pattern change -- it lands like
|   temp reload, on the first step all its tracks share, in phase. (A reload of a pattern you are NOT on
|   is one: it lands offline and stock's cue takes the OT there -- CHAIN AFTER, or DIRECT JUMP when on.)
rt3_all:
    moveq   #0,%d4
rt3_al:
    bsr.w   rl_ready
    tst.l   %d0
    beq.w   rt3_done                   | not every track starts a step here: wait
    addq.l  #1,%d4
    cmpi.l  #16,%d4
    bne.b   rt3_al
    tst.l   %d6
    beq.b   rt3_go
    move.l  %d7,%d1                    | the master too, old and new
    remu.l  %d5,%d2:%d1
    tst.l   %d2
    bne.w   rt3_done
    movea.l #RQ_SLAB,%a0
    bsr.w   rl_mrate
    move.l  %d7,%d1
    remu.l  %d0,%d2:%d1
    tst.l   %d2
    bne.w   rt3_done
rt3_go:
    bsr.w   rl_landall
    tst.l   %d6
    beq.b   rt3_ca
    bsr.w   rl_rephase
    bra.b   rt3_done
rt3_ca:
    moveq   #0,%d4
rt3_cl:
    bsr.w   rl_ctr
    addq.l  #1,%d4
    cmpi.l  #16,%d4
    bne.b   rt3_cl
    bra.b   rt3_done
rt3_off:
|   the target no longer plays (a pattern change, a DIRECT JUMP): no phase to keep, land it now
    bsr.w   rl_landall
rt3_done:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
rt3_out:
    tst.l   RELOAD_NOW                 | displaced; stock's beq.w follows on these flags
    jmp     TICK_RES

| ================= rl_wrap: the wrap body's entry, 0x400a43a0 =================
| Replaces `move.l (%a2),%d0 ; moveq #1,%d2 ; or.l %d2,%d0` (6 B). Phase G at a master wrap, and when
| a stock pattern change lands. CLYPS' measured rule (A1/A2 oracles): a copy HERE equals a stock
| change, because the wrap body re-homes every track right after; phase D of the next tick is one
| tick too late. So whatever is pending lands here, data only, with the scale caches set before the
| re-home -- or, when a pattern change lands or the target no longer plays, just the data.
    .global rl_wrap
rl_wrap:
    tst.b   rl_arm
    beq.b   rw2_out
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    bsr.w   rl_landall
    move.b  PEND_PAT,%d1
    cmp.b   ACT_PAT,%d1
    bne.b   rw2_done
    move.b  PEND_BANK,%d1
    cmp.b   PLAY_BANK,%d1
    bne.b   rw2_done
    move.b  rl_tpat,%d1
    cmp.b   ACT_PAT,%d1
    bne.b   rw2_done
    move.b  rl_tbank,%d1
    cmp.b   PLAY_BANK,%d1
    bne.b   rw2_done
    bsr.w   rl_scales                  | it plays on: the scale caches before stock's re-home
rw2_done:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
rw2_out:
    move.l  (%a2),%d0                  | displaced
    moveq   #1,%d2                     | displaced
    or.l    %d2,%d0                    | displaced
    jmp     WRAP_RES

| ================= rl_uitick: the UI task's 1/60 s tick, 0x40056c28 =================
| Replaces `move.l 0x460d1e6c,%d0` (6 B, the toast countdown read; stock's beq follows on its flags).
| UI context (task 0x40056c40, once per tick message -- CLYPS' cl_uitick). A landing still pending
| with the transport stopped lands here (nothing plays); a landing the tick made gets its UI half.
    .global rl_uitick
rl_uitick:
    tst.b   rl_arm
    beq.b   ru2_post
    tst.l   RUNNING
    bne.b   ru2_post
    move.w  %sr,%d0
    move.w  %d0,-(%sp)
    ori.l   #0x0700,%d0
    move.w  %d0,%sr
    bsr.w   rl_landall
    move.w  (%sp)+,%d0
    move.w  %d0,%sr
ru2_post:
    tst.b   rl_post
    beq.b   ru2_out
    bsr.w   rl_follow
ru2_out:
    move.l  TOAST_CD,%d0               | displaced; stock's beq follows on these flags
    jmp     UITICK_RES

| rl_putm (d0 = kind): rl_put with interrupts masked, for a task context while the sequencer may run
rl_putm:
    move.l  %d1,-(%sp)
    move.w  %sr,%d1
    move.w  %d1,-(%sp)
    ori.l   #0x0700,%d1
    move.w  %d1,%sr
    bsr.w   rl_put
    move.w  (%sp)+,%d1
    move.w  %d1,%sr
    move.l  (%sp)+,%d1
    rts

| rl_put(d0 = kind) -- land what the worker staged (RQ_SLAB, RQ_PART) on the target (rl_tbank,
| rl_tpat; a track: rl_t). No counters (the caller's). Writes RAM only (the slab, the Part, engine
| state through stock's per-track applies, our state): safe in the sequencer tick, as CLYPS'
| cl_apply / cl_fullone. Stock's whole-Part apply 0x40009094 posts a kernel message, so a changed
| Part link gets it later, from rl_follow (rl_lnk).
|   TRK SEQ   the track's record (+ the pattern's length / scale in NORMAL mode, Session 89)
|   TRK FULL  + its slice of the Part (CLYPS' cl_slice tables), published for that track alone
|   PTN       the whole slab (its saved Part link included) + that whole Part, published per track
|             when sounding (the playing pattern, or one sharing its Part)
| A new audio machine sets its restart bit (stock's machine edit 0x400973b4) and owes the PICKUP
| setup (rl_mch). Keeps every register.
rl_put:
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    move.l  %d0,%d7                    | d7 = kind
    moveq   #0,%d0
    move.b  rl_tbank,%d0
    move.l  %d0,%d6                    | d6 = the bank
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a5
    adda.l  %d0,%a5                    | a5 = the bank
    moveq   #0,%d5
    move.b  rl_tpat,%d5                | d5 = the pattern
    move.l  %d5,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l %a5,%a4
    adda.l  %d0,%a4                    | a4 = its live slab
    cmpi.l  #RQ_PTN,%d7
    bne.w   rp_trk
|   ---- the whole pattern ----
    move.l  #PATSTRIDE,-(%sp)
    pea     RQ_SLAB
    move.l  %a4,-(%sp)
    jsr     FWMEMCPY
    lea     12(%sp),%sp
    tst.b   rl_nopart
    bne.w   rp_out
    movea.l %a4,%a0
    adda.l  #PAT_PART,%a0
    moveq   #0,%d2
    move.b  (%a0),%d2
    andi.l  #3,%d2                     | d2 = its Part (the saved link)
    bsr.w   rl_partp                   | a3 = that Part
    bsr.w   rl_sounds                  | d4 = 1: it is sounding (CUR_PART becomes it when playing)
    tst.l   %d4
    beq.b   rp_pcopy
    moveq   #0,%d3                     | machine changes: the voices restart (audio)
rp_mc:
    move.b  0x22(%a3,%d3.l),%d0
    movea.l #RQ_PART,%a0
    cmp.b   0x22(%a0,%d3.l),%d0
    beq.b   rp_mn
    bsr.w   rl_restart                 | d3 = t
rp_mn:
    addq.l  #1,%d3
    cmpi.l  #8,%d3
    bne.b   rp_mc
rp_pcopy:
    move.l  #PARTSZ,-(%sp)
    pea     RQ_PART
    move.l  %a3,-(%sp)
    jsr     FWMEMCPY
    lea     12(%sp),%sp
    moveq   #1,%d0
    move.b  %d0,rl_pfull
    tst.l   %d4
    beq.w   rp_out
    moveq   #0,%d3                     | publish it, track by track
rp_pub:
    move.l  %d3,-(%sp)
    move.l  %d2,-(%sp)
    move.l  %d6,-(%sp)
    jsr     TRK_APPLY                  | audio t
    bsr.w   rl_mapply                  | MIDI m (same arguments)
    lea     12(%sp),%sp
    addq.l  #1,%d3
    cmpi.l  #8,%d3
    bne.b   rp_pub
    bra.w   rp_out
|   ---- one track ----
rp_trk:
    moveq   #0,%d3
    move.b  rl_t,%d3                   | d3 = t 0..15
    move.l  %d3,%d0
    bsr.w   rl_toff                    | d0 = offset, d1 = length
    move.l  %d0,%d4
    move.l  %d1,-(%sp)
    move.l  #RQ_SLAB,%d1
    add.l   %d0,%d1
    move.l  %d1,-(%sp)
    move.l  %a4,%d1
    add.l   %d0,%d1
    move.l  %d1,-(%sp)
    jsr     FWMEMCPY                   | the record
    lea     12(%sp),%sp
    movea.l #RQ_SLAB,%a0               | Session 93: the trig masks as landed (rl_follow verifies)
    adda.l  %d4,%a0
    lea     rl_vsnap,%a1
    moveq   #16,%d0
rp_sn:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   rp_sn
    move.l  %d4,rl_voff
    moveq   #1,%d0
    move.b  %d0,rl_varm
|   Session 89: NORMAL mode -- the pattern's length / scale come back with the track
    movea.l %a4,%a0
    adda.l  #PAT_SMODE,%a0
    tst.b   (%a0)
    bne.b   rp_full
    movea.l %a4,%a0
    adda.l  #PAT_LEN,%a0
    move.b  RQ_SLAB+PAT_LEN,%d0
    move.b  %d0,(%a0)
    move.b  RQ_SLAB+PAT_SCALE,%d0
    move.b  %d0,1(%a0)
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    cmp.l   %d5,%d1
    bne.b   rp_full                    | not playing: the live master scale is another pattern's
    cmp.b   SCALE_IX,%d0
    beq.b   rp_full
    move.b  %d0,SCALE_IX               | the saved rate genuinely differs -> apply it
rp_full:
    cmpi.l  #RQ_TRKFULL,%d7
    bne.w   rp_out
    tst.b   rl_nopart
    bne.w   rp_out
    movea.l %a4,%a0
    adda.l  #PAT_PART,%a0
    moveq   #0,%d2
    move.b  (%a0),%d2
    andi.l  #3,%d2                     | d2 = the Part the pattern links to now
    bsr.w   rl_partp                   | a3 = it
    bsr.w   rl_sounds                  | d4 = 1: sounding
    tst.l   %d4
    beq.b   rp_fcopy
    cmpi.l  #8,%d3
    bcc.b   rp_fcopy
    move.b  0x22(%a3,%d3.l),%d0
    movea.l #RQ_PART,%a0
    cmp.b   0x22(%a0,%d3.l),%d0
    beq.b   rp_fcopy
    bsr.w   rl_restart
rp_fcopy:
    pea     RQ_PART
    move.l  %a3,-(%sp)
    move.l  %d3,-(%sp)
    bsr.w   rl_slice
    lea     12(%sp),%sp
    moveq   #1,%d0
    move.b  %d0,rl_pfull
    tst.l   %d4
    beq.b   rp_out
    move.l  %d3,%d0
    cmpi.l  #8,%d0
    bcs.b   rp_ft
    subq.l  #8,%d0
rp_ft:
    move.l  %d0,-(%sp)                 | t / m
    move.l  %d2,-(%sp)                 | part
    move.l  %d6,-(%sp)                 | bank
    cmpi.l  #8,%d3
    bcc.b   rp_fm
    jsr     TRK_APPLY
    bra.b   rp_fp
rp_fm:
    bsr.w   rl_mapply
rp_fp:
    lea     12(%sp),%sp
rp_out:
    moveq   #1,%d0
    move.b  %d0,rl_post                | the UI half is owed (rl_follow)
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
    rts

| rl_partp (a5 = the bank, d2 = Part index) -> a3 = that Part. Uses d0.
rl_partp:
    move.l  #PARTSZ,%d0
    muls.l  %d2,%d0
    movea.l %a5,%a3
    adda.l  #PART_OFF,%a3
    adda.l  %d0,%a3
    rts
| rl_sounds (d5 = pattern, d2 = its Part) -> d4 = 1 when that Part is sounding: the pattern plays
| (then it becomes the current Part, 0x80000003 -- a changed link owes stock's whole-Part apply,
| rl_lnk) or it shares the playing pattern's Part. Uses d0.
rl_sounds:
    moveq   #0,%d4
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d5,%d0
    bne.b   rs2_sh
    move.b  rl_tbank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   rs2_out
    moveq   #1,%d4
    move.b  CUR_PART,%d0
    cmp.b   %d2,%d0
    beq.b   rs2_out
    move.b  %d2,CUR_PART
    moveq   #1,%d0
    move.b  %d0,rl_lnk
    rts
rs2_sh:
    move.b  rl_tbank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   rs2_out
    move.b  CUR_PART,%d0
    cmp.b   %d2,%d0
    bne.b   rs2_out
    moveq   #1,%d4
rs2_out:
    rts
| rl_restart (d3 = audio track): its voice restarts on a new machine (stock's machine edit,
| 0x400973b4); the PICKUP setup is owed (rl_mch). Uses d0-d1.
rl_restart:
    moveq   #1,%d0
    lsl.l   %d3,%d0
    move.b  ENG_RESTART,%d1
    or.l    %d1,%d0
    move.b  %d0,ENG_RESTART
    moveq   #1,%d0
    move.b  %d0,rl_mch
    rts
| rl_toff (d0 = t 0..15) -> d0 = the record's offset in a slab, d1 = its length
rl_toff:
    cmpi.l  #8,%d0
    bcc.b   to2_m
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    rts
to2_m:
    subq.l  #8,%d0
    move.l  #TRAC_M,%d1
    muls.l  %d1,%d0
    addi.l  #MIDI_BASE,%d0
    rts
| rl_tps (d0 = scale index) -> d0 = ticks per step (stock's table; out of range reads as 1x, as
| DIRECT JUMP and CLYPS do). Uses a0.
rl_tps:
    cmpi.l  #6,%d0
    bls.b   tp2_ok
    moveq   #2,%d0
tp2_ok:
    lea     LEN_TBL,%a0
    move.l  (%a0,%d0.l*4),%d0
    rts
| rl_rate (a0 = a slab, d0 = t) -> d0 = ticks per step, d1 = length, d2 = scale index that track
| plays at from that slab: PER TRACK the record's own (audio +0x50/+0x51, MIDI +0x28/+0x29), NORMAL
| the pattern's (+0x8e53 / +0x8e54). A zero length reads as 16 (never divide by it). Uses a0-a1.
rl_rate:
    movea.l %a0,%a1
    adda.l  #PAT_LEN,%a1
    tst.b   PAT_SMODE-PAT_LEN(%a1)
    bne.b   rr2_pt
    moveq   #0,%d1
    move.b  (%a1),%d1
    moveq   #0,%d2
    move.b  1(%a1),%d2
    bra.b   rr2_t
rr2_pt:
    move.l  %d3,-(%sp)
    move.l  %d0,%d3
    bsr.w   rl_toff                    | d0 = offset
    movea.l %a0,%a1
    adda.l  %d0,%a1
    moveq   #0x50,%d0
    cmpi.l  #8,%d3
    bcs.b   rr2_a
    moveq   #0x28,%d0
rr2_a:
    moveq   #0,%d1
    move.b  (%a1,%d0.l),%d1
    moveq   #0,%d2
    move.b  1(%a1,%d0.l),%d2
    move.l  (%sp)+,%d3
rr2_t:
    tst.l   %d1
    bne.b   rr2_l
    moveq   #16,%d1
rr2_l:
    move.l  %d2,%d0
    bra.w   rl_tps

| rl_scales: the master scale cache and every track's scale cache from the target's live slab, after
| a landing that changed the pattern's own rate (at a wrap, before stock re-homes every track; or an
| INF master): NORMAL the pattern's scale, PER TRACK the master scale and each record's own.
| Keeps every register.
rl_scales:
    lea     -24(%sp),%sp
    movem.l %d0-%d4/%a2,(%sp)
    moveq   #0,%d0
    move.b  rl_tbank,%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a2
    adda.l  %d0,%a2
    moveq   #0,%d0
    move.b  rl_tpat,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    adda.l  %d0,%a2                    | a2 = the live slab
    movea.l %a2,%a0
    adda.l  #PAT_SCALE,%a0
    movea.l %a2,%a1
    adda.l  #PAT_SMODE,%a1
    tst.b   (%a1)
    beq.b   sc2_m
    movea.l %a2,%a0
    adda.l  #PAT_MSCALE,%a0
sc2_m:
    move.b  (%a0),%d0
    move.b  %d0,SCALE_IX
    moveq   #0,%d4
sc2_l:
    movea.l %a2,%a0
    move.l  %d4,%d0
    bsr.w   rl_rate
    lea     TSCALE_ARR,%a0
    move.b  %d2,(%a0,%d4.l)
    addq.l  #1,%d4
    cmpi.l  #16,%d4
    bne.b   sc2_l
    movem.l (%sp),%d0-%d4/%a2
    lea     24(%sp),%sp
    rts

| rl_rdpart (d3 = the working Part to read, d6 = the version word; rl_fh open): that PART chunk ->
| RQ_PART -- a direct seek, else the file again chunk by chunk. rl_fh is closed on every path.
| -> d0 = 0 read, -1 not. Keeps d2-d7/a2-a6.
rl_rdpart:
    move.l  %d4,-(%sp)
|   straight to that PART chunk (CLYPS' direct path, 2026-11-04). Fixed offsets per version, checked
|   there on 816 real bank files (.strd + .work, versions 0x14..0x17): PTRN n at 0x16 + st * n,
|   st = 0x8eec from version 0x17 on, 0x8ee8 before; working PART p at 0x16 + 16 * st + 0x18bb * p.
|   The parser checks the chunk's tag (PART, 0x400d1690), so a wrong offset fails -> rf_seq.
    cmpi.l  #0x14,%d6
    bcs.b   rf_seq                     | an older format: chunk by chunk
    move.l  #0x8ee8,%d4
    cmpi.l  #0x17,%d6
    bcs.b   rf_st
    move.l  #0x8eec,%d4                | d4 = the pattern chunk stride
rf_st:
    move.l  #0x18bb,%d0
    muls.l  %d3,%d0
    lsl.l   #4,%d4
    add.l   %d4,%d0
    addi.l  #0x16,%d0
    move.l  %d0,-(%sp)
    bsr.w   rl_seek
    addq.l  #4,%sp
    tst.l   %d0
    bmi.b   rf_seq
    move.l  %d3,%d0
    bsr.w   rf_parse
    tst.l   %d0
    bpl.w   rr_parsed
|   anything unexpected on the direct path: the file again, chunk by chunk from the top -- stock's
|   own reading order: the 16 PTRN chunks, then the working PART chunks up to d3
rf_seq:
    pea     rl_fh
    jsr     FCLOSE
    addq.l  #4,%sp
    jsr     rl_openstrd
    tst.l   %d0
    bmi.w   rf_fail0                   | not open: nothing to close
    move.l  #22,-(%sp)
    pea     rl_hdrbuf
    pea     rl_fh
    jsr     FREAD
    lea     12(%sp),%sp
    tst.l   %d0
    ble.b   rf_fail
    moveq   #16,%d4
rf_pl:
    move.l  %d6,-(%sp)
    pea     SCRATCH
    pea     rl_fh
    jsr     PARSEPAT
    lea     12(%sp),%sp
    tst.l   %d0
    bmi.b   rf_fail
    subq.l  #1,%d4
    bne.b   rf_pl
rf_prl:
    move.l  %d4,%d0
    bsr.w   rf_parse
    tst.l   %d0
    bmi.b   rf_fail
    cmp.l   %d3,%d4
    beq.b   rr_parsed
    addq.l  #1,%d4
    bra.b   rf_prl
rf_fail:
    pea     rl_fh
    jsr     FCLOSE
    addq.l  #4,%sp
rf_fail0:
    moveq   #-1,%d0
    bra.b   rr_out
rr_parsed:
    pea     rl_fh
    jsr     FCLOSE
    addq.l  #4,%sp
    moveq   #0,%d0
rr_out:
    move.l  (%sp)+,%d4
    rts

| rl_pmark (a5 = the playing bank, a3 = a Part of it, d2 = its index), after that Part changed:
|   stock's Part-edited mark: set, unless the Part now equals its SAVE PART copy (bank +0x9504a +
|   part * PARTSZ, valid when +0x9b312 + part != 0 -- the test stock's PART RELOAD makes), as after
|   stock's own PART RELOAD; the bank changed. A byte: bset / bclr, never or.l (S119).
rl_pmark:
    move.l  %a2,-(%sp)
    movea.l %a5,%a2
    adda.l  #PEDIT,%a2                 | a2 = the edited byte
    bset    %d2,(%a2)
    movea.l %a5,%a0
    adda.l  #PSAVED,%a0
    tst.b   (%a0,%d2.l)
    beq.b   pm_dirty
    move.l  #PARTSZ,%d0
    muls.l  %d2,%d0
    movea.l %a5,%a1
    adda.l  #PSAVECPY,%a1
    adda.l  %d0,%a1                    | a1 = its SAVE PART copy
    movea.l %a3,%a0
    move.l  #PARTSZ/2,%d1
pm_cmp:
    move.w  (%a0)+,%d0
    cmp.w   (%a1)+,%d0
    bne.b   pm_dirty
    subq.l  #1,%d1
    bne.b   pm_cmp
    bclr    %d2,(%a2)                  | equal: not edited
pm_dirty:
    movea.l %a5,%a0
    adda.l  #BDIRTY,%a0
    moveq   #1,%d0
    move.l  %d0,(%a0)
    move.l  %d0,DIRTY2
    move.l  (%sp)+,%a2
    rts

| rf_parse (d0 = Part index): PARSEPRT(rl_fh, RQ_PART, d0, d6) -> d0 < 0: failed
rf_parse:
    move.l  %d6,-(%sp)
    move.l  %d0,-(%sp)
    pea     RQ_PART
    pea     rl_fh
    jsr     PARSEPRT
    lea     16(%sp),%sp
    rts

| rl_seek(off) -> d0 < 0: error. rl_fh's read position = off, as if read up to there (CLYPS' rq_seek):
| the backend seek (0x46c8243e: the card filesystem's, installed at 0x400145de / 0x400146f0 /
| 0x40014806) to off's 512 B block, the buffer marked empty (+12, the read index: 0 = refill), then
| off mod 512 read and dropped. Not stock's buffered seek 0x4001660c: it keeps a partly read buffer
| and then re-seeks the backend to the exact offset -- measured there: the parse after it saw no tag.
rl_seek:
    move.l  4(%sp),%d0
    andi.l  #-512,%d0
    move.l  %d0,-(%sp)
    move.l  rl_fh,-(%sp)               | the backend's file id (+0)
    movea.l LLSEEK,%a0
    jsr     (%a0)
    addq.l  #8,%sp
    tst.l   %d0
    bmi.b   rs_out
    clr.l   rl_fh+12                   | the buffer empty: the next read refills from that block
    move.l  4(%sp),%d0
    andi.l  #511,%d0
    beq.b   rs_ok
    move.l  %d0,-(%sp)
    clr.l   -(%sp)                     | dst 0: read and drop (0x400165ce)
    pea     rl_fh
    jsr     FREAD
    lea     12(%sp),%sp
    tst.l   %d0
    bgt.b   rs_ok
    moveq   #-1,%d0
    rts
rs_ok:
    moveq   #0,%d0
rs_out:
    rts

| rl_slice(t, dst Part, src Part): track t's slice (rl_slA / rl_slM: off, stride, size, count, step;
| ends with 0xffff) -- CLYPS' cl_slice, unchanged. Uses d0-d1/a0-a1.
rl_slice:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a2,(%sp)
    move.l  24(%sp),%d2
    lea     rl_slA,%a2
    cmpi.l  #8,%d2
    bcs.b   sl_seg
    subq.l  #8,%d2
    lea     rl_slM,%a2
sl_seg:
    moveq   #0,%d0
    move.w  (%a2)+,%d0                 | offset
    cmpi.l  #0xffff,%d0
    beq.b   sl_out
    moveq   #0,%d1
    move.w  (%a2)+,%d1                 | stride
    muls.l  %d2,%d1
    add.l   %d1,%d0                    | d0 = offset + stride * t
    moveq   #0,%d3
    move.w  (%a2)+,%d3                 | size
    moveq   #0,%d4
    move.w  (%a2)+,%d4                 | count
    moveq   #0,%d1
    move.w  (%a2)+,%d1                 | step
sl_rep:
    movea.l 28(%sp),%a0
    adda.l  %d0,%a0
    movea.l 32(%sp),%a1
    adda.l  %d0,%a1
    move.l  %d3,%d5
sl_b:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d5
    bne.b   sl_b
    add.l   %d1,%d0
    subq.l  #1,%d4
    bne.b   sl_rep
    bra.b   sl_seg
sl_out:
    movem.l (%sp),%d2-%d5/%a2
    lea     20(%sp),%sp
    rts

| rl_mapply(bank, part, m): one MIDI track's Part values -> the engine -- CLYPS' cl_mapply, unchanged:
| stock's whole-Part apply 0x40009094 does this for every m (0x400094b0..0x400095e0), RAM writes only.
rl_mapply:
    lea     -20(%sp),%sp
    movem.l %d2-%d4/%a2-%a3,(%sp)
    move.l  24(%sp),%d0                | bank
    move.l  28(%sp),%d1                | part
    move.l  32(%sp),%d2                | m
    move.l  #BANKSTRIDE,%d3
    muls.l  %d0,%d3
    movea.l #BLOB+PART_OFF,%a2
    adda.l  %d3,%a2
    move.l  #PARTSZ,%d3
    muls.l  %d1,%d3
    adda.l  %d3,%a2                    | a2 = the Part
    moveq   #68,%d3
    muls.l  %d2,%d3
    movea.l #MENG,%a0
    adda.l  %d3,%a0                    | a0 = the engine's record m
    move.l  %d2,%d3
    lsl.l   #5,%d3
    movea.l %a2,%a1
    adda.l  #0x3e2,%a1
    adda.l  %d3,%a1                    | page values, 32 B
    moveq   #32,%d4
ma_p:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d4
    bne.b   ma_p
    moveq   #36,%d3
    muls.l  %d2,%d3
    movea.l %a2,%a1
    adda.l  #0x4e2,%a1
    adda.l  %d3,%a1                    | setup, 36 B
    movea.l %a1,%a3
    adda.l  #9,%a3                     | a3 = its 3 LFO waves
    moveq   #36,%d4
ma_s:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d4
    bne.b   ma_s
    moveq   #0,%d4                     | each LFO on a designer wave (> 10): its 16 B and slope
ma_d:
    move.b  (%a3,%d4.l),%d0
    extb.l  %d0
    moveq   #10,%d1
    cmp.l   %d1,%d0
    ble.b   ma_dn
    subi.l  #11,%d0                    | d0 = the designer it uses
    movea.l %a2,%a1
    adda.l  #0x1792,%a1
    move.l  %d0,%d1
    lsl.l   #4,%d1
    adda.l  %d1,%a1
    move.l  %d2,%d1                    | d1 = 3m + i
    add.l   %d1,%d1
    add.l   %d2,%d1
    add.l   %d4,%d1
    movea.l #MDES,%a0
    move.l  %d1,%d3
    lsl.l   #4,%d3
    adda.l  %d3,%a0
    moveq   #16,%d3
ma_w:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d3
    bne.b   ma_w
    movea.l %a2,%a1
    adda.l  #0x1812,%a1
    add.l   %d0,%d0
    adda.l  %d0,%a1
    movea.l #MSLP,%a0
    add.l   %d1,%d1
    adda.l  %d1,%a0
    move.w  (%a1),(%a0)
ma_dn:
    addq.l  #1,%d4
    cmpi.l  #3,%d4
    bne.b   ma_d
    movea.l #MBANK,%a0
    move.l  24(%sp),%d0
    move.b  %d0,(%a0,%d2.l)
    move.l  28(%sp),%d0
    move.b  %d0,8(%a0,%d2.l)
    move.l  %d2,%d0
    lsl.l   #2,%d0
    movea.l #MZERO,%a0
    clr.l   (%a0,%d0.l)
    movem.l (%sp),%d2-%d4/%a2-%a3
    lea     20(%sp),%sp
    rts

| the slices (CLYPS scope §1.7, measured there): off, stride, size, count, step. Audio = what stock's
| TRACK COPY / PASTE carries (machine, FX, levels, every page, slot record, recorder setup) plus its
| 16 scene-lock rows, per-scene bytes and LFO designer; MIDI = page values, setup, LFO designer.
    .align 2
rl_slA:
    .short 0x000, 1, 1, 1, 0           | FX1
    .short 0x008, 1, 1, 1, 0           | FX2
    .short 0x012, 2, 2, 1, 0           | levels
    .short 0x022, 1, 1, 1, 0           | machine
    .short 0x02a, 30, 30, 1, 0         | machine page 1 (all 5 machines)
    .short 0x1da, 30, 30, 1, 0         | machine page 2
    .short 0x11a, 24, 24, 1, 0         | AMP / LFO / FX1 / FX2 page 1
    .short 0x2f2, 30, 30, 1, 0         | LFO, AMP / FX page 2, MULT / TRIG
    .short 0x2ca, 5, 5, 1, 0           | slot record
    .short 0x602, 12, 12, 1, 0         | recorder setup
    .short 0x662, 32, 32, 16, 0x100    | 16 scene-lock rows
    .short 0x1662, 1, 1, 16, 10        | per-scene bytes
    .short 0x1702, 16, 16, 1, 0        | LFO designer
    .short 0x1782, 2, 2, 1, 0          | ... its slope
    .short 0xffff
rl_slM:
    .short 0x3e2, 32, 32, 1, 0         | page values
    .short 0x4e2, 36, 36, 1, 0         | setup: channel, bank, program, ...
    .short 0x1792, 16, 16, 1, 0        | LFO designer
    .short 0x1812, 2, 2, 1, 0          | ... its slope
    .short 0xffff

    .align 2
rl_kind:
    .space 4
|   Session 98: the chord -> worker request, moved here from 0x80006a50-55 (see the note
|   where the old .equ lines were). Same meaning, same byte widths.
G_KIND:
    .space 1                           | 0 idle / 1 PTN SEQ / 2 PART+PTN SEQ / 3 TRK SEQ
G_PAT:
    .space 1                           | pattern to reload
G_TRK:
    .space 1                           | TRK SEQ: track index 0..7
G_TMIDI:
    .space 1                           | TRK SEQ: 0 audio / 1 MIDI
    .global G_KIND, G_PAT, G_TRK, G_TMIDI
|   Session 85: the .ifdef that used to open this block lived in a picker-era
|   section that the redesign deletes, so it is re-opened here. rl_own is the
|   one-shot "the next stock whole-bank reload is ours to suppress" flag that
|   rl_done consumes -- the suppression is the piece worth keeping from RELOAD2.
    .ifdef RL_DONE
rl_own:
    .space 4
    .endif
|   Session 86: both are one-shot handshake bytes between the [BANK] key handlers.
|   rl3_showing  -- open for exactly one pass through stock's show tail
|   rl3_bank_used -- "our chord consumed this [BANK] gesture, swallow the release"
|   Session 93: which message the completed job should draw, set by the chord handler
|   and consumed by rl_done. 0 none / 1 TRK SEQ / 2 TRK FULL / 4 SEQ RELOAD LOST /
|   5 the sequence but not the Part chunk (2026-11-08; 3, SAVE PART FIRST, is gone).
rl_msg:
    .space 2
|   Session 93: the verify pair -- a copy of the 16 trig-mask bytes we wrote, and where.
|   In OUR cave on purpose: SCRATCH lives inside a stock 64 KB file buffer.
rl_voff:
    .space 4
rl_varm:
    .space 2
rl_vsnap:
    .space 16
rl3_showing:
    .space 2
rl3_bank_used:
    .space 2
|   2026-11-08: rl_full -> rl_done: the UI owes a [BANK] + [TRACK n] slice its PICKUP setup (rl_mch:
|   an audio machine changed) and its page redraw.
rl_pfull:
    .space 1
rl_mch:
    .space 1
rl_ptngo:
    .space 1                           | 0x80 | N: rl_follow sends the OT to pattern N
|   2026-11-08 (3): the landing
rl_arm:
    .space 1                           | 3 / 4 / 5: a staged reload waits for its tick
rl_post:
    .space 1                           | 1: it has landed, the UI half is owed (rl_follow)
rl_lp:
    .space 1                           | 1: a whole pattern is pending (tick-visible)
rl_dp:
    .space 1                           | 1: a whole pattern landed (for the UI half)
rl_jobq:
    .space 1                           | 1: a staging job is running
rl_jgen:
    .space 1                           | ... for this generation
rl_gen:
    .space 1                           | the request's generation (rq_fresh)
rq_act:
    .space 1                           | 1: a generation is open (its target below)
rq_bank:
    .space 1
rq_pat:
    .space 1
rq_ptn:
    .space 1                           | 1: it is a whole-pattern reload
st_ok:
    .space 1                           | 1: its data is staged (RQ_SLAB / RQ_PART)
    .align 2
rq_seqm:
    .space 2                           | tracks wanted (bit t)
rq_fullm:
    .space 2                           | ... of them with their slice
rl_lm:
    .space 2                           | tracks pending (tick-visible)
rl_lf:
    .space 2                           | ... with their slice
rl_ldm:
    .space 2                           | tracks landed (for the UI half)
rl_ldf:
    .space 2                           | ... with their slice
rl_tbank:
    .space 1                           | the target: bank,
rl_tpat:
    .space 1                           | pattern,
rl_t:
    .space 1                           | track 0..15 (track reloads)
rl_nopart:
    .space 1                           | 1: the Part chunk was not read (the sequence still lands)
rl_lnk:
    .space 1                           | 1: the playing pattern's Part link changed (stock's apply owed)
    .align 4
RQ_SLAB:
    .space PATSTRIDE                   | the saved pattern, as staged by the worker
RQ_PART:
    .space PARTSZ+2                    | the saved working Part it links to
    .align 2
rl_cksum:
    .space 4
rl_pathbuf:
    .space 128
rl_fh:
    .space 64
rl_hdrbuf:
    .space 32
rl_tbuf:
    .space 24

    .ifdef RL_DIAG
| ================= Session 98: the DIAG toast (see the RL_DIAG block near RDRAW) =================
| Formats the captured bytes into rl_dtext (four 24-byte lines) and shows them through
| rl3_toast2, the hardware-proven multi-line block toast. Called from rl_done (doneFn
| context) exactly where the success message used to be drawn.
    .text
rl3_diag_show:
    lea     -24(%sp),%sp
    movem.l %d2-%d4/%a2-%a4,(%sp)
|   ---- line 0: "P pppppppp S ssssssss" ----
    lea     rl_dtext,%a2               | a2 = write cursor, one 24-byte slot per line
    lea     dg_lP,%a1
    bsr.w   dg_lit
    lea     rl_dpre,%a1
    moveq   #4,%d1
    bsr.w   dg_hex
    lea     dg_lS,%a1
    bsr.w   dg_lit
    lea     rl_vsnap,%a1
    moveq   #4,%d1
    bsr.w   dg_hex
    clr.b   (%a2)
|   ---- line 1: "L llllllll K kkkkkkkk" ----
    lea     rl_dtext+24,%a2
    lea     dg_lL,%a1
    bsr.w   dg_lit
    lea     rl_dlive,%a1
    moveq   #4,%d1
    bsr.w   dg_hex
    lea     dg_lK,%a1
    bsr.w   dg_lit
    lea     rl_dcache,%a1
    moveq   #4,%d1
    bsr.w   dg_hex
    clr.b   (%a2)
|   ---- line 2: "C bptm W bptm D bp" ----
    lea     rl_dtext+48,%a2
    lea     dg_lC,%a1
    bsr.w   dg_lit
    lea     rl_dc,%a1
    moveq   #4,%d1
    bsr.w   dg_dig
    lea     dg_lW,%a1
    bsr.w   dg_lit
    lea     rl_dw,%a1
    moveq   #4,%d1
    bsr.w   dg_dig
    lea     dg_lD,%a1
    bsr.w   dg_lit
    lea     rl_dd,%a1
    moveq   #2,%d1
    bsr.w   dg_dig
    clr.b   (%a2)
|   ---- line 3: "Mn Vn Kn R rr" ----
    lea     rl_dtext+72,%a2
    lea     dg_lM,%a1
    bsr.w   dg_lit
    lea     rl_dm,%a1
    moveq   #1,%d1
    bsr.w   dg_dig
    lea     dg_lV,%a1
    bsr.w   dg_lit
    lea     rl_dv,%a1
    moveq   #1,%d1
    bsr.w   dg_dig
    lea     dg_lKk,%a1
    bsr.w   dg_lit
    lea     rl_dk,%a1
    moveq   #1,%d1
    bsr.w   dg_dig
    lea     dg_lR,%a1
    bsr.w   dg_lit
    lea     rl_dr,%a1
    moveq   #1,%d1
    bsr.w   dg_hex
    clr.b   (%a2)
|   ---- show: same call shape as rl3_show2, four lines ----
    pea     4                          | nlines  (pushed FIRST -> higher address)
    pea     rl_dlines                  | lines[] (pushed LAST  -> first argument)
    jsr     rl3_toast2
    addq.l  #8,%sp
    movem.l (%sp),%d2-%d4/%a2-%a4
    lea     24(%sp),%sp
    rts

| a1 = asciz literal -> copied to (a2) without its NUL. Clobbers d0.
dg_lit:
    move.b  (%a1)+,%d0
    beq.b   dg_lit_done
    move.b  %d0,(%a2)+
    bra.b   dg_lit
dg_lit_done:
    rts

| a1 = bytes, d1 = count -> 2 hex chars each at (a2). Clobbers d0/d1.
dg_hex:
    moveq   #0,%d0
    move.b  (%a1),%d0
    lsr.l   #4,%d0                     | ColdFire has no byte shifts; d0 is zero-extended
    bsr.b   dg_nib
    move.b  (%a1)+,%d0
    bsr.b   dg_nib
    subq.l  #1,%d1
    bne.b   dg_hex
    rts

| a1 = bytes, d1 = count -> ONE hex digit each (low nibble) at (a2). Clobbers d0/d1.
dg_dig:
    move.b  (%a1)+,%d0
    bsr.b   dg_nib
    subq.l  #1,%d1
    bne.b   dg_dig
    rts

| d0 low nibble -> one hex character at (a2)+. Clobbers d0.
dg_nib:
    andi.l  #15,%d0
    cmpi.l  #10,%d0
    blt.b   dg_nib_d
    addq.l  #7,%d0                     | 10..15 -> 'A'..'F'
dg_nib_d:
    addi.l  #'0',%d0
    move.b  %d0,(%a2)+
    rts

dg_lP:  .asciz "P "
dg_lS:  .asciz " S "
dg_lL:  .asciz "L "
dg_lK:  .asciz " K "
dg_lC:  .asciz "C "
dg_lW:  .asciz " W "
dg_lD:  .asciz " D "
dg_lM:  .asciz "M"
dg_lV:  .asciz " V"
dg_lKk: .asciz " K"
dg_lR:  .asciz " R "
    .align 2
rl_dlines:
    .long   rl_dtext
    .long   rl_dtext+24
    .long   rl_dtext+48
    .long   rl_dtext+72
| captures -- all written by the code paths marked DIAG above
rl_dc:      .space 4                   | chord:  bank, pattern, track, midi
rl_dw:      .space 4                   | worker: bank, pattern, track, midi
rl_dd:      .space 2                   | doneFn: PLAY_BANK, ACT_PAT
rl_dk:      .space 1                   | G_KIND as the worker read it
rl_dr:      .space 1                   | last PARSEPAT return, low byte
rl_dm:      .space 1                   | message code that would have been shown
rl_dv:      .space 1                   | verify: 0 not armed / 1 pass / 2 fail
    .align 2
rl_dpre:    .space 4                   | live record, first 4 bytes, BEFORE the copy
rl_dlive:   .space 4                   | live record at doneFn
rl_dcache:  .space 4                   | live-cache record at doneFn
rl_dtext:   .space 96                  | 4 lines x 24
    .endif
