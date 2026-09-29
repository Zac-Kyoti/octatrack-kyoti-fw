| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
|
| patch_qlrec -- surface QUANTIZE LIVE REC (PERSONALIZE) to the front panel.
|
|   [REC] held + [PLAY]                 opens a toast showing the CURRENT
|                                       QUANTIZE LIVE REC setting (no change)
|   [PLAY] again while that toast is up  inverts the setting; the toast
|                                       re-opens showing the new one
|   ... and again, and again             inverts each time
|   [PLAY] after the toast has gone      just shows the current setting again
|
|   This is the OT's ALL-OR-NOTHING live-record quantize (the PERSONALIZE row),
|   NOT the per-track 50% TRIG QUANT tweak in the TRACK TRIG MENU.
|
| ============================================================================
| Session 93 -- THE 0x400522ca TICK DETOUR IS GONE.  It crashed the unit.
| ============================================================================
| Session 92 shipped this gesture with the toast's life counted by `qlr_tick`,
| a detour of 0x400522ca inside FUN_40052200, on the strength of a Session-21
| note calling that site a "per-control-frame handler" that "ticks every frame,
| playing or stopped".  Flashed 2026-09-25: **a few uses hard-crash the
| machine** -- dead controls plus a loud, persistent high-frequency crackle --
| and, separately, the setting flipped on presses made AFTER the toast had
| already gone.
|
| Both symptoms are the same root cause, and the note was wrong.
|
|   1. WHY IT CRASHED.  qlr_tick called NOTIFY / NOTIFY_CLOSE.  Both bottom out
|      in FUN_40000c3c, which is the kernel's POST/WAKE primitive, not a draw
|      call:  it saves %sr and masks to 0x2700, writes the caller's word into a
|      ring buffer (base +0x14, index +0x18, mask +0x10), bumps the count at
|      +0x04, and -- if a task is blocked on that queue (+0x0c) -- marks it
|      runnable (+0x4c) and pokes the ready-list head 0x800068d8.  That is a
|      SCHEDULER operation.  Running it from inside the engine's frame handler
|      leaves the audio path unserviced: exactly the reported crackle + frozen
|      panel.  (FUN_40056bec reaches it at 0x40056c1a; FUN_4005a2b8 reaches it
|      via its own NOTIFY_CLOSE call at 0x4005a2cc and via FUN_40057008.)
|   2. WHY THE WINDOW NEVER CLOSED.  G_ARM/G_LIVE were only ever decremented in
|      qlr_tick.  The site fires rarely (route A: 0 entries across a bare boot,
|      a --load-project run and a 4000-frame --sequencer run), so the window
|      stayed open indefinitely and every later press flipped.
|   3. WHY SESSIONS 50/51 SURVIVED IT.  There, G_ARM was only set after a
|      successful double-tap FLIP, so the dangerous window was rare -- and the
|      double-taps themselves often failed to register (that is what all the
|      MAX_GAP feedback was about).  Session 92 armed it on EVERY press, which
|      is why the latent crash finally became reproducible.  WARNING: the crash
|      was therefore ALREADY LATENT in the "hardware-confirmed, final" Session
|      51 build; it was rare, not absent.
|
| THE FIX: do not tick anything ourselves.  Ask the OS whether its toast is on
| screen.  There is no detour on 0x400522ca any more, and nothing this patch
| does runs outside a key-handler context.
|
|   NOTIF_H 0x460d1e70  the notification's window handle.  FUN_4005a2b8 stores
|                       it; FUN_40056bec clears it through FUN_40055db4 (see
|                       the `clrl %a2@` at 0x40055dd8).  Non-zero == a toast
|                       is on screen.
|   NOTIF_T 0x460d1e6c  its remaining duration.  Counted down by FUN_40056c28
|                       (0x40056c28: load, beq out, subq #1, store, bne out,
|                       else bra FUN_40056bec) -- i.e. at zero the OS closes
|                       the toast itself.  > 0 == still ticking.
|
| Both are maintained by stock, in the UI task, which is the correct context
| for that kernel post.  We only read them.
|
| ---- the toast clock, and why 0.8 s is exactly 0x30 (Session 93) ----
| NOTIF_T is decremented by FUN_40056c28, called from the UI task FUN_40056c40
| when it receives message type 1 (the byte at 0x400a727a) on queue 0x460d1664.
| That message is posted by the DTIM1 interrupt handler at 0x40055cb8 (it ends
| in `rte` and clears DTER at 0xfc074003), through a divide-by-2 prescaler in
| 0x400c0cf0 (reloaded with 2 at 0x40055cf4).
|
| DTIM1 is programmed once at 0x40040498:
|     DTRR (0xfc074004) = 68750
|     DTMR (0xfc074000) = 0x001d  -> RST=1, CLK=2 (bus clock / 16), FRR=1
|                                    (restart), ORRI=1 (irq on reference), PS=0
|     period = (68750 + 1) * 16 / f_bus
| With f_bus = CPU/2 = 132 MHz (the boot halts at 0x4000fa8c unless the CPU PLL
| reads 264 MHz): DTIM1 = 8.3335 ms = 119.998 Hz, and the UI tick, being every
| SECOND interrupt, is 16.667 ms = 59.999 Hz.
|
| So one NOTIFY duration unit is 1/60 s, and:
|     0.8 s  =  48  =  0x30
| which is also, independently, stock's own house value -- 87 of stock's
| FUN_4005a2b8 call sites pass 0x30 (then 7x 0x60, 3x 0x44, 2x 0x5a).  A stock
| toast and this one are now the same length, which is a free sanity check on
| the hardware: if they look different, this derivation is wrong.
| (The f_bus = CPU/2 step is the one assumption.  At f_bus = 264 MHz the tick
| would be 120 Hz and stock's 0x30 would be a 0.4 s toast -- implausibly brief
| for "PART n RELOADED", which is why CPU/2 is taken as correct.)
|
| STATE  0x800000ac  -- the stock PERSONALIZE runtime word (getter 0x40068ce0 /
|   setter 0x40068ca0, menu index 0).  It already lives inside the stock 0x64
|   'ANDY'-restore span (0x80000070..0xd3), so it persists across a power cycle
|   with NO build change.  We only mirror what the stock setter does: write the
|   battery-SRAM shadow 0x100fff3c (= 0x100fff00 + 0xac - 0x70) and -- because
|   we bypass the PERSONALIZE dispatcher's `jmp 0x4001f23c @ 0x40069074` --
|   re-checksum the 'ANDY' block ourselves (jsr FUN_4001f23c).
|   WARNING Session 51, HW-confirmed: the checked/unchecked glyph in the
|   PERSONALIZE menu is the OPPOSITE sense from the Session 46 write-up's
|   "0 = OFF" guess -- raw 0 draws as the row's ON/checked state.  The toast
|   text below matches what the MENU shows, not the raw bit's face value.
|
| ---- the combo (RE: NOTES "Session 46") ----
| REC handler 0x40048774(keycode@4, event@8): keymap code 0x29, handles press
|   AND release.  Every press ends by setting 0x460d1726 = 1 ("REC held"); the
|   release path 0x4004883a clears it.  No other handler distinguishes it -- a
|   clean held-modifier flag.
| PLAY handler 0x40061778(keycode@4, event@8): keymap code 0x28, press only.
|   We detour its first instruction (jsr 0x4009b5c0, the "project ready?" gate)
|   so our check runs first, and resume at 0x4006177e for the stock path.
|
| ---- which presses still reach stock (Session 93: from STOCK state) ----
| REC+PLAY is stock's "start LIVE RECORDING" gesture and this mod must not eat
| it.  Stock's own test for "is this the start press" is LIVE_REC == 0:
|     0x40061798  tst.l REC_HELD    ; held?
|     0x400617a0  tst.l LIVE_REC    ; already recording?
|     0x400617a6  bne  0x400618bc   ; yes -> and 0x400618bc is a bare `rts`
| so stock does NOTHING for a REC+PLAY while live rec is already running.  We
| therefore pass the press through iff LIVE_REC == 0 and swallow it otherwise,
| which is behaviourally identical to stock while needing NO state of our own.
| Session 92 used a private press counter (G_CNT) for this; that counter lived
| beyond the boot zero-fill (below), so at power-on it held garbage and could
| swallow the first live-rec start of the session.  Gone.
| Verified by disassembly that stock's REC-held branch (0x400617a0..0x40061816)
| issues NO notification of its own, so our toast survives the pass-through.
| The one NOTIFY on that path is 0x40061782, the "no project loaded" toast when
| PROJ_GATE returns 0 -- there, stock replacing our toast is correct.
|
| ---- still open from Session 51 (not addressed here) ----
|   * An occasional small, textless box flashes where the toast was, right
|     after it closes.
|   * The PERSONALIZE menu does not live-redraw the row while you are looking
|     at it (the VALUE is correct; the on-screen widget is stale).
|
| Detours (applied by build_qlrec.py) -- TWO, both key handlers:
|   0x40061778  6 B  `jsr 0x4009b5c0`           -> jmp qlr_play
|   0x4004883a  6 B  `clr.l 0x460d1726`         -> jmp qlr_recrel

    .equ REC_HELD,     0x460d1726        | longword, 1 while [REC] is physically held
    .equ LIVE_REC,     0x460d172a        | longword, 1 while LIVE RECORDING is running
    .equ QLR,          0x800000ac        | PERSONALIZE: QUANTIZE LIVE REC (bool)
    .equ QLR_SH,       0x100fff3c        | its 'ANDY' battery-SRAM shadow
    .equ CKSUM,        0x4001f23c        | FUN_4001f23c -- recompute+store 'ANDY' checksum
    .equ NOTIFY,       0x4005a2b8        | FUN_4005a2b8(text, dur); dur>0 ONLY -- dur<=0
                                          |   tail-jumps into the modal overlay stack
                                          |   (FUN_40031494) and HUNG a real MKI, Session 50.
    .equ NOTIFY_CLOSE, 0x40056bec        | tears down the toast; no-op if none open.
                                          |   WARNING: reaches the kernel post FUN_40000c3c --
                                          |   only ever call it from a key-handler context.
    .equ NOTIF_H,      0x460d1e70        | the toast's window handle; 0 == none on screen
    .equ NOTIF_T,      0x460d1e6c        | its remaining duration; 0 == expired
    .equ PROJ_GATE,    0x4009b5c0        | displaced from 0x40061778
    .equ PLAY_RESUME,  0x4006177e        | 0x40061778 + 6  (tst.l %d0 ; bne.s ...)

    | The toast's life == the window in which a press flips, because they are
    | the same thing: the OS's own countdown.  At the 59.999 Hz UI tick derived
    | in the header, one unit is 1/60 s:
    |     0x30 = 48 = 0.800 s     0x3c = 60 = 1.000 s     0x44 = 68 = 1.133 s
    | Session 96, user's call after living with it: 0x30 -> 0x3c, "1s feels a
    | little better".  Overridable: `python3 tools/build_qlrec.py 140C_KYOTI 0xNN`.
    |
    | Side note worth keeping: 0x30 landing as a usable-but-slightly-short toast
    | on hardware is independent corroboration of the f_bus = CPU/2 step.  Had
    | f_bus been 264 MHz the tick would be 120 Hz and 0x30 a 0.4 s flash, which
    | is not what it looked like on the unit.
    | MUST be > 0.  dur <= 0 is the Session 50 hang.
    .ifndef LIVE_DUR
    .equ LIVE_DUR,       0x3c
    .endif

|   NO SCRATCH RAM.  Session 95 removed the last private word (G_OWN,
|   0x80006a60) after hardware proved it does not survive between key presses.
|   0x80006a5c..0x80006a73 is released; nothing in this patch reads or writes
|   0x8000xxxx except the stock PERSONALIZE word QLR itself (0x800000ac), which
|   is inside the boot re-image span and is stock's own storage.

    .text

| ================= [PLAY] press -- detour @ 0x40061778 =================
| Entry stack (exactly what stock 0x40061778 sees): 0(sp)=ret, 4(sp)=keycode,
| 8(sp)=event (always 1 here).  Only d0/a0 touched.
    .global qlr_play
qlr_play:
    tst.l   REC_HELD
    beq     qp_stock                    | REC not held -> stock PLAY

|   --- is a toast on screen right now? ---
|   Session 95: THIS PATCH NOW KEEPS NO STATE OF ITS OWN.
|   The Session 93/94 gate also required a private magic word G_OWN (0x80006a60)
|   to prove the toast was ours.  Flashed 2026-09-25 with a diagnostic build:
|   every press reported "QLR DIAG: OWN", i.e. G_OWN was NOT the magic even on
|   the press immediately after we wrote it.  **The scratch word does not
|   survive between key presses on hardware** -- while it persists perfectly in
|   the emulator, which does not run the DSP/audio path for real.  0x80006a60 is
|   inside the DSP shared-RAM window; something in the live audio path writes it.
|   See NOTES "Session 95" -- this also puts DIRECT JUMP (0x80006a40-4a) and
|   RELOAD3 (0x80006a50-55) under suspicion.
|
|   So the gate is now the OS's notification handle ALONE:
|       NOTIF_H != 0  ==  a toast is on screen  ==  a press flips
|   which is also the user's spec verbatim ("it being displayed is what should
|   allow for a setting switch to occur"), needs no RAM of ours, and cannot be
|   corrupted by anything we do not control.
|
|   Trade-off, accepted and bounded: if a STOCK toast happens to be on screen
|   while [REC] is held, the first [PLAY] press flips instead of only showing.
|   Rare (stock issues no notification on the live-rec path -- checked), and the
|   toast then displays the new value, so it is visible rather than silent.
|   qlr_recrel closing the toast on [REC] release is what stops a leftover toast
|   from arming an instant flip at the start of the NEXT gesture.
    tst.l   NOTIF_H
    beq     qp_no_handle                | nothing on screen -> just show the setting

    bra.b   qp_flip

|   Gate shut.  The plain build just re-shows the current setting; the
|   diagnostic build (--defsym QLR_DIAG=1, tools/build_qlrec_diag.py) says so on
|   screen, which is how the Session 93/94 G_OWN failure was found at all.
qp_no_handle:
    .ifdef QLR_DIAG
    lea     qlr_d_noh,%a0
    bra     qp_diag
    .else
    bra     qp_open
    .endif

    .ifdef QLR_DIAG
qp_diag:
    pea     LIVE_DUR
    move.l  %a0,-(%sp)
    jsr     NOTIFY
    addq.l  #8,%sp
    tst.l   LIVE_REC
    beq     qp_stock
    rts
    .endif

|   --- a toast IS up: invert QUANTIZE LIVE REC ---
qp_flip:
    move.l  QLR,%d0
    eori.l  #1,%d0
    andi.l  #1,%d0
    move.l  %d0,QLR
    move.l  %d0,QLR_SH                   | battery-SRAM shadow
    jsr     CKSUM                        | re-checksum the 'ANDY' block
|   fall through: show the setting we just wrote

|   --- (re)open the toast on the CURRENT setting, and restart its 0.8 s ---
qp_open:
    | Session 51: HW-confirmed the menu's checked/unchecked glyph is the
    | OPPOSITE of the raw bit's face value -- raw 0 draws as checked/ON in
    | PERSONALIZE.  Show the string that matches the MENU, not the bit.
    move.l  QLR,%d0
    lea     qlr_msg_on,%a0
    tst.l   %d0
    beq.b   qp_show
    lea     qlr_msg_off,%a0
qp_show:
    pea     LIVE_DUR                     | dur>0 -- self-timing, non-modal (Session 50)
    move.l  %a0,-(%sp)
    jsr     NOTIFY                       | FUN_4005a2b8(text, LIVE_DUR)
    addq.l  #8,%sp

|   --- stock's own rule: the press starts LIVE REC iff none is running ---
|   (0x400618bc, stock's "already recording" arm, is a bare `rts`, so swallowing
|   that case is exactly what stock does.)
    tst.l   LIVE_REC
    beq.b   qp_stock
    rts                                 | swallow

qp_stock:
    jsr     PROJ_GATE                    | displaced: jsr 0x4009b5c0
    jmp     PLAY_RESUME                  | -> 0x4006177e

| ================= [REC] release -- detour @ 0x4004883a =================
| Reached only for event 0 (release) of keycode 0x29 -- a key-handler context,
| which is where NOTIFY_CLOSE's kernel post is safe (HW-confirmed, Session 51
| item 4: "closes the instant [REC] is released").
    .global qlr_recrel
qlr_recrel:
    clr.l   REC_HELD                     | displaced: clr.l 0x460d1726
    tst.l   NOTIF_H
    beq.b   qr_done                      | nothing on screen -> nothing to close
    jsr     NOTIFY_CLOSE                 | close instantly (Session 51 item 4), and so
                                          |   leave no toast behind that would arm an
                                          |   instant flip on the next gesture
qr_done:
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

    .ifdef QLR_DIAG
|   Diagnostic strings -- which gate condition shut the flip out.
qlr_d_noh:
    .asciz "QLR DIAG: NO TOAST"
    .align 2
    .endif
