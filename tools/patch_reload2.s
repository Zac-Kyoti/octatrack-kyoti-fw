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

|   [PTN] key handler FUN_4005a044(keycode@4, event@8).  Detour @ entry:
|   displaced `move.l 8(sp),d0 ; moveq #1,d1` (6 B).  event 2 = HOLD.
    .equ PTN_HOLD_H,  0x4005a044
    .equ PTN_RESUME,  0x4005a04a        | after the displaced 2 insns (cmp d0,d1 ; bne ...)
    .equ PTN_HOLDTAIL,0x4005a0d2        | stock hold tail: PTN_MODE = 1 ; jmp 0x40027de4

|   [NO] handler @ 0x4005e25c.  Detour replaces `move.l 8(sp),d0 ; beq.s 0x4005e276` (6 B).
    .equ NO_REL,    0x4005e276          | event 0 -> stock release cleanup
    .equ NO_PRESS,  0x4005e262          | press/hold path after the displaced 2 insns

|   [YES] handler @ 0x4005e4c8.  Detour replaces `move.l 4(sp),d1 ; move.l 8(sp),d0` (8 B).
    .equ YES_RESUME,0x4005e4d0

    .equ JOB_POST,  0x40022778          | FUN_40022778(mask) -> post the type-0x14 storage job
    .equ JOB14_EXIT,0x400858a8          | 0x14 case: tst.l d0 ; ... ; done-dance ; -> dequeue loop
    .equ JOB14_ORIG,0x4008586c          | 0x14 case: resume after the displaced 2 insns

|   arrow keys -- keycodes 0x34 (UP) / 0x21 (RIGHT) -> ARROW_A ; 0x33 (DOWN) /
|   0x20 (LEFT) -> ARROW_B.  Verified against the 26-byte keymap tables
|   (T1 0x400bfc10 / T2 0x400c01f4) + octabam MAINMENU.md sec 7 (HW-tested).
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

| ================= [PTN] HOLD -- open the picker  (@ 0x4005a044) =================
| Detour replaces 6 bytes: move.l 8(%sp),%d0 ; moveq #1,%d1

    .global rl_ptn
rl_ptn:
    move.l  8(%sp),%d0                 | displaced -- d0 = event
    moveq   #2,%d1
    cmp.l   %d0,%d1
    bne.b   rlp_stock                  | not a hold -> stock

|   --- [PTN] HOLD ---
|   Session 80 continued: dropped the RUNNING gate (user's ask -- these actions
|   must work whether the transport is playing or stopped; none of the worker's
|   own logic in rl_job actually depends on RUNNING, so there was never a real
|   correctness reason to require it here -- see that session's NOTES.md entry
|   for the open display-refresh-while-stopped question this raises).
|
|   Also dropped the G_KIND ("a reload is already queued") gate here -- this is
|   what made the picker permanently unopenable after the hardware report of
|   "PTN hold stops working entirely, no recovery": if G_KIND ever got stuck
|   nonzero for ANY reason (a real storage-task timing edge this session could
|   not pin down conclusively -- see NOTES.md "Session 80 continued", the
|   FUN_40022778 single-fixed-scratch-buffer finding), this gate meant NOTHING
|   could ever reopen the picker again, full stop. The re-entrancy protection
|   that gate existed for moved to rl_yes_exec instead (guards the actual
|   ARM+POST step, where a genuine double-post could corrupt an in-flight job)
|   -- opening the picker itself is now always available, so a stuck flag is a
|   diagnosable "YES seems to do nothing" instead of an unrecoverable dead key.
    tst.b   G_MENU
    bne.b   rlp_holdtail               | already open
    tst.l   POPUP
    bne.b   rlp_holdtail               | a modal dialog is up
    tst.l   ARR_ACT
    bne.b   rlp_holdtail               | arranger

    moveq   #1,%d0
    move.b  %d0,G_MENU                 | open
    clr.b   G_SEL                      | default = item 0 (TRK SEQ) -- [YES] straight away
    move.l  %d0,PTN_USED               | suppress SELECT PATTERN on the [PTN] release
    jsr     rl_draw

rlp_holdtail:
    jmp     PTN_HOLDTAIL               | stock: PTN_MODE = 1 ; jmp 0x40027de4

rlp_stock:
    moveq   #1,%d1                     | displaced #2
    jmp     PTN_RESUME

| ================= [NO] -- close the window  (@ 0x4005e25c) =================
| Detour replaces 6 bytes: move.l 8(%sp),%d0 ; beq.s 0x4005e276

    .global rl_no
rl_no:
    move.l  8(%sp),%d0                 | displaced -- event
    bne.b   rln_notrel
    jmp     NO_REL                     | event 0 -> stock release cleanup
rln_notrel:
    moveq   #1,%d1
    cmp.l   %d0,%d1
    bne.b   rln_stock                  | hold / other -> stock

    tst.b   G_MENU
    beq.b   rln_stock                  | window closed -> stock [NO]
    tst.l   POPUP
    bne.b   rln_stock                  | a modal dialog is up -> let stock [NO] answer it

    bsr.w   rl_no_exec
    rts                                | swallow

rln_stock:
    jmp     NO_PRESS

| ---- rl_no_ptnheld: poked into the [PTN]-held keymap layer's own NO press slot,
| REPLACING stock NO_PTNHELD_STOCK (0x40056aa8) -- see the header comment above
| for why that's safe (an unconditional no-op for every PTN_MODE our own [PTN]-
| hold gesture can produce). Only reachable while [PTN] is physically held.
    .global rl_no_ptnheld
rl_no_ptnheld:
    moveq   #1,%d1
    cmp.l   8(%sp),%d1                 | event == press ?
    bne.b   rnph_stock
    tst.b   G_MENU
    beq.b   rnph_stock                 | window closed -> replay the real stock behaviour
    tst.l   POPUP
    bne.b   rnph_stock

    bsr.w   rl_no_exec
    rts                                | swallow

rnph_stock:
    jmp     NO_PTNHELD_STOCK           | 0x40056aa8, byte-for-byte, stack undisturbed (jmp,
                                        | not jsr -- see rl_yes_ptnheld's identical idiom)

| ---- rl_no_exec: shared "close the window" body -- bsr'd from rl_no AND
| rl_no_ptnheld so both entry points drive identical logic. Ends in rts back to
| whichever entry bsr'd it. ----
    .global rl_no_exec
rl_no_exec:
    clr.b   G_MENU
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    jsr     CLOSE_CB
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    rts

| ================= [YES]  -- execute + close  (@ 0x4005e4c8) =================
| Detour replaces 8 bytes: move.l 4(%sp),%d1 ; move.l 8(%sp),%d0

    .global rl_yes
rl_yes:
    move.l  8(%sp),%d0                 | event
    moveq   #1,%d1
    cmp.l   %d0,%d1
    bne.w   rly_stock
    tst.b   G_MENU
    beq.w   rly_stock                  | window closed -> stock YES (DJ toggle slots in here)
    tst.l   POPUP
    bne.w   rly_stock                  | a modal dialog came up -> stock YES

    bsr.w   rl_yes_exec
    rts

| ---- rl_yes_ptnheld: poked into the [PTN]-held keymap layer's own YES press
| slot (stock: NULL -- see the header comment above; the exact bug Session 60
| found and fixed for DIRECT JUMP, applied here identically). Only reachable
| while [PTN] is physically held.
    .global rl_yes_ptnheld
rl_yes_ptnheld:
    move.l  8(%sp),%d0                 | event
    moveq   #1,%d1
    cmp.l   %d0,%d1
    bne.b   ryph_rts
    tst.b   G_MENU
    beq.b   ryph_rts                   | window closed -> stock's own NULL slot did nothing
    tst.l   POPUP
    bne.b   ryph_rts

    bsr.w   rl_yes_exec
ryph_rts:
    rts

| ---- rl_yes_exec: shared "close the window + execute the selection" body --
| bsr'd from rl_yes AND rl_yes_ptnheld so both entry points drive identical
| logic. Ends in rts back to whichever entry bsr'd it. ----
    .global rl_yes_exec
rl_yes_exec:
|   --- close the window ---
    clr.b   G_MENU
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    jsr     CLOSE_CB                   | dismiss the 0x460d1e64 popup
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp

|   Session 80 continued: refuse to arm a NEW request while a previous one's
|   G_KIND hasn't been serviced/cleared yet (rl_job clears it right at entry,
|   normally within a frame or two) -- this is now the ONLY re-entrancy guard
|   in the whole feature (rl_ptn no longer blocks reopening on G_KIND; see its
|   own comment). Arming anyway here would write G_TRK/G_TMIDI/G_PAT/G_KIND
|   out from under a job that's still in flight, and Session 80's static read
|   of FUN_40022778 found it always posts through ONE fixed scratch message
|   buffer (0x460bd912) -- a second post before the first is read is a real,
|   not just theoretical, corruption risk. Toast instead of silently no-op'ing
|   so a stuck G_KIND is an observable, reportable symptom, not a mystery.
    tst.b   G_KIND
    beq.b   ryx_ok
    lea     rl_msg_busy,%a0
    bra.w   rly_show
ryx_ok:
    moveq   #0,%d2
    move.b  G_SEL,%d2                  | 0 TRK SEQ / 1 PTN SEQ / 2 PART + PTN SEQ

    tst.l   %d2
    bne.b   rly_ptn
|   --- item 0: TRK SEQ -- arm a per-track reload of the currently-addressed track ---
    jsr     rl_arm_trk
    bra.w   rly_toast

rly_ptn:
|   --- item 1 (PTN SEQ, kind 1) or item 2 (PART + PTN SEQ, kind 2) ---
|   d2 is already the kind (1 or 2).
    move.b  %d2,G_KIND
    move.b  ACT_PAT,%d0
    move.b  %d0,G_PAT
    moveq   #0,%d0
    move.b  CUR_BANK,%d0
    moveq   #1,%d1
    lsl.l   %d0,%d1
    move.l  %d1,-(%sp)
    jsr     JOB_POST                   | FUN_40022778(1<<curbank)
    addq.l  #4,%sp

rly_toast:
    tst.l   %d2
    bne.b   rly_toast_ptn

|   --- TRK SEQ toast: "T<n> SEQ" (audio) / "MT<n> SEQ" (MIDI) ---
    moveq   #0,%d0
    move.b  G_TRK,%d0
    addq.l  #1,%d0                     | 1-based track number
    lea     rl_fmt_trk,%a0
    tst.b   G_TMIDI
    beq.b   rly_tk1
    lea     rl_fmt_mtrk,%a0
rly_tk1:
    move.l  %d0,-(%sp)                 | n
    move.l  %a0,-(%sp)                 | fmt
    pea     rl_tbuf
    jsr     SPRINTF                    | sprintf(rl_tbuf, fmt, n)
    lea     12(%sp),%sp
    lea     rl_tbuf,%a0
    bra.b   rly_show

rly_toast_ptn:
    lea     rl_msg_ptn,%a0
    moveq   #1,%d0
    cmp.l   %d2,%d0
    beq.b   rly_show
    lea     rl_msg_ppt,%a0             | item 2 = PART + PTN SEQ

rly_show:
    pea     0x44
    move.l  %a0,-(%sp)
    jsr     TOAST                      | FUN_4005a2b8(text, dur)
    addq.l  #8,%sp
    rts                                | swallow YES

rly_stock:
    .ifdef MERGE
    jmp     DJ_TOGGLE                  | chain: DIRECT JUMP checks [PTN]+[YES], else replays -> stock
    .else
    move.l  4(%sp),%d1                 | displaced
    move.l  8(%sp),%d0                 | displaced
    jmp     YES_RESUME
    .endif

| ================= arrow keys -- move the highlight while the window is open =================
| ARROW_A (@ 0x4004b970) replaces 8 bytes: lea -12(%sp),%sp ; movem.l %d2-%d3/%a2,(%sp)
| ARROW_B (@ 0x400491a0) replaces 6 bytes: move.l %d2,-(%sp) ; movea.l 8(%sp),%a0
| When the window is closed both replay the displaced prologue and fall straight
| through -- behaviourally invisible.

    .global rl_arr_a
rl_arr_a:                              | UP / RIGHT -- previous item (wrapping)
    tst.b   G_MENU
    bne.b   raa_pick
    lea     -12(%sp),%sp               | displaced original
    movem.l %d2-%d3/%a2,(%sp)          | displaced original
    jmp     ARROW_A_RESUME
raa_pick:
    moveq   #0,%d0
    move.b  G_SEL,%d0
    subq.l  #1,%d0
    bpl.b   raa_set
    moveq   #N_ITEMS-1,%d0
raa_set:
    move.b  %d0,G_SEL
    jsr     rl_draw
    rts                                | swallow (stack untouched on entry)

    .global rl_arr_b
rl_arr_b:                              | DOWN / LEFT -- next item (wrapping)
    tst.b   G_MENU
    bne.b   rab_pick
    move.l  %d2,-(%sp)                 | displaced original
    movea.l %sp@(8),%a0                | displaced original
    jmp     ARROW_B_RESUME
rab_pick:
    moveq   #0,%d0
    move.b  G_SEL,%d0
    addq.l  #1,%d0
    cmpi.l  #N_ITEMS,%d0
    bcs.b   rab_set
    moveq   #0,%d0
rab_set:
    move.b  %d0,G_SEL
    jsr     rl_draw
    rts                                | swallow

| ---- rl_draw: (re)show the popup for G_SEL ----
| clobbers only d0/a0 (POPUP2 preserves d2-d7/a2-a6 per ABI).
    .global rl_draw
rl_draw:
    moveq   #0,%d0
    move.b  G_SEL,%d0
    lea     rl_menu_tbl,%a0
    move.l  (%a0,%d0.l*4),%a0
    move.l  %a0,-(%sp)
    jsr     POPUP2                     | FUN_4005a0e0(text)
    addq.l  #4,%sp
    rts

| ---- rl_arm_trk: arm a TRK SEQ reload of the currently-addressed track ----
| Reads CUR_TRACK (0x80000000) + MIDI_MODE (0x80000012), sets G_TRK / G_TMIDI /
| G_PAT / G_KIND=3, posts FUN_40022778(1<<curbank).  Clobbers d0/d1 only
| (preserves d2 -- rl_yes still needs G_SEL there).  Also the entry point for the
| (unbuilt) [PTN]+[TRACK] power move.
    .global rl_arm_trk
rl_arm_trk:
    moveq   #0,%d0
    move.b  CUR_TRACK,%d0
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

rl_menu_tbl:
    .long   rl_msg_trk
    .long   rl_msg_ptn
    .long   rl_msg_ppt
rl_msg_trk:
    .asciz "TRK SEQ"
    .align 2
rl_msg_ptn:
    .asciz "PTN SEQ"
    .align 2
rl_msg_ppt:
    .asciz "PART + PTN SEQ"
    .align 2
rl_msg_busy:
    .asciz "RELOAD BUSY"
    .align 2
rl_fmt_trk:
    .asciz "T%d SEQ"
    .align 2
rl_fmt_mtrk:
    .asciz "MT%d SEQ"
    .align 2

| ================= the SEQ worker -- jmp detour @ the type-0x14 case 0x40085864 =================
| replaces 8 bytes: move.l %a2,%fp@(-650) ; move.l %a2@(4),%sp@-
|
| G_KIND on entry:  1 = PTN SEQ (whole slab, Part link preserved)
|                   2 = PART + PTN SEQ (whole slab incl. Part link, then apply it)
|                   3 = TRK SEQ (one track's region only)

    .global rl_job
rl_job:
    move.l  %a2,-650(%fp)              | displaced #1 -- stash msg for both exit paths
    tst.b   G_KIND
    bne.b   rlj_ours
    move.l  %a2@(4),-(%sp)            | displaced #2
    jmp     JOB14_ORIG                | not ours -> stock: jsr 0x40084094

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
    move.l  %d5,%d0
    move.b  ACT_PAT,%d1
    cmp.b   %d1,%d0
    bne.b   rlj_ok
    moveq   #1,%d0
    move.l  %d0,RELOAD_NOW

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
