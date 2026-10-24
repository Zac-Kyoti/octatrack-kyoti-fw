| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| CLYPS -- phase 2 (reference/handoffs/CLYPS_SCOPE.md): Clyps mode, the Clyps view (2 x 8 table
| of the active track's sequence in each pattern of a bank) and the Clyps grid (trig LEDs), with
| the held / latched states of scope §1.1. Loads copy the source track record into the playing
| pattern at once (phase 2: no cued landing yet, scope §8 phase 4).
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
    .equ MIDI_MODE,   0x80000012        | != 0 -> MIDI tracks
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
    .equ PRIO,        3                 | menus' rank: toasts / the name editor open over it

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
    .equ COL0_X,      4                 | highlight x0 = col - 2, x1 = col + 50: column 0 2..54,
    .equ COL1_X,      59                | column 1 57..109 -- one px to the frame (0 / 111) on both
                                        | outer sides, a 2 px gap between the columns
    .equ SUM_GAP,     5                 | gap between the slot number and its summary

    .text
    .global cl_ptn, cl_bankp, cl_bankr

| ================================================================ detours
| [PTN] key handler 0x4005a044 (press, release, hold). Replaces 6 B:
|   move.l 8(sp),%d0 ; moveq #1,%d1
cl_ptn:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   cp_notpress
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
cp_notpress:
    tst.l   %d0
    bne.b   cp_stock                    | hold events: stock (harmless)
    tst.b   cl_open
    beq.b   cp_stock
    jsr     cl_chord_rel                | then stock's release: PTN_CONSUMED -> teardown only
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

| [BANK] release handler 0x4007b3e0. Replaces 8 B: moveq #2,d0 ; cmp.l 0x460e73c6,d0
| (the resume point is stock's beq on that compare, so the compare is replayed LAST).
cl_bankr:
    tst.b   cl_open
    beq.b   cr_stock
    jsr     cl_chord_rel
cr_stock:
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

| cl_enter(bankfirst)
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
|   the shown bank and the cursor: where the track's playing sequence came from
    jsr     cl_playing                  | d0 = bank<<8 | pattern
    move.l  %d0,%d1
    lsr.l   #8,%d1
    move.b  %d1,cl_bank
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
    move.b  %d0,cl_held
    clr.b   cl_loaded
    pea     cl_layer
    jsr     LAYER_PUSH
    pea     cl_led
    jsr     LED_PUSH
    addq.l  #8,%sp
    jsr     cl_refresh
ce_fail:
    rts

| the one teardown: [YES]/[NO]/trig/release paths AND the window's close_cb (eviction).
| Idempotent; stock never clears a slot's close_cb, so it may be called again later.
cl_close:
    tst.b   cl_open
    beq.b   cc_out
    clr.b   cl_open
    clr.b   cl_held
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

| a chord key was released (either one): the hold ends
cl_chord_rel:
    tst.b   cl_held
    beq.b   cr_out
    clr.b   cl_held
    tst.b   cl_loaded
    beq.b   cr_latch
    bra.w   cl_close                    | loads were made during the hold: close
cr_latch:
    jsr     cl_draw                     | latched: stays open
cr_out:
    rts

| ================================================================ keymap handlers
| UP 0x33 / DOWN 0x20: cursor 0..15, wrapping, auto-repeat (hold events)
cl_k_ud:
    tst.l   8(%sp)
    beq.b   ku_out
    moveq   #0,%d0
    move.b  cl_cur,%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x33,%d1
    bne.b   ku_down
    addi.l  #15,%d0                     | UP = previous
    bra.b   ku_set
ku_down:
    addq.l  #1,%d0
ku_set:
    andi.l  #15,%d0
    move.b  %d0,cl_cur
    jsr     cl_draw
ku_out:
    rts

| LEFT 0x34 / RIGHT 0x21: bank A..P, wrapping
cl_k_lr:
    tst.l   8(%sp)
    beq.b   kl_out
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x34,%d1
    bne.b   kl_right
    addi.l  #15,%d0
    bra.b   kl_set
kl_right:
    addq.l  #1,%d0
kl_set:
    andi.l  #15,%d0
    move.b  %d0,cl_bank
    jsr     cl_refresh
kl_out:
    rts

| TRIG 1-16 (codes 0x00..0x0f): load that slot of the shown bank
cl_k_trig:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kt_out
    move.l  4(%sp),%d0
    andi.l  #15,%d0
    move.b  %d0,cl_cur
    move.l  %d0,-(%sp)
    jsr     cl_load
    addq.l  #4,%sp
    tst.b   cl_held
    beq.w   cl_close                    | latched: a load closes Clyps
    moveq   #1,%d0
    move.b  %d0,cl_loaded               | held: stays; the release will close
    bra.w   cl_refresh
kt_out:
    rts

| [YES]: latched -> load the cursor slot and close. Held -> nothing in phase 2 (DIRECT JUMP's
| toggle in an image that has it; scope §1.1).
cl_k_yes:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   ky_out
    tst.b   cl_held
    bne.b   ky_out
    moveq   #0,%d0
    move.b  cl_cur,%d0
    move.l  %d0,-(%sp)
    jsr     cl_load
    addq.l  #4,%sp
    bra.w   cl_close
ky_out:
    rts

| [NO]: latched -> close, no load. Held -> swallowed.
cl_k_no:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kn_out
    tst.b   cl_held
    beq.w   cl_close
kn_out:
    rts

| TRACK 1-8 (0x10..0x17): every event goes through stock's own base handler, as the base keymap
| does (press marks the key held in 0x460fab40 and handles double taps; the RELEASE selects the
| track and clears the held mark). After the release the view and the grid follow.
cl_k_track:
    move.l  8(%sp),-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     TRK_BASE
    addq.l  #8,%sp
    tst.l   8(%sp)
    beq.w   cl_refresh                  | release: the track has changed
    rts

| [PTN] / [BANK] pressed or released while Clyps is open (keys pressed AFTER our layer went up
| reach these records; the chord keys held when it went up reach stock, see the detours)
cl_k_chord:
    move.l  8(%sp),%d0
    beq.w   cl_chord_rel                | release
    cmpi.l  #1,%d0
    bne.b   kc_out
|   whatever happens next, a later release of this key under stock's own record (after Clyps
|   closes) must not open SELECT PATTERN / SELECT BANK
    moveq   #1,%d1
    move.l  %d1,PTN_CONSUMED
    moveq   #2,%d1
    move.l  %d1,BANK_SEL
    move.l  4(%sp),%d1
    move.l  BANK_HELD,%d0               | [PTN] pressed: is [BANK] held?
    cmpi.l  #0x2e,%d1
    beq.b   kc_test
    move.l  PTN_HELD,%d0                | [BANK] pressed: is [PTN] held?
kc_test:
    tst.l   %d0
    beq.b   kc_out
    moveq   #1,%d0
    move.b  %d0,cl_held                 | the chord again: held state, no loads yet
    clr.b   cl_loaded
kc_out:
    rts

| [FUNC]: phase 2 only redraws (the FULL label arrives with FULL loads)
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
    tst.b   MIDI_MODE
    beq.b   ct_out
    addq.l  #8,%d0
ct_out:
    rts

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

| d0 = (bank << 8) | pattern of the sequence playing on the active track: its Clyps source
| while the load still belongs to the playing pattern, otherwise the playing pattern itself
cl_playing:
    move.l  %d2,-(%sp)
    jsr     cl_trk
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

| ================================================================ the load (phase 2: at once)
| cl_load(n): the shown bank's pattern n -> the playing pattern, active track
cl_load:
    lea     -32(%sp),%sp
    movem.l %d2-%d7/%a2-%a3,(%sp)
    move.l  36(%sp),%d7                 | d7 = source pattern
    jsr     cl_trk
    move.l  %d0,%d6                     | d6 = track 0..15
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
    move.l  %d7,-(%sp)
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a3                     | a3 = source slab
    cmpa.l  %a2,%a3
    beq.w   cl_ld_own                   | the playing pattern's own slot: nothing to copy
    move.l  %d5,-(%sp)
    move.l  %a3,%d0
    add.l   %d4,%d0
    move.l  %d0,-(%sp)
    move.l  %a2,%d0
    add.l   %d4,%d0
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
|   length / scale (scope §1.5a, §4.6). Track len/scale bytes: audio +0x50/+0x51, MIDI +0x28/+0x29.
    moveq   #0x50,%d3
    cmpi.l  #8,%d6
    bcs.b   ld_lsoff
    moveq   #0x28,%d3
ld_lsoff:
    add.l   %d4,%d3                     | d3 = offset of this record's len byte
    lea     (%a2,%d3.l),%a0             | a0 -> the destination record's len byte
    movea.l %a3,%a1
    adda.l  #TRAILER,%a1                | a1 -> the source trailer
    tst.b   T_SMODE(%a1)
    bne.b   ld_srcpt
    move.b  T_LEN(%a1),%d0              | NORMAL source: its own length is the pattern's
    move.b  %d0,(%a0)
    move.b  T_SCALE(%a1),%d0
    move.b  %d0,1(%a0)
ld_srcpt:
    movea.l %a2,%a1
    adda.l  #TRAILER,%a1                | a1 -> the destination trailer
    tst.b   T_SMODE(%a1)
    bne.b   ld_mirror                   | PER TRACK destination: done
    move.b  (%a0),%d0
    cmp.b   T_LEN(%a1),%d0
    bne.b   ld_conv
    move.b  1(%a0),%d0
    cmp.b   T_SCALE(%a1),%d0
    beq.b   ld_mirror                   | NORMAL, same len/scale: nothing to convert
ld_conv:
    jsr     cl_convert                  | a2 = slab, d3 = len-byte offset (kept)
ld_mirror:
|   the SRAM mirror holds the UI bank only
    move.b  PLAY_BANK,%d0
    cmp.b   UI_BANK,%d0
    bne.b   ld_dirty
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    addi.l  #SRAM_PAT,%d0
    pea     PATSTRIDE                   | the whole slab: covers a NORMAL->PER TRACK conversion
    move.l  %a2,-(%sp)
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
ld_dirty:
    move.l  %d6,%d0
    andi.l  #7,%d0
    move.l  %d0,-(%sp)
    jsr     SEQ_DIRTY                   | dirty flags + the refresh stock's undo-restore runs
    addq.l  #4,%sp
|   provenance: this track now plays (cl_bank, n) on the playing pattern
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_src,%a0
    move.b  cl_bank,%d1
    move.b  %d1,(%a0,%d0.l)
    move.b  %d7,1(%a0,%d0.l)
    lea     cl_home,%a0
    move.b  PLAY_BANK,%d1
    move.b  %d1,(%a0,%d0.l)
    move.b  ACT_PAT,%d1
    move.b  %d1,1(%a0,%d0.l)
    bra.b   ld_out
cl_ld_own:
    move.l  %d6,%d0                     | back to its own: provenance off
    add.l   %d0,%d0
    lea     cl_home,%a0
    moveq   #-1,%d1
    move.b  %d1,(%a0,%d0.l)
ld_out:
    movem.l (%sp),%d2-%d7/%a2-%a3
    lea     32(%sp),%sp
    rts

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
|   the load mode, right-aligned in the header ([FUNC] held = the FULL label; FULL loads arrive
|   in a later phase)
    lea     cl_s_seq,%a0
    moveq   #LOAD_X,%d0
    tst.b   cl_fn
    beq.b   cd_mode
    lea     cl_s_full,%a0
    moveq   #LOADF_X,%d0
cd_mode:
    move.l  %a0,-(%sp)
    pea     HDR_Y
    move.l  %d0,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
    pea     WIN_H-2                     | the band, inverted with its text
    pea     WIN_W-2
    pea     HDR_Y-2
    pea     1
    bsr.w   cl_xor
    lea     16(%sp),%sp
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
|   the summary: "n TRIGS" / "LOCKS" / "---"
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
|   the cursor: an inverted bar over the cell, one row above and below the text
    moveq   #0,%d0
    move.b  cl_cur,%d0
    cmp.l   %d2,%d0
    bne.b   cd_next
    move.l  %d4,%d0
    addq.l  #5,%d0
    move.l  %d0,-(%sp)                  | y1
    move.l  %d3,%d0
    addi.l  #WIN_W/2-6,%d0
    move.l  %d0,-(%sp)                  | x1
    move.l  %d4,%d0
    subq.l  #1,%d0
    move.l  %d0,-(%sp)                  | y0
    move.l  %d3,%d0
    subq.l  #2,%d0
    move.l  %d0,-(%sp)                  | x0
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
| no args: stock calls it from 0x4007e998 / its rebuilds
cl_paint:
    lea     -36(%sp),%sp
    movem.l %d2-%d6/%a2-%a5,(%sp)
    lea     LED_BRI,%a3
    lea     LED_ON,%a4
    lea     LED_OFF,%a5
    jsr     cl_playing
    move.l  %d0,%d6                     | bank<<8 | pattern playing
    moveq   #0,%d2
cp_lp:
    lea     LED_TBL,%a0
    move.l  (%a0,%d2.l*4),%d3           | d3 = red die, d3+1 = green die
    move.l  %d3,%d4
    addq.l  #1,%d4
    moveq   #0,%d0
    move.b  cl_bank,%d0
    lsl.l   #8,%d0
    or.l    %d2,%d0
    cmp.l   %d6,%d0
    bne.b   cp_notplay
    pea     15                          | red: playing
    move.l  %d3,-(%sp)
    jsr     (%a3)
    move.l  %d3,(%sp)
    jsr     (%a4)
    move.l  %d4,(%sp)
    jsr     (%a5)
    addq.l  #8,%sp
    bra.b   cp_next
cp_notplay:
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
    bne.b   cp_lp
    movem.l (%sp),%d2-%d6/%a2-%a5
    lea     36(%sp),%sp
    rts

| ================================================================ data (in .text: the blob runs from RAM)
    .align 2
cl_layer:   .long 0, cl_keys, cl_encs, 0, 0     | +16 is written -1 by the push

| key record: code, 0, press, release, hold, sub-map, 4 x 0, hold delay (w), repeat (w)
    .macro KREC code, press, rel, hold, dly=0, rep=0
    .byte \code, 0
    .long \press, \rel, \hold, 0, 0
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
    KREC 0x34, cl_k_lr, 0, cl_k_lr, 20, 10   | the user: bank cycling at least 2x stock's 30-tick repeat
    KREC 0x21, cl_k_lr, 0, cl_k_lr, 20, 10   | (non-zero delay: the add/remove rule above holds)
    KREC 0x31, cl_k_yes, 0, 0, 0, 0
    KREC 0x32, cl_k_no, 0, 0, 0, 0
    KREC 0x2e, cl_k_chord, cl_k_chord, 0, 30, 0
    KREC 0x2f, cl_k_chord, cl_k_chord, 0, 30, 0
    KREC 0x2d, cl_k_func, cl_k_func, 0, 0, 0
    KREC 0x1b, 0, 0, 0, 0, 0             | [PAGE]: swallowed in phase 2 (ORIG arrives in phase 3)
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
cl_ledrec:  .long 0, cl_paint, 0
            .byte 0, 0
            .long -1
            .align 2

cl_win:     .long 0
cl_open:    .byte 0
cl_held:    .byte 0
cl_loaded:  .byte 0
cl_bank:    .byte 0
cl_cur:     .byte 0
cl_fn:      .byte 0                     | [FUNC] held (our own press/release record)
            .align 2
cl_cls:     .space 16
cl_src:     .space 32                   | per track: (bank, pattern) the sequence came from
cl_home:    .fill 32, 1, 0xff           | per track: the playing (bank, pattern) at that load
cl_buf:     .space 32

cl_corners: .short 0,63, 1,63, 0,62, WIN_W-1,63, WIN_W-2,63, WIN_W-1,62
cl_fmt_hdr: .asciz "%c%d BANK %c"
cl_fmt_num: .asciz "%d"
cl_fmt_trg: .asciz "%d TRIGS"
cl_s_lck:   .asciz "LOCKS"
cl_s_emp:   .asciz "---"
cl_s_seq:   .asciz "LOAD: SEQ"
cl_s_full:  .asciz "LOAD: SEQ+MCH/FX"
    .align 2
