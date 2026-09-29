| =========================================================================================
| DIRECT JUMP V7.0.1 (Session 108, 2026-09-27) -- CLOCK-LOCKED LANDING + stock's switch hand-off.
| V6.4 (patch_directjump_v6.s, frozen) is the OT<->AR PARITY build. V7 changes ONE input of
| V6's hardware-proven landing: WHERE the incoming pattern lands.  V6/AR derive it from the
| OUTGOING pattern's master counter (0x800065b2, which wraps with that pattern) -> whole-step
| shifts, measured by tools/cmp_reflock.py.  V7 lands every track at the position it would
| hold had the incoming pattern played since START (the author's spec, see
| reference/handoffs/DIRECTJUMP_V7_DESIGN.md), computed from an absolute clock-tick counter:
|
|   master cycle C = mlen*tps_M (PER-TRACK INF: none);   u  = (T + tps_M - 1) mod C
|   t' = u - (tps_M - 1)                                   (time within the master cycle)
|   master step = u / tps_M      track step = (t' / tps_t) mod len_t   (snapshot values)
|
| (model verified tick-for-tick against the engine's own never-switched runs by
| tools/model_reflock.py).  V7.0 lands only on a tick where EVERY track of the incoming
| pattern is at a window start (t' = 0 mod lcm(all tps)), so stock's landing -- unchanged
| since V6 -- schedules every track exactly; uniform-scale patterns land on the next master
| step as before.  Plus: primacy purge of the outgoing pattern's pending events, and the
| reload fix-up the reference requires.  Nothing touches the wrap-change body.
| =========================================================================================
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
    .equ MSG_PART,    0x400d8169        | message 0x14: {code, part} -- stock's wrap-change post @0x400a459a
    .equ MSG_PART_ARG,0x400d816a        |   (V7.0.1: V7.0 never posted it -> the Part never changed on a jump)
    .equ P_PART,      0x8e57            | pattern blob: the pattern's Part (stock reads 0x400eb036+off+1)
    .equ T_SILENT,    3                 | track record +3 (audio +0x53, MIDI +0x48fb): START SILENT (1 / -1 = default)
    .equ SILENT_DEF,  0x8000004f        | the default START SILENT is used when a track's byte is -1
    .equ ENG_AFLAGS,  0x46c7fa80        | audio engine pattern-change flags (bit0|bit1 + track bits 8..15)
    .equ ENG_ATIME,   0x800019e4        | audio engine: when the switch takes effect (sample clock)
    .equ ENG_ABANK,   0x46c7ff40        | audio engine: bank to apply
    .equ ENG_APART,   0x46c7ff62        | audio engine: Part to apply (-> light Part apply 0x40009e00)
    .equ ENG_MFLAGS,  0x46c7a120        | MIDI engine pattern-change flags (3 + track bits 8..15)
    .equ ENG_MTIME1,  0x46c76aa6        | MIDI engine switch times (MIDI clock domain)
    .equ ENG_MFLAG,   0x46c76a22
    .equ ENG_MTIME2,  0x46c76aaa
    .equ ENG_MBANK,   0x46c7a850
    .equ ENG_MPART,   0x46c7a934
    .equ COND_RESET,  0x400a539c        | FUN_400a539c(track | -1): reset A:B cycle counters / pending FILL
    .equ MSG_PAT,     0x400d816b        | message 0x11: {code, pattern, 1} -- stock's WRAP-CHANGE
    .equ MSG_PAT_ARG, 0x400d816c        |   post @0x400a4b9a.  NOT 0x400d8164 -- see dl_commit.

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
    .equ ST_FIXUP,   3                  | V7: the tick after a landing -> reload fix-up
|   V7 -- measured layout (stock landing loader 0x400a2124-0x400a21e2, Session 107/108):
    .equ TRK_SCALE,  0x8000663e         | byte[16] live per-track scale index
    .equ RELOAD,     0x800065d3         | byte[16] per-track reload (0 / catch-up in the ref)
    .equ P_SCALE_N,  0x8e54             | NORMAL: pattern scale index (master + every track)
    .equ P_MSCALE,   0x8e52             | PER-TRACK: master scale index
    .equ T_LEN,      0                  | track record (+base_t): length
    .equ T_SCL,      1                  |   PER-TRACK scale index
    .equ T_FLAG,     4                  |   !=0: stock keeps the LIVE scale (does not reload)
    .equ SCLK,       0x4610757c         | audio-domain sample clock (fire-time base)
    .equ MCLK,       0x46107564         | MIDI-domain clock (MIDI fire-time base)
    .ifndef DJ_TOFS
    .equ DJ_TOFS,    0                  | t of this ISR = dj_T + DJ_TOFS.  MEASURED 0 (rl_v70: t - dj_T == 0
                                        | at all 301 ticks); the first build's guess of 1 landed
                                        | every jump exactly one tick early (oracle: d = +1 tick)
    .endif

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
|   V7: dj_T counts EVERY running tick, DJ on or off (cave RAM only -- stock-invisible), so
|   a DIRECT JUMP turned on mid-song still knows where START was.  0 while stopped.
    moveq   #1,%d0
    cmp.l   TRANSPORT_L,%d0
    beq.b   dt_run
    clr.l   dj_T
    bra.b   dt_done
dt_run:
    addq.l  #1,dj_T
dt_done:
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
    beq.w   dl_idle
    cmpi.b  #ST_FIXUP,%d0
    bne.b   dl_notfix
    bsr.w   dl_fixup                   | the tick after a landing: reload := reference value
    clr.b   dj_state
    bra.w   dl_done
dl_notfix:
    cmpi.b  #ST_ARMED,%d0
    bne.w   dl_done                    | LANDING is consumed by Hook N; nothing here
|   V7.0.1: the cue changed while we wait (re-cue, cue back to the playing pattern, or -1)?
|   Take our countdown back and handle the new cue on this same tick.  Measured before the fix
|   (pc_v701_fast): cue 4 then 5 -> PC(4) sent, 5 landed; cue 3 then back to 5 -> PC(3) sent,
|   3 never played, and 5 re-landed onto itself.  The landing never copies a stale or -1 cue.
    move.b  PEND_PAT,%d0
    cmp.b   dj_armpat,%d0
    bne.b   da_recue
    move.b  PEND_BANK,%d0
    cmp.b   dj_armbank,%d0
    beq.b   da_same
da_recue:
    clr.b   LAND_CNTDN                 | ours: stock then sees 0 and does not land
    clr.b   dj_state
    bra.w   dl_idle
da_same:
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
    bne.b   dl_real
|   cued == active.  V7.0.1: if our last Program Change named a pattern that is NOT playing (a
|   cue was cancelled back to the playing pattern), re-send the playing pattern's so external
|   gear follows what the OT actually plays.  After a normal landing the last PC IS the playing
|   pattern, so nothing is sent; dl_clear then resets the latch.
    move.b  dj_pcpat,%d0
    cmpi.b  #-1,%d0
    beq.w   dl_clear
    cmp.b   ACT_PAT,%d0
    bne.b   dl_pcfix
    move.b  dj_pcbank,%d0
    cmp.b   ACT_BANK,%d0
    beq.w   dl_clear
dl_pcfix:
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    moveq   #0,%d0
    move.b  ACT_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     PC_SEND
    addq.l  #8,%sp
    bra.w   dl_clear
dl_real:
    .ifdef DJ_DIAG
    addq.l  #1,dj_cnt_req
    .endif
|   MIDI Program Change once per distinct cued pattern (what every DJ build since v1 did)
    move.b  PEND_PAT,%d0
    cmp.b   dj_pcpat,%d0
    bne.b   dl_pcsend
    move.b  PEND_BANK,%d0
    cmp.b   dj_pcbank,%d0
    beq.b   dl_arm                     | V7.0.1: latch on pattern AND bank
dl_pcsend:
    move.b  PEND_PAT,%d0
    move.b  %d0,dj_pcpat
    move.b  PEND_BANK,%d0
    move.b  %d0,dj_pcbank
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
|   V7.0: the incoming pattern's parameters, then the first tick t_L >= this one whose
|   master-cycle time t' is a multiple of L = lcm(tps_M, every track's tps): every track at
|   a window start, the master on a step boundary -> stock's landing is exact there.
    moveq   #0,%d0
    move.b  PEND_BANK,%d0
    moveq   #0,%d1
    move.b  PEND_PAT,%d1
    bsr.w   dj_blob                    | a2 = incoming pattern blob
    bsr.w   dj_bparams
    move.l  dj_T,%d7
    addi.l  #DJ_TOFS,%d7               | d7 = t of this ISR
    moveq   #0,%d6                     | d6 = candidate offset k-1
da_scan:
    move.l  %d7,%d0
    add.l   %d6,%d0
    bsr.w   dj_tprime                  | d0 = t' (signed) for tick d0
    tst.l   %d0
    blt.b   da_next
    move.l  dj_L,%d1
    move.l  %d0,%d2
    divu.l  %d1,%d2
    muls.l  %d1,%d2
    cmp.l   %d2,%d0
    beq.b   da_found
da_next:
    addq.l  #1,%d6
    cmpi.l  #120,%d6
    blt.b   da_scan
    bra.w   dl_done                    | (unreachable: L <= 96) -- retry next tick
da_found:
    move.b  PEND_PAT,%d0               | V7.0.1: what this arm is for (re-cue detection)
    move.b  %d0,dj_armpat
    move.b  PEND_BANK,%d0
    move.b  %d0,dj_armbank
    move.l  %d6,%d1
    addq.l  #1,%d1                     | k = offset + 1: stock decrements below us
    move.b  %d1,LAND_CNTDN
    .ifdef DJ_DIAG
    addq.l  #1,dj_cnt_arm
    .endif
|   V6.4: k == 1 means this very tick lands (stock's same-tick decrement would otherwise run
|   the zero-landing off the stale transport-start snapshot and wedge dj_state).
    cmpi.l  #1,%d1
    bne.b   dl_arm2
    bsr.w   dl_commit
    bra.w   dl_done
dl_arm2:
    moveq   #ST_ARMED,%d0
    move.b  %d0,dj_state
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
|   V7.0: the reference position of the incoming pattern at THIS tick (see header).
    bsr.w   dj_bparams                 | a2 = ACT blob (set above) -> tps/len/C/L tables
    move.l  dj_T,%d7
    addi.l  #DJ_TOFS,%d7               | d7 = t_L
    move.l  %d7,dj_tland
    move.l  dj_tpsM,%d3
    move.l  %d7,%d0
    add.l   %d3,%d0
    subq.l  #1,%d0                     | u = t + tps_M - 1
    move.l  dj_C,%d1
    beq.b   dc_noc                     | INF: no master cycle
    move.l  %d0,%d2
    divu.l  %d1,%d2
    muls.l  %d1,%d2
    sub.l   %d2,%d0                    | u mod C
dc_noc:
    move.l  %d0,%d4
    divu.l  %d3,%d4                    | master step = u / tps_M
    move.l  %d4,RESUME_L
    move.l  %d0,%d5
    sub.l   %d3,%d5
    addq.l  #1,%d5                     | d5 = t' (>= 0: t' = 0 mod L by construction)
    lea     SNAP_STEP,%a0
    lea     SNAP_TICK,%a1
    lea     dj_tps,%a3
    lea     dj_len,%a4
    moveq   #16,%d6
dc_loop:
    moveq   #0,%d1
    move.b  (%a3)+,%d1                 | tps_t
    move.l  %d5,%d0
    divu.l  %d1,%d0                    | t' / tps_t
    moveq   #0,%d2
    move.b  (%a4)+,%d2                 | len_t
    moveq   #2,%d1
    cmp.l   %d2,%d1
    bgt.b   dc_step0                   | len_t < 2 -> step 0
    move.l  %d0,%d1
    divu.l  %d2,%d1
    muls.l  %d2,%d1
    sub.l   %d1,%d0                    | mod len_t
    bra.b   dc_store
dc_step0:
    moveq   #0,%d0
dc_store:
    move.w  %d0,(%a0)+
    clr.b   (%a1)+
    subq.l  #1,%d6
    bne.b   dc_loop
    bsr.w   dj_purge                   | primacy: the outgoing pattern's pending events go
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
|   0x100b14d0.  {0x11, pattern} is the message that can.  The kernel post is stock-legal
|   from the tick ISR; CLAUDE.md's rule is about UI PRIMITIVES from the engine FRAME path,
|   which this is not.
|
|   CONFIRMED AT RUNTIME (tools/diag_led_pend.py, this session -- the handoff 2.3 experiment).
|   Stock, DJ off, cue at t40 committing at its natural wrap t90:
|       t90  ACT_PAT <- 4               pc=0x400a44d0     (the wrap swap)
|       t90  POST 0x400d8167 15 00 14   ret=0x400a4568    ({0x15, bank})
|       t90  POST 0x400d816b 11 04 01   ret=0x400a4b9a    ({0x11, pat})
|       t90  0x100b14d0 <- 4            pc=0x4006210e     (handler case 0x10) -> LED goes red
|   V6.2, DJ on, landings at t41 / t143: the {0x15} post ONLY, and 0x100b14d0 stays 3 for
|   the whole run -- the reported defect, reproduced in the emulator.
|
|   TEMPLATE CHOICE MATTERS.  There are two {0x11} templates and they differ in byte 2,
|   which the handler branches on: byte2 == 0 -> it also calls FUN_4009c550(), which
|   re-applies the TEMPO (0x80001814/18, from the pattern's own +0x8e58 field when
|   per-pattern tempo is enabled); byte2 != 0 -> it does not.
|       0x400d8164 = {0x11, arg@0x400d8165, 0x00}  -- the UI / arranger / reset posters
|       0x400d816b = {0x11, arg@0x400d816c, 0x01}  -- stock's WRAP-CHANGE poster
|   A jump is a wrap-change analogue, not a UI pattern-set, so we use 0x400d816b and leave
|   the tempo alone.  Posting 0x400d8164 here would re-apply tempo on every landing -- a
|   deviation from stock that nothing asked for.
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
    bsr.w   dj_handoff                 | V7.0.1: the rest of stock's real-switch hand-off
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
    moveq   #ST_FIXUP,%d0              | V7: next tick fixes reload (D0 dead here, see above)
    move.b  %d0,dj_state
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

| ================= V7.0.1: stock's real-switch hand-off, replayed at the landing ============
| Stock's wrap-change, on a REAL switch (d6: PEND != ACT), does all of this between its {0x15}
| and {0x11} posts (0x400a4568-0x400a4856).  V7.0 skipped the wrap-change and with it every one
| of these -- measured: a jump into a pattern on another Part set the UI's current Part but the
| engine never applied it (stock: light Part apply 0x40009e00 from 0x4000b1dc, on time).  Times:
| stock stamps "now + one master step" because it switches one step ahead of the audible
| switch; V7's landing sounds the new pattern's first step NOW, so every time here is "now".
| a2 = the ACT (incoming) pattern blob, preserved by the caller (KPOST keeps a2).
dj_handoff:
|   {0x14, part} -- the UI side of the Part change (dispatcher case 0x13)
    move.l  #P_PART,%d1
    move.b  (%a2,%d1.l),%d0
    move.b  %d0,MSG_PART_ARG
    pea     MSG_PART
    pea     UI_QUEUE
    jsr     KPOST
    addq.l  #8,%sp
|   audio engine: flags = bit0 | bit1 | START-SILENT tracks (bits 8..15), 0x400a45a8-0x400a463a
    moveq   #3,%d4
    move.l  #A_LEN+T_SILENT,%d3        | audio track 0 record +3 (= +0x53)
    move.l  #A_STRIDE,%d6
    bsr.w   ho_bits
    move.l  %d4,ENG_AFLAGS
    move.l  SCLK,%d0                   | stock: a3 + sclk; V7 switches now
    move.l  %d0,ENG_ATIME
    move.b  ACT_BANK,%d0
    move.b  %d0,ENG_ABANK
    move.l  #P_PART,%d1
    move.b  (%a2,%d1.l),%d0
    move.b  %d0,ENG_APART
|   MIDI engine: flags = 3 | START-SILENT tracks, 0x400a469e-0x400a4708
    moveq   #3,%d4
    move.l  #M_LEN+T_SILENT,%d3        | MIDI track 0 record +3 (= +0x48fb)
    move.l  #M_STRIDE,%d6
    bsr.w   ho_bits
    move.l  %d4,ENG_MFLAGS
|   MIDI switch times, 0x400a470a-0x400a47b2 (d5 = 0): the offsets depend on the MIDI clock
|   settings exactly as in stock
    moveq   #0,%d5                     | d5 = 1: the "fast" branch
    tst.b   0x80001860
    bne.b   ho_mt
    move.b  0x80000028,%d0
    btst    #0,%d0                     | (ColdFire: no byte AND)
    beq.b   ho_mt
    tst.l   0x46104ca8
    beq.b   ho_mt
    moveq   #1,%d5
ho_mt:
    move.l  MCLK,%d0
    tst.l   %d5
    bne.b   ho_mt1
    addi.l  #12600,%d0
ho_mt1:
    move.l  %d0,ENG_MTIME1
    moveq   #1,%d0
    move.l  %d0,ENG_MFLAG
    move.l  MCLK,%d0
    tst.l   %d5
    beq.b   ho_mt2
    subi.l  #16800,%d0
    bra.b   ho_mt3
ho_mt2:
    subi.l  #4200,%d0
ho_mt3:
    move.l  %d0,ENG_MTIME2
    move.b  ACT_BANK,%d0
    move.b  %d0,ENG_MBANK
    move.l  #P_PART,%d1
    move.b  (%a2,%d1.l),%d0
    move.b  %d0,ENG_MPART
|   conditional trigs start fresh, as on every stock switch (0x400a484c-0x400a4856)
    pea     -1
    jsr     COND_RESET
    addq.l  #4,%sp
    rts

| ho_bits: OR (1 << (t+8)) into d4 for each of 8 tracks whose START SILENT byte is 1, or -1
| with the default set.  d3 = offset of track 0's byte in the blob, d6 = record stride.
ho_bits:
    moveq   #8,%d5
ho_lp:
    move.b  (%a2,%d3.l),%d0
    beq.b   ho_nx
    cmpi.b  #1,%d0
    beq.b   ho_set
    cmpi.b  #-1,%d0
    bne.b   ho_nx
    tst.b   SILENT_DEF
    beq.b   ho_nx
ho_set:
    moveq   #1,%d0
    lsl.l   %d5,%d0
    or.l    %d0,%d4
ho_nx:
    add.l   %d6,%d3
    addq.l  #1,%d5
    moveq   #16,%d0
    cmp.l   %d5,%d0
    bne.b   ho_lp
    rts

| ================= V7 helpers (all called from dj_land's saved-register context) ==========
| dj_blob: d0 = bank, d1 = pattern -> a2 = pattern blob
dj_blob:
    move.l  #BANK_STRIDE,%d2
    muls.l  %d2,%d0
    move.l  #PAT_STRIDE,%d2
    muls.l  %d2,%d1
    add.l   %d1,%d0
    lea     PAT_BASE,%a2
    adda.l  %d0,%a2
    rts

| dj_bparams: a2 = blob -> dj_tpsM, dj_C (0 = INF), dj_L, dj_tps[16], dj_len[16].  Scales
| are resolved EXACTLY as stock's landing loader will load them (0x400a2124-0x400a21e2):
| a track whose flag byte (+4) is non-zero keeps its LIVE scale.
dj_bparams:
    lea     LEN_TBL,%a0
    move.l  #P_SCALE_MODE,%d0
    move.b  (%a2,%d0.l),%d7            | d7 = mode (0 NORMAL)
    moveq   #0,%d1
    tst.b   %d7
    bne.b   bp_pt
    move.l  #P_SCALE_N,%d0
    move.b  (%a2,%d0.l),%d1
    move.l  (%a0,%d1.l*4),%d3          | tps_M
    move.l  #P_LEN_BYTE,%d0
    moveq   #0,%d4
    move.b  (%a2,%d0.l),%d4            | mlen
    bra.b   bp_c
bp_pt:
    move.l  #P_MSCALE,%d0
    move.b  (%a2,%d0.l),%d1
    move.l  (%a0,%d1.l*4),%d3
    move.l  #P_MLEN_WORD,%d0
    move.w  (%a2,%d0.l),%d4
    ext.l   %d4
    bgt.b   bp_c
    moveq   #0,%d4                     | INF (-1) / 0 -> no master cycle
bp_c:
    move.l  %d3,dj_tpsM
    move.l  %d4,%d0
    muls.l  %d3,%d0
    move.l  %d0,dj_C                   | C = mlen * tps_M (0 = INF)
    move.l  %d3,%d5                    | d5 = running lcm
    lea     dj_tps,%a3
    lea     dj_len,%a4
    lea     TRK_SCALE,%a5
    moveq   #0,%d6                     | t
bp_loop:
    moveq   #8,%d0
    cmp.l   %d6,%d0
    ble.b   bp_midi
    move.l  #A_STRIDE,%d0
    muls.l  %d6,%d0
    addi.l  #A_LEN,%d0
    bra.b   bp_base
bp_midi:
    move.l  %d6,%d0
    subq.l  #8,%d0
    move.l  #M_STRIDE,%d1
    muls.l  %d1,%d0
    addi.l  #M_LEN,%d0
bp_base:
    lea     (%a2,%d0.l),%a1            | a1 = track record base
    tst.b   T_FLAG(%a1)
    beq.b   bp_blobscl
    moveq   #0,%d1
    move.b  (%a5,%d6.l),%d1            | flag set: stock keeps the LIVE scale
    bra.b   bp_scl
bp_blobscl:
    moveq   #0,%d1
    tst.b   %d7
    bne.b   bp_ptscl
    move.l  #P_SCALE_N,%d0
    move.b  (%a2,%d0.l),%d1
    bra.b   bp_scl
bp_ptscl:
    move.b  T_SCL(%a1),%d1
bp_scl:
    move.l  (%a0,%d1.l*4),%d2          | tps_t
    move.b  %d2,(%a3)+
    tst.b   %d7
    bne.b   bp_ptlen
    move.b  %d4,(%a4)+                 | NORMAL: every track shares the pattern length
    bra.b   bp_lcm
bp_ptlen:
    move.b  T_LEN(%a1),(%a4)+
bp_lcm:
|   lcm(d5, d2) = d5 / gcd * d2
    move.l  %d5,%d0
    move.l  %d2,%d1
bp_gcd:
    tst.l   %d1
    beq.b   bp_gcdok
    move.l  %d0,%d3
    divu.l  %d1,%d3
    muls.l  %d1,%d3
    sub.l   %d3,%d0                    | d0 = d0 mod d1
    move.l  %d0,%d3                    | (ColdFire has no exg)
    move.l  %d1,%d0
    move.l  %d3,%d1
    bra.b   bp_gcd
bp_gcdok:
    divu.l  %d0,%d5
    muls.l  %d2,%d5
    addq.l  #1,%d6
    moveq   #16,%d0
    cmp.l   %d6,%d0
    bne.w   bp_loop
    move.l  %d5,dj_L
    rts

| dj_tprime: d0 = tick t -> d0 = t' = ((t + tps_M - 1) mod C) - (tps_M - 1)  (signed)
dj_tprime:
    move.l  dj_tpsM,%d3
    add.l   %d3,%d0
    subq.l  #1,%d0
    move.l  dj_C,%d1
    beq.b   tp_noc
    move.l  %d0,%d2
    divu.l  %d1,%d2
    muls.l  %d1,%d2
    sub.l   %d2,%d0
tp_noc:
    sub.l   %d3,%d0
    addq.l  #1,%d0
    rts

| dj_purge: cancel every still-pending event (fire time >= now) in the two audio tables and
| the MIDI table, with stock's own cancellation (0x400a43b6-0x400a4464): clear the record
| long and the slot's bit in the track mask; the fire time itself is left alone.
dj_purge:
    move.l  SCLK,%d5
    lea     0x80001904,%a0
    lea     0x46c7e998,%a1
    lea     0x46c7fe44,%a3
    bsr.b   pg_table
    lea     0x80001984,%a0
    lea     0x46c7faa4,%a1
    lea     0x46c7fe8c,%a3
    bsr.b   pg_table
    move.l  MCLK,%d5
    lea     0x46c76a26,%a0
    lea     0x46c769c0,%a1
    lea     0x46c77be2,%a3
|   fall through
| pg_table: a0 = times[t + slot*8] (longs), a1 = records (same layout), a3 = mask[8], d5 = now
pg_table:
    moveq   #0,%d6                     | track
pg_trk:
    moveq   #0,%d4                     | slot
pg_slot:
    moveq   #0,%d0
    move.b  (%a3,%d6.l),%d0
    btst    %d4,%d0
    beq.b   pg_next
    move.l  %d4,%d1
    lsl.l   #3,%d1
    add.l   %d6,%d1                    | idx = track + slot*8
    move.l  (%a0,%d1.l*4),%d2
    sub.l   %d5,%d2
    bmi.b   pg_next                    | already due: leave it (stock's boundary rule)
    clr.l   (%a1,%d1.l*4)
    bclr    %d4,%d0
    move.b  %d0,(%a3,%d6.l)
pg_next:
    addq.l  #1,%d4
    moveq   #3,%d0
    cmp.l   %d4,%d0
    bne.b   pg_slot
    addq.l  #1,%d6
    moveq   #8,%d0
    cmp.l   %d6,%d0
    bne.b   pg_trk
    rts

| dl_fixup: the tick after a landing.  Stock's landing leaves reload = tps_t - 1 (it drives
| the landing's immediate first fire); the reference holds 0 until the first master wrap
| since START, then the wrap-change catch-up max(0, tps_t - tps_M).  Nothing reads reload
| between here and the next wrap (cntdn idle, first-fire mask consumed), so this is for the
| state-equality proof -- and it makes the next wrap start from the reference's value.
dl_fixup:
    lea     LEN_TBL,%a0
    moveq   #0,%d0
    move.b  SCALE_IX,%d0
    move.l  (%a0,%d0.l*4),%d3          | tps_M (live, as loaded by the landing)
    moveq   #0,%d5                     | "past the first master wrap"
    move.l  dj_C,%d1
    beq.b   fx_go                      | INF: never wraps
    sub.l   %d3,%d1
    addq.l  #1,%d1                     | first wrap sample tick = C - tps_M + 1
    cmp.l   dj_tland,%d1
    bgt.b   fx_go
    moveq   #1,%d5
fx_go:
    lea     TRK_SCALE,%a1
    lea     RELOAD,%a2
    moveq   #0,%d6
fx_loop:
    moveq   #0,%d1
    tst.l   %d5
    beq.b   fx_store
    moveq   #0,%d0
    move.b  (%a1,%d6.l),%d0
    move.l  (%a0,%d0.l*4),%d1
    sub.l   %d3,%d1                    | tps_t - tps_M
    bpl.b   fx_store
    moveq   #0,%d1
fx_store:
    move.b  %d1,(%a2,%d6.l)
    addq.l  #1,%d6
    moveq   #16,%d0
    cmp.l   %d6,%d0
    bne.b   fx_loop
    rts

    .align 2
dj_state:  .byte ST_IDLE               | 0 idle / 1 armed (we own LAND_CNTDN) / 2 landing / 3 fixup
dj_pcpat:  .byte -1                    | cued pattern the PC was last sent for
dj_zero:   .byte 0                     | constant 0 for Hook N's flag trick
dj_pcbank: .byte -1                    | V7.0.1: bank the last PC was sent for
dj_armpat: .byte -1                    | V7.0.1: the cue this arm is for
dj_armbank: .byte -1
    .align 2
dj_T:      .long 0                     | V7: running clock ticks since START (0 while stopped)
dj_tland:  .long 0                     | V7: t of the last landing
dj_tpsM:   .long 0                     | V7: incoming pattern's master ticks/step
dj_C:      .long 0                     |     master cycle in ticks (0 = INF)
dj_L:      .long 0                     |     lcm of every tps (landing grid)
dj_tps:    .space 16                   |     per-track ticks/step as stock will load them
dj_len:    .space 16                   |     per-track length
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
