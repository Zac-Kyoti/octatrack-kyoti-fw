| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
|
| patch_qlrec -- surface QUANTIZE LIVE REC (PERSONALIZE) to the front panel.
|
|   [REC] held + [PLAY] pressed twice, close enough together   toggles
|   QUANTIZE LIVE REC  0 <-> 1
|
|   This is the OT's ALL-OR-NOTHING live-record quantize (the PERSONALIZE row),
|   NOT the per-track 50% TRIG QUANT tweak in the TRACK TRIG MENU.
|
|   A "QUANT LIVE REC ON" / "QUANT LIVE REC OFF" toast shows while [REC] stays
|   held and closes the instant [REC] is released (Session 51: back to an
|   explicit close, now that dur is never <=0 -- see below).
|
| STATE  0x800000ac  -- the stock PERSONALIZE runtime word (getter 0x40068ce0 /
|   setter 0x40068ca0, menu index 0).  It already lives inside the stock 0x64
|   'ANDY'-restore span (0x80000070..0xd3), so it persists across a power cycle
|   with NO build change.  We only mirror what the stock setter does: write the
|   battery-SRAM shadow 0x100fff3c (= 0x100fff00 + 0xac - 0x70) and -- because
|   we bypass the PERSONALIZE dispatcher's `jmp 0x4001f23c @ 0x40069074` --
|   re-checksum the 'ANDY' block ourselves (jsr FUN_4001f23c).
|   ⚠️ Session 51, HW-confirmed: the checked/unchecked glyph in the PERSONALIZE
|   menu is the OPPOSITE sense from the Session 46 write-up's "0 = OFF" guess --
|   raw 0 draws as the row's ON/checked state. The toast text below is chosen
|   to match what the MENU actually shows, not the raw bit's face value.
|
| ---- the combo (RE: NOTES "Session 46") ----
| REC handler 0x40048774(keycode@4, event@8): keymap code 0x29, handles press
|   AND release.  Every press ends by setting 0x460d1726 = 1 ("REC held"); the
|   release path 0x4004883a clears it.  No other handler distinguishes it -- a
|   clean held-modifier flag.  (Also readable via is_key_held: FUN_4003171c,
|   *(u32*)(0x46c7d8ee + code*24).)
| PLAY handler 0x40061778(keycode@4, event@8): keymap code 0x28, press only
|   (flags word = 0 -> no hold/repeat events).  Stock already branches on
|   0x460d1726 -- REC held -> start LIVE REC (0x460d172a = 1); not held -> plain
|   transport toggle.  We detour its first instruction (jsr 0x4009b5c0, the
|   "project ready?" gate) so our check runs before anything else and resume at
|   0x4006177e for the stock path.
|
| ---- Session 50: the persistent (dur<=0) toast HUNG THE UNIT on real
|   hardware (flashed + confirmed on a MKI).  Root cause, from real disassembly
|   of FUN_4005a2b8: dur<=0 does NOT produce a passive banner -- it tail-jumps
|   into FUN_40031494, which inserts the notification onto a linked list headed
|   at 0x460d165c that is structurally a MODAL WINDOW / OVERLAY STACK.  dur>0
|   (the self-timing path every other HW-confirmed toast in this project uses --
|   DIRECT JUMP v3, RELOAD2) never touches that list at all.  FIX: never call
|   NOTIFY with dur<=0 -- open it with a short dur>0 (REARM_DUR) and
|   PERIODICALLY REOPEN it every REARM_INTERVAL frames while [REC] stays held
|   (`qlr_tick`, detour of 0x400522ca, the same per-control-frame site DIRECT
|   JUMP v2's dj_tick2 uses -- ticks every frame, playing or stopped).
|   HW-flashed 2026-09-13: confirmed no hang. Six follow-up requests from that
|   session, addressed below (Session 51):
|
|   1. Double-tap timing was pure press-COUNTING with no notion of elapsed time
|      -- any 2nd press, however long after the 1st, flipped it.  User wants a
|      genuine pairing WINDOW: two presses only count as "the double-tap" if
|      the second follows the first within MAX_GAP ticks; a too-slow pair is
|      discarded entirely (not flipped) and the late press becomes the start
|      of a fresh pairing attempt.  New state: G_WINDOW, decremented by
|      qlr_tick once per frame while a hold is in progress; a press checks it
|      instead of a simple odd/even parity.  MAX_GAP is an untuned starting
|      guess (see the .equ below) -- same class of "needs an HW eyeball pass"
|      constant as REARM_DUR/DJ_TOAST_DUR elsewhere in this project.
|      HW-CONFIRMED BUG in the first cut of this (flashed, tested): after a
|      successful flip the window was immediately re-armed as if ready for a
|      fresh pair -- so a fast press RIGHT AFTER a flip could complete a
|      "pair" with the flip itself, occasionally firing an unwanted 3rd-tap
|      flip.  Fixed with an explicit G_PEND flag: a flip clears it, so the
|      very next press can only ever become a NEW pending reference (no
|      flip) -- completing a pair now strictly requires two FRESH presses
|      after any flip, never one press riding on the flip's own timing.
|   2. Toast fade-out shortened ~1/3: REARM_DUR 0x30 -> 0x20, REARM_INTERVAL
|      0x18 -> 0x10 (kept at half of REARM_DUR, the same safety margin as
|      before).
|   3. An occasional small square, textless box flashes where the toast was,
|      right after it closes, then clears itself.  Not chased further this
|      session -- most likely an artefact of FUN_4005a2b8/NOTIFY_CLOSE's own
|      stock close/redraw sequence (this project is now the first mod to
|      exercise a toast opening or closing anywhere near this often); NOTES.md
|      "Session 51" has the reasoning.  Re-adding the explicit close (item 4)
|      likely makes this glitch show up predictably at release time too, not
|      just after a natural timeout -- flagged, not fixed.
|   4. `qlr_recrel` now calls NOTIFY_CLOSE again for an instant close on
|      release.  Safe now (unlike the pre-Session-50 design) because dur is
|      NEVER <=0 any more, so the modal path this whole rewrite exists to
|      avoid is never registered in the first place -- there is nothing about
|      calling NOTIFY_CLOSE itself that was ever the problem.
|   5. Menu doesn't live-redraw while you're already looking at the
|      PERSONALIZE row we just changed (it reads correctly next time you open
|      the menu -- this is a stale ON-SCREEN WIDGET, not a stale VALUE).  Not
|      fixed this session: doing it safely needs the specific "personalize row
|      N is dirty" mechanism, not a borrowed redraw sequence built for a
|      different UI context (risk of a new, different hang) -- see NOTES.md
|      "Session 51".
|   6. HW-confirmed the toast's ON/OFF label was backwards relative to what
|      the PERSONALIZE menu shows checked/unchecked -- fixed by swapping which
|      string qp_show picks for a given raw value (the raw bit's meaning and
|      the flip mechanics are UNCHANGED; only the label was wrong).
|
| Detours (applied by build_qlrec.py):
|   0x40061778  6 B  `jsr 0x4009b5c0`           -> jmp qlr_play
|   0x4004883a  6 B  `clr.l 0x460d1726`         -> jmp qlr_recrel
|   0x400522ca  6 B  `lea 0x46c7dfba,%a2`       -> jsr qlr_tick

    .equ REC_HELD,     0x460d1726        | longword, 1 while [REC] is physically held
    .equ QLR,          0x800000ac        | PERSONALIZE: QUANTIZE LIVE REC (bool)
    .equ QLR_SH,       0x100fff3c        | its 'ANDY' battery-SRAM shadow
    .equ CKSUM,        0x4001f23c        | FUN_4001f23c -- recompute+store 'ANDY' checksum
    .equ NOTIFY,       0x4005a2b8        | FUN_4005a2b8(text, dur); dur>0 ONLY -- see the
                                          |   Session 50 note above.  NEVER pass dur<=0.
    .equ NOTIFY_CLOSE, 0x40056bec        | tears down the FUN_4005a2b8 toast; no-op if none open
    .equ PROJ_GATE,    0x4009b5c0        | displaced from 0x40061778
    .equ PLAY_RESUME,  0x4006177e        | 0x40061778 + 6  (tst.l %d0 ; bne.s ...)
    .equ WATCHDOG_A2,  0x46c7dfba        | displaced lea target from 0x400522ca (SOFT MUTE
                                          |   release watchdog; untouched, just replayed)

    | toast timing -- NOT yet HW-tuned (Session 51).  REARM_DUR must stay
    | comfortably above one re-arm interval's worth of frames so the toast
    | never visibly flickers/expires between refreshes; the actual frame-to-ms
    | ratio of the 0x400522ca tick is not pinned.
    .equ REARM_DUR,      0x20            | dur passed to NOTIFY on every (re)open (Session 51: was 0x30)
    .equ REARM_INTERVAL, 0x10            | ticks between re-arms while [REC] is held (was 0x18)

    | double-tap pairing window (Session 51, new) -- also untuned.  Two [PLAY]
    | presses count as THE double-tap only if the second follows the first
    | within MAX_GAP ticks of qlr_tick; otherwise the pair is discarded (no
    | flip) and the late press starts a fresh pairing attempt.
    .equ MAX_GAP,        0x10                 | Session 51-ter: back to 0x10. The 0x08 guess was
                                          |   WRONG -- HW-confirmed the "slow taps execute" symptom
                                          |   was actually the G_PEND re-arm-on-flip bug (fixed
                                          |   above), not the window being too generous. At 0x08 a
                                          |   real fast double-tap became too hard to land at all
                                          |   ("has to be WAY too fast to execute"). 0x10 is the
                                          |   value that already worked for genuine fast taps before
                                          |   this detour -- still technically untuned, but no longer
                                          |   a blind guess in this direction.

|   free scratch RAM -- above the 0x80004000 boot re-image window, disjoint from
|   MUTE MODE 0x80006c66 / DIRECT JUMP 0x80006a40-44 / RELOAD2 0x80006a50-53
|   (see reference/MERGE.md).  Nothing here needs to persist.
    .equ G_CNT,        0x80006a5c        | long: 0 until the very first [PLAY] press this hold
    .equ G_ARM,        0x80006a60        | byte: 1 => qlr_tick should keep re-arming the toast
    .equ G_RTICKS,     0x80006a64        | long: frames left until the next toast re-arm
    .equ G_LASTMSG,    0x80006a68        | long: text pointer of the currently-shown toast
    .equ G_WINDOW,     0x80006a6c        | long: ticks left in the current pairing window
    .equ G_PEND,       0x80006a70        | byte: 1 => a press is waiting for its FRESH partner
                                          |   (Session 51-bis: without this, a flip's own re-armed
                                          |   window could be completed by the VERY NEXT press,
                                          |   i.e. a fast 3rd tap could flip again on its own --
                                          |   HW-confirmed. G_PEND is cleared on every flip so the
                                          |   next press can only ever become a NEW pending
                                          |   reference, never complete a pair by itself.)

    .text

| ================= [PLAY] press -- detour @ 0x40061778 =================
| Entry stack (exactly what stock 0x40061778 sees): 0(sp)=ret, 4(sp)=keycode,
| 8(sp)=event (always 1 here).  Only d0/d1/a0 touched.
    .global qlr_play
qlr_play:
    tst.l   REC_HELD
    beq     qp_stock                    | REC not held -> stock PLAY (out of .b range now)

    addq.l  #1,G_CNT
    move.l  G_CNT,%d0
    moveq   #1,%d1
    cmp.l   %d0,%d1
    beq     qp_first                    | very first press of this hold (out of .b range)

|   --- not the first press: is a press currently pending its partner? ---
    tst.b   G_PEND
    beq.b   qp_rearm_window              | no pending press -> this one becomes the new pending

|   --- there IS a pending press: does THIS one land inside its window? ---
    move.l  G_WINDOW,%d0
    ble.b   qp_rearm_window              | too slow -> discard, this press starts a fresh pair

|   --- fast enough: this completes the pair -- flip QUANTIZE LIVE REC ---
    clr.b   G_PEND                       | require a FRESH pair before the next flip
                                          | (HW-confirmed fix: a fast press right after a flip
                                          |  must NOT be able to complete a "pair" with the flip
                                          |  itself)
    move.l  QLR,%d0
    eori.l  #1,%d0
    andi.l  #1,%d0
    move.l  %d0,QLR
    move.l  %d0,QLR_SH                   | battery-SRAM shadow
    jsr     CKSUM                        | re-checksum the 'ANDY' block

    | Session 51: HW-confirmed the menu's checked/unchecked glyph is the
    | OPPOSITE of the raw bit's face value -- raw 0 draws as checked/ON in
    | PERSONALIZE.  Show the string that matches the MENU, not the bit.
    move.l  QLR,%d0
    lea     qlr_msg_on,%a0
    tst.l   %d0
    beq.b   qp_show
    lea     qlr_msg_off,%a0
qp_show:
    move.l  %a0,G_LASTMSG                | remember it for qlr_tick's re-arm calls
    pea     REARM_DUR                    | dur>0 -- self-timing, non-modal (Session 50)
    move.l  %a0,-(%sp)
    jsr     NOTIFY                       | FUN_4005a2b8(text, REARM_DUR)
    addq.l  #8,%sp
    move.l  #REARM_INTERVAL,%d0          | GAS on this target rejects #imm -> absolute
    move.l  %d0,G_RTICKS
    moveq   #1,%d0
    move.b  %d0,G_ARM                    | keep the toast re-armed until [REC] releases
    rts                                 | swallow -- G_PEND stays 0 (cleared above): the very
                                          | next press can only become a fresh pending, never
                                          | complete a pair with this flip

|   --- no pending press yet, OR the pending one was too slow: THIS press
|   becomes the new (sole) pending reference.  No flip. ---
qp_rearm_window:
    moveq   #1,%d0
    move.b  %d0,G_PEND
    move.l  #MAX_GAP,%d0
    move.l  %d0,G_WINDOW
    rts                                 | swallow -- wait for a fresh, fast partner

qp_first:
    moveq   #1,%d0
    move.b  %d0,G_PEND
    move.l  #MAX_GAP,%d0
    move.l  %d0,G_WINDOW                 | arm the window for press #2
qp_stock:
    jsr     PROJ_GATE                    | displaced: jsr 0x4009b5c0
    jmp     PLAY_RESUME                  | -> 0x4006177e

| ================= [REC] release -- detour @ 0x4004883a =================
| Reached only for event 0 (release) of keycode 0x29.  Session 51: back to an
| explicit close (safe now -- dur is never <=0, so the modal path Session 50
| exists to avoid is never registered in the first place; NOTIFY itself does
| this same "close if one is open" check every time it opens a new one).
    .global qlr_recrel
qlr_recrel:
    clr.l   REC_HELD                     | displaced: clr.l 0x460d1726
    clr.l   G_CNT
    clr.b   G_PEND
    tst.b   G_ARM
    beq.b   qr_done
    clr.b   G_ARM
    jsr     NOTIFY_CLOSE                 | close instantly (Session 51 item 4)
qr_done:
    rts

| ================= per-control-frame tick -- detour @ 0x400522ca =================
| jsr-kind detour: this cave is entered via `jsr`, so the return address is
| already the instruction right after the 6-byte site -- we replay the
| displaced `lea` and `rts`, we do not `jmp` back.  Runs every control frame,
| playing or stopped (same site DIRECT JUMP v2's dj_tick2 uses).
    .global qlr_tick
qlr_tick:
|   --- Session 51: count down the double-tap pairing window while a press is
|   actually pending (independent of G_ARM/toast state -- the window tracks
|   TAP TIMING, not toast visibility).  Gated on G_PEND, not G_CNT: right
|   after a flip G_CNT is still nonzero but nothing is pending, so this must
|   NOT keep ticking (it would be harmless either way, since qlr_play ignores
|   G_WINDOW whenever G_PEND is 0, but ticking only while genuinely pending is
|   the precise statement of what this counter means). ---
    tst.l   REC_HELD
    beq.b   qt_toast
    tst.b   G_PEND
    beq.b   qt_toast                    | nothing pending right now
    subq.l  #1,G_WINDOW                 | let it go negative; qlr_play only checks <=0

qt_toast:
    tst.b   G_ARM
    beq.b   qt_stock                    | not re-arming right now -> just passthrough

    subq.l  #1,G_RTICKS
    bgt.b   qt_stock                    | not time to re-arm yet

    move.l  #REARM_INTERVAL,%d0          | GAS on this target rejects #imm -> absolute
    move.l  %d0,G_RTICKS
    | NOTIFY may route through kernel post like FUN_40056bc0 does (dj_tick2's own
    | precedent at this exact hook site) -- save D0-D1/A0-A1 defensively so whatever
    | 0x40052200 does right after our rts sees them unclobbered, same as dj_tick2.
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    move.l  G_LASTMSG,%a0
    pea     REARM_DUR
    move.l  %a0,-(%sp)
    jsr     NOTIFY                       | FUN_4005a2b8(text, REARM_DUR) again -- refresh
    addq.l  #8,%sp
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp

qt_stock:
    lea     WATCHDOG_A2,%a2              | displaced: lea 0x46c7dfba,%a2
    rts

|   "QUANT LIVE REC ON/OFF" (17/18 ch) -- chosen to fit the 128 px screen;
|   FUN_4005a2b8 sizes the window to textpx+15, and the full "QUANTIZE LIVE
|   REC OFF" (21 ch) overruns it.
qlr_msg_on:
    .asciz "QUANT LIVE REC ON"
    .align 2
qlr_msg_off:
    .asciz "QUANT LIVE REC OFF"
    .align 2
