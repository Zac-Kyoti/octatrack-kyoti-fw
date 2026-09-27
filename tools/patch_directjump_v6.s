| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
|
| DIRECT JUMP V6 -- Session 105 (2026-09-26).  AR's DIRECT JUMP through OT's OWN landing.
|
| Everything the V1-V5 line hooked in the sequencer (dj_a/dj_b/dj_c/dj_d7/dj_scaleix_fix,
| Hooks Z/X/V, the boundary-body offset 0x80006628) is gone.  What stays from those builds
| is the UI: the [PTN]+[YES] toggle (dj_toggle, written into the PTN-held keymap layer by
| the build), the OS toast, dj_ptnrel (close the toast on [PTN] release) and DJ_MODE's
| power-on-OFF guarantee.  Read NOTES.md "Session 105 continued" first.
|
| ---- the mechanism, measured (reference/AR_SEQUENCER_ENGINE.md; NOTES S105 cont.) ----
| OT's tick handler (consumer_a6c0_a33f8 @0x400a1eea) is AR's phase for phase.  Phase D,
| at 0x400a1f72, counts a byte 0x80006687 down once per tick and, when it reaches 0,
| RE-LANDS THE WHOLE SEQUENCER from a snapshot -- exactly what AR's DIRECT JUMP commit
| does (AR FUN_4009905c 0x40099174-0x4009936c):
|     reload 0x800065d3[t] = tps_t - 1 (16 tracks)      master tick 0x800065b6 = tps - 1
|     first-fire mask 0x80006624 = 0xffff                CNTDN 0x800065c3[t] = -1 (idle)
|     STEP 0x800064d0[t] = 0x80006516[t] (word)          0x800064e0[t] = that - 1
|     ticks-in-step 0x800064f0[t] = 0x80006536[t]        MASTER_STEP 0x800065b2 = 0x8000663a
|     scale caches, ARMED for enabled tracks, transport running, (MIDI START if enabled)
| and the scheduler (phase E, 0x400a2982) then fires every track's landing step in the
| same tick, F advances every track, G runs the master step body.  Stock uses this path
| for a deferred transport start; AR uses the same layout for DIRECT JUMP.  So:
|
|   Hook L @0x400a1f72 (replaces `move.b (0x80006687).l,%d0`, 6 B):
|     idle, a manual pattern cued (PEND != ACT), stock's countdown idle
|         -> ARM: 0x80006687 = LEN_TBL[SCALE_IX] - TICK_CTR   (AR D1: the next MASTER step
|            boundary; stock's own decrement follows in this very tick)
|     armed and the countdown reads 1 (this tick lands)
|         -> prev = cur; cur = PEND; new_step = MASTER_STEP mod masterLen(new);
|            0x80006638 = new_step; per track 0x80006516[t] = new_step mod len_t,
|            0x80006536[t] = 0; hold / per-track resync masks cleared; state = LANDING
|         then stock lands.
|   Hook N @0x400a221c (replaces `tst.b (0x8000002a).l`, 6 B): while LANDING, take the
|     "no MIDI send" branch so a jump does not emit MIDI START (0xFA); consume the state.
|
| DJ_MODE == 0 -> both hooks replay the displaced instruction and nothing else: stock.
|
| State lives IN THE CAVE (this blob is loaded into RAM with the OS), never in the
| 0x80006a40..0x80006abf scratch block (Session 98: the unit overwrites it).

    .equ DJ_MODE,   0x800000d8          | state word (0 = OFF/stock, 1 = ON); power-on 0
    .equ PTN_MODE,  0x460d1742          | 1 = [PTN] currently held
    .equ PTN_USED,  0x460d173e          | !=0 on [PTN] release -> the chooser does NOT open
    .equ POPUP,     0x460e5cd0          | !=0 = a modal popup is up
    .equ ARR_ACT,   0x460d1aec          | !=0 = arranger running (FUN_40033968)
    .equ CHAIN_ACT, 0x80006546          | !=0 = pattern chain running
    .equ NOTIFY,    0x4005a2b8          | FUN_4005a2b8(char *text, int dur_frames)
    .equ NOTIFY_HANDLE,    0x460d1e70   | nonzero while a FUN_4005a2b8 toast is open
    .equ NOTIFY_COUNTDOWN, 0x460d1e6c   | frames left; stock's tick closes it at 0
    .equ PTN_LAYER_REL_RESUME, 0x4004341e
    .ifndef DJ_TOAST_DUR
    .equ DJ_TOAST_DUR, 0x44
    .endif

|   ---- sequencer state (all MEASURED, NOTES Session 105 cont.) ----
    .equ TRANSPORT_L, 0x800065b8        | long: 1 while the transport is running
    .equ ACT_BANK,  0x800065bd
    .equ ACT_PAT,   0x800065be
    .equ PEND_BANK, 0x800065bf
    .equ PEND_PAT,  0x800065c0
    .equ PREV_PAT,  0x800065c1
    .equ PREV_BANK, 0x800065c2
    .equ MASTER_STEP, 0x800065b2        | word: the master STEP index, ++ once per step
    .equ TICK_CTR,  0x800065b6          | byte: master ticks-within-step, 0..tps-1
    .equ SCALE_IX,  0x8000663d          | byte: LIVE master scale index
    .equ LEN_TBL,   0x400aba50          | [scaleIdx] -> ticks per step (long)
    .equ LAND_CNTDN, 0x80006687         | byte: stock's landing countdown (phase D)
    .equ SNAP_STEP, 0x80006516          | word[16]: per-track landing step
    .equ SNAP_TICK, 0x80006536          | byte[16]: per-track landing ticks-in-step
    .equ RESUME_L,  0x80006638          | long; its low word 0x8000663a lands MASTER_STEP
    .equ HOLD_MASK, 0x80006626          | word, bit per track: skip one advance
    .equ RESYNC80,  0x80006680          | word masks: PER-TRACK length-boundary resync
    .equ RESYNC82,  0x80006682
    .equ RESYNC84,  0x80006684
    .equ MIDI_SEND, 0x8000002a          | byte: send MIDI transport (START/STOP/...)
    .equ PC_SEND,   0x4009e884          | FUN_4009e884(bank, pat): MIDI Program Change
    .equ SPRINTF,   0x40013a08          | varargs sprintf (DJ_DIAG toast only)
    .equ KPOST,     0x40000c3c          | kernel post(queue, msg) -- see dl_commit
    .equ UI_QUEUE,  0x460d17ae          | the sequencer->UI message queue
    .equ MSG_BANKPAT, 0x400d8167        | message 0x15: {code, bank} -- stock's wrap-change post
    .equ MSG_BANKPAT_ARG, 0x400d8168
    .equ MSG_PAT,     0x400d8164        | message 0x11: {code, pattern, 0} -- stock @0x400a40fc
    .equ MSG_PAT_ARG, 0x400d8165

    .equ PAT_BASE,  0x400e21e0          | pattern blobs: + bank*0x9b340 + pat*0x8ed8
    .equ BANK_STRIDE, 0x9b340
    .equ PAT_STRIDE,  0x8ed8
    .equ P_LEN_BYTE,  0x8e53            | NORMAL mode: pattern length (byte)
    .equ P_MLEN_WORD, 0x8e50            | PER-TRACK mode: MASTER LENGTH (word, -1 = INF)
    .equ P_SCALE_MODE,0x8e55            | 0 = NORMAL, else PER-TRACK
    .equ A_LEN,     0x50                | audio track length, + t*0x91a
    .equ A_STRIDE,  0x91a
    .equ M_LEN,     0x48f8              | MIDI track length, + (t-8)*0x8b0
    .equ M_STRIDE,  0x8b0

    .equ ST_IDLE,    0
    .equ ST_ARMED,   1
    .equ ST_LANDING, 2

    .text

| ================= [PTN]+[YES] toggle (called from the PTN-held keymap layer) =================
| press(keycode, event): 4(%sp) = keycode, 8(%sp) = event (1 press / 0 release / 2 hold).
    .global dj_toggle
dj_toggle:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0                 | press only
    bne.w   djt_stock
    move.l  PTN_MODE,%d0
    subq.l  #1,%d0
    bne.w   djt_stock                  | [PTN] not held
    tst.l   ARR_ACT
    bne.w   djt_stock                  | arranger up -> don't shadow arranger-YES
    tst.l   POPUP
    bne.w   djt_stock
    move.l  DJ_MODE,%d0
    eori.l  #1,%d0
    andi.l  #1,%d0
    move.l  %d0,DJ_MODE                | no shadow, no checksum: power-on is 0 (stock's own
                                       | DSP-window re-image; asserted by the build)
    lea     dj_msg_off,%a0
    tst.l   %d0
    beq.b   djt_show
    lea     dj_msg_on,%a0
djt_show:
    .ifdef DJ_DIAG
|   V6.1 diagnostic (Session 106): instead of ON/OFF the toast prints the hook's own
|   view of the sequencer and resets the counters.  Key-handler context: sprintf and
|   NOTIFY are legal here (never from the engine path).  Fields:
|     A = arms   L = landings   R = ticks a cued pattern was seen while idle
|     C = raw 0x80006687 byte (signed) at the last tick   T = TRANSPORT_L low byte
|     H = CHAIN_ACT low byte   G = ARR_ACT low byte
|   Expected on a working jump: A == L == number of switches, R small.  R > 0 with A == 0
|   -> the arm gate refuses: read C/T/H/G.  R == 0 -> PEND never differs from ACT here.
    moveq   #0,%d0
    move.b  dj_obs_g,%d0
    move.l  %d0,-(%sp)
    moveq   #0,%d0
    move.b  dj_obs_h,%d0
    move.l  %d0,-(%sp)
    moveq   #0,%d0
    move.b  dj_obs_t,%d0
    move.l  %d0,-(%sp)
    move.b  dj_obs_c,%d0
    ext.w   %d0
    ext.l   %d0
    move.l  %d0,-(%sp)                 | C printed SIGNED: a stale byte >= 0x80 reads negative
    move.l  dj_cnt_req,-(%sp)
    move.l  dj_cnt_land,-(%sp)
    move.l  dj_cnt_arm,-(%sp)
    pea     dj_diag_fmt
    pea     dj_diag_buf
    jsr     SPRINTF
    lea     36(%sp),%sp
    clr.l   dj_cnt_arm
    clr.l   dj_cnt_land
    clr.l   dj_cnt_req
    lea     dj_diag_buf,%a0
    .endif
    pea     DJ_TOAST_DUR
    move.l  %a0,-(%sp)
    jsr     NOTIFY
    addq.l  #8,%sp
    moveq   #1,%d0
    move.l  %d0,PTN_USED               | [PTN] release must not open the chooser
    rts
djt_stock:
    rts                                | the layer's stock [YES] slot is NULL: nothing

dj_msg_on:
    .asciz "DIRECT JUMP ON"
    .align 2
dj_msg_off:
    .asciz "DIRECT JUMP OFF"
    .align 2

| ================= Hook L @ 0x400a1f72 -- arm, then land through stock =================
| Inside the tick handler, phase D, once per clock tick (the handler keeps live values
| in D3-D7/A2-A6 across its whole body -> save everything).  Must end by replaying
| `move.b LAND_CNTDN,%d0` LAST: stock's next instruction is `ble.w` on its flags.
    .global dj_land
dj_land:
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    .ifdef DJ_DIAG
    move.b  LAND_CNTDN,%d0
    move.b  %d0,dj_obs_c
    move.b  TRANSPORT_L+3,%d0
    move.b  %d0,dj_obs_t
    move.b  CHAIN_ACT+3,%d0
    move.b  %d0,dj_obs_h
    move.b  ARR_ACT+3,%d0
    move.b  %d0,dj_obs_g
    .endif
    tst.l   DJ_MODE
    beq.w   dl_off
    moveq   #1,%d0
    cmp.l   TRANSPORT_L,%d0
    bne.w   dl_off                     | not running -> never arm, cancel if armed
    tst.l   ARR_ACT
    bne.w   dl_off
    tst.l   CHAIN_ACT
    bne.w   dl_off
    move.b  dj_state,%d0
    beq.b   dl_idle
    cmpi.b  #ST_ARMED,%d0
    bne.w   dl_done                    | LANDING is consumed by Hook N; nothing here
    move.b  LAND_CNTDN,%d0
    cmpi.b  #1,%d0
    bne.w   dl_done                    | still counting (stock decrements below us)
    bsr.w   dl_commit                  | this tick lands: prepare the snapshot
    bra.w   dl_done

dl_off:                                | DJ off / stopped / arranger / chain
    move.b  dj_state,%d0
    cmpi.b  #ST_ARMED,%d0              | (ColdFire cmpi takes only a Dn destination)
    bne.b   dl_clear
    clr.b   LAND_CNTDN                 | WE armed stock's countdown -> take it back
dl_clear:
    clr.b   dj_state
    moveq   #-1,%d0
    move.b  %d0,dj_pcpat
    bra.w   dl_done

dl_idle:
    move.b  PEND_PAT,%d0
    cmpi.b  #-1,%d0
    beq.b   dl_clear                   | nothing cued (also resets the PC latch)
    cmp.b   ACT_PAT,%d0
    bne.b   dl_real
    move.b  PEND_BANK,%d0
    cmp.b   ACT_BANK,%d0
    beq.b   dl_clear                   | cued == active: nothing to do
dl_real:
    .ifdef DJ_DIAG
    addq.l  #1,dj_cnt_req
    .endif
|   MIDI Program Change once per distinct cued pattern (what every DJ build since v1 did)
    move.b  PEND_PAT,%d0
    cmp.b   dj_pcpat,%d0
    beq.b   dl_arm
    move.b  %d0,dj_pcpat
    moveq   #0,%d0
    move.b  PEND_PAT,%d0
    move.l  %d0,-(%sp)
    moveq   #0,%d0
    move.b  PEND_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     PC_SEND
    addq.l  #8,%sp
dl_arm:
|   V6.1 (Session 106): only a POSITIVE countdown means stock has a landing pending.  The
|   PLAY path seeds this byte from 0x80006688 (0x4009bb2a), which the arranger writes with a
|   raw word's low byte (0x400a0e6e) and nothing clears at boot; the ISR counts it down only
|   while positive (`ble.w` at 0x400a1f78).  A stale byte >= 0x80 therefore sits there for
|   ever on hardware -- V6's `bne` never armed (flashed 2026-09-27: toast ON, no jump).  The
|   emulator zero-fills that RAM, which is why its gate passed.
    tst.b   LAND_CNTDN
    bgt.w   dl_done                    | stock's own landing pending -> stay out of its way
    moveq   #0,%d0
    move.b  SCALE_IX,%d0
    lea     LEN_TBL,%a0
    move.l  (%a0,%d0.l*4),%d1          | tps of the OUTGOING master
    moveq   #0,%d0
    move.b  TICK_CTR,%d0
    sub.l   %d0,%d1                    | 1..tps: ticks to the next master step boundary
    move.b  %d1,LAND_CNTDN             | AR D1; stock decrements it right after we return
    moveq   #ST_ARMED,%d0
    move.b  %d0,dj_state
    .ifdef DJ_DIAG
    addq.l  #1,dj_cnt_arm
    .endif
dl_done:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
    move.b  LAND_CNTDN,%d0             | displaced original -- sets the flags for ble.w
    rts

| dl_commit: the landing tick.  Registers are free (saved by the caller).
dl_commit:
    move.b  ACT_PAT,%d0
    move.b  %d0,PREV_PAT
    move.b  ACT_BANK,%d0
    move.b  %d0,PREV_BANK
    move.b  PEND_PAT,%d0
    move.b  %d0,ACT_PAT
    move.b  PEND_BANK,%d0
    move.b  %d0,ACT_BANK
|   a2 = new pattern blob
    moveq   #0,%d0
    move.b  ACT_BANK,%d0
    move.l  #BANK_STRIDE,%d1
    muls.l  %d1,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    move.l  #PAT_STRIDE,%d2
    muls.l  %d2,%d1
    add.l   %d1,%d0
    lea     PAT_BASE,%a2
    adda.l  %d0,%a2
    move.l  #P_SCALE_MODE,%d6          | pattern offsets exceed a 16-bit displacement:
    move.l  #P_LEN_BYTE,%d7            | index them (ColdFire has no (d32,An))
|   d3 = master length of the NEW pattern (NORMAL: byte +0x8e53; PER-TRACK: word +0x8e50)
    tst.b   (%a2,%d6.l)
    bne.b   dc_pertrack_mlen
    moveq   #0,%d3
    move.b  (%a2,%d7.l),%d3
    bra.b   dc_mlen_got
dc_pertrack_mlen:
    move.l  #P_MLEN_WORD,%d0
    move.w  (%a2,%d0.l),%d3
    ext.l   %d3                        | -1 = INF -> no reduction
dc_mlen_got:
|   d4 = new_step = MASTER_STEP mod masterLen (only if masterLen >= 2; AR 0x4009926c)
    moveq   #0,%d4
    move.w  MASTER_STEP,%d4
    moveq   #2,%d0
    cmp.l   %d3,%d0
    bgt.b   dc_newstep_got             | masterLen < 2 (incl. INF -1): keep as is
    move.l  %d4,%d0
    divu.l  %d3,%d0                    | d0 = q
    muls.l  %d3,%d0
    sub.l   %d0,%d4                    | d4 = new_step
dc_newstep_got:
    move.l  %d4,RESUME_L               | low word 0x8000663a -> MASTER_STEP at the landing
|   per track: SNAP_STEP[t] = new_step mod len_t, SNAP_TICK[t] = 0
    lea     SNAP_STEP,%a0
    lea     SNAP_TICK,%a1
    moveq   #0,%d5                     | t
    lea     A_LEN(%a2),%a3             | audio length cursor
    lea     M_LEN(%a2),%a4             | MIDI length cursor
dc_loop:
    tst.b   (%a2,%d6.l)
    beq.b   dc_len_normal
    moveq   #8,%d0
    cmp.l   %d5,%d0
    ble.b   dc_len_midi
    moveq   #0,%d2
    move.b  (%a3),%d2                  | audio track t length
    bra.b   dc_len_got
dc_len_midi:
    moveq   #0,%d2
    move.b  (%a4),%d2                  | MIDI track t-8 length
    bra.b   dc_len_got
dc_len_normal:
    moveq   #0,%d2
    move.b  (%a2,%d7.l),%d2
dc_len_got:
    move.l  %d4,%d1                    | new_step
    moveq   #2,%d0
    cmp.l   %d2,%d0
    bgt.b   dc_step1                   | len_t < 2 -> step 0
    move.l  %d1,%d0
    divu.l  %d2,%d0
    muls.l  %d2,%d0
    sub.l   %d0,%d1                    | new_step mod len_t
    bra.b   dc_store
dc_step1:
    moveq   #0,%d1
dc_store:
    move.w  %d1,(%a0)+
    clr.b   (%a1)+
    moveq   #8,%d0
    cmp.l   %d5,%d0
    ble.b   dc_adv_midi
    lea     A_STRIDE(%a3),%a3
    bra.b   dc_next
dc_adv_midi:
    lea     M_STRIDE(%a4),%a4
dc_next:
    addq.l  #1,%d5
    moveq   #16,%d0
    cmp.l   %d5,%d0
    bne.b   dc_loop
|   hygiene: no held advance, no PER-TRACK resync pending, across the landing
    clr.w   HOLD_MASK
    clr.w   RESYNC80
    clr.w   RESYNC82
    clr.w   RESYNC84
|   V6.3 (Session 107): tell the UI -- and tell it the PATTERN, which is what the LED
|   predicate actually reads.  MEASURED this session (Ghidra + opcode-filtered image scan;
|   image base is 0x40000400, NOT 0x40000000 -- anchors 0x400a1f72 / the painter confirm it):
|
|     * The PTN-page painter FUN_4007afe8 @0x4007b182 paints "cued" (yellow) while
|       PEND_PAT != [0x100b14d0] && PEND_BANK == [0x80000002].
|     * 0x100b14d0 has exactly FOUR writers image-wide, and it is the project-RAM twin of
|       0x80000004 (the UI's "current pattern"); 0x80000002 twins 0x100b14ce (current bank).
|     * The UI task's message dispatcher is FUN_40061a94 (4618 B, no callers = a task entry);
|       it switches on msg[0]-1.  Case 0x10 == message 0x11 does
|       `0x100b14d0 = 0x80000004 = msg[1]`, refreshes the part index 0x100b14cf and repaints
|       (@0x400620ec-0x4006211a).  Case 0x14 == message 0x15 writes ONLY the bank pair
|       (0x80000002 / 0x100b14ce) and early-outs when the bank is unchanged.
|
|   So V6.2's {0x15, bank} post could never clear the yellow: that handler cannot reach
|   0x100b14d0.  {0x11, pattern} is the message that can, and stock posts it with exactly
|   this idiom from inside this same tick ISR at 0x400a40fc-0x400a4114 (and from
|   FUN_400a0570 / candidate_400a10d2, the other two ACT_PAT writers).  The kernel post is
|   stock-legal from the tick ISR; CLAUDE.md's rule is about UI PRIMITIVES from the engine
|   FRAME path, which this is not.
|
|   ORDER MATTERS: the bank message first.  Case 0x10's part-index refresh indexes the bank
|   base pointer 0x46c82456, and that pointer is what case 0x14 rewrites when the bank
|   changes -- so a bank-changing jump must land {0x15} before {0x11} or the part index is
|   read out of the old bank.
    move.b  ACT_BANK,%d0
    move.b  %d0,MSG_BANKPAT_ARG
    pea     MSG_BANKPAT
    pea     UI_QUEUE
    jsr     KPOST
    addq.l  #8,%sp
    move.b  ACT_PAT,%d0
    move.b  %d0,MSG_PAT_ARG
    pea     MSG_PAT
    pea     UI_QUEUE
    jsr     KPOST
    addq.l  #8,%sp
    moveq   #ST_LANDING,%d0
    move.b  %d0,dj_state
    .ifdef DJ_DIAG
    addq.l  #1,dj_cnt_land
    .endif
    rts

| ================= Hook N @ 0x400a221c -- no MIDI START on a jump =================
| Replaces `tst.b (0x8000002a).l` (6 B); stock's next instruction is `beq.b` (skip the
| 0xFA send when the byte is 0).  While LANDING: consume the state and give it Z=1
| (dj_zero is a 0 byte).  D0 is DEAD here on both of stock's branches -- the send path
| and the skip path both reach `move.w (0x80006514).l,%d0` at 0x400a2230 -- so it is
| the one register this unsaved hook may use.
    .global dj_nofa
dj_nofa:
    move.b  dj_state,%d0
    cmpi.b  #ST_LANDING,%d0
    bne.b   dn_stock
    clr.b   dj_state
    tst.b   dj_zero                    | Z = 1 -> "do not send"
    rts
dn_stock:
    tst.b   MIDI_SEND                  | displaced original
    rts

| ================= [PTN] release -- close the toast (Session 61-63, kind=jmp) =================
    .global dj_ptnrel
dj_ptnrel:
    tst.l   NOTIFY_HANDLE
    beq.b   dpr_done
    moveq   #1,%d0
    move.l  %d0,NOTIFY_COUNTDOWN
dpr_done:
    pea     0x400bf0f2                  | displaced original -- the value MUST survive on
    jmp     PTN_LAYER_REL_RESUME        | the stack (see V4's dj_ptnrel history)

| ================= cave state =================
    .align 2
dj_state:  .byte ST_IDLE               | 0 idle / 1 armed (we own LAND_CNTDN) / 2 landing
dj_pcpat:  .byte -1                    | cued pattern the PC was last sent for
dj_zero:   .byte 0                     | constant 0 for Hook N's flag trick
    .byte 0
    .ifdef DJ_DIAG
    .align 2
dj_cnt_arm:  .long 0
dj_cnt_land: .long 0
dj_cnt_req:  .long 0
dj_obs_c:    .byte 0
dj_obs_t:    .byte 0
dj_obs_h:    .byte 0
dj_obs_g:    .byte 0
dj_diag_fmt:
    .asciz  "A%d L%d R%d C%d T%d H%d G%d"
    .align 2
dj_diag_buf:
    .space  64
    .endif
