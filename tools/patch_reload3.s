| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
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
|   [BANK] + [TRACK n] -> the same, PLUS re-apply the saved Part from RAM.
|
| Carried over unchanged because it is proven: rl_job's per-track slice, rl_arm_trk,
| rl_openstrd, and the whole-bank suppression (rl_done + the FUN_4000faf0 live
| refresh) that cut a reload from 6852 buffered card reads to 354.
|
| Full rationale, measurements and open risks: reference/RELOAD_REDESIGN.md

| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
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
    .equ G_KIND,    0x80006a50          | worker request: 0 idle / 1 PTN SEQ / 2 PART+PTN SEQ / 3 TRK SEQ
    .equ G_PAT,     0x80006a51          | pattern to reload (byte)
    .equ G_MENU,    0x80006a52          | 1 = the picker window is open
    .equ G_SEL,     0x80006a53          | highlighted item: 0 TRK SEQ / 1 PTN SEQ / 2 PART + PTN SEQ
    .equ G_TRK,     0x80006a54          | TRK SEQ: track index 0..7
    .equ G_TMIDI,   0x80006a55          | TRK SEQ: 0 = audio track, 1 = MIDI track

|   ---- stock symbols ----
    .equ PTN_USED,  0x460d173e          | set 1 to suppress SELECT PATTERN on [PTN] release
    .equ PTN_MODE,  0x460d1ab2          | stock: "[PTN] was not already in SELECT mode"
    .equ POPUP,     0x460e5cd0          | != 0 -> a blocking FUN_4006d57c dialog is up
    .equ ARR_ACT,   0x460d1aec          | arranger active
    .equ RUNNING,   0x800065b8          | transport state -- LONGWORD (=1 playing)
    .equ ACT_PAT,   0x800065be          | sequencer's active pattern (byte)
    .equ CUR_BANK,  0x80000002
    .equ CUR_PART,  0x80000003          | the Part the sounding pattern is assigned to (byte)
    .equ CUR_TRACK, 0x80000000          | UI-selected track (byte 0..7 ; mirror 0x100b14cc)
    .equ MIDI_MODE, 0x80000012          | != 0 -> the MIDI pages are up (track index means MIDI track)
    .equ RELOAD_NOW,0x46c8028a          | step engine polls this at 0x400a2530
    .equ POPUP2,    0x4005a0e0          | FUN_4005a0e0(text) -- bare text box, no timeout
    .equ CLOSE_CB,  0x40056bc0          | FUN_40056bc0 -- close the 0x460d1e64 popup
    .equ TOAST,     0x4005a2b8          | FUN_4005a2b8(text, dur) -- the "PART %d RELOADED" toast
    .equ PARTAPPLY, 0x40009094          | FUN_40009094(bank, part) -- apply a Part by event (parts-switch path)
    .equ RDRAW,     0x46c7c72c          | screen redraw dirty flag (set to 1)

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
    .equ DONE_RESUME,  0x40023c68       | resume after the displaced mvs.w (move.l d0,-(sp))
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
    .equ OPEN_BUF,  0x460a8f60          | the loader's 64 KB buffer (idle while we hold the task)
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
    .equ PTN_TRK_H,      0x40083dc4     | [PTN]-overlay TRACK handler. All 8 refs to it
    .equ PTN_TRK_RES,    0x40083dca     | are the 8 [PTN] overlay track slots, so
                                        | arriving here IS [PTN]+[TRACK]: no held test.
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
|   ---- Session 88: our own titled, centered, SELF-DISMISSING card ----
|   Hardware report #10 asked for four things on the notification box: title
|   "RELOAD FROM PROJ", the second line CENTRED, NO "OK" prompt to dismiss, and the
|   same card style for the plain TRK SEQ message instead of the big block toast.
|
|   MLNOTIFY (0x4006d57c) cannot do it and is dropped. Decoded, it is a BLOCKING
|   dialog by construction:
|     * it pushes keymap layer 0x400cdff8 (0x4006d722) -- that IS the "OK" prompt's
|       input handler, so the box waits for a key by design
|     * it has NO duration argument anywhere. (An earlier comment in this file claimed
|       0x460e5e20 was "a 40-frame countdown". WRONG, and the hardware report is what
|       exposed it: 0x460e5e20 is the box WIDTH accumulator -- seeded to 40 at
|       0x4006d596, then max'd against each measured line width + 9 and clamped to 128.
|       0x460e5e24 is the height, 7*nlines+27 clamped to [34,64].)
|     * its body renderer 0x4006d128 draws every line with x hardcoded to 4
|       (0x4006d170) -- that is exactly the left-justification the user is reporting.
|
|   So build the card directly out of the same primitives MLNOTIFY uses, on the OTHER
|   popup slot -- the one SHOW_WIN uses -- because that slot already owns stock's
|   countdown and never pushes a keymap layer. Result: no OK prompt exists to press,
|   the dismiss is stock's own timer, and every line is centred because we pass a
|   computed x instead of 4. Width/height formulas, body font and line spacing are all
|   copied from MLNOTIFY so the box keeps the proportions the user already approved.
    .equ WIN_NEW,        0x4005829c     | (w,h,x,y,style,onClose) -> handle.
                                        | style 4 = the CARD look MLNOTIFY uses;
                                        | style 0xa = the block toast SHOW_WIN uses.
    .equ WIN_TITLE,      0x40057c84     | (handle, text, flag) -- the title bar
    .equ WIN_CLEAR,      0x400356a8     | (winptr) -- clear the interior
    .equ DRAWTEXT,       0x40012bd8     | (font, winptr, x, y, len, text)
    .equ TEXTW,          0x40012f30     | (font, maxlen, text) -> pixel width
    .equ FONT_BODY,      0x400ba876     | the font MLNOTIFY measures AND draws with
    .equ WIN_SLOT,       0x460d1e5c     | the countdown-owned popup handle
    .equ WIN_ONCLOSE,    0x460d1e60     | called after the countdown dismisses it
    .equ CD_CUR,         0x460d1e50     | ticks left in this segment
    .equ CD_RELOAD,      0x460d1e58     | reload value for CD_CUR
    .equ CD_SEGS,        0x460d1e54     | segments left == number of countdown dots.
                                        | We set it to 1: one segment, therefore no
                                        | dots, and the expiry dismisses directly.
    .equ CD_FLAG,        0x460d1e4c     | tick gate: ZERO = countdown disabled
    .equ CD_TICK,        0x40056ab8     | the gate + tick entry (NOT 0x40056ac0, which
                                        | is past the gate -- hook the gate, not the body)
    .equ WIN_DISMISS,    0x40056a70     | tears the slot down + calls WIN_ONCLOSE
|   NOT called, on purpose -- this is the dot drawer. Kept documented so a future
|   session does not "helpfully" add it back and reintroduce the countdown dots.
    .equ WIN_REFRESH,    0x40037cc8     | draws the countdown dots (y 7..11)
    .equ CARD_STYLE,     4
    .equ CARD_DUR,       0x18           | ticks the card stays up (~0.5 s). Goes into
                                        | CD_CUR whole, since CD_SEGS is 1. SELECT BANK
                                        | uses 0xf0 across 4 segments for its
                                        | several-second countdown -- same units.
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
    .equ TOAST_DUR,      0x18           | stock's duration for this toast family
                                        | (0x4005e09c). RELOAD2 used 0x44; this is the
                                        | "OT standard" the spec asks for.

| ================= [PTN] + [TRACK n] -- reload that track's CF-saved sequence =================
| The Part is NOT touched. Toast "TRK SEQ RELOADED".
| Releasing [PTN] afterwards must not raise SELECT PATTERN -- achieved with stock's
| OWN mechanism rather than a detour on the [PTN] handler: set PTN_CONSUMED, which
| stock's release path already tests and skips the window on.
| Displaces 6 B: move.l %d2,-(%sp) ; move.l 8(%sp),%d2
    .global rl3_ptn_trk
rl3_ptn_trk:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0                 | event == press ?
    bne.w   r3p_stock
    moveq   #0,%d0
    move.b  7(%sp),%d0                 | low byte of the keycode long at 4(sp)
    bsr.w   rl3_do_ptn
    rts                                | swallow: stock's [PTN]+[TRACK] does nothing
                                       | observable on hardware (user-confirmed)
r3p_stock:
    move.l  %d2,-(%sp)                 | displaced original
    move.l  8(%sp),%d2                 | displaced original (reads the pre-push 4(sp))
    jmp     PTN_TRK_RES

| ============ [BANK] + [TRACK n] -- sequence PLUS the saved Part, from RAM ============
| Toast "TRK SEQ + PART RELOADED", or stock's "SAVE PART FIRST!" when the Part has
| never been saved -- which PART_RELOAD itself reports, so we need no dirty-flag
| logic of our own. A saved Part DOES replace a dirty Part: that is the point.
| Displaces 6 B: move.l %d2,-(%sp) ; move.l 8(%sp),%d1
    .global rl3_bank_trk
rl3_bank_trk:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0                 | event == press ?
    bne.w   r3b_stock
|   Session 85: BOTH chords are tested here, because the [PTN] overlay was measured
|   NOT to redirect the TRACK keys (see PTN_HELD_FLAG). rl3_ptn_trk is kept as well,
|   for the case where the overlay IS active in some UI context -- both routes run
|   the same body, so whichever fires, the behaviour is identical.
    tst.l   PTN_HELD_FLAG
    beq.b   r3b_try_bank
    moveq   #0,%d0
    move.b  7(%sp),%d0
    bsr.w   rl3_do_ptn
    rts
r3b_try_bank:
    tst.l   BANK_HELD_FLAG
    beq.w   r3b_stock                  | neither modifier -> ordinary track select
    moveq   #0,%d0
    move.b  7(%sp),%d0
    subi.l  #0x10,%d0
    jsr     rl3_arm_n                  | --- the SEQUENCE half ---
|   --- the PART half: stock's own routine, from RAM (the per-Part SAVED copy) ---
    moveq   #0,%d0
    move.b  CUR_PART,%d0               | the Part the sounding pattern is assigned to
    move.l  %d0,-(%sp)
    jsr     PART_RELOAD
    addq.l  #4,%sp
    move.l  %d0,-(%sp)                 | PART_RELOAD's verdict must survive the call
    moveq   #1,%d0
    move.b  %d0,rl3_bank_used          | claim the [BANK] release: rl3_bank_rel swallows
                                       | it AND runs the overlay teardown there, so the
                                       | teardown happens exactly once, on the release.
|   Session 86: no BANK_WIN_CLOSE here any more. With the window deferred, the chord has
|   no window up at all -- which is also why MLNOTIFY below can draw: it bails out
|   entirely while 0x460e5cd0 is non-zero, and now that flag is clear.
    move.l  (%sp)+,%d0
    tst.l   %d0
    beq.b   r3b_unsaved
|   Part reloaded to its saved version. TWO lines, at the user's request (hardware
|   report #9 item 1): the split is "TRK SEQ + PART" / "RELOADED", which also buys
|   back the spaces around the + that the 21-char single-line width budget had
|   forced out -- each line is now well inside the box width.
    lea     rl3_lines_trkpart,%a0
    moveq   #2,%d0
    bsr.w   rl3_show
    bra.b   r3b_done
r3b_unsaved:
|   Never saved: the SEQUENCE still reloaded, so saying only "SAVE PART FIRST!"
|   (stock's wording) would wrongly imply nothing happened. Two lines instead, so
|   both facts are visible at once.
    lea     rl3_lines_unsaved,%a0
    moveq   #2,%d0
    bsr.w   rl3_show
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
    jsr     rl3_arm_n                  | arm TRK SEQ for that track and post the job
    move.l  #-1,%d0
    move.l  %d0,PTN_CONSUMED           | same value stock writes at 0x40056b44
|   Session 88 item 4: this used to be the big block TOAST (FUN_4005a2b8). It is now
|   the same card as the [BANK] message, at the user's request, so both reload
|   messages look alike.
    lea     rl3_lines_trk,%a0
    moveq   #2,%d0
    bra.w   rl3_show                   | tail-call: its rts returns to our caller

| ---- rl3_card(title, nlines, lines[]) -- titled, centred, self-dismissing ----
| Replaces BOTH the old rl3_toast (the block toast) and MLNOTIFY (the OK dialog), so
| every RELOAD message is now the same card. No keymap layer is pushed anywhere in
| here, which is precisely why there is no "OK" to answer.
rl3_card:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)      | 40 B saved; ret at 40(sp), args at 44/48/52
    move.l  44(%sp),%a5                | a5 = title (0 = no title bar)
    move.l  48(%sp),%d7                | d7 = nlines
    move.l  52(%sp),%a4                | a4 = lines[]
|   Something already in this slot would be leaked, so dismiss it first -- exactly
|   what SHOW_WIN does at its own head (0x40059fa4).
    tst.l   WIN_SLOT
    beq.b   rc_noprev
    jsr     WIN_DISMISS
rc_noprev:
|   --- width: MLNOTIFY's formula. max(40, each measured width + 9), capped at 128 ---
    moveq   #40,%d6
    move.l  %a5,%d0
    beq.b   rc_wlines
    move.l  %a5,%a0
    bsr.w   rc_measure
    addq.l  #4,%d0                     | title sits in a bar; a little more slack
    addq.l  #5,%d0
    cmp.l   %d6,%d0
    ble.b   rc_wlines
    move.l  %d0,%d6
rc_wlines:
    moveq   #0,%d5
rc_wloop:
    cmp.l   %d7,%d5
    bge.b   rc_wdone
    move.l  %d5,%d0
    lsl.l   #2,%d0
    move.l  (%a4,%d0.l),%a0
    bsr.w   rc_measure
    addq.l  #4,%d0
    addq.l  #5,%d0                     | +9 total, as MLNOTIFY does
    cmp.l   %d6,%d0
    ble.b   rc_wnext
    move.l  %d0,%d6
rc_wnext:
    addq.l  #1,%d5
    bra.b   rc_wloop
rc_wdone:
    cmpi.l  #128,%d6
    ble.b   rc_wok
    move.l  #128,%d6
rc_wok:
|   --- height: 7*nlines + 27, clamped [34,64] -- MLNOTIFY's formula ---
    move.l  %d7,%d0
    lsl.l   #3,%d0
    sub.l   %d7,%d0
    addi.l  #27,%d0
    cmpi.l  #34,%d0
    bge.b   rc_h1
    moveq   #34,%d0
rc_h1:
    cmpi.l  #64,%d0
    ble.b   rc_h2
    moveq   #64,%d0
rc_h2:
    move.l  %d0,%d4                    | d4 = height
|   --- create the window: style 4 = card, onClose = stock's own dismiss ---
    pea     WIN_DISMISS
    pea     CARD_STYLE
    clr.l   -(%sp)
    clr.l   -(%sp)
    move.l  %d4,-(%sp)
    move.l  %d6,-(%sp)
    jsr     WIN_NEW
    lea     24(%sp),%sp
    tst.l   %d0
    beq.w   rc_out                     | no window slot free -- say nothing, don't fault
    move.l  %d0,WIN_SLOT
    move.l  %d0,%a3
    move.l  %a3,%d3
    addi.l  #36,%d3                    | d3 = winptr (handle+36), as MLNOTIFY uses
    move.l  %d3,-(%sp)
    jsr     WIN_CLEAR
    addq.l  #4,%sp
    move.l  %a5,%d0
    beq.b   rc_notitle
    clr.l   -(%sp)
    move.l  %a5,-(%sp)
    move.l  %a3,-(%sp)
    jsr     WIN_TITLE                  | the title bar, y = height-10
    lea     12(%sp),%sp
rc_notitle:
|   --- the body lines, each CENTRED. y counts UP from the bottom, so line 0 (the
|   --- highest y) lands on top, matching MLNOTIFY's own ordering.
    move.l  %d4,%d5
    subi.l  #17,%d5                    | y = height-17, then -7 per line
    moveq   #0,%d2
rc_dloop:
    cmp.l   %d7,%d2
    bge.b   rc_ddone
    move.l  %d2,%d0
    lsl.l   #2,%d0
    move.l  (%a4,%d0.l),%a2            | a2 = lines[i]
    move.l  %a2,%a0
    bsr.w   rc_measure                 | d0 = raw pixel width
    move.l  %d6,%d1
    sub.l   %d0,%d1
    bpl.b   rc_xok
    moveq   #0,%d1                     | wider than the box -- clamp to the left edge
rc_xok:
    asr.l   #1,%d1                     | x = (boxwidth - textwidth) / 2
    move.l  %a2,-(%sp)
    move.l  #-1,-(%sp)
    move.l  %d5,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %d3,-(%sp)
    pea     FONT_BODY
    jsr     DRAWTEXT
    lea     24(%sp),%sp
    addq.l  #1,%d2
    subi.l  #7,%d5
    bra.b   rc_dloop
rc_ddone:
|   --- arm stock's countdown: it is what dismisses the card, with no key involved ---
|   ** ONE SEGMENT, and WIN_REFRESH is deliberately NOT called. ** That is what keeps
|   the countdown DOTS off the card -- hardware report #10: "I'd rather not have
|   countdown dots anywhere. These are instantly executed functions." A progress
|   indicator would imply something is still pending, which is wrong here.
|   MEASURED: 0x40037cc8 is the only thing that draws those dots, and it has exactly
|   two callers -- SHOW_WIN's tail (0x4005a034, which we do not use) and the tick at
|   0x40056aea. The tick only reaches it when CD_SEGS is STILL non-zero after being
|   decremented (0x40056ae2 bne). With CD_SEGS = 1 the single segment expires straight
|   into the dismiss at 0x40056ae4 instead, so the dot routine is never entered at all.
|   CD_CUR therefore carries the whole duration rather than a quarter of it.
    clr.l   WIN_ONCLOSE
    move.l  #CARD_DUR,%d0
    move.l  %d0,CD_RELOAD
    move.l  %d0,CD_CUR
    moveq   #1,%d0
    move.l  %d0,CD_SEGS                | exactly one segment -> no dots, just a dismiss
|   ** CD_FLAG MUST BE NON-ZERO or the countdown never runs at all. ** The tick is
|   gated on it: 0x40056ab8 `tstl 0x460d1e4c` / 0x40056abe `beq -> rts`, and only then
|   does the body at 0x40056ac0 decrement anything. An earlier version of this code
|   CLEARED the flag, which would have left the card up forever on hardware -- i.e.
|   exactly the stuck box the report asked us to get rid of. The emulator cannot catch
|   this (its harness never drives the tick at all, stock SELECT BANK included, which
|   is why diag_reload3_card.py gates that assertion on a stock control); static
|   reading of the gate is what found it.
    move.l  %d0,CD_FLAG                | 1 = countdown armed and running
    move.l  %d0,RDRAW                  | d0 is still 1
rc_out:
    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    rts

| a0 = text -> d0 = pixel width. Clobbers d0/d1/a0/a1 only.
rc_measure:
    move.l  %a0,-(%sp)
    move.l  #-1,-(%sp)
    pea     FONT_BODY
    jsr     TEXTW                      | FUN_40012f30(font, maxlen, text)
    lea     12(%sp),%sp
    rts

| ---- rl3_show: a0 = lines[], d0 = nlines. Always titled "RELOAD FROM PROJ". ----
rl3_show:
    move.l  %a0,-(%sp)
    move.l  %d0,-(%sp)
    pea     rl3_title
    jsr     rl3_card
    lea     12(%sp),%sp
    rts

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
    tst.l   BANK_COMMIT
    bne.b   r3r_show
|   Toggle-OFF tap: no window of ours to open. But the PRESS pushed the overlay, and
|   with no window there is no onClose to pop it -- so pop it here unless a popup IS
|   up, in which case stock's own dismiss below will run onClose and do it.
    tst.l   POPUP
    bne.b   r3r_stock
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
rl3_msg_trk:
    .asciz "TRK SEQ RELOADED"
    .align 2
|   21 chars -- inside the ~21 that stock's longest single-line toasts use
|   ("RELOADING SAVED FILES"). The toast box auto-sizes to the measured text width
|   (0x40012f30 then `addil #15,%d0`), so over-long text is clipped at the screen
|   edge rather than wrapped. The spec's "TRK SEQ + PART RELOADED" was 23; this
|   drops the spaces around the + to fit.
|   Session 86: split across two lines, so the spaces around the + come back.
rl3_msg_trkpart_1:
    .asciz "TRK SEQ + PART"
    .align 2
rl3_msg_trkpart_2:
    .asciz "RELOADED"
    .align 2
|   Session 88 item 1: the card's title bar, was "RELOAD".
rl3_title:
    .asciz "RELOAD FROM PROJ"
    .align 2
rl3_msg_reloaded:
    .asciz "RELOADED"
    .align 2
rl3_msg_trkonly:
    .asciz "TRK SEQ"
    .align 2
rl3_msg_empty:
    .asciz ""
    .align 2
|   MLNOTIFY's line array. Stock's own groups carry an empty-string terminator
|   after the lines (0x400b44b5), so mirror that shape.
|   rl3_card takes an explicit line count, so these no longer need stock's
|   empty-string terminator. Every line is centred by the drawing code.
rl3_lines_unsaved:
    .long   rl3_msg_trk                | "TRK SEQ RELOADED"   -- what DID happen
    .long   STOCK_SAVEFIRST            | "SAVE PART FIRST!"   -- stock's own wording
    .align 2
rl3_lines_trkpart:
    .long   rl3_msg_trkpart_1          | "TRK SEQ + PART"
    .long   rl3_msg_trkpart_2          | "RELOADED"
    .align 2
|   Session 88 item 4: the plain TRK SEQ message, split to mirror the [BANK] card.
rl3_lines_trk:
    .long   rl3_msg_trkonly            | "TRK SEQ"
    .long   rl3_msg_reloaded           | "RELOADED"
    .align 2

| ---- rl_arm_trk: arm a TRK SEQ reload of the currently-addressed track ----
| Reads CUR_TRACK (0x80000000) + MIDI_MODE (0x80000012), sets G_TRK / G_TMIDI /
| G_PAT / G_KIND=3, posts FUN_40022778(1<<curbank).  Clobbers d0/d1 only
| (preserves d2 -- rl_yes still needs G_SEL there).  Also the entry point for the
| (unbuilt) [PTN]+[TRACK] power move.
    .global rl_arm_trk
rl_arm_trk:
    moveq   #0,%d0
    move.b  CUR_TRACK,%d0
|   Session 85: the chord design knows WHICH track from the keycode, so it enters
|   here with the index already in d0 instead of reading the UI-selected track.
|   Everything below is the proven rl_arm_trk tail, unchanged.
    .global rl3_arm_n
rl3_arm_n:
    andi.l  #7,%d0
    move.b  %d0,G_TRK
    moveq   #0,%d0
    move.b  MIDI_MODE,%d0
    beq.b   rat_aud
    moveq   #1,%d0
rat_aud:
    move.b  %d0,G_TMIDI
    move.b  ACT_PAT,%d0
    move.b  %d0,G_PAT
    moveq   #3,%d0
    move.b  %d0,G_KIND
    moveq   #0,%d0
    move.b  CUR_BANK,%d0
    moveq   #1,%d1
    lsl.l   %d0,%d1
    move.l  %d1,-(%sp)
    jsr     JOB_POST                   | FUN_40022778(1<<curbank)
    addq.l  #4,%sp
    rts
rl_fmt_trk:
    .asciz "T%d SEQ"
    .align 2
rl_fmt_mtrk:
    .asciz "MT%d SEQ"
    .align 2

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
|   0x40023c62  mvs.w 0x460bd910,d0       ; the bank mask (stashed at buf-2)
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
    move.w  MASK_SAVED,%d0             | displaced (mvs.w 0x460bd910,d0), as
    ext.l   %d0                        | plain m68k -- no ColdFire mvs needed
    jmp     DONE_RESUME
rld_skip:
    clr.b   rl_own                     | one-shot: consume it
    jmp     DONE_EPILOG                | skip the whole-bank reload entirely
    .endif

| ================= the SEQ worker -- jmp detour @ the type-0x14 case 0x40085864 =================
| replaces 8 bytes: move.l %a2,%fp@(-650) ; move.l %a2@(4),%sp@-
|
| G_KIND on entry:  1 = PTN SEQ (whole slab, Part link preserved)
|                   2 = PART + PTN SEQ (whole slab incl. Part link, then apply it)
|                   3 = TRK SEQ (one track's region only)

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
    cmpi.l  #3,%d0
    bls.b   rlj_isours                 | 1..3 = a request we made
    clr.b   G_KIND                     | garbage -> drop it, let stock have the job
rlj_notours:
    move.l  (%sp)+,%d0
    move.l  %a2@(4),-(%sp)            | displaced #2
    jmp     JOB14_ORIG                | not ours -> stock: jsr 0x40084094
rlj_isours:
    move.l  (%sp)+,%d0
    bra.w   rlj_ours                   | .w: rlj_ours is out of byte-branch range

rlj_ours:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)

    moveq   #0,%d5
    move.b  G_PAT,%d5                  | d5 = target pattern P
    moveq   #0,%d0
    move.b  G_KIND,%d0
    move.l  %d0,rl_kind                | stash the kind across the FUN_4008cebc calls
    clr.b   G_KIND                     | consume now -- a re-entrant real RELOAD BANK
                                       | must NOT see it set
|   Session 83: RESTORED (see the rl_done block for the full retry rationale).
|   Claim the whole-bank reload that THIS job's doneFn is about to perform, so
|   rl_done suppresses that one and only that one. One-shot, set only here, on
|   the path that has already established the job is ours.
    .ifdef RL_DONE
    moveq   #1,%d0
    move.b  %d0,rl_own
    .endif
    move.w  CKSUM,%d0
    move.w  %d0,rl_cksum

    jsr     rl_openstrd                | -> d0 = open result (fh in rl_fh)
    tst.l   %d0
    bpl.b   rlj_opened
    moveq   #-12,%d0                   | ENOENT -> stock "THIS BANK HAS NEVER BEEN SAVED!"
    bra.w   rlj_exit

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
    tst.l   %d0
    bmi.w   rlj_readfail
    addq.l  #1,%d4
    cmp.l   %d5,%d4
    ble.b   rlj_ploop                  | parse patterns 0..P (0..P-1 discarded)

    pea     rl_fh
    jsr     FCLOSE
    addq.l  #4,%sp

    moveq   #0,%d0
    move.b  CUR_BANK,%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    move.l  #BLOB,%a4
    add.l   %d0,%a4
    move.l  %d5,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    add.l   %d0,%a4                    | a4 = live slab for P

    move.l  rl_kind,%d7                | d7 = kind (1 / 2 / 3)
    moveq   #3,%d0
    cmp.l   %d7,%d0
    beq.w   rlj_trk

|   --- kind 1 / 2: copy the whole 0x8ed8 slab ---
|   Stash the CURRENT Part-link byte in a cave word (don't trust d3/a5 across the
|   FWMEMCPY call -- the ABI says d2-d7/a2-a6 are preserved, but this one byte is
|   the whole point of the "mask", so be explicit).
    move.l  %a4,%a5
    add.l   #PAT_PART,%a5              | a5 -> the live pattern->Part link byte
    moveq   #0,%d0
    move.b  (%a5),%d0
    move.l  %d0,rl_asgn                | current assignment (may be a reassignment)

    move.l  #PATSTRIDE,-(%sp)
    pea     SCRATCH
    move.l  %a4,-(%sp)
    jsr     FWMEMCPY                   | memcpy(liveslab, SCRATCH, 0x8ed8)
    lea     12(%sp),%sp

    move.l  %a4,%a5                    | recompute -- a4 is preserved, be safe on a5
    add.l   #PAT_PART,%a5

    moveq   #1,%d0
    cmp.l   %d7,%d0
    bne.b   rlj_faithful
|   kind 1 = PTN SEQ: put the current assignment back (a sequence reload must not
|   silently re-point the pattern at a different Part)
    move.l  rl_asgn,%d0
    move.b  %d0,(%a5)
    bra.w   rlj_setflag

rlj_faithful:
|   kind 2 = PART + PTN SEQ: the assignment is now the SAVED one (from the memcpy).
|   Read it, mirror it to 0x80000003, and apply that Part to the engine.
    moveq   #0,%d3
    move.b  (%a5),%d3
    andi.l  #3,%d3                     | saved Part 0..3
    move.b  %d3,CUR_PART               | 0x80000003 = current-part mirror
    moveq   #0,%d0
    move.b  CUR_BANK,%d0
    move.l  %d3,-(%sp)                 | part  (rightmost arg)
    move.l  %d0,-(%sp)                 | bank
    jsr     PARTAPPLY                  | FUN_40009094(bank, savedPart)
    addq.l  #8,%sp
    moveq   #1,%d0
    move.l  %d0,RDRAW                  | refresh the Part display
    bra.w   rlj_setflag

rlj_trk:
|   --- kind 3 = TRK SEQ: copy just the selected track's region ---
|   d2 = in-slab byte offset, d3 = length
    moveq   #0,%d0
    move.b  G_TRK,%d0
    andi.l  #7,%d0
    tst.b   G_TMIDI
    bne.b   rlj_trk_midi
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0                    | d0 = t * 0x91a
    move.l  %d0,%d2
    move.l  #TRAC_A,%d3
    bra.b   rlj_trk_copy
rlj_trk_midi:
    move.l  #TRAC_M,%d1
    muls.l  %d1,%d0                    | d0 = t * 0x8b0
    add.l   #MIDI_BASE,%d0             | + 0x48d0
    move.l  %d0,%d2
    move.l  #TRAC_M,%d3
rlj_trk_copy:
    move.l  %d3,-(%sp)                 | length
    move.l  #SCRATCH,%d0
    add.l   %d2,%d0
    move.l  %d0,-(%sp)                 | src = SCRATCH + off
    move.l  %a4,%d0
    add.l   %d2,%d0
    move.l  %d0,-(%sp)                 | dst = liveslab + off
    jsr     FWMEMCPY
    lea     12(%sp),%sp

rlj_setflag:
    .ifdef RL_DONE
|   Session 83: RESTORED together with rl_done -- the two stand or fall together.
|   Without the suppression, stock's own whole-bank reload refills the live cache;
|   with it, nothing does, and the slice lands in the cold blob while playback
|   keeps reading stale bytes (measured in "(4)" as "LIVE copy: STILL SCRIBBLED").
    moveq   #0,%d0
    move.b  CUR_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     LIVE_REFRESH               | FUN_4000faf0(bank): RAM->RAM, no card
    addq.l  #4,%sp
    .endif
|   Session 80 continued (4): refresh the LIVE cache from the cold blob.
|   MEASURED: our worker writes only the cold blob (0x400e21e0...). Stock's
|   whole-bank reload -- the one rl_done now suppresses -- was what refilled the
|   downstream live cache at 0x1001614e, so with it gone the slice landed in the
|   blob while playback kept reading stale bytes ("LIVE copy: STILL SCRIBBLED"
|   in diag_reload2_deser.py). Suppressing the reload without this would have
|   made every reload inaudible.
|   FUN_4000faf0(bank) is stock's own "make bank current": memcpy(0x1001614e,
|   blob + bank*0x9b340, 0x8ed80) + the parts region -> 0x100a4ece. It is
|   RAM->RAM, no card access, so it costs none of the ~1 s the card read did,
|   and NOTES.md (Session 27 thread) already records it as safe to call for
|   exactly this purpose: it copies all 16 slabs, but only the reloaded one
|   differs. Direction matters and is correct -- the cold blob is the working
|   store (p-lock edits land there) and the live cache is downstream of it.
|   ** BACKED OUT in Session 80 continued (5) along with rl_done -- see the
|   rl_done block below for why. The call was:
|       moveq #0,%d0 ; move.b CUR_BANK,%d0 ; move.l %d0,-(%sp)
|       jsr LIVE_REFRESH ; addq.l #4,%sp
|   It is only needed WITH the rl_done suppression (without it, stock's own
|   whole-bank reload refills the live cache), so the two stand or fall together. **
|   ===== Session 86: RELOAD_NOW IS NEVER ARMED. =====
|   Hardware report #9 item 3: "Reloading restarts the track sequence from step 1,
|   AND the internal (master) metronome is also restarted." MEASURED root cause --
|   the flag at 0x46c8028a is polled once per step at 0x400a2530 and the block it
|   gates is stock's WHOLE-BANK re-home, which is POSITIONAL, not just a cache
|   refresh. In that block:
|     0x400a26fe  movew #0,0x800065b4    | previous master step
|     0x400a2704  movew #0,0x800065b2    | THE MASTER PLAYHEAD -> sequence restart
|     0x400a2658  moveb LEN_TBL[..]-1,0x800065b6  | ticks-within-step -> wrap next tick
|     0x400a27e2  movel #1,0x800065b8    | RUNNING = 1 -- this is ALSO the old
|                                        | "reload while stopped starts playback" bug,
|                                        | which the RUNNING gate here was papering over
|   0x800065b2 is DIRECT JUMP's MASTER_STEP / BAR_CTR -- measured there as the bounded
|   master playhead -- and the metronome's beat flags are derived from it by masking
|   against 0x400abae4 / 0x400abacc (0x400a4264..0x400a42a0). So zeroing it restarts
|   the sequence AND the metronome from one write: two symptoms, one cause.
|
|   Nothing in that block is needed here, which is why dropping it costs nothing:
|     * trig data -- our worker writes the cold blob and the LIVE_REFRESH above copies
|       blob -> live cache, so both consumers already see the new bytes.
|     * per-track scale/length -- stock re-reads it from the blob on EVERY wrap
|       (0x400a3d08 `moveb %a2@(1),%a3@` -> TRK_SCALE_IX[t], DIRECT JUMP's own
|       finding), so a changed step count self-heals within one cycle, in time.
|   So ask for a screen refresh and touch the transport on NO path at all -- the same
|   conclusion DIRECT JUMP reached the hard way: keep time by READING the clock, never
|   by reseeding it. ACT_PAT / RUNNING are no longer consulted: there is nothing left
|   to gate, because we no longer do anything that could disturb the transport.
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
    bra.b   rlj_exit

| ---- rl_openstrd: d0 = open result; builds rl_pathbuf, fills rl_fh ----
    .global rl_openstrd
rl_openstrd:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)

    clr.l   -(%sp)
    clr.l   -(%sp)
    jsr     PROJDIR                    | d0 = char* project dir
    addq.l  #8,%sp

    moveq   #0,%d1
    move.b  CUR_BANK,%d1
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

    .align 2
rl_kind:
    .space 4
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
rl3_showing:
    .space 2
rl3_bank_used:
    .space 2
rl_asgn:
    .space 4
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
