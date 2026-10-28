| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| CLYPS (reference/handoffs/CLYPS_SCOPE.md): Clyps mode, the Clyps view (2 x 8 table of the active
| track's sequence in each pattern of a bank) and the Clyps grid (trig LEDs), with the held /
| latched states of scope §1.1. A load copies the source track record into the playing pattern:
| at once when stopped, cued while running (§1.5a). Saved sequences ([FUNC]+[YES] / [FUNC]+[NO],
| §1.6). Originals (§1.5, redefined by the user 2026-10-26): a track's original is what it held when
| its bank was last loaded (power-on, LOAD PROJECT, a reload); Clyps snapshots every bank as it is
| loaded, and the ORIG entry / [PAGE] / [FUNC]+[PAGE] put a track back from that snapshot.
|
| Calling conventions (stock, C): args on the stack, caller pops; d0-d1/a0-a1 scratch,
| d2-d7/a2-a6 preserved. Key handlers are called as handler(code@4, event@8):
| event 1 = press, 2 = hold/repeat, 0 = release.
|
| State lives in this blob (it runs from RAM), never in 0x80006a40+ (CLAUDE.md).

| ---------------------------------------------------------------- stock addresses (scope §3)
    .equ PLAY_BANK,   0x800065bd        | the PLAYED bank (pair with ACT_PAT, RELOAD S92)
    .equ ACT_PAT,     0x800065be
    .equ UI_BANK,     0x80000002        | the bank the SRAM mirror holds
    .equ CUR_TRACK,   0x80000000        | active track 0..7
    .equ MIDI_MODE,   0x80000012        | LONG, != 0 -> MIDI tracks (stock: tst.l / clr.l / move.l;
                                        | a byte read sees its high byte, always 0 -- the CLYP6 bug)
    .equ BLOB,        0x400e21e0
    .equ BANKSTRIDE,  0x9b340
    .equ PATSTRIDE,   0x8ed8
    .equ TRAC_A,      0x91a
    .equ MIDI_BASE,   0x48d0
    .equ TRAC_M,      0x8b0
    .equ SRAM_PAT,    0x1001614e        | SRAM mirror of the UI bank's 16 slabs
    .equ TRAILER,     0x8e50            | slab + 0x8e50: the pattern trailer (beyond d16 range,
    .equ T_MLEN,      0                 | so it is addressed through a register)
    .equ T_MSCALE,    2                 | u16 master length at +0 (-1 = INF)
    .equ T_LEN,       3
    .equ T_SCALE,     4
    .equ T_SMODE,     5                 | 0 = NORMAL
    .equ HELD_BASE,   0x46c7d8ee        | is_key_held(code) = (0x46c7d8ee + code*24) != 0
    .equ FUNC_HELD,   0x46c7dd26        | code 0x2d
    .equ PTN_HELD,    0x46c7dd3e        | code 0x2e
    .equ BANK_HELD,   0x46c7dd56        | code 0x2f
    .equ PTN_CONSUMED,0x460d173e        | !=0 on [PTN] release -> teardown only, no window
    .equ BANK_SEL,    0x460e73c6        | 2 -> [BANK] release takes the (no-op) dismiss
    .equ WIN_SLOT,    0x460d1e5c        | SHOW_WIN popup handle (SELECT BANK lives here)
    .equ WIN_ONCLOSE, 0x460d1e60
    .equ BANK_TEARDOWN,0x4007b408       | SELECT BANK's onClose: pops its layers
    .equ DISMISS,     0x40056a70        | dismiss the SHOW_WIN popup (runs its onClose)
    .equ ARR_ACT,     0x460d1aec        | arranger running
    .equ POPUP,       0x460e5cd0        | a blocking MLNOTIFY dialog is up
    .equ LAYER_PUSH,  0x40031494
    .equ LAYER_POP,   0x4003146c
    .equ LED_PUSH,    0x4007e760
    .equ LED_POP,     0x4007e81c
    .equ LED_PAINT,   0x4007e998        | (slot) repaint + flush
    .equ LED_TBL,     0x400a74ce        | trig n red die id (long); green = +1
    .equ LED_BRI,     0x400135b0        | (id, 0..15)
    .equ LED_ON,      0x400131a0        | (id)
    .equ LED_OFF,     0x400131c8        | (id)
    .equ WIN_NEW,     0x4005829c        | (w, h, dx, dy, prio, close_cb) -> win or 0
    .equ WIN_DEL,     0x40055db4        | (&handle): destroy, RDRAW, handle = 0
    .equ RECT,        0x40012254        | (surf, x0, y0, x1, y1, mode) 0 clear, -1 xor
    .equ TEXT,        0x40012bd8        | (font, surf, x, y, mode, str)
    .equ FONT,        0x400ba876
    .equ SPRINTF,     0x40013a08
    .equ RDRAW,       0x46c7c72c
    .equ MEMCPY,      0x40020898        | (dst, src, n)
    .equ SEQ_DIRTY,   0x40029b9c        | (t 0..7): dirty flags + refresh, as stock's undo-restore
    .ifndef TRK_BASE
    .equ TRK_BASE,    0x40040250        | stock base TRACK handler (press, release, hold). In an image
    .endif                              | with RELOAD_FROM_PROJECT's detour there, point it at a stub
    .equ FUNC_PRESS,  0x4004e954        | stock [FUNC] press (sets 0x46c7c730)
    .equ FUNC_REL,    0x400568e4        | stock [FUNC] release
    .equ PTN_RESUME,  0x4005a04a        | after `move.l 8(sp),d0 ; moveq #1,d1`
    .equ BANKP_RESUME,0x4007af86        | after `tst.l 0x460e73bc`
    .equ BANKR_RESUME,0x4007b3e8        | after `moveq #2,d0 ; cmp.l 0x460e73c6,d0`
    .equ RUNNING,     0x800065b8        | long: 1 while the transport runs
    .equ PEND_BANK,   0x800065bf
    .equ PEND_PAT,    0x800065c0
    .equ MASTER_STEP, 0x800065b2        | u16: the master step, ++ at each master tick 0
    .equ TICK_CTR,    0x800065b6        | byte: master ticks within the step
    .equ SCALE_IX,    0x8000663d        | byte: the live master scale index
    .equ LEN_TBL,     0x400aba50        | long[scale]: ticks per step (2 = 1x = 6)
    .equ QUANT_TBL,   0x400d80dc        | long[17]: CHAIN AFTER lengths in steps, [0] = -1 (off)
    .equ PROJ_QUANT,  0x8000004e        | byte: the project default CHAIN AFTER index
    .equ STEP_ARR,    0x800064d0        | byte[16]: per-track step   (audio 0..7, MIDI 8..15)
    .equ STEPM1_ARR,  0x800064e0        | byte[16]: per-track step - 1 (mod len)
    .equ TICKS_ARR,   0x800064f0        | byte[16]: per-track ticks within the step
    .equ TSCALE_ARR,  0x8000663e        | byte[16]: per-track scale cache
    .equ LAND_RESUME, 0x400a1f78        | after `move.b 0x80006687,%d0` (stock's ble.w follows)
    .equ UIT_RESUME,  0x40062d22        | after `tst.l 0x46c7c72c` (stock's beq.w follows)
    .equ WRAP_RESUME, 0x400a43a6        | after `move.l (a2),d0 ; moveq #1,d2 ; or.l d2,d0`
    .equ PRIO,        3                 | menus' rank: toasts / the name editor open over it
    .equ CL_BLINK,    15                | the cue flash period, UI ticks (stock's bank-load blink)
    .equ YES_RESUME,  0x4005e4d0        | stock [YES] after its first 8 B
    .equ NO_PRESSP,   0x4005e262        | stock [NO], its press path / release path
    .equ NO_RELP,     0x4005e276
    .equ LIVE_REC,    0x460d172a        | LIVE REC on (stock's [NO] + TRACK / knob erase live then)
    .equ TOAST,       0x4005a2b8        | (text, dur): stock's block toast (legal from a key handler)
    .equ TOAST_DUR,   0x30              | stock's standard duration
    .equ SCLK,        0x4610757c        | the audio engine's time accumulator: ~127 M units / s
                                        | (2880 per sample at 44.1 kHz, measured in the emulator)
    .equ TAP_T,       38102400          | a quick tap: under ~300 ms
    .equ TEXT_EDIT,   0x4007e664        | (maxchars, title, buf, layout, done_cb(confirmed)): stock's name
                                        | editor (RENAME PART, project naming: layout 0 = the full one);
                                        | its window is prio 5, so the Clyps view (3) stays under it.
                                        | maxchars = the characters it lets you type: the cursor stops at
                                        | maxchars - 1 (0x4007e57e), and [YES] writes maxchars + 1 bytes
                                        | back (0x4007e3a4; RENAME PART: 6 into 7-byte names)
    .equ NAME_W,      10                | a sequence name: 9 characters + NUL (9 x 4 - 1 = 35 px: the
                                        | 37 px a slot has after its number)
    .equ BANKS_RESUME,0x400905dc        | the masked bank loader 0x400905d4(ctx, mask, ...) after its
                                        | `lea -328(sp),sp ; movem.l d2-d7/a2-a6,(sp)` (8 B)
    .equ SRAM_RESTORE,0x4000fbb4        | (bank): the SRAM mirror -> RAM (power-on resume: the
                                        | current bank's unsaved edits; one caller 0x40025808)
    .equ BANK_HASDATA,0x4000fd78        | (bank) -> d0 != 0: stock's bank LEDs light it green
    .equ BANKSZ,      0x9b340           | one bank: 16 slabs + its Parts; 16 banks end at the arena
    .equ RESET_BANKS, 0x4000fd34        | (flag): every bank to defaults (bank 0 init, copied over 1..15)
    .equ CL_MAGIC,    0x434c5950        | 'CLYP': the DRAM part is loaded (cl_magic)
| sources other than a slot: the bank byte of a cue / provenance code (bank << 8 | pattern)
    .equ SRC_ORIG,    0xfd              | the track's original (the load snapshot) on the playing pattern
    .equ SRC_SAVED,   0xfe              | the track's saved sequence
    .equ NSLOT,       16                | cursor 16 = the ORIG entry (scope §1.5, option a)

| ---- the view's geometry (window-local, y = 0 is the bottom row; text occupies y..y+4). Measured
| in the emulator by rendering stock's own compositor output (tools/clyps_render.py).
    .equ WIN_W,       112               | screen columns 8..119: on stock's own border lines
    .equ WIN_H,       64                | (the main playback window's and ATTR's), the user's spec
    .equ WIN_DX,      -1                | x = (128 - 112) / 2 + 1 - 1 = 8
    .equ FONT_S,      0x400ba876        | the interface font: 3 px glyphs, 1 px apart, 5 rows
    .equ DIGIT_W,     4                 | digit advance
    .equ ROW_PITCH,   6
    .equ HDR_Y,       57                | header: lit band 55..63 (63 = the border), text 57..61:
                                        | two lit rows above and below the inverted text
    .equ BODY_TOP,    54                | the rows' field: y 1..54 (border at 0, band from 55)
    .equ ROW0_Y,      46                | row r text at 46 - 6r: the 47-row block 4..50, centred in
                                        | 1..54 (4 rows above, 3 below: the field is odd by one)
    .equ LOAD_X,      77                | "LOAD: SEQ" (32 px) right-aligned to x = 108
    .equ LOADF_X,     49                | "LOAD: SEQ+MCH/FX" (60 px), [FUNC] held
| A cell, from its column x "col" (the 2-digit number field): bar edge (col - 5), the "edited" mark
| (col - 4..-2), 1 px, the number (col..col + 6), 5 px, the label (col + 12, up to 35 px: a 9-character
| name; the source label is "A14 64TRG"), 1 px, bar edge (col + 47). Column 1: bar 2..54; column 2:
| bar 56..108, mark 57..59 -- 2 px clear of column 1's bar / box (the user, 2026-10-27), 1 px
| between the bars.
    .equ COL0_X,      7
    .equ COL1_X,      61
    .equ SUM_GAP,     4                 | the number field (2 x DIGIT_W) + 4 = the label at col + 12
    .equ HL_X0,       -5                | the bar / box: col - 5 .. col + 47
    .equ HL_X1,       47
    .equ ED_X,        -4                | the "edited" mark: a 3 x 3 "x" (the four corners + the centre)
                                        | at col - 4..-2, rows y + 1..3, left of the slot number
    .equ BOX_R,       109               | a dark header box's right column (text ends at 107)
    .equ ORIG_W,      15                | "ORIG", "SAVED": widths from the font's table 0x400c246a
    .equ SAVED_W,     19
    .equ MID_X,       47                | "SAVED" (the saved sequence plays) between the two labels

| Two sections, linked together (tools/build_clyps.py): `.text` = the ROM part in the classic cave
| (the sequencer-tick code -- phase D, the wrap body -- and the cue state it touches: ISR code
| stays out of DRAM, build_kyoti.py's policy); `.dram` = everything else (the UI task's handlers,
| the view, the grid, the keymap / LED layers), linked at the arena reserve and carried by the
| boot loader (tools/dram/). The buffers (CL_BSS_SIZE) follow `.dram`'s end, uninitialised.
| Calls between the two are absolute (jsr / lea abs.l): a pc-relative branch across them fails
| the link (R_68K_PC16 overflow), so nothing slips through.
    .global cl_ptn, cl_bankp, cl_bankr, cl_land, cl_uitail, cl_wrap, cl_projload, cl_rstall
    .global cl_yes, cl_no
    .section .dram,"ax"

| ================================================================ detours
| [PTN] key handler 0x4005a044 (press, release, hold). Replaces 6 B:
|   move.l 8(sp),%d0 ; moveq #1,%d1
| A press with [BANK] held enters Clyps; everything else is stock's (inside Clyps only the chord's
| own [PTN] reaches here: PTN_CONSUMED makes its release a teardown).
cl_ptn:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   cp_stock
    tst.l   BANK_HELD                   | [BANK] held: [PTN] completes the chord
    beq.b   cp_stock
    tst.b   cl_open
    bne.b   cp_stock
    jsr     cl_gate
    tst.l   %d0
    beq.b   cp_stock
    pea     1                           | 1 = [BANK] came first: undo its press
    jsr     cl_enter
    addq.l  #4,%sp
    rts                                 | stock's press never runs
cp_stock:
    move.l  8(%sp),%d0
    moveq   #1,%d1
    jmp     PTN_RESUME

| [BANK] press handler 0x4007af80. Replaces 6 B: tst.l 0x460e73bc
cl_bankp:
    tst.l   PTN_HELD
    beq.b   cb_stock
    tst.b   cl_open
    bne.b   cb_stock
    jsr     cl_gate
    tst.l   %d0
    beq.b   cb_stock
    clr.l   -(%sp)                      | 0 = [PTN] came first: nothing to undo
    jsr     cl_enter
    addq.l  #4,%sp
    rts                                 | no SELECT BANK, no [BANK] layers
cb_stock:
    tst.l   0x460e73bc
    jmp     BANKP_RESUME

| [BANK] release handler 0x4007b3e0. Replaces 8 B: moveq #2,d0 ; cmp.l 0x460e73c6,d0. Nothing of
| ours any more (no chord states: only [NO] closes Clyps); kept so the site stays claimed.
cl_bankr:
    moveq   #2,%d0
    cmp.l   BANK_SEL,%d0
    jmp     BANKR_RESUME

| ================================================================ entering / leaving
| d0 = 1 when Clyps may open now
cl_gate:
    moveq   #0,%d0
    tst.l   ARR_ACT
    bne.b   cg_no
    tst.l   POPUP
    bne.b   cg_no
    moveq   #1,%d0
cg_no:
    rts

| cl_enter(bankfirst). Clyps opens on the bank of the pattern you are on (its slot highlighted),
| with the select box on that slot.
cl_enter:
    tst.l   4(%sp)
    beq.b   ce_noundo
    move.l  WIN_SLOT,%d0
    beq.b   ce_tear
    move.l  WIN_ONCLOSE,%d0
    cmpi.l  #BANK_TEARDOWN,%d0
    bne.b   ce_tear
    jsr     DISMISS                     | closes SELECT BANK; its onClose pops the layers
    bra.b   ce_noundo
ce_tear:
    jsr     BANK_TEARDOWN               | no window: pop the layers it pushed directly
ce_noundo:
    moveq   #2,%d0
    move.l  %d0,BANK_SEL                | [BANK] release -> dismiss (nothing up: no-op)
    moveq   #1,%d0
    move.l  %d0,PTN_CONSUMED            | [PTN] release -> teardown only
    move.b  PLAY_BANK,%d0
    move.b  %d0,cl_bank
    move.b  %d0,cl_sbank
    move.b  ACT_PAT,%d0
    move.b  %d0,cl_cur
    pea     cl_close                    | close_cb: eviction lands in the same teardown
    pea     PRIO
    clr.l   -(%sp)                      | dy
    pea     WIN_DX
    pea     WIN_H
    pea     WIN_W
    jsr     WIN_NEW
    lea     24(%sp),%sp
    move.l  %d0,cl_win
    beq.b   ce_fail                     | all 5 window slots busy: stay out of Clyps
    moveq   #1,%d0
    move.b  %d0,cl_open
    clr.b   cl_flash
    pea     cl_layer
    jsr     LAYER_PUSH
    pea     cl_led
    jsr     LED_PUSH
    addq.l  #8,%sp
    jsr     cl_refresh
ce_fail:
    rts

| the one teardown: [NO] AND the window's close_cb (eviction). Nothing else closes Clyps (the
| user, 2026-10-27). Idempotent; stock never clears a slot's close_cb, so it may be called again.
cl_close:
    tst.b   cl_open
    beq.b   cc_out
    clr.b   cl_open
    tst.l   cl_win
    beq.b   cc_nowin
    pea     cl_win
    jsr     WIN_DEL                     | destroys, RDRAW = 1, cl_win = 0
    addq.l  #4,%sp
cc_nowin:
    pea     cl_layer
    jsr     LAYER_POP
    pea     cl_led
    jsr     LED_POP
    clr.l   (%sp)
    jsr     LED_PAINT                   | slot 0 back to whatever is underneath
    addq.l  #8,%sp
    moveq   #1,%d0
    move.l  %d0,RDRAW
cc_out:
    rts

| ================================================================ keymap handlers
| The highlight (inverted bar) = the pattern you are on, in its bank; it moves only when the pattern
| changes. The select box (1 px frame) = what a [YES] loads: (cl_sbank, cl_cur), cl_cur 16 = ORIG.
| [BANK] held: the arrows page the shown bank instead (the slot selector rests).

| bank paging: d0 = +1 / -1
cl_page:
    moveq   #0,%d1
    move.b  cl_bank,%d1
    add.l   %d0,%d1
    andi.l  #15,%d1
    move.b  %d1,cl_bank
    bra.w   cl_refresh

| UP 0x33 / DOWN 0x20: the box through 1..16 -> ORIG -> 1, wrapping, auto-repeat (hold events).
| A move made in another bank than the box's brings the box into the shown bank (same slot).
| [BANK] held: UP = previous bank, DOWN = next bank.
cl_k_ud:
    tst.l   8(%sp)
    beq.b   ku_out
    clr.b   cl_flash
    tst.l   BANK_HELD
    beq.b   ku_sel
    moveq   #1,%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x33,%d1
    bne.w   cl_page
    moveq   #-1,%d0
    bra.w   cl_page
ku_sel:
    jsr     cl_origok
    addi.l  #NSLOT,%d0
    movea.l %d0,%a1                     | a1 = entries in the cycle (16 or 17)
    moveq   #0,%d0
    move.b  cl_cur,%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x33,%d1
    bne.b   ku_down
    tst.l   %d0                         | UP = previous
    bne.b   ku_prev
    move.l  %a1,%d0
ku_prev:
    subq.l  #1,%d0
    bra.b   ku_set
ku_down:
    addq.l  #1,%d0
    cmpa.l  %d0,%a1
    bne.b   ku_set
    moveq   #0,%d0
ku_set:
    move.b  %d0,cl_cur
    move.b  cl_bank,%d0
    move.b  %d0,cl_sbank
    jsr     cl_draw
    clr.l   -(%sp)
    jsr     LED_PAINT                   | the yellow box LED follows
    addq.l  #4,%sp
ku_out:
    rts

| LEFT 0x34 / RIGHT 0x21: the box to the same row of the other column (1 <-> 9 ... 8 <-> 16);
| nothing on ORIG. [BANK] held: LEFT = previous bank, RIGHT = next bank.
cl_k_lr:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kl_out
    clr.b   cl_flash
    tst.l   BANK_HELD
    beq.b   kl_sel
    moveq   #1,%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x34,%d1
    bne.w   cl_page
    moveq   #-1,%d0
    bra.w   cl_page
kl_sel:
    moveq   #0,%d0
    move.b  cl_cur,%d0
    cmpi.l  #NSLOT,%d0
    bcc.b   kl_out
    eori.l  #8,%d0
    move.b  %d0,cl_cur
    move.b  cl_bank,%d0
    move.b  %d0,cl_sbank
    jsr     cl_draw
    clr.l   -(%sp)
    jsr     LED_PAINT
    addq.l  #4,%sp
kl_out:
    rts

| TRIG 1-16 (codes 0x00..0x0f): the box to that slot of the shown bank, and load it (cued while
| running). [BANK] held: nothing yet (stock's bank select inside Clyps is the next step).
cl_k_trig:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kt_out
    clr.b   cl_flash
    tst.l   BANK_HELD
    bne.b   kt_out
    move.l  4(%sp),%d0
    andi.l  #15,%d0
    move.b  %d0,cl_cur
    move.b  cl_bank,%d1
    move.b  %d1,cl_sbank
    move.l  %d0,-(%sp)
    jsr     cl_load
    addq.l  #4,%sp
    bra.w   cl_refresh
kt_out:
    rts

| [YES]: load the box's entry (a slot of its bank, or ORIG: restore); Clyps stays. The [PTN]+[BANK]
| chord held -> nothing: DIRECT JUMP must not toggle there (the user, 2026-10-25). [PTN]+[YES]
| ([PTN] held, [BANK] not) -> DIRECT JUMP's toggle in an image that has it (--defsym DJ_TOGGLE=
| its entry), nothing here; never a load. [FUNC]+[YES] -> save (§1.6).
cl_k_yes:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   ky_out
    tst.b   cl_fn
    bne.b   ky_out                      | [FUNC]+[YES]: nothing in Clyps (temp save lives outside)
    clr.b   cl_flash
    tst.l   PTN_HELD
    beq.b   ky_noptn
    tst.l   BANK_HELD
    bne.b   ky_out                      | the chord: nothing
.ifdef DJ_TOGGLE
    jsr     DJ_TOGGLE                   | [PTN]+[YES]: DIRECT JUMP on / off
.endif
    rts
ky_noptn:
    moveq   #0,%d0
    move.b  cl_cur,%d0
    cmpi.l  #NSLOT,%d0
    beq.b   ky_orig
    move.l  %d0,-(%sp)
    jsr     cl_load
    addq.l  #4,%sp
    bra.w   cl_refresh
ky_orig:
    jsr     cl_restore
    bra.w   cl_refresh
ky_out:
    rts

| [NO]: close Clyps (the only key that does). [FUNC]+[NO]: nothing (temp reload lives outside).
cl_k_no:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kn_out
    clr.b   cl_flash
    tst.b   cl_fn
    beq.w   cl_close
kn_out:
    rts

| [PAGE] 0x1b: this track's original back; [FUNC]+[PAGE]: every changed track of the playing
| pattern, on one landing (scope §1.5'). Nothing if already original.
cl_k_page:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kn_out
    clr.b   cl_flash
    tst.b   cl_fn
    bne.b   kp_all
    jsr     cl_restore
    bra.w   cl_refresh
kp_all:
    jsr     cl_restoreall
    bra.w   cl_refresh

| TRACK 1-8 (0x10..0x17): every event goes through stock's own base handler, as the base keymap
| does (press marks the key held in 0x460fab40 and handles double taps; the RELEASE selects the
| track and clears the held mark). After the release the view and the grid follow.
cl_k_track:
    clr.b   cl_flash
    move.l  8(%sp),-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     TRK_BASE
    addq.l  #8,%sp
    tst.l   8(%sp)
    beq.w   cl_refresh                  | release: the track has changed
    rts

| [PTN] / [BANK] pressed while Clyps is open (keys pressed AFTER our layer went up reach these
| records): swallowed for now -- [BANK] held is the paging modifier (read from its held flag);
| stock's SELECT PATTERN / SELECT BANK inside Clyps are the next step. A later release under
| stock's own record (after Clyps closes) must not open SELECT PATTERN / SELECT BANK.
cl_k_chord:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kc_out
    moveq   #1,%d1
    move.l  %d1,PTN_CONSUMED
    moveq   #2,%d1
    move.l  %d1,BANK_SEL
    tst.b   cl_fn
    beq.b   kc_out
    move.l  4(%sp),%d1
    cmpi.l  #0x2f,%d1
    beq.w   cl_rename                   | [FUNC]+[BANK] (EDIT): name the box's sequence
kc_out:
    rts

| [FUNC]+[BANK] in Clyps: stock's name editor (as project naming) on the sequence under the select
| box (nothing on ORIG). It edits a scratch copy; its [YES] stores it (cl_named), its [NO] keeps the
| old name; either way the Clyps view is under it again.
cl_rename:
    tst.b   cl_namesok
    beq.b   rn_out
    moveq   #0,%d0
    move.b  cl_cur,%d0
    cmpi.l  #NSLOT,%d0
    bcc.b   rn_out
    move.l  %d0,%d1
    moveq   #0,%d0
    move.b  cl_sbank,%d0
    jsr     cl_nidx                     | d0 = the name's index (bank, pattern, active track)
    move.l  %d0,cl_nedit
    jsr     cl_nptr                     | a0 = its name
    lea     cl_nbuf,%a1
    moveq   #NAME_W,%d0
rn_cp:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   rn_cp
    clr.b   cl_nbuf+NAME_W-1
    pea     cl_named
    clr.l   -(%sp)                      | layout 0: the full editor, as project naming
    pea     cl_nbuf
    pea     cl_s_rename
    pea     NAME_W-1                    | 9 characters: input stops there, and the copy back
    jsr     TEXT_EDIT                   | (10 bytes) fills cl_nbuf exactly
    lea     20(%sp),%sp
rn_out:
    rts

| the editor's done_cb(confirmed): [YES] stores the name; the view and grid redraw (Clyps stays)
cl_named:
    tst.l   4(%sp)
    beq.b   nd_draw
    move.l  cl_nedit,%d0
    jsr     cl_nptr
    lea     cl_nbuf,%a1
    moveq   #NAME_W,%d0
nd_cp:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d0
    bne.b   nd_cp
    clr.b   -1(%a0)
nd_draw:
    tst.b   cl_open
    beq.b   nd_out
    jsr     cl_refresh
nd_out:
    rts

| [FUNC]: redraws (the FULL label arrives with FULL loads)
cl_k_func:
    move.l  8(%sp),%d0
    beq.b   kf_rel
    cmpi.l  #1,%d0
    bne.b   kf_out                      | hold events: nothing (stock's record has no hold handler)
    move.l  %d0,-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     FUNC_PRESS                  | stock's own press (its state 0x46c7c730)
    addq.l  #8,%sp
    moveq   #1,%d0
    bra.b   kf_set
kf_rel:
    clr.l   -(%sp)
    move.l  8(%sp),-(%sp)
    jsr     FUNC_REL                    | stock's own release
    addq.l  #8,%sp
    moveq   #0,%d0
kf_set:
    move.b  %d0,cl_fn
    bra.w   cl_draw
kf_out:
    rts

| ================================================================ helpers
| d0 = active track 0..15 (MIDI tracks 8..15)
cl_trk:
    moveq   #0,%d0
    move.b  CUR_TRACK,%d0
    andi.l  #7,%d0
    tst.l   MIDI_MODE
    beq.b   ct_out
    addq.l  #8,%d0
ct_out:
    rts

    .text
| cl_slab(bank, pat) -> a0
cl_slab:
    move.l  4(%sp),%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a0
    adda.l  %d0,%a0
    move.l  8(%sp),%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    adda.l  %d0,%a0
    rts

| cl_toff(t) -> d0 = record offset in the slab, d1 = record length
cl_toff:
    move.l  4(%sp),%d0
    cmpi.l  #8,%d0
    bcc.b   to_midi
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    rts
to_midi:
    subq.l  #8,%d0
    move.l  #TRAC_M,%d1
    muls.l  %d1,%d0
    addi.l  #MIDI_BASE,%d0
    rts

    .section .dram,"ax"
| d0 = (bank << 8) | pattern of the sequence playing on the active track: its Clyps source
| while the load still belongs to the playing pattern, otherwise the playing pattern itself
cl_playing:
    jsr     cl_trk
| cl_playt (d0 = track): the same for any track
cl_playt:
    move.l  %d2,-(%sp)
    add.l   %d0,%d0
    move.l  %d0,%d1                     | d1 = 2 * track
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0                 | d0 = the playing pattern
    lea     cl_home,%a0
    moveq   #0,%d2
    move.b  (%a0,%d1.l),%d2
    lsl.l   #8,%d2
    move.b  1(%a0,%d1.l),%d2
    cmp.l   %d0,%d2
    bne.b   cy_out
    lea     cl_src,%a0
    moveq   #0,%d0
    move.b  (%a0,%d1.l),%d0
    lsl.l   #8,%d0
    move.b  1(%a0,%d1.l),%d0
cy_out:
    move.l  (%sp)+,%d2
    rts

| cl_classify(rec, midi) -> d0 = 0 empty, 1 half (data, no sample/note trigs), 2 full
cl_classify:
    movea.l 4(%sp),%a0
    move.l  (%a0),%d0                   | +0x00 note / sample trigs
    or.l    4(%a0),%d0
    bne.b   cf_full
    tst.l   8(%sp)
    bne.b   cf_midi
    lea     8(%a0),%a1                  | audio: +0x08..+0x37 trigless layers + recorder trigs
    moveq   #12,%d1
cf_lay:
    tst.l   (%a1)+
    bne.b   cf_half
    subq.l  #1,%d1
    bne.b   cf_lay
    lea     0x59(%a0),%a1               | locks: 64 x 32 B, 0xff = none (byte-aligned)
    bra.b   cf_locks
cf_midi:
    move.l  8(%a0),%d0                  | MIDI: +0x08 trigless layer
    or.l    12(%a0),%d0
    bne.b   cf_half
    lea     0x30(%a0),%a1
cf_locks:
    move.l  #0x800,%d1
cf_lk:
    moveq   #0,%d0
    move.b  (%a1)+,%d0
    cmpi.l  #0xff,%d0
    bne.b   cf_half
    subq.l  #1,%d1
    bne.b   cf_lk
    moveq   #0,%d0
    rts
cf_half:
    moveq   #1,%d0
    rts
cf_full:
    moveq   #2,%d0
    rts

| rebuild the 16 classes for (cl_bank, active track), then redraw the view and the grid
cl_refresh:
    lea     -16(%sp),%sp
    movem.l %d2-%d4/%a2,(%sp)
    moveq   #0,%d0                      | the one cursor choke point: ORIG only while it exists
    move.b  cl_cur,%d0
    cmpi.l  #NSLOT,%d0
    bcs.b   crf_cur
    jsr     cl_origok
    tst.l   %d0
    bne.b   crf_cur
    clr.b   cl_cur
crf_cur:
    jsr     cl_trk
    move.l  %d0,%d3                     | d3 = track
    move.l  %d3,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d4                     | d4 = record offset
    moveq   #0,%d2                      | d2 = pattern
crf_lp:
    move.l  %d2,-(%sp)
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d4,%a0
    moveq   #0,%d0
    cmpi.l  #8,%d3
    scc     %d0                         | MIDI flag
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    jsr     cl_classify
    addq.l  #8,%sp
    lea     cl_cls,%a0
    move.b  %d0,(%a0,%d2.l)
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   crf_lp
    movem.l (%sp),%d2-%d4/%a2
    lea     16(%sp),%sp
    jsr     cl_draw
    clr.l   -(%sp)
    jsr     LED_PAINT
    addq.l  #4,%sp
    rts

| ================================================================ loads
| cl_load(n): the box bank's pattern n onto the active track of the playing pattern
cl_load:
    jsr     cl_trk
    moveq   #0,%d1
    move.b  cl_sbank,%d1
    lsl.l   #8,%d1
    or.l    4(%sp),%d1                  | bank<<8 | pattern
    clr.l   -(%sp)                      | cued
    move.l  %d1,-(%sp)
    move.l  %d0,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
    rts

| cl_cueload(t, code, now): source `code` (bank<<8 | pattern, SRC_SAVED<<8, SRC_ORIG<<8) onto track
| t of the playing pattern. Stopped: at once. Running: cued (scope §1.5a), the sequencer tick lands
| it (cl_land / cl_wrap); now != 0 arms it at once: it lands at the track's next window start,
| phase-continuous ([FUNC]+[NO], O3).
cl_cueload:
    lea     -16(%sp),%sp
    movem.l %d2-%d4/%a2,(%sp)
    move.l  20(%sp),%d3                 | d3 = track
    move.l  24(%sp),%d2                 | d2 = code
    move.l  28(%sp),%d4                 | d4 = now
    tst.l   RUNNING
    bne.b   lo_cue
    move.l  %d2,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)
    move.l  %d2,%d0
    lsr.l   #8,%d0
    move.l  %d0,-(%sp)
    move.l  %d3,-(%sp)
    jsr     cl_apply                    | at once
    lea     12(%sp),%sp
    move.l  %d3,-(%sp)
    jsr     cl_post_ui
    addq.l  #4,%sp
    bra.b   lo_out
lo_cue:
    lea     cl_cue,%a2
|   re-picking the slot that already plays (its source, or the pattern's own slot) cancels the cue
    move.l  %d3,%d0
    jsr     cl_playt                    | d0 = playing
    cmp.l   %d2,%d0
    beq.b   lo_cancel
    move.l  %d3,%d1
    add.l   %d1,%d1
    move.w  %d2,(%a2,%d1.l)             | cue[t] = code
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0
    lea     cl_cueh,%a0
    move.w  %d0,(%a0,%d1.l)             | the pattern it is aimed at
    lea     cl_arm,%a0
    move.b  %d4,(%a0,%d3.l)             | 0 = wait for the gate; 1 = armed already
    jsr     cl_count
    bra.b   lo_out
lo_cancel:
    move.l  %d3,%d1
    add.l   %d1,%d1
    moveq   #-1,%d0
    move.w  %d0,(%a2,%d1.l)
    lea     cl_arm,%a0
    clr.b   (%a0,%d3.l)
    jsr     cl_count
lo_out:
    movem.l (%sp),%d2-%d4/%a2
    lea     16(%sp),%sp
    rts

| cl_diff (d0 = track) -> d0 = 1 when the playing pattern's record of the track differs from its
| original (the load snapshot); 0 when equal or when there is no snapshot. Keeps d2-d7/a2-a6.
cl_diff:
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    move.l  %d0,%d2
    jsr     cl_origok
    tst.l   %d0
    beq.b   df_out
    move.l  %d2,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d3                     | d3 = record offset
    move.l  %d1,-(%sp)                  | its length
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    jsr     cl_snapslab
    adda.l  %d3,%a0
    move.l  %a0,-(%sp)                  | the original record
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d3,%a0                     | a0 = the playing record
    movea.l (%sp)+,%a1
    move.l  (%sp)+,%d0
    jsr     cl_cmpw
df_out:
    movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
    rts

| cl_restore: the active track's original back (cued like any load). d0 = 1 if it differed.
cl_restore:
    jsr     cl_trk
    move.l  %d0,-(%sp)
    jsr     cl_diff
    move.l  (%sp)+,%d1
    tst.l   %d0
    beq.b   rs_out
    clr.l   -(%sp)
    pea     SRC_ORIG<<8
    move.l  %d1,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
    moveq   #1,%d0
rs_out:
    rts

| cl_restoreall: every track of the playing pattern that differs from its original, on one
| landing. d0 = 1 if any did.
cl_restoreall:
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    moveq   #0,%d2                      | d2 = track
    moveq   #0,%d3                      | d3 = any
ra_l:
    move.l  %d2,%d0
    jsr     cl_diff
    tst.l   %d0
    beq.b   ra_n
    moveq   #1,%d3
    clr.l   -(%sp)
    pea     SRC_ORIG<<8
    move.l  %d2,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
ra_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   ra_l
    move.l  %d3,%d0
    movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
    rts

| cl_savet(t): what track t plays now -> its saved sequence (the temp save), with its resolved length
| / scale written into the copy's own bytes (a NORMAL pattern's are the pattern's)
cl_savet:
    lea     -12(%sp),%sp
    movem.l %d2-%d3/%a2,(%sp)
    move.l  16(%sp),%d2                 | d2 = track
    move.l  %d2,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d3                     | d3 = record offset (d1 = length)
    move.l  %d1,-(%sp)
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a2                     | a2 = the playing slab
    move.l  %a2,%d0
    add.l   %d3,%d0
    move.l  %d0,-(%sp)                  | src
    move.l  %d2,%d0
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    addi.l  #SAVED_BASE,%d0
    move.l  %d0,-(%sp)                  | dst = saved[t]
    jsr     MEMCPY
    move.l  (%sp),%a1                   | a1 = saved[t]
    lea     12(%sp),%sp
    movea.l %a2,%a0
    adda.l  #TRAILER,%a0
    tst.b   T_SMODE(%a0)
    bne.b   sv_valid                    | PER TRACK: the record's own bytes are its length / scale
    moveq   #0x50,%d0
    cmpi.l  #8,%d2
    bcs.b   sv_off
    moveq   #0x28,%d0
sv_off:
    adda.l  %d0,%a1
    move.b  T_LEN(%a0),%d0
    move.b  %d0,(%a1)
    move.b  T_SCALE(%a0),%d0
    move.b  %d0,1(%a1)
sv_valid:
    lea     cl_svalid,%a0
    moveq   #1,%d0
    move.b  %d0,(%a0,%d2.l)
    tst.b   cl_namesok                  | and its name
    beq.b   sv_out
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    lsl.l   #4,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    add.l   %d1,%d0
    lsl.l   #4,%d0
    add.l   %d2,%d0
    jsr     cl_nptr
    move.l  %d2,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #SNAMES,%a1
    adda.l  %d0,%a1
    moveq   #NAME_W,%d0
sv_nl:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   sv_nl
sv_out:
    movem.l (%sp),%d2-%d3/%a2
    lea     12(%sp),%sp
    rts

| ================================================================ temp save / reload (outside Clyps)
| The user, 2026-10-27, as on other Elektrons: hold [YES] + TRACK = temp save that track; hold [NO] +
| TRACK = reload it (at its next step, in step: the cue path, armed at once). Stock's ARM / DISARM
| (a plain [YES] / [NO]) moves to a QUICK TAP: it runs (stock's press, then its release) when the
| key is released within TAP_T and no TRACK key was pressed meanwhile; a longer hold without a
| TRACK key does nothing. Stock untouched: with the arranger running, and in LIVE REC (where stock's
| [NO] + TRACK / knob erase live -- its NO sub-map 0x400bfbfc). Inside Clyps our layer owns
| [YES] / [NO], so none of this is reachable there (the user: not a Clyps gesture).

| 0x4005e4c8 stock [YES] (replaces `move.l 4(sp),d1 ; move.l 8(sp),d0`, 8 B)
cl_yes:
    moveq   #0,%d1                      | key 0 = [YES]
    bra.b   cl_yn
| 0x4005e25c stock [NO] (replaces `move.l 8(sp),d0 ; beq.s 0x4005e276`, 6 B)
cl_no:
    moveq   #1,%d1                      | key 1 = [NO]
cl_yn:
    tst.l   ARR_ACT
    bne.w   yn_stock
    tst.l   LIVE_REC
    bne.w   yn_stock
    move.l  %d2,-(%sp)                  | 0 d2, 4 ret, 8 code, 12 event
    move.l  %d1,%d2                     | d2 = which key
    move.l  12(%sp),%d0
    cmpi.l  #1,%d0
    beq.b   yn_press
    tst.l   %d0
    bne.b   yn_done                     | hold events: none (delay 0)
    lea     cl_ynact,%a0                | release
    tst.b   (%a0,%d2.l)
    beq.b   yn_stock2                   | its press was not ours: stock's release
    clr.b   (%a0,%d2.l)
    jsr     cl_ynpop
    lea     cl_ynused,%a0
    tst.b   (%a0,%d2.l)
    bne.b   yn_done                     | a chord was made: nothing else
    move.l  SCLK,%d0
    lea     cl_ynt0,%a0
    sub.l   (%a0,%d2.l*4),%d0
    cmpi.l  #TAP_T,%d0
    bcc.b   yn_done                     | held too long: nothing
    pea     1                           | a quick tap: stock's press ...
    move.l  12(%sp),-(%sp)
    jsr     cl_ynstock
    addq.l  #8,%sp
    clr.l   -(%sp)                      | ... then its release
    move.l  12(%sp),-(%sp)
    jsr     cl_ynstock
    addq.l  #8,%sp
yn_done:
    move.l  (%sp)+,%d2
    rts
yn_press:
    lea     cl_ynact,%a0
    moveq   #1,%d0
    move.b  %d0,(%a0,%d2.l)
    lea     cl_ynused,%a0
    clr.b   (%a0,%d2.l)
    lea     cl_ynt0,%a0
    move.l  SCLK,%d0
    move.l  %d0,(%a0,%d2.l*4)
    pea     cl_tlayer                   | the TRACK keys: save / reload while it is held
    jsr     LAYER_PUSH
    addq.l  #4,%sp
    bra.b   yn_done                     | stock's press waits for the release
yn_stock2:
    move.l  %d2,%d1
    move.l  (%sp)+,%d2
yn_stock:                               | d1 = which key; the stack as at the handler's entry
    tst.l   %d1
    bne.b   yn_nostock
    move.l  4(%sp),%d1                  | [YES]: the displaced instructions, then stock
    move.l  8(%sp),%d0
    jmp     YES_RESUME
yn_nostock:
    move.l  8(%sp),%d0                  | [NO]: the displaced test, then stock's own branch
    beq.b   yn_norel
    jmp     NO_PRESSP
yn_norel:
    jmp     NO_RELP

| cl_ynstock(code, event), d2 = which key: stock's [YES] / [NO] as if unpatched
cl_ynstock:
    move.l  %d2,%d1
    bra.b   yn_stock

| pop the TRACK layer once neither [YES] nor [NO] is held
cl_ynpop:
    tst.b   cl_ynact
    bne.b   yp_out
    tst.b   cl_ynact+1
    bne.b   yp_out
    pea     cl_tlayer
    jsr     LAYER_POP
    addq.l  #4,%sp
yp_out:
    rts

| TRACK 1-8 while [YES] / [NO] is held (cl_tlayer): save / reload that track (the MIDI track when
| the MIDI tracks are showing). The track is not selected; the release and holds are swallowed.
cl_k_tsave:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.w   ts_out
    move.l  %d2,-(%sp)
    move.l  8(%sp),%d2
    subi.l  #0x10,%d2
    andi.l  #7,%d2
    tst.l   MIDI_MODE
    beq.b   ts_a
    addq.l  #8,%d2                      | d2 = track 0..15
ts_a:
    tst.b   cl_ynact
    beq.b   ts_no
    moveq   #1,%d0                      | [YES] held: save
    move.b  %d0,cl_ynused
    move.l  %d2,-(%sp)
    jsr     cl_savet
    addq.l  #4,%sp
    lea     cl_fmt_tsv,%a0
    bra.b   ts_toast
ts_no:
    tst.b   cl_ynact+1
    beq.b   ts_done
    moveq   #1,%d0                      | [NO] held: reload
    move.b  %d0,cl_ynused+1
    lea     cl_svalid,%a0
    lea     cl_fmt_tno,%a1
    tst.b   (%a0,%d2.l)
    beq.b   ts_toast1
    pea     1                           | armed at once: its next step, in step
    pea     SRC_SAVED<<8
    move.l  %d2,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
    lea     cl_fmt_trl,%a0
    bra.b   ts_toast
ts_toast1:
    movea.l %a1,%a0
ts_toast:
    move.l  %d2,%d0                     | "TRK 3 SAVED" / "MIDI TRK 3 RELOADED" / "TRK 3: SAVE FIRST" (the user)
    lea     cl_s_none,%a1
    cmpi.l  #8,%d0
    bcs.b   ts_l
    lea     cl_s_midi,%a1
    subq.l  #8,%d0
ts_l:
    move.l  %a1,%d1
    addq.l  #1,%d0
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    pea     cl_buf
    jsr     SPRINTF
    lea     16(%sp),%sp
    pea     TOAST_DUR
    pea     cl_buf
    jsr     TOAST
    addq.l  #8,%sp
ts_done:
    move.l  (%sp)+,%d2
ts_out:
    rts

| The masked bank loader 0x400905d4(ctx, mask, ...) (storage task): bit n of mask = bank n is read
| from the card. Every LOAD PROJECT goes through it (measured, emulator: mask 0xffff on a first
| load from 0x400853d8, 0xfffe on the power-on / reload resume from 0x40084d60, whose current bank
| comes back from the SRAM mirror instead: cl_sramrest). Entry: the banks being read lose their
| snapshot, and eight banks or more = a project load: the saved sequences, the provenance and every
| cue go (scope §1.6). The return goes through cl_ldexit, which snapshots every bank just read: the
| new originals. Then the loader's first two instructions, replayed.
cl_projload:
    move.l  8(%sp),%d0
    andi.l  #0xffff,%d0                 | d0 = the bank mask
    move.w  %d0,cl_ldmask
    moveq   #0,%d1
    move.w  cl_snapok,%d1
    not.l   %d0
    and.l   %d0,%d1
    move.w  %d1,cl_snapok               | no originals for these banks until the load is done
    moveq   #0,%d0
    move.w  cl_ldmask,%d0
    moveq   #0,%d1                      | d1 = banks in it
pl_cnt:
    tst.l   %d0
    beq.b   pl_counted
    move.l  %d0,%a0
    subq.l  #1,%d0
    move.l  %a0,-(%sp)
    and.l   (%sp)+,%d0                  | clear the lowest set bit
    addq.l  #1,%d1
    bra.b   pl_cnt
pl_counted:
    cmpi.l  #8,%d1
    bcs.w   pl_go
    movea.l #NAMES,%a0                  | a project load: the names go (they live in memory only, for
    move.l  #(4096*NAME_W+16*NAME_W)/4,%d0 | now) -- every sequence's and every saved one's
pl_n:
    clr.l   (%a0)+
    subq.l  #1,%d0
    bne.b   pl_n
    moveq   #1,%d0
    move.b  %d0,cl_namesok
    lea     cl_svalid,%a0               | ... and no saved sequence survives
    clr.l   (%a0)+
    clr.l   (%a0)+
    clr.l   (%a0)+
    clr.l   (%a0)+
    lea     cl_home,%a0
    moveq   #-1,%d1
    moveq   #8,%d0
pl_h:
    move.l  %d1,(%a0)+
    subq.l  #1,%d0
    bne.b   pl_h
    clr.b   cl_flash
    moveq   #0,%d0
    move.b  cl_nproj,%d0
    addq.l  #1,%d0
    move.b  %d0,cl_nproj
    jsr     cl_dropall
pl_go:
    move.l  (%sp),cl_ldret              | the loader returns through cl_ldexit
    move.l  #cl_ldexit,(%sp)
    lea     -328(%sp),%sp               | displaced
    movem.l %d2-%d7/%a2-%a6,(%sp)
    jmp     BANKS_RESUME

| the masked loader's return: snapshot every bank it read, then back to its caller (d0 kept)
cl_ldexit:
    lea     -12(%sp),%sp
    movem.l %d0/%d2-%d3,(%sp)
    moveq   #0,%d2                      | d2 = bank
    moveq   #0,%d3
    move.w  cl_ldmask,%d3
le_l:
    btst    %d2,%d3
    beq.b   le_n
    move.l  %d2,-(%sp)
    jsr     cl_snapbank
    addq.l  #4,%sp
le_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   le_l
    movem.l (%sp),%d0/%d2-%d3
    lea     12(%sp),%sp
    move.l  cl_ldret,-(%sp)
    rts

| 0x40025808 `jsr 0x4000fbb4` (the power-on resume: the current bank's unsaved edits, SRAM -> RAM)
| -> here: the same call, then that bank's snapshot (whatever wrote the bank last, its snapshot is
| taken last)
cl_sramrest:
    move.l  4(%sp),-(%sp)
    jsr     SRAM_RESTORE
    addq.l  #4,%sp
    move.l  4(%sp),-(%sp)
    jsr     cl_snapbank
    addq.l  #4,%sp
    rts

| cl_snapall: every bank -> its snapshot
cl_snapall:
    move.l  %d2,-(%sp)
    moveq   #0,%d2
sa_l:
    move.l  %d2,-(%sp)
    jsr     cl_snapbank
    addq.l  #4,%sp
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   sa_l
    move.l  (%sp)+,%d2
    rts

| cl_snapbank(bank): the bank as it is now -> its snapshot (the originals); mark it valid
cl_snapbank:
    move.l  4(%sp),%d0
    move.l  #BANKSZ,%d1
    muls.l  %d1,%d0
    pea     BANKSZ
    movea.l #BLOB,%a0
    pea     (%a0,%d0.l)
    movea.l #SNAPB,%a0
    pea     (%a0,%d0.l)
    jsr     MEMCPY
    lea     12(%sp),%sp
    tst.b   cl_namesok                  | the bank's names as loaded, too (ORIG restores them)
    beq.b   sb_ok
    move.l  4(%sp),%d0
    move.l  #256*NAME_W,%d1
    muls.l  %d1,%d0
    pea     256*NAME_W
    movea.l #NAMES,%a0
    pea     (%a0,%d0.l)
    movea.l #NAMESNAP,%a0
    pea     (%a0,%d0.l)
    jsr     MEMCPY
    lea     12(%sp),%sp
sb_ok:
    move.l  4(%sp),%d1
    moveq   #0,%d0
    move.w  cl_snapok,%d0
    bset    %d1,%d0
    move.w  %d0,cl_snapok
    rts

    .text
| cl_apply(t, sbank, spat) -> d0 = 1 copied, 0 not (the playing pattern's own slot, or no saved
| sequence / original to put back). The record, its length/scale (scope §4.6) and the provenance. Writes RAM only (slab + our state): safe in
| the sequencer tick. sbank = SRC_SAVED / SRC_ORIG: the saved sequence / the original of t.
cl_apply:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)
    move.l  44(%sp),%d6                 | d6 = track 0..15
    move.l  48(%sp),%d2                 | d2 = source bank (or SRC_*)
    move.l  52(%sp),%d7                 | d7 = source pattern
    move.l  %d6,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d4                     | d4 = record offset
    move.l  %d1,%d5                     | d5 = record length
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a2                     | a2 = destination slab
    cmpi.l  #16,%d2
    bcc.b   ap_src                      | a saved sequence / an original: never the own slot
    move.l  %d7,-(%sp)
    move.l  %d2,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    cmpa.l  %a2,%a0
    beq.w   ap_own                      | the playing pattern's own slot: nothing to copy
ap_src:
    move.l  %d7,-(%sp)
    move.l  %d2,-(%sp)
    move.l  %d6,-(%sp)
    jsr     cl_srcrec
    lea     12(%sp),%sp
    move.l  %a0,%d3
    beq.w   ap_none
    movea.l %a0,%a3                     | a3 = the source record
    movea.l %d0,%a4                     | a4 = its length
    movea.l %d1,%a5                     | a5 = its scale
ap_copy:
    move.l  %d5,-(%sp)
    move.l  %a3,-(%sp)
    move.l  %a2,%d0
    add.l   %d4,%d0
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    jsr     cl_nload                    | the name comes with the sequence
|   length / scale: the source's, resolved. Track len/scale bytes: audio +0x50/+0x51, MIDI +0x28/+0x29.
    moveq   #0x50,%d3
    cmpi.l  #8,%d6
    bcs.b   ap_lsoff
    moveq   #0x28,%d3
ap_lsoff:
    add.l   %d4,%d3                     | d3 = offset of this record's len byte
    lea     (%a2,%d3.l),%a0             | a0 -> the destination record's len byte
    cmpi.l  #SRC_ORIG,%d2
    bne.b   ap_wlen
    movea.l %a2,%a1                     | putting an original back onto a NORMAL pattern: its own
    adda.l  #TRAILER,%a1                | bytes stand (the slab comes back byte for byte)
    tst.b   T_SMODE(%a1)
    beq.b   ap_back
ap_wlen:
    move.l  %a4,%d0
    move.b  %d0,(%a0)
    move.l  %a5,%d0
    move.b  %d0,1(%a0)
    cmpi.l  #SRC_ORIG,%d2
    bne.b   ap_dst
ap_back:
    jsr     cl_back                     | put back: with every track original again, the pattern's
    move.l  %d6,%d0                     | length / scale / mode too; provenance off
    add.l   %d0,%d0
    lea     cl_home,%a0
    moveq   #-1,%d1
    move.b  %d1,(%a0,%d0.l)
    moveq   #1,%d0
    bra.b   ap_out
ap_dst:
    movea.l %a2,%a1
    adda.l  #TRAILER,%a1                | a1 -> the destination trailer
    tst.b   T_SMODE(%a1)
    bne.b   ap_prov                     | PER TRACK destination: done
    move.b  (%a0),%d0
    cmp.b   T_LEN(%a1),%d0
    bne.b   ap_conv
    move.b  1(%a0),%d0
    cmp.b   T_SCALE(%a1),%d0
    beq.b   ap_prov                     | NORMAL, same len/scale: nothing to convert
ap_conv:
    jsr     cl_convert                  | a2 = slab, d3 = len-byte offset (kept)
ap_prov:
|   provenance: this track now plays (sbank, spat) on the playing pattern
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_src,%a0
    move.b  %d2,(%a0,%d0.l)
    move.b  %d7,1(%a0,%d0.l)
    lea     cl_home,%a0
    move.b  PLAY_BANK,%d1
    move.b  %d1,(%a0,%d0.l)
    move.b  ACT_PAT,%d1
    move.b  %d1,1(%a0,%d0.l)
    moveq   #1,%d0
    bra.b   ap_out
ap_own:
    move.l  %d6,%d0                     | back to its own: provenance off
    add.l   %d0,%d0
    lea     cl_home,%a0
    moveq   #-1,%d1
    move.b  %d1,(%a0,%d0.l)
ap_none:
    moveq   #0,%d0
ap_out:
    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    rts

| cl_nload (d6 = t, d2 = sbank or SRC_*, d7 = spat): the source's name -> the playing pattern's
| name of t (a slot's, the saved sequence's, or the one it had when loaded). Keeps d2-d7/a2-a6.
cl_nload:
    tst.b   cl_namesok
    beq.b   nl_out
    moveq   #0,%d0                      | the destination
    move.b  PLAY_BANK,%d0
    lsl.l   #4,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    add.l   %d1,%d0
    lsl.l   #4,%d0
    add.l   %d6,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #NAMES,%a1
    adda.l  %d0,%a1                     | a1 = the destination name
    cmpi.l  #SRC_SAVED,%d2
    beq.b   nl_saved
    cmpi.l  #SRC_ORIG,%d2
    beq.b   nl_orig
    move.l  %d2,%d0                     | a slot
    lsl.l   #4,%d0
    add.l   %d7,%d0
    lsl.l   #4,%d0
    add.l   %d6,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #NAMES,%a0
    adda.l  %d0,%a0
    bra.b   nl_cp
nl_saved:
    move.l  %d6,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #SNAMES,%a0
    adda.l  %d0,%a0
    bra.b   nl_cp
nl_orig:
    move.l  %a1,%d0                     | the same index in the names as loaded
    subi.l  #NAMES,%d0
    movea.l #NAMESNAP,%a0
    adda.l  %d0,%a0
nl_cp:
    cmpa.l  %a0,%a1
    beq.b   nl_out                      | its own slot
    moveq   #NAME_W,%d0
nl_l:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   nl_l
nl_out:
    rts

| cl_srcrec(t, sbank, spat) -> a0 = the source record (0 = none), d0 = its resolved length, d1 =
| its resolved scale. sbank 0..15: a slot (a NORMAL pattern's length / scale are the pattern's);
| SRC_SAVED: saved[t] (resolved when saved); SRC_ORIG: t's record in the playing pattern's load
| snapshot (resolved through that snapshot's trailer). Uses d0-d1/a0-a1 only.
cl_srcrec:
    move.l  8(%sp),%d0
    cmpi.l  #SRC_SAVED,%d0
    beq.b   sr_saved
    cmpi.l  #SRC_ORIG,%d0
    beq.b   sr_orig
    move.l  4(%sp),-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,-(%sp)                  | the record offset
    move.l  16(%sp),-(%sp)              | spat
    move.l  16(%sp),-(%sp)              | sbank
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a1
    adda.l  #TRAILER,%a1                | a1 -> the source trailer
    adda.l  (%sp)+,%a0                  | a0 -> the source record
    tst.b   T_SMODE(%a1)
    bne.b   sr_rec                      | PER TRACK: the record's own bytes
    moveq   #0,%d0
    move.b  T_LEN(%a1),%d0
    moveq   #0,%d1
    move.b  T_SCALE(%a1),%d1
    rts
sr_saved:
    move.l  4(%sp),%d0
    lea     cl_svalid,%a0
    tst.b   (%a0,%d0.l)
    beq.b   sr_none
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    movea.l #SAVED_BASE,%a0
    adda.l  %d0,%a0
    bra.b   sr_rec
sr_orig:
    jsr     cl_origok
    tst.l   %d0
    beq.b   sr_none
    move.l  4(%sp),-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,-(%sp)                  | the record offset
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    jsr     cl_snapslab                 | a0 = the playing pattern's slab, as loaded
    movea.l %a0,%a1
    adda.l  #TRAILER,%a1
    adda.l  (%sp)+,%a0                  | a0 = the original record
    tst.b   T_SMODE(%a1)
    bne.b   sr_rec                      | PER TRACK when loaded: the record's own bytes
    moveq   #0,%d0                      | NORMAL when loaded: the pattern's length / scale
    move.b  T_LEN(%a1),%d0
    moveq   #0,%d1
    move.b  T_SCALE(%a1),%d1
    rts
sr_none:
    suba.l  %a0,%a0
    rts
sr_rec:                                 | a0 = a record whose own bytes count; t at 4(sp)
    move.l  4(%sp),%d1
    moveq   #0x50,%d0
    cmpi.l  #8,%d1
    bcs.b   sr_ra
    moveq   #0x28,%d0
sr_ra:
    movea.l %a0,%a1
    adda.l  %d0,%a1
    moveq   #0,%d0
    move.b  (%a1),%d0
    moveq   #0,%d1
    move.b  1(%a1),%d1
    rts

| d0 = 1 when the playing bank has its load snapshot (the originals). Uses d0-d1.
cl_origok:
    moveq   #0,%d1
    move.b  PLAY_BANK,%d1
    moveq   #0,%d0
    move.w  cl_snapok,%d0
    btst    %d1,%d0
    beq.b   ok_no
    moveq   #1,%d0
    rts
ok_no:
    moveq   #0,%d0
    rts

| cl_snapslab (d0 = bank, d1 = pattern) -> a0 = that pattern's slab in the load snapshot. d0-d1/a0.
cl_snapslab:
    move.l  %d1,-(%sp)
    move.l  #BANKSZ,%d1
    muls.l  %d1,%d0
    movea.l #SNAPB,%a0
    adda.l  %d0,%a0
    move.l  (%sp)+,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    adda.l  %d0,%a0
    rts

| cl_cmpw (a0, a1, d0 = an even byte count) -> d0 = 0 equal, 1 not; a0/a1 advance. Uses d1.
cl_cmpw:
    lsr.l   #1,%d0
    beq.b   cw_eq
cw_l:
    move.w  (%a0)+,%d1
    cmp.w   (%a1)+,%d1
    bne.b   cw_ne
    subq.l  #1,%d0
    bne.b   cw_l
cw_eq:
    moveq   #0,%d0
    rts
cw_ne:
    moveq   #1,%d0
    rts

| cl_back (a2 = the playing slab): an original has been put back. When every track of the pattern
| equals its original again (its length / scale bytes aside: a conversion rewrote them), the
| pattern's own length / scale / mode (+0x50..+0x55) and every track's length / scale come back
| from the snapshot too: a NORMAL -> PER TRACK conversion is undone, the slab is as loaded.
cl_back:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a3,(%sp)
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    jsr     cl_snapslab
    movea.l %a0,%a3                     | a3 = the snapshot slab
    moveq   #0,%d2                      | d2 = track
bk_l:
    move.l  %d2,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d3                     | d3 = record offset
    move.l  %d1,%d4                     | d4 = record length
    moveq   #0x50,%d5
    cmpi.l  #8,%d2
    bcs.b   bk_a
    moveq   #0x28,%d5                   | d5 = the len byte's offset in the record
bk_a:
    lea     (%a2,%d3.l),%a0
    lea     (%a3,%d3.l),%a1
    move.l  %d5,%d0
    jsr     cl_cmpw                     | up to the length / scale bytes
    tst.l   %d0
    bne.w   bk_out
    addq.l  #2,%a0
    addq.l  #2,%a1
    move.l  %d4,%d0
    sub.l   %d5,%d0
    subq.l  #2,%d0
    jsr     cl_cmpw                     | after them
    tst.l   %d0
    bne.w   bk_out
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   bk_l
    movea.l %a2,%a0                     | every track original: the rest comes back
    adda.l  #TRAILER,%a0
    movea.l %a3,%a1
    adda.l  #TRAILER,%a1
    moveq   #6,%d0
bk_tr:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d0
    bne.b   bk_tr
    moveq   #0,%d0
bk_pa:
    move.l  #TRAC_A,%d1
    muls.l  %d0,%d1
    lea     0x50(%a3,%d1.l),%a1
    lea     0x50(%a2,%d1.l),%a0
    move.b  (%a1)+,(%a0)+
    move.b  (%a1)+,(%a0)+
    addq.l  #1,%d0
    cmpi.l  #8,%d0
    bne.b   bk_pa
    moveq   #0,%d0
bk_pm:
    move.l  #TRAC_M,%d1
    muls.l  %d0,%d1
    addi.l  #MIDI_BASE+0x28,%d1
    lea     (%a3,%d1.l),%a1
    lea     (%a2,%d1.l),%a0
    move.b  (%a1)+,(%a0)+
    move.b  (%a1)+,(%a0)+
    addq.l  #1,%d0
    cmpi.l  #8,%d0
    bne.b   bk_pm
bk_out:
    movem.l (%sp),%d2-%d5/%a3
    lea     20(%sp),%sp
    rts

    .section .dram,"ax"
| cl_post_ui(t): what a load owes the UI side (never from the tick): the SRAM mirror, which holds
| the UI bank only (the whole slab: covers a NORMAL->PER TRACK conversion), and stock's dirty
| flags + refresh (the undo-restore's own 0x40029b9c).
cl_post_ui:
    move.b  PLAY_BANK,%d0
    cmp.b   UI_BANK,%d0
    bne.b   pu_dirty
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    addi.l  #SRAM_PAT,%d0
    pea     PATSTRIDE
    move.l  %a0,-(%sp)
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
pu_dirty:
    move.l  4(%sp),%d0
    andi.l  #7,%d0
    move.l  %d0,-(%sp)
    jsr     SEQ_DIRTY
    addq.l  #4,%sp
    rts

    .text
| ================================================================ the landing (sequencer tick)
| Measured rule (scope §3.4), stated in what each hook sees:
|  * MASTER WRAP (or a stock pattern change): stock's wrap body, entry 0x400a43a0 in phase G
|    (cl_wrap). A stock change landing there drops every cue (O8); a plain wrap lands every cue,
|    copy only -- the wrap body re-homes every track right after (the A1/A2 oracle).
|  * CHAIN AFTER point mid-pattern: phase D, 0x400a1f72 (cl_land, replaces `move.b 0x80006687,%d0`,
|    6 B; stock's ble.w follows on those flags, so the replay comes LAST). Phase G of the previous
|    tick has already advanced the master: TICK_CTR == 0 means this is the first tick of master
|    step s = MASTER_STEP; CHAIN AFTER N > 0 and s % N == 0 arms every cue. An armed track lands on the
|    first tick that is a window start for its old AND new rate, phase-continuous:
|    t0 = (MASTER_STEP - 1) * tps_M + TICK_CTR,  STEP = (t0 / tps + 1) mod len,  TICKS = t0 mod tps
|    (the A4..A8 oracles: t0 66 -> step 23 at 2x, t0 114 -> step 20).
cl_land:
    tst.b   cl_nq
    beq.w   la_out                      | nothing cued: one byte test per tick
    tst.l   RUNNING
    beq.w   la_out
|   mid-function in stock's tick handler: every register may be live -- save them all
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
|   tps_M and t0
    moveq   #0,%d0
    move.b  SCALE_IX,%d0
    jsr     cl_tps
    move.l  %d0,%d5                     | d5 = tps_M
    moveq   #0,%d3
    move.w  MASTER_STEP,%d3             | d3 = s
    moveq   #0,%d1
    move.b  TICK_CTR,%d1
    move.l  %d3,%d0
    subq.l  #1,%d0
    muls.l  %d5,%d0
    add.l   %d1,%d0
    move.l  %d0,%d7                     | d7 = t0
    tst.l   %d1
    bne.w   la_tracks                   | not the first tick of a master step
    tst.l   %d3
    beq.w   la_tracks
|   the playing pattern's CHAIN AFTER
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  #TRAILER,%a0
    move.b  6(%a0),%d0                  | +0x8e56: CHAIN AFTER index (signed), < 0 = project default
    extb.l  %d0
    bpl.b   la_q
    moveq   #0,%d0
    move.b  PROJ_QUANT,%d0
la_q:
    cmpi.l  #16,%d0
    bhi.w   la_tracks
    lea     QUANT_TBL,%a1
    move.l  (%a1,%d0.l*4),%d1           | N
    ble.w   la_tracks                   | CHAIN AFTER at its default: only the master wrap lands (cl_wrap)
    move.l  %d3,%d0
    remu.l  %d1,%d2:%d0                 | d2 = s mod N
    tst.l   %d2
    bne.w   la_tracks
|   a stock change cued for this same point lands it at the wrap body: leave that to cl_wrap
    move.b  PEND_PAT,%d0
    cmp.b   ACT_PAT,%d0
    bne.w   la_tracks
    move.b  PEND_BANK,%d0
    cmp.b   PLAY_BANK,%d0
    bne.w   la_tracks
|   arm every cue
    lea     cl_cue,%a0
    lea     cl_arm,%a1
    moveq   #0,%d0
la_arml:
    move.w  (%a0)+,%d1
    cmpi.w  #-1,%d1
    beq.b   la_armn
    moveq   #1,%d1
    move.b  %d1,(%a1,%d0.l)
la_armn:
    addq.l  #1,%d0
    cmpi.l  #16,%d0
    bne.b   la_arml

| every armed track whose old and new rates both start a window at t0
la_tracks:
    moveq   #0,%d6                      | d6 = track
la_tl:
    lea     cl_arm,%a0
    tst.b   (%a0,%d6.l)
    beq.w   la_tn
|   the cue must still aim at the playing pattern
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cueh,%a0
    move.w  (%a0,%d0.l),%d1
    moveq   #0,%d2
    move.b  PLAY_BANK,%d2
    lsl.l   #8,%d2
    move.b  ACT_PAT,%d2
    cmp.w   %d2,%d1
    beq.b   la_aimed
    jsr     cl_dropone                  | d6 = track
    bra.w   la_tn
la_aimed:
|   old rate
    lea     TSCALE_ARR,%a0
    moveq   #0,%d0
    move.b  (%a0,%d6.l),%d0
    jsr     cl_tps                      | d0 -> ticks per step
    move.l  %d7,%d1
    remu.l  %d0,%d2:%d1
    tst.l   %d2
    bne.w   la_tn                       | old window not at its start: wait
|   new rate: the source record's (after the copy's NORMAL/PER TRACK rule -- peek it first)
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d1
    move.w  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)                  | spat
    lsr.l   #8,%d1
    move.l  %d1,-(%sp)                  | sbank
    move.l  %d6,-(%sp)
    jsr     cl_newrate                  | d0 = new tps, d1 = new len, d2 = new scale index
    lea     12(%sp),%sp
    tst.l   %d0
    bne.b   la_rate
    jsr     cl_dropone                  | nothing to land any more
    bra.w   la_tn
la_rate:
    move.l  %d0,%a3                     | a3 = tps_new
    move.l  %d1,%a4                     | a4 = len_new
    move.l  %d2,%a5                     | a5 = scale_new
    move.l  %d7,%d1
    remu.l  %d0,%d2:%d1
    tst.l   %d2
    bne.w   la_tn                       | new window not at its start: wait
    jsr     cl_landone                  | d6 = track: copy + clear the cue
|   phase-continuous counters
    move.l  %d7,%d0
    move.l  %a3,%d1
    divu.l  %d1,%d0                     | t0 / tps
    addq.l  #1,%d0
    move.l  %a4,%d1
    remu.l  %d1,%d2:%d0                 | d2 = STEP
    lea     STEP_ARR,%a0
    move.b  %d2,(%a0,%d6.l)
    add.l   %d1,%d2
    subq.l  #1,%d2
    remu.l  %d1,%d0:%d2                 | d0 = (STEP + len - 1) mod len
    lea     STEPM1_ARR,%a0
    move.b  %d0,(%a0,%d6.l)
    move.l  %d7,%d0
    move.l  %a3,%d1
    remu.l  %d1,%d2:%d0
    lea     TICKS_ARR,%a0
    move.b  %d2,(%a0,%d6.l)             | 0 at a window start
    move.l  %a5,%d0
    lea     TSCALE_ARR,%a0
    move.b  %d0,(%a0,%d6.l)
la_tn:
    addq.l  #1,%d6
    cmpi.l  #16,%d6
    bne.w   la_tl
la_done:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
la_out:
    move.b  0x80006687,%d0              | displaced; stock's ble.w follows on these flags
    jmp     LAND_RESUME

| Phase G, the wrap body's entry 0x400a43a0 (replaces `move.l (a2),d0 ; moveq #1,d2 ;
| or.l d2,d0`, 6 B). Reached at a master wrap and when a stock pattern change lands.
cl_wrap:
    tst.b   cl_nq
    beq.b   wr_out
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    move.b  PEND_PAT,%d0
    cmp.b   ACT_PAT,%d0
    bne.b   wr_drop
    move.b  PEND_BANK,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   wr_drop
    moveq   #0,%d6                      | a plain wrap: every cue lands, copy only
wr_l:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    move.w  (%a0,%d0.l),%d1
    cmpi.w  #-1,%d1
    beq.b   wr_n
    lea     cl_cueh,%a0
    move.w  (%a0,%d0.l),%d1
    moveq   #0,%d2
    move.b  PLAY_BANK,%d2
    lsl.l   #8,%d2
    move.b  ACT_PAT,%d2
    cmp.w   %d2,%d1
    beq.b   wr_land
    jsr     cl_dropone                  | aimed at a pattern no longer playing
    bra.b   wr_n
wr_land:
    jsr     cl_landone
wr_n:
    addq.l  #1,%d6
    cmpi.l  #16,%d6
    bne.b   wr_l
    bra.b   wr_done
wr_drop:
    jsr     cl_dropall                  | the pattern is changing: the cues' destination goes
wr_done:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
wr_out:
    move.l  (%a2),%d0                   | displaced
    moveq   #1,%d2
    or.l    %d2,%d0
    jmp     WRAP_RESUME

| d0 = scale index -> d0 = ticks per step (out-of-range scale reads as 1x, as DIRECT JUMP does)
cl_tps:
    cmpi.l  #6,%d0
    bls.b   tp_ok
    moveq   #2,%d0
tp_ok:
    lea     LEN_TBL,%a0
    move.l  (%a0,%d0.l*4),%d0
    rts

| cl_newrate(t, sbank, spat) -> d0 = tps, d1 = len, d2 = scale index the track will have after
| cl_apply (the source's resolved length / scale, cl_srcrec); d0 = 0: there is no source (no saved
| sequence / original any more).
cl_newrate:
    move.l  12(%sp),-(%sp)              | spat
    move.l  12(%sp),-(%sp)              | sbank
    move.l  12(%sp),-(%sp)              | t
    jsr     cl_srcrec
    lea     12(%sp),%sp
    move.l  %a0,%d2
    beq.b   nr_none
    move.l  %d1,%d2                     | scale
    move.l  %d0,%d1                     | len
    move.l  %d1,-(%sp)
    move.l  %d2,%d0
    jsr     cl_tps
    move.l  (%sp)+,%d1
    tst.l   %d1
    bne.b   nr_out
    moveq   #16,%d1                     | never divide by a zero length
nr_out:
    rts
nr_none:
    moveq   #0,%d0
    rts

| cl_landone (d6 = track): copy the cue onto the playing pattern, clear it, owe the UI follow-up
cl_landone:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d1
    move.w  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)
    lsr.l   #8,%d1
    move.l  %d1,-(%sp)
    move.l  %d6,-(%sp)
    jsr     cl_apply
    lea     12(%sp),%sp
    jsr     cl_dropone
    move.w  cl_post,%d0
    moveq   #1,%d1
    lsl.l   %d6,%d1
    or.l    %d1,%d0
    move.w  %d0,cl_post                 | the UI side writes the SRAM mirror + dirty flags
    rts

| cl_dropone (d6 = track): forget its cue
cl_dropone:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #-1,%d1
    move.w  %d1,(%a0,%d0.l)
    lea     cl_arm,%a0
    clr.b   (%a0,%d6.l)
    bra.w   cl_count

cl_dropall:
    lea     cl_cue,%a0
    moveq   #-1,%d1
    moveq   #16,%d0
da_l:
    move.w  %d1,(%a0)+
    subq.l  #1,%d0
    bne.b   da_l
    lea     cl_arm,%a0
    moveq   #16,%d0
da_l2:
    clr.b   (%a0)+
    subq.l  #1,%d0
    bne.b   da_l2
| cl_nq = number of cues pending (the tick's one-byte fast path)
cl_count:                               | uses d0, d1, a0, a1 only
    lea     cl_cue,%a0
    lea     cl_cue+32,%a1
    moveq   #0,%d0
cn_l:
    move.w  (%a0)+,%d1
    cmpi.w  #-1,%d1
    beq.b   cn_n
    addq.l  #1,%d0
cn_n:
    cmpa.l  %a1,%a0
    bne.b   cn_l
    move.b  %d0,cl_nq
    rts

    .section .dram,"ax"
| ================================================================ the UI tail
| The UI task's message loop, common tail 0x40062d1c (replaces `tst.l 0x46c7c72c`, 6 B; stock's
| beq.w follows on those flags). Runs after every UI message. Does what a landing owes the UI.
cl_uitail:
    tst.b   cl_open
    beq.b   ut_post
    moveq   #0,%d0                      | the pattern you are on changed: the highlight follows
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0
    cmp.w   cl_lastp,%d0
    beq.b   ut_post
    move.w  %d0,cl_lastp
    jsr     cl_refresh
ut_post:
    move.w  cl_post,%d0
    beq.b   ut_out
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    clr.w   cl_post
    moveq   #0,%d2
    move.l  %d0,%d3
ut_l:
    btst    %d2,%d3
    beq.b   ut_n
    move.l  %d2,-(%sp)
    jsr     cl_post_ui
    addq.l  #4,%sp
ut_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   ut_l
    tst.b   cl_open
    beq.b   ut_closed
    jsr     cl_refresh                  | a landing: the slot labels and the grid follow
ut_closed:
    movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
ut_out:
    tst.l   RDRAW                       | displaced; stock's beq.w follows on these flags
    jmp     UIT_RESUME

    .text
| NORMAL -> PER TRACK, preserving every other track (scope §4.6). a2 = slab; d3 = this record's
| len-byte offset (its own len/scale are already written and are kept).
cl_convert:
    lea     -24(%sp),%sp
    movem.l %d2-%d5/%a2-%a3,(%sp)
    movea.l %a2,%a3
    adda.l  #TRAILER,%a3                | a3 -> trailer
    move.b  (%a2,%d3.l),%d4             | this track's own len / scale, kept
    move.b  1(%a2,%d3.l),%d5
    moveq   #0,%d0
    move.b  T_LEN(%a3),%d0
    move.w  %d0,T_MLEN(%a3)             | master length = the pattern length (u16)
    move.b  T_SCALE(%a3),%d1
    move.b  %d1,T_MSCALE(%a3)           | master scale = the pattern scale
    moveq   #0,%d2                      | every audio track
cv_a:
    move.l  %d2,%d1
    move.l  #TRAC_A,%d0
    muls.l  %d0,%d1
    move.b  T_LEN(%a3),%d0
    move.b  %d0,0x50(%a2,%d1.l)
    move.b  T_SCALE(%a3),%d0
    move.b  %d0,0x51(%a2,%d1.l)
    addq.l  #1,%d2
    moveq   #8,%d0
    cmp.l   %d2,%d0
    bne.b   cv_a
    moveq   #0,%d2                      | every MIDI track
cv_m:
    move.l  %d2,%d1
    move.l  #TRAC_M,%d0
    muls.l  %d0,%d1
    addi.l  #MIDI_BASE,%d1
    move.b  T_LEN(%a3),%d0
    move.b  %d0,0x28(%a2,%d1.l)
    move.b  T_SCALE(%a3),%d0
    move.b  %d0,0x29(%a2,%d1.l)
    addq.l  #1,%d2
    moveq   #8,%d0
    cmp.l   %d2,%d0
    bne.b   cv_m
    move.b  %d4,(%a2,%d3.l)             | this track's own length and scale back
    move.b  %d5,1(%a2,%d3.l)
    moveq   #1,%d0
    move.b  %d0,T_SMODE(%a3)            | PER TRACK
    movem.l (%sp),%d2-%d5/%a2-%a3
    lea     24(%sp),%sp
    rts

| The four `jsr 0x4000fd34` sites (every bank to defaults: a new project, the start of a load) ->
| here. The reset may be the last thing to write the banks (measured in the emulator: a reload
| whose loader pass came BEFORE the reset), so the originals are retaken after it: whatever wrote
| the banks last defines them. In ROM because 0x4001fb1e may run before the boot loader has put
| the DRAM part in place: the snapshot is only taken once cl_magic says it is there.
| the LED layer's tick (stock calls it every CL_BLINK ticks from 0x4007e940, inside FUN_40052200 --
| the context of the QLREC crash: LED bits only, CLAUDE.md; ROM, as tick-path code): the active track's cued slot, if it is shown and is not the pattern you are on,
| alternates yellow / off
cl_blink:
    move.l  %d2,-(%sp)
    moveq   #0,%d0
    move.b  cl_bph,%d0
    eori.l  #1,%d0
    move.b  %d0,cl_bph
    moveq   #0,%d0                      | the active track (cl_trk, inlined: this is ROM)
    move.b  CUR_TRACK,%d0
    andi.l  #7,%d0
    tst.l   MIDI_MODE
    beq.b   bl_trk
    addq.l  #8,%d0
bl_trk:
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d1
    move.w  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    lsr.l   #8,%d0
    moveq   #0,%d2
    move.b  cl_bank,%d2
    cmp.l   %d2,%d0
    bne.b   bl_out                      | none, another bank, or SAVED / ORIG
    andi.l  #0xff,%d1
    move.b  PLAY_BANK,%d0
    cmp.b   cl_bank,%d0
    bne.b   bl_led
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d1,%d0
    beq.b   bl_out                      | red wins
bl_led:
    lea     LED_TBL,%a0
    move.l  (%a0,%d1.l*4),%d2           | the red die; green = +1
    lea     LED_ON,%a0
    tst.b   cl_bph
    bne.b   bl_set
    lea     LED_OFF,%a0
bl_set:
    move.l  %a0,-(%sp)
    move.l  %d2,-(%sp)
    jsr     (%a0)
    addq.l  #1,(%sp)
    movea.l 4(%sp),%a0
    jsr     (%a0)
    addq.l  #8,%sp
bl_out:
    move.l  (%sp)+,%d2
    rts

cl_rstall:
    move.l  4(%sp),-(%sp)
    jsr     RESET_BANKS
    addq.l  #4,%sp
    move.l  cl_magic,%d0
    cmpi.l  #CL_MAGIC,%d0
    bne.b   rs_skip
    jmp     cl_snapall                  | returns to our caller
rs_skip:
    rts

    .section .dram,"ax"
| ================================================================ the Clyps view
| text(x, y, str) in the small font onto the window surface (a4); keeps d2-d7/a2-a6
cl_text:
    move.l  12(%sp),-(%sp)              | str
    pea     -1                          | mode
    move.l  16(%sp),-(%sp)              | y
    move.l  16(%sp),-(%sp)              | x
    move.l  %a4,-(%sp)
    pea     FONT_S
    jsr     TEXT
    lea     24(%sp),%sp
    rts

| xor(x0, y0, x1, y1) on the window surface (a4)
cl_xor:
    pea     -1
    move.l  20(%sp),-(%sp)              | y1
    move.l  20(%sp),-(%sp)              | x1
    move.l  20(%sp),-(%sp)              | y0
    move.l  20(%sp),-(%sp)              | x0
    move.l  %a4,-(%sp)
    jsr     RECT
    lea     24(%sp),%sp
    rts

cl_draw:
    tst.b   cl_open
    beq.w   cd_out
    lea     -36(%sp),%sp
    movem.l %d2-%d7/%a2-%a4,(%sp)
    movea.l cl_win,%a4
    lea     0x24(%a4),%a4               | a4 = the window's surface
|   clear, then a 1 px border (xor on a cleared surface = set)
    clr.l   -(%sp)
    pea     WIN_H-1
    pea     WIN_W-1
    clr.l   -(%sp)
    clr.l   -(%sp)
    move.l  %a4,-(%sp)
    jsr     RECT
    lea     24(%sp),%sp
    pea     WIN_H-1                     | top
    pea     WIN_W-1
    pea     WIN_H-1
    clr.l   -(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    clr.l   -(%sp)                      | bottom
    pea     WIN_W-1
    clr.l   -(%sp)
    clr.l   -(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    pea     WIN_H-2                     | left
    clr.l   -(%sp)
    pea     1
    clr.l   -(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    pea     WIN_H-2                     | right
    pea     WIN_W-1
    pea     1
    pea     WIN_W-1
    bsr.w   cl_xor
    lea     16(%sp),%sp
|   header: "T6  BANK A", inverted in a band one row taller than the text above and below
    jsr     cl_trk
    moveq   #'T',%d1
    cmpi.l  #8,%d0
    bcs.b   cd_ta
    moveq   #'M',%d1
    subq.l  #8,%d0
cd_ta:
    addq.l  #1,%d0
    moveq   #0,%d2
    move.b  cl_bank,%d2
    addi.l  #'A',%d2
    move.l  %d2,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    pea     cl_fmt_hdr
    pea     cl_buf
    jsr     SPRINTF
    lea     20(%sp),%sp
    pea     cl_buf
    pea     HDR_Y
    pea     3
    bsr.w   cl_text
    lea     12(%sp),%sp
|   the header's right side, first match: [FUNC] held = the FULL label (FULL loads arrive in a
|   later phase); the cursor on ORIG = a dark ORIG box; a save just made = a dark SAVED box; else
|   the load mode. d5 = the dark box's left column, 0 = none.
    moveq   #0,%d5
    lea     cl_s_full,%a0
    moveq   #LOADF_X,%d0
    tst.b   cl_fn
    bne.b   cd_mode
    lea     cl_s_orig,%a0
    moveq   #BOX_R-1-ORIG_W,%d0
    moveq   #0,%d1
    move.b  cl_cur,%d1
    cmpi.l  #NSLOT,%d1
    beq.b   cd_box
    lea     cl_s_saved,%a0
    moveq   #BOX_R-1-SAVED_W,%d0
    tst.b   cl_flash
    bne.b   cd_box
    lea     cl_s_seq,%a0
    moveq   #LOAD_X,%d0
    bra.b   cd_mode
cd_box:
    move.l  %d0,%d5
    subq.l  #2,%d5                      | 2 dark columns each side of the text
cd_mode:
    move.l  %a0,-(%sp)
    pea     HDR_Y
    move.l  %d0,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
|   "SAVED" between the labels while the active track plays its saved sequence (no slot is red)
    tst.b   cl_fn
    bne.b   cd_band
    jsr     cl_playing
    lsr.l   #8,%d0
    cmpi.l  #SRC_SAVED,%d0
    bne.b   cd_band
    pea     cl_s_saved
    pea     HDR_Y
    pea     MID_X
    bsr.w   cl_text
    lea     12(%sp),%sp
cd_band:
    pea     WIN_H-2                     | the band, inverted with its text
    pea     WIN_W-2
    pea     HDR_Y-2
    pea     1
    bsr.w   cl_xor
    lea     16(%sp),%sp
    tst.l   %d5
    beq.b   cd_nobox
    pea     WIN_H-2                     | the dark box: lit letters, one lit row below (the band's)
    pea     BOX_R                       | and one above (the border)
    pea     HDR_Y-1
    move.l  %d5,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
cd_nobox:
|   round the two top corners (a card): clear (0,63) (1,63) (0,62) and their mirror images
    lea     cl_corners,%a2
    moveq   #6,%d2
cd_corner:
    clr.l   -(%sp)                      | mode 0 = clear
    move.w  (%a2)+,%d0
    ext.l   %d0
    move.w  (%a2)+,%d1
    ext.l   %d1
    move.l  %d1,-(%sp)                  | y1 = y
    move.l  %d0,-(%sp)                  | x1 = x
    move.l  %d1,-(%sp)                  | y0
    move.l  %d0,-(%sp)                  | x0
    move.l  %a4,-(%sp)
    jsr     RECT
    lea     24(%sp),%sp
    subq.l  #1,%d2
    bne.b   cd_corner
|   the 16 cells
    jsr     cl_trk
    move.l  %d0,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d7                     | d7 = record offset
    moveq   #0,%d2                      | d2 = slot 0..15
cd_cell:
    moveq   #COL0_X,%d3                 | d3 = column x
    cmpi.l  #8,%d2
    bcs.b   cd_c0
    moveq   #COL1_X,%d3
cd_c0:
    move.l  %d2,%d4
    andi.l  #7,%d4
    moveq   #ROW_PITCH,%d0
    muls.l  %d0,%d4
    moveq   #ROW0_Y,%d0
    sub.l   %d4,%d0
    move.l  %d0,%d4                     | d4 = y
|   the slot number, right-aligned by position (a space is narrower than a digit)
    move.l  %d2,%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)
    pea     cl_fmt_num
    pea     cl_buf
    jsr     SPRINTF
    lea     12(%sp),%sp
    move.l  %d3,%d0
    cmpi.l  #9,%d2
    bcc.b   cd_two
    addq.l  #DIGIT_W,%d0                | one digit: start one digit in
cd_two:
    pea     cl_buf
    move.l  %d4,-(%sp)
    move.l  %d0,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
|   the "edited" mark: this sequence differs from its original (the user, 2026-10-27)
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d2,%d1
    jsr     cl_edited
    tst.l   %d0
    beq.w   cd_noed
    lea     cl_xpix,%a2                 | five (dx, dy) pixels
    moveq   #5,%d5
cd_edp:
    move.l  %d3,%d6
    subq.l  #-ED_X,%d6
    move.b  (%a2)+,%d0
    extb.l  %d0
    add.l   %d0,%d6                     | x
    move.b  (%a2)+,%d0
    extb.l  %d0
    add.l   %d4,%d0                     | y
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    subq.l  #1,%d5
    bne.b   cd_edp
cd_noed:
|   a named sequence shows its name; else the summary: "n TRIGS" / "LOCKS" / "---"; on the
|   highlighted slot (the pattern you are on), while the track plays a sequence Clyps put there
|   unedited: its source, "A14 6 TRG" / "SAVED"
    tst.b   cl_namesok
    beq.b   cd_noname
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d2,%d1
    jsr     cl_nidx
    jsr     cl_nptr
    tst.b   (%a0)
    bne.w   cd_sum                      | the name
cd_noname:
    move.b  cl_bank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   cd_plain
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   cd_plain
    jsr     cl_srclbl
    move.l  %a0,%d0
    bne.b   cd_sum
cd_plain:
    lea     cl_cls,%a0
    moveq   #0,%d0
    move.b  (%a0,%d2.l),%d0
    beq.b   cd_empty
    subq.l  #1,%d0
    beq.b   cd_half
    move.l  %d2,-(%sp)
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d7,%a0
    moveq   #0,%d1
    move.l  4(%a0),-(%sp)
    move.l  (%a0),%d0
    bsr.w   cl_popc
    move.l  (%sp)+,%d0
    bsr.w   cl_popc
    move.l  %d1,-(%sp)
    pea     cl_fmt_trg
    pea     cl_buf
    jsr     SPRINTF
    lea     12(%sp),%sp
    lea     cl_buf,%a0
    bra.b   cd_sum
cd_half:
    lea     cl_s_lck,%a0
    bra.b   cd_sum
cd_empty:
    lea     cl_s_emp,%a0
cd_sum:
    move.l  %a0,-(%sp)
    move.l  %d4,-(%sp)
    move.l  %d3,%d0
    addi.l  #2*DIGIT_W+SUM_GAP,%d0
    move.l  %d0,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
|   the cell's rectangle: x d5..d6, y d4-1 .. d4+5 (one row above and below the text)
    move.l  %d3,%d5
    subq.l  #-HL_X0,%d5
    move.l  %d3,%d6
    addi.l  #HL_X1,%d6
|   the highlight: an inverted bar over the pattern you are on (only in its bank)
    move.b  cl_bank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   cd_sbox
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   cd_sbox
    move.l  %d4,%d0
    addq.l  #5,%d0
    move.l  %d0,-(%sp)                  | y1
    move.l  %d6,-(%sp)                  | x1
    move.l  %d4,%d0
    subq.l  #1,%d0
    move.l  %d0,-(%sp)                  | y0
    move.l  %d5,-(%sp)                  | x0
    bsr.w   cl_xor
    lea     16(%sp),%sp
|   the select box: a 1 px frame on the same rectangle (only in the box's bank; not over the
|   highlight, where the bar alone shows it)
cd_sbox:
    move.b  cl_bank,%d0
    cmp.b   cl_sbank,%d0
    bne.w   cd_next
    cmp.b   PLAY_BANK,%d0               | on the highlight: the bar alone (the user, 2026-10-27)
    bne.b   cd_frame
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    beq.w   cd_next
cd_frame:
    moveq   #0,%d0
    move.b  cl_cur,%d0
    cmp.l   %d2,%d0
    bne.w   cd_next
    move.l  %d4,%d0                     | top edge
    addq.l  #5,%d0
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d5,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    move.l  %d4,%d0                     | bottom edge
    subq.l  #1,%d0
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d5,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    move.l  %d4,%d0                     | left edge (corners belong to top / bottom)
    addq.l  #4,%d0
    move.l  %d0,-(%sp)
    move.l  %d5,-(%sp)
    move.l  %d4,-(%sp)
    move.l  %d5,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    move.l  %d4,%d0                     | right edge
    addq.l  #4,%d0
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d4,-(%sp)
    move.l  %d6,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
cd_next:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.w   cd_cell
    moveq   #1,%d0
    move.l  %d0,RDRAW
    movem.l (%sp),%d2-%d7/%a2-%a4
    lea     36(%sp),%sp
cd_out:
    rts

| cl_nidx (d0 = bank, d1 = pattern) -> d0 = the name index of (bank, pattern, the active track).
| Keeps d2-d7/a2-a6.
cl_nidx:
    lsl.l   #4,%d0
    add.l   %d1,%d0
    lsl.l   #4,%d0
    move.l  %d0,-(%sp)
    jsr     cl_trk
    add.l   (%sp)+,%d0
    rts

| cl_nptr (d0 = a name index) -> a0 = that name (NAME_W bytes, NUL-terminated; "" = none). d0-d1/a0.
cl_nptr:
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #NAMES,%a0
    adda.l  %d0,%a0
    rts

| cl_edited (d0 = bank, d1 = pattern) -> d0 = 1 when the active track's sequence there differs from
| its original (the load snapshot): the record (its length / scale bytes aside), or its EFFECTIVE
| length / scale (the record's own in PER TRACK, the pattern's in NORMAL -- so a NORMAL -> PER
| TRACK conversion does not mark the untouched tracks). 0 = original, or no snapshot. Keeps
| d2-d7/a2-a6.
cl_edited:
    lea     -28(%sp),%sp
    movem.l %d2-%d6/%a2-%a3,(%sp)
    move.l  %d0,%d2                     | d2 = bank
    move.l  %d1,%d3                     | d3 = pattern
    moveq   #0,%d0
    move.w  cl_snapok,%d0
    btst    %d2,%d0
    beq.b   ed_no
    jsr     cl_trk
    move.l  %d0,%d4                     | d4 = track
    move.l  %d4,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d5                     | d5 = record offset
    move.l  %d3,-(%sp)
    move.l  %d2,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a2                     | a2 = the slab now
    move.l  %d2,%d0
    move.l  %d3,%d1
    jsr     cl_snapslab
    movea.l %a0,%a3                     | a3 = the slab as loaded
    lea     (%a2,%d5.l),%a0
    lea     (%a3,%d5.l),%a1
    move.l  %d4,%d0
    jsr     cl_same
    tst.l   %d0
    bne.b   ed_yes
    movea.l %a2,%a0
    bsr.b   cl_efflen
    move.l  %d0,%d6
    movea.l %a3,%a0
    bsr.b   cl_efflen
    cmp.l   %d6,%d0
    bne.b   ed_yes
ed_no:
    moveq   #0,%d0
    bra.b   ed_out
ed_yes:
    moveq   #1,%d0
ed_out:
    movem.l (%sp),%d2-%d6/%a2-%a3
    lea     28(%sp),%sp
    rts

| cl_efflen (a0 = a slab, d5 = the record's offset, d4 = its track) -> d0 = length << 8 | scale as
| it plays: the record's own in PER TRACK, the pattern's in NORMAL. Uses d0-d1/a1.
cl_efflen:
    movea.l %a0,%a1
    adda.l  #TRAILER,%a1
    tst.b   T_SMODE(%a1)
    bne.b   ef_rec
    moveq   #0,%d0
    move.b  T_LEN(%a1),%d0
    lsl.l   #8,%d0
    move.b  T_SCALE(%a1),%d0
    rts
ef_rec:
    moveq   #0x50,%d1
    cmpi.l  #8,%d4
    bcs.b   ef_a
    moveq   #0x28,%d1
ef_a:
    add.l   %d5,%d1
    moveq   #0,%d0
    move.b  (%a0,%d1.l),%d0
    lsl.l   #8,%d0
    move.b  1(%a0,%d1.l),%d0
    rts

| cl_srclbl -> a0 = the label for the highlighted slot when the active track plays a sequence
| Clyps put on this pattern and it is unedited (length / scale bytes aside): "A14 6 TRG",
| "A14 LOCKS", "A14 ---" (in cl_buf) or "SAVED"; else a0 = 0. Keeps d2-d7/a2-a6.
cl_srclbl:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a2,(%sp)
    jsr     cl_trk
    move.l  %d0,%d2                     | d2 = track
    jsr     cl_playt
    move.l  %d0,%d3                     | d3 = what plays: bank << 8 | pattern
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d3,%d0
    beq.w   sl_none                     | its own sequence
    move.l  %d2,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d4                     | d4 = record offset
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d4,%a0
    movea.l %a0,%a2                     | a2 = the playing record
    move.l  %d3,%d5
    lsr.l   #8,%d5                      | d5 = source bank (or SRC_SAVED)
    cmpi.l  #SRC_SAVED,%d5
    beq.w   sl_saved
    cmpi.l  #16,%d5
    bcc.w   sl_none
    move.l  %d3,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)
    move.l  %d5,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d4,%a0
    movea.l %a0,%a1                     | a1 = the source record
    movea.l %a2,%a0
    move.l  %d2,%d0
    jsr     cl_same
    tst.l   %d0
    bne.w   sl_none                     | edited since: the plain summary
    moveq   #0,%d0
    cmpi.l  #8,%d2
    scc     %d0
    move.l  %d0,-(%sp)
    move.l  %a2,-(%sp)
    jsr     cl_classify
    addq.l  #8,%sp
    move.l  %d3,%d1
    andi.l  #0xff,%d1
    addq.l  #1,%d1                      | slot number
    addi.l  #'A',%d5                    | bank letter
    subq.l  #1,%d0
    beq.b   sl_lck
    bcs.b   sl_emp
    moveq   #0,%d1
    move.l  4(%a2),-(%sp)
    move.l  (%a2),%d0
    bsr.w   cl_popc
    move.l  (%sp)+,%d0
    bsr.w   cl_popc
    move.l  %d1,-(%sp)                  | trig count
    move.l  %d3,%d1
    andi.l  #0xff,%d1
    addq.l  #1,%d1
    move.l  %d1,-(%sp)
    move.l  %d5,-(%sp)
    pea     cl_fmt_srct
    bra.b   sl_fmt
sl_lck:
    clr.l   -(%sp)
    move.l  %d1,-(%sp)
    move.l  %d5,-(%sp)
    pea     cl_fmt_srcl
    bra.b   sl_fmt
sl_emp:
    clr.l   -(%sp)
    move.l  %d1,-(%sp)
    move.l  %d5,-(%sp)
    pea     cl_fmt_srce
sl_fmt:
    pea     cl_buf
    jsr     SPRINTF
    lea     20(%sp),%sp
    lea     cl_buf,%a0
    bra.b   sl_out
sl_saved:
    move.l  %d2,%d0
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    movea.l #SAVED_BASE,%a1
    adda.l  %d0,%a1                     | a1 = the saved sequence
    movea.l %a2,%a0
    move.l  %d2,%d0
    jsr     cl_same
    tst.l   %d0
    bne.b   sl_none
    lea     cl_s_saved,%a0
    bra.b   sl_out
sl_none:
    suba.l  %a0,%a0
sl_out:
    movem.l (%sp),%d2-%d5/%a2
    lea     20(%sp),%sp
    rts

| cl_same (a0, a1 = two records of track d0) -> d0 = 0 when equal, their length / scale bytes
| aside (a load writes the resolved ones). Uses d1/a0/a1; keeps d2-d7/a2-a6.
cl_same:
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    move.l  #TRAC_A,%d3                 | d3 = record length
    moveq   #0x50,%d2                   | d2 = the length byte's offset
    cmpi.l  #8,%d0
    bcs.b   cs_a
    move.l  #TRAC_M,%d3
    moveq   #0x28,%d2
cs_a:
    move.l  %d2,%d0
    jsr     cl_cmpw
    tst.l   %d0
    bne.b   cs_out
    addq.l  #2,%a0
    addq.l  #2,%a1
    move.l  %d3,%d0
    sub.l   %d2,%d0
    subq.l  #2,%d0
    jsr     cl_cmpw
cs_out:
    movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
    rts

| d1 += number of set bits in d0 (uses d0, a1)
cl_popc:
    tst.l   %d0
    beq.b   pc_out
    movea.l %d0,%a1
    subq.l  #1,%d0
    move.l  %a1,-(%sp)
    and.l   (%sp)+,%d0                  | clear the lowest set bit
    addq.l  #1,%d1
    bra.b   cl_popc
pc_out:
    rts

| ================================================================ the Clyps grid (LED slot 0)
| no args: stock calls it from 0x4007e998 / its rebuilds. Per slot of the shown bank, first match:
|   red          the pattern you are on (red wins: the user, 2026-10-27)
|   yellow       the active track's cued sequence -- flashing (cl_blink), solid once it plays
|   yellow       the select box
|   green 15 / 7 a slot with sample/note trigs / other data only; off = empty
cl_paint:
    lea     -36(%sp),%sp
    movem.l %d2-%d6/%a2-%a5,(%sp)
    lea     LED_BRI,%a3
    lea     LED_ON,%a4
    lea     LED_OFF,%a5
    jsr     cl_trk
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d0
    move.w  (%a0,%d0.l),%d0
    movea.l %d0,%a2                     | a2 = the active track's cue (0xffff = none)
    moveq   #0,%d2
cp_lp:
    lea     LED_TBL,%a0
    move.l  (%a0,%d2.l*4),%d3           | d3 = red die, d4 = green die
    move.l  %d3,%d4
    addq.l  #1,%d4
    pea     15
    move.l  %d3,-(%sp)
    jsr     (%a3)
    move.l  %d4,(%sp)
    jsr     (%a3)                       | full brightness on both (half green is set below)
    addq.l  #8,%sp
    move.b  cl_bank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   cp_nothere
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   cp_nothere
    move.l  %d3,-(%sp)                  | red: the pattern you are on
    jsr     (%a4)
    move.l  %d4,(%sp)
    jsr     (%a5)
    addq.l  #4,%sp
    bra.w   cp_next
cp_nothere:
    moveq   #0,%d0
    move.b  cl_bank,%d0
    lsl.l   #8,%d0
    or.l    %d2,%d0
    cmp.l   %a2,%d0
    beq.b   cp_yellow                   | cued (cl_blink flashes it)
    move.b  cl_bank,%d0
    cmp.b   cl_sbank,%d0
    bne.b   cp_green
    moveq   #0,%d0
    move.b  cl_cur,%d0
    cmp.l   %d2,%d0
    bne.b   cp_green
cp_yellow:
    move.l  %d3,-(%sp)                  | yellow: red + green
    jsr     (%a4)
    move.l  %d4,(%sp)
    jsr     (%a4)
    addq.l  #4,%sp
    bra.b   cp_next
cp_green:
    move.l  %d3,-(%sp)
    jsr     (%a5)                       | red off
    addq.l  #4,%sp
    lea     cl_cls,%a0
    moveq   #0,%d0
    move.b  (%a0,%d2.l),%d0
    beq.b   cp_off
    moveq   #15,%d1
    subq.l  #2,%d0
    beq.b   cp_bri
    moveq   #7,%d1                      | half: stock's dim level
cp_bri:
    move.l  %d1,-(%sp)
    move.l  %d4,-(%sp)
    jsr     (%a3)
    move.l  %d4,(%sp)
    jsr     (%a4)
    addq.l  #8,%sp
    bra.b   cp_next
cp_off:
    move.l  %d4,-(%sp)
    jsr     (%a5)
    addq.l  #4,%sp
cp_next:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.w   cp_lp
    movem.l (%sp),%d2-%d6/%a2-%a5
    lea     36(%sp),%sp
    rts

| ================================================================ data (both parts run from RAM)
    .align 2
cl_layer:   .long 0, cl_keys, cl_encs, 0, 0     | +16 is written -1 by the push

| key record: code, 0, press, release, hold, sub-map, 4 x 0, hold delay (w), repeat (w)
    .macro KREC code, press, rel, hold, dly=0, rep=0, sub=0
    .byte \code, 0
    .long \press, \rel, \hold, \sub, 0
    .short \dly, \rep
    .endm
cl_keys:
| ⚠️ Every record's hold delay / repeat MUST equal the base keymap's (T1 0x400bfc10) for that key.
| set_key_state appends a key's timer record to the repeat list 0x460d1660 at press when its
| delay is non-zero, and removes it at release only when the record it then holds has a non-zero
| delay. A key pressed under one layer and released under another (the chord's second key: our
| layer goes up inside its press handler) with differing delays leaves a stale entry, and that
| key's next press links the record to itself: the UI task loops forever (measured, emulator).
    .irp c, 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
    KREC \c, cl_k_trig, 0, 0, 16, 0
    .endr
    .irp c, 0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17
    KREC \c, cl_k_track, cl_k_track, cl_k_track, 30, 0
    .endr
    KREC 0x33, cl_k_ud, 0, cl_k_ud, 15, 4
    KREC 0x20, cl_k_ud, 0, cl_k_ud, 15, 4
    KREC 0x34, cl_k_lr, 0, 0, 15, 6      | the other column, no repeat (the delay stays non-zero:
    KREC 0x21, cl_k_lr, 0, 0, 15, 6      | the add/remove rule above holds)
    KREC 0x31, cl_k_yes, 0, 0, 0, 0
    KREC 0x32, cl_k_no, 0, 0, 0, 0
    KREC 0x2e, cl_k_chord, cl_k_chord, 0, 30, 0
    KREC 0x2f, cl_k_chord, cl_k_chord, 0, 30, 0
    KREC 0x2d, cl_k_func, cl_k_func, 0, 0, 0, cl_fsub
    KREC 0x1b, cl_k_page, 0, 0, 0, 0     | [PAGE]: the original back ([FUNC]+[PAGE]: every track's)
    .byte 0xff, 0
    .align 2
| [FUNC]'s sub-map. A key's sub-maps are not overridden by a higher layer but CHAINED: the rebuild
| (0x4003125c) appends each layer's sub-map for the key after the ones below, and the press links
| the chain at the end of the layer list (0x40031766), stock's FUNC sub-map 0x400bfa1e first. So
| ours comes after it and wins for the keys it lists (measured: without it, [FUNC]+[YES] reached
| stock's 0x4005e3d8). Delays as stock's sub-map; a key held across [FUNC]'s release keeps the
| record it was pressed with (0x400312e2). +12 / +16 are written by stock: RAM.
cl_fsub:    .long 0, cl_fkeys, 0, 0, 0
cl_fkeys:
    KREC 0x31, cl_k_yes, 0, 0, 0, 0      | [FUNC]+[YES]: nothing in Clyps
    KREC 0x32, cl_k_no, 0, 0, 0, 0       | [FUNC]+[NO]: nothing in Clyps
    KREC 0x1b, cl_k_page, 0, 0, 0, 0     | [FUNC]+[PAGE] restore all
    KREC 0x33, cl_k_ud, 0, cl_k_ud, 15, 4
    KREC 0x20, cl_k_ud, 0, cl_k_ud, 15, 4
    KREC 0x34, cl_k_lr, 0, 0, 15, 5
    KREC 0x21, cl_k_lr, 0, 0, 15, 5
    KREC 0x2e, cl_k_chord, cl_k_chord, 0, 0, 0
    KREC 0x2f, cl_k_chord, cl_k_chord, 0, 0, 0
    .irp c, 0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17
    KREC \c, cl_k_track, cl_k_track, cl_k_track, 0, 0
    .endr
    KREC 0x35, 0, 0, 0, 0, 0             | [FUNC]+[MIDI] (PARTS): nothing in Clyps mode (scope §1.7)
    .byte 0xff, 0
    .align 2

| encoder records (22 B): id, 0, handler 0 = locked (stock lists do the same)
cl_encs:
    .irp e, 0,1,2,3,4,5,6
    .byte \e, 0
    .long 0, 0, 0, 0, 0
    .endr
    .byte 0xff, 0
    .align 2

| LED layer: {next, records}; record {slot, paint, tick, period, pad}, ended by -1
cl_led:     .long 0, cl_ledrec
cl_ledrec:  .long 0, cl_paint, cl_blink
            .byte CL_BLINK, 0
            .long -1
            .align 2

cl_win:     .long 0
cl_open:    .byte 0
cl_sbank:   .byte 0                     | the select box's bank (cl_cur its slot, 16 = ORIG)
cl_bank:    .byte 0
cl_cur:     .byte 0
cl_fn:      .byte 0                     | [FUNC] held (our own press/release record)
cl_flash:   .byte 0                     | the header shows SAVED (a save) until the next key
cl_nproj:   .byte 0                     | project loads seen (the emulator gate reads it)
            .align 2
cl_cls:     .space 16
| the valid marks: inside the loaded image, so every boot's depack zeroes them (the buffers they
| describe are not)
cl_lastp:   .short 0xffff               | the pattern you were on at the last redraw (cl_uitail)
cl_magic:   .long CL_MAGIC              | the DRAM part is in place (the boot loader put it there)
cl_svalid:  .space 16                   | per track: a saved sequence is held
cl_namesok: .byte 0                     | the names are cleared (at the first project load) and usable
            .align 2
cl_nedit:   .long 0                     | the name being edited (its index)
cl_nbuf:    .space NAME_W               | the editor's scratch copy
            .align 2
cl_ynact:   .byte 0, 0                  | [YES] / [NO] held (their press was ours)
cl_ynused:  .byte 0, 0                  | ... and a TRACK key was pressed meanwhile (a chord)
            .align 2
cl_ynt0:    .long 0, 0                  | ... and SCLK at its press
| the TRACK keys while [YES] / [NO] is held. Delay 30 = the base keymap's (T1 0x400bfc10).
cl_tlayer:  .long 0, cl_tkeys, 0, 0, 0
cl_tkeys:
    .irp c, 0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17
    KREC \c, cl_k_tsave, 0, 0, 30, 0
    .endr
    .byte 0xff, 0
    .align 2
cl_snapok:  .short 0                    | bit b: bank b's load snapshot (its originals) is valid
cl_ldmask:  .short 0                    | the masked loader in progress: its banks
cl_ldret:   .long 0                     | ... and its caller's return address
cl_buf:     .space 32

| the tick's state: in the ROM part, beside the code that writes it
    .text
    .align 2
cl_src:     .space 32                   | per track: (bank, pattern) the sequence came from
cl_home:    .fill 32, 1, 0xff           | per track: the playing (bank, pattern) at that load
cl_cue:     .fill 16, 2, 0xffff         | per track: the cued (bank<<8 | pattern), 0xffff = none
cl_cueh:    .fill 16, 2, 0xffff         | per track: the playing (bank<<8 | pattern) it aims at
cl_arm:     .space 16                   | per track: the gate has passed; waiting for a window start
cl_post:    .short 0                    | tracks whose landing the UI side has not followed up yet
cl_bph:     .byte 0                     | the cue flash phase (cl_blink)
cl_nq:      .byte 0                     | cues pending (the tick's fast path)
            .align 2

    .section .dram,"ax"

cl_corners: .short 0,63, 1,63, 0,62, WIN_W-1,63, WIN_W-2,63, WIN_W-1,62
cl_xpix:    .byte 0,1, 2,1, 1,2, 0,3, 2,3   | the "x": corners and centre of a 3 x 3 at rows y + 1..3
cl_fmt_hdr: .asciz "%c%d BANK %c"
cl_fmt_num: .asciz "%d"
cl_fmt_trg: .asciz "%d TRIGS"
cl_s_lck:   .asciz "LOCKS"
cl_s_emp:   .asciz "---"
cl_s_seq:   .asciz "LOAD: SEQ"
cl_s_full:  .asciz "LOAD: SEQ+MCH/FX"
cl_s_orig:  .asciz "ORIG"
cl_s_saved: .asciz "SAVED"
cl_fmt_srct:.asciz "%c%d %dTRG"          | <= 34 px: "A14 64TRG"
cl_fmt_srcl:.asciz "%c%d LOCKS"
cl_fmt_srce:.asciz "%c%d ---"
cl_s_rename:.asciz "RENAME SEQUENCE"
cl_fmt_tsv: .asciz "%sTRK %d SAVED"
cl_fmt_trl: .asciz "%sTRK %d RELOADED"
cl_fmt_tno: .asciz "%sTRK %d: SAVE FIRST"       | toast window = text + 15 px: 126 px at most (MIDI TRK 8)
cl_s_midi:  .asciz "MIDI "
cl_s_none:  .byte 0
    .align 4
| the buffers: past the loaded image, uninitialised (dram.build's bss); read only behind a valid
| mark. The snapshot is every bank as loaded (16 slabs + its Parts each: the Parts are there for
| FULL restores), so every track's original is always there.
cl_bss:
    .equ SNAPB,       cl_bss                    | 16 x BANKSZ: the banks as loaded (the originals)
    .equ SAVED_BASE,  cl_bss + 16*BANKSZ        | 16 x TRAC_A: the saved sequences
    .equ NAMES,       SAVED_BASE + 16*TRAC_A    | 4096 x NAME_W: (bank, pattern, track) -> its name
    .equ SNAMES,      NAMES + 4096*NAME_W       | 16 x NAME_W: the saved sequences' names (right after
                                                | NAMES: one clear covers both)
    .equ NAMESNAP,    SNAMES + 16*NAME_W        | 4096 x NAME_W: the names as loaded (ORIG)
    .equ CL_BSS_SIZE, 16*BANKSZ + 16*TRAC_A + 4096*NAME_W + 16*NAME_W + 4096*NAME_W
    .global CL_BSS_SIZE, cl_bss
