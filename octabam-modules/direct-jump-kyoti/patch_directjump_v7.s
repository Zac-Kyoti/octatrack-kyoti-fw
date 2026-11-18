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
| V7.0.2 (2026-11-13, WIP; the user's rule from Clyps): a jump no longer restarts the trig
| conditions (COND_RESET(-1)); dj_cond puts every A:B counter where the never-switched
| reference holds it (graded by tools/cmp_reflock.py --cond).
| V7.1 (2026-11-13, WIP; the user's decision, Clyps CL26's fix): a jump lands one tick BEFORE the
| boundary (the next tick's t' = 0 mod L) and fires for it -- every reload and the master tick one
| less after stock's loader (ahead 2), the engines' switch one tick ahead, and dj_purge a tick
| ahead with a half-tick margin.  V7.0.x landed ON the boundary tick, where the outgoing boundary
| event tied the sample clock exactly (+0.0000 tick) and only `bmi` decided it.  The new step
| fires exactly where the old boundary event would have (REF-LOCK unchanged).
| V7.2.2 (2026-11-15, WIP, hardware A/B): the tracks the switch will silence are released with stock's
| note-off on the tick after the landing (dj_relsil), so SILENCE TRACKS' hard kill lands on faded voices.
| V7.1.1 (2026-11-13): stock's wrap-change never takes a cue DIRECT JUMP has armed (dj_hide).
| V7.2 (2026-11-13, WIP): each track's own Part reaches the engine with its first sounding trig of
| the incoming pattern (dj_sparm .. dj_mapply); the jump keeps the Part-wide items.
| V7.3 (2026-11-16, WIP; the author's decision, option (b)): the time origin is the LAST RESTART -- PLAY, or
| any stock pattern switch (DJ off, a chain, the arranger: whatever runs stock's `jsr COND_RESET` at
| 0x400a4850).  dj_swres re-bases dj_T there, so a jump lands -- and sets its trig conditions -- as if the
| incoming pattern had started at that switch.  RELOAD_FROM_PROJECT and Clyps count from the same moment.
| =========================================================================================
| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| DIRECT JUMP V6 -- Session 105 (2026-09-26).  the AR's DIRECT JUMP behaviour, reproduced through OT's OWN landing.
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

| Where DJ_MODE lives. DEFAULT: in the cave (DJ_MODE_IN_CAVE) -- the KYOTI V1.0 image and
| the octabam module, whose build cannot pass assembler symbols. tools/build_direct_jump_kyoti.py
| (the standalone V7.0.1 image, promoted with the word at 0x800000d8) passes DJ_MODE_IN_RAM=1.
    .ifndef DJ_MODE_IN_RAM
    .ifndef DJ_MODE_IN_CAVE
    .equ DJ_MODE_IN_CAVE, 1
    .endif
    .endif

    .ifndef DJ_MODE_IN_CAVE
    .equ DJ_MODE,   0x800000d8          | state word (0 = OFF/stock, 1 = ON); power-on 0
    .endif                              | DJ_MODE_IN_CAVE (the combined KYOTI image): see the
                                        | state block at the end -- MUTE MODE widens the ANDY
                                        | restore over 0x800000d8 (reference/MERGE.md B1)
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
|   LEN_TBL holds the seven scales at 0..6 (index 2 = 1x); what follows is other data, and
|   index 12 is 0. Stock can leave a garbage scale byte (0xff) for a MIDI track under PER
|   TRACK scale (BATCH_BUGFIXES bug 1, MIDI_PLAYS_FREE_FIX), and LEN_TBL[0xff]'s low byte is
|   0 -- a divide by zero in the tick handler (Sam Banks' static review, octabam #561).
|   Every lookup below takes a scale byte only if it is <= SCALE_MAX: a track's out-of-range
|   scale reads as the master's, the master's as 1x.
    .equ SCALE_MAX, 6
    .equ SCALE_1X,  2
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
|                                         (V7.3: stock's switch calls it at 0x400a4850 -> dj_swres)
    .equ P_CHAINQ,    0x8e56            | pattern blob: CHAIN AFTER index (signed; < 0 = the project's)
    .equ PROJ_QUANT,  0x8000004e        | byte: the project's CHAIN AFTER index
    .equ QUANT_TBL,   0x400d80dc        | long[]: CHAIN AFTER length in master steps (<= 0 = off)
    .equ END_STEP,    0x8000662c        | long: a pattern-end override step (-1 = none), stock 0x400a431a
    .equ STOP_END,    0x8000667e        | byte: stop at the next master step (stock 0x400a4006)
|   V7.2 -- the incoming Part per track at its first sounding trig:
    .equ TRK_APPLY,   0x40001f18        | (bank, part, t): one audio track's Part values -> the engine
    .equ PART_OFF,    0x8ed80           | a bank's 4 Parts, after its 16 pattern blobs
    .equ PARTSZ,      0x18b2
    .equ MENG,        0x46c76dc0        | 8 x 68 B: a MIDI track's page values (32) + setup (36)
    .equ MDES,        0x46c7738c        | 24 x 16 B: the MIDI LFOs' designer waves
    .equ MSLP,        0x46c7750c        | 24 x u16: ... their slopes
    .equ MBANK,       0x8000666e        | byte[8] bank / [8+m] Part the MIDI track's values came from
    .equ MZERO,       0x8000664e        | long[8], cleared by stock's apply
    .equ M_REC,       0x48d0            | pattern blob: MIDI track 0's record (+ m * M_STRIDE)
    .equ NOTE_OFF,    0x40008f84        | (t): stock's note-off -- the release with the DSP's declick (STOP)
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
    .equ TICK_A,     0x285ff0           | one sequencer tick in SCLK units (44100*60: tempo-independent)
    .equ TICK_M,     16800              | one sequencer tick in MCLK units (stock's 0x400a4728)
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
    bsr.w   dj_unhide                  | V7.1.1: the cue dj_hide held back last tick
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
|   V7.3: ... where the LAST RESTART was: PLAY, or stock's last pattern switch (dj_swres re-bases it).
    moveq   #1,%d0
    cmp.l   TRANSPORT_L,%d0
    beq.b   dt_run
    clr.l   dj_T
    clr.l   dj_rsm                     | V7.3: stopped -> the next origin is PLAY
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
    bsr.w   dj_relsil                  | V7.2.2: release the tracks the switch will silence
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
    tst.b   dj_spn
    beq.b   1f
    bsr.w   dj_spflush                 | V7.2: STOP (or DJ off) publishes what still waits, at once
1:  move.b  dj_state,%d0
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
    .ifdef DJ_SELFHOOK
|   KYOTI with Clyps: cued == active, but Clyps asks for a jump to the playing pattern as it was
|   loaded (ORIG PTN+PART, the user 2026-11-04) -> arm as for any cue (dj_selfvec, below)
    move.l  dj_selfvec,%d0
    beq.b   di_nself
    movea.l %d0,%a0
    movea.l (%a0),%a0                  | [0] -> d0 != 0: a self-jump is requested
    jsr     (%a0)
    tst.l   %d0
    bne.w   dl_real
di_nself:
    .endif
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
|   V7.3: t' is counted from the last restart (dj_T; dj_tprime adds dj_rsm master steps).
    moveq   #0,%d0
    move.b  PEND_BANK,%d0
    moveq   #0,%d1
    move.b  PEND_PAT,%d1
    bsr.w   dj_blob                    | a2 = incoming pattern blob
    .ifdef DJ_SELFHOOK
    bsr.w   dj_selfblob                | a self-jump: the pattern as it was loaded (Clyps)
    .endif
    bsr.w   dj_bparams
    move.l  dj_T,%d7
    addi.l  #DJ_TOFS,%d7               | d7 = t of this ISR
    moveq   #0,%d6                     | d6 = candidate offset k-1
da_scan:
    move.l  %d7,%d0
    add.l   %d6,%d0
    addq.l  #1,%d0                     | V7.1: the NEXT tick's t' -- a jump lands one tick before
    bsr.w   dj_tprime                  | the boundary (Clyps CL26); d0 = t' (signed) of tick d0
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
    tst.b   dj_spn
    beq.b   1f
    bsr.w   dj_spdo                    | V7.2: the tracks whose first trig is due now get their Part
1:  move.b  dj_state,%d0
    cmpi.b  #ST_ARMED,%d0
    bne.b   dl_out
    bsr.w   dj_hide                    | V7.1.1: stock's switch must not take an armed cue
dl_out:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
    move.b  LAND_CNTDN,%d0             | displaced original -- sets the flags for ble.w
    rts

| ================= V7.1.1: an armed cue is DIRECT JUMP's, not stock's switch's =================
| The race (found 2026-11-13, REF-LOCK run o4/n4): a cue made shortly before the outgoing pattern's
| switch point (its last master step, or a CHAIN AFTER boundary) is armed for the incoming pattern's
| landing grid, up to L - 1 ticks away (L = 24 with a 1/4x track).  Stock's phase G reached its
| switch point first: the wrap body (0x400a43a0) commits PEND whenever it is set (0x400a44b8-
| 0x400a44dc, whatever d6 says) and, PEND != ACT, runs the full switch (step 0 one master step on,
| COND_RESET(-1)); DIRECT JUMP then re-landed on its grid -- 11 ticks of the incoming pattern from
| step 0, off the reference.  Fix: on the one tick whose phase G will take the switch (stock's own
| decision 0x400a3fdc-0x400a439c, replayed by dj_hide), PEND reads as the playing pattern -- the
| wrap body then wraps the outgoing pattern as if nothing were cued -- and the next tick, first
| thing in phase D, dj_unhide puts the cue back (unless the performer cued meanwhile) and repaints
| the UI with the wrap's own {0x11} message.  No stock site, no new hook.
| dj_hide (dj_land's saved-register context, state ARMED): d0-d3/a0/a2 used.
dj_hide:
    tst.b   STOP_END
    bne.w   dh_no                      | stock's stop at the step end commits the cue: leave it
    moveq   #0,%d0
    move.b  ACT_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    bsr.w   dj_blob                    | a2 = the playing pattern (stock's a4 in phase G)
    moveq   #0,%d1
    move.b  SCALE_IX,%d1
    moveq   #SCALE_MAX,%d0
    cmp.l   %d0,%d1
    bls.b   1f
    moveq   #SCALE_1X,%d1              | out of range: 1x (as everywhere here)
1:  lea     LEN_TBL,%a0
    move.l  (%a0,%d1.l*4),%d2          | the live tps_M
    move.b  TICK_CTR,%d1
    extb.l  %d1
    addq.l  #1,%d1                     | phase G: ++tick, a master step when it reaches tps_M
    cmp.l   %d2,%d1
    blt.w   dh_no
    moveq   #0,%d2
    move.w  MASTER_STEP,%d2
    addq.l  #1,%d2
    andi.l  #0xffff,%d2                | d2 = the master step phase G is about to start (mvz.w)
    move.l  #P_CHAINQ,%d0
    move.b  (%a2,%d0.l),%d1
    extb.l  %d1
    bpl.b   2f
    move.b  PROJ_QUANT,%d1
    extb.l  %d1
2:  lea     QUANT_TBL,%a0
    move.l  (%a0,%d1.l*4),%d3          | N = CHAIN AFTER (master steps)
    tst.l   %d3
    ble.b   dh_end
    move.l  %d2,%d0
    rems.l  %d3,%d1:%d0                | a cue switches where the step is 0 mod N
    tst.l   %d1
    beq.b   dh_yes
dh_end:
    move.l  END_STEP,%d0
    moveq   #-1,%d1
    cmp.l   %d1,%d0
    beq.b   dh_len
    cmp.l   %d2,%d0
    bgt.b   dh_no
    bra.b   dh_yes
dh_len:
    move.l  #P_SCALE_MODE,%d0
    tst.b   (%a2,%d0.l)
    beq.b   3f
    move.l  #P_MLEN_WORD,%d0
    move.w  (%a2,%d0.l),%d1            | PER-TRACK: master length (-1 = INF)
    ext.l   %d1
    bra.b   4f
3:  move.l  #P_LEN_BYTE,%d0
    move.b  (%a2,%d0.l),%d1            | NORMAL: the pattern length
    extb.l  %d1
4:  moveq   #-1,%d0
    cmp.l   %d0,%d1
    beq.b   dh_no
    cmp.l   %d2,%d1
    bgt.b   dh_no                      | the pattern's end is not reached
dh_yes:
    move.b  ACT_PAT,%d0
    move.b  %d0,PEND_PAT
    move.b  ACT_BANK,%d0
    move.b  %d0,PEND_BANK
    moveq   #1,%d0
    move.b  %d0,dj_hid
dh_no:
    rts

| dj_unhide: first thing in phase D, every tick (DJ on or off: the cue is the performer's).  The
| cue goes back only while PEND still reads as the playing pattern -- one cued in between stands
| (dj_land's re-cue rule handles it).  Uses d0 (+ KPOST's scratch).
dj_unhide:
    tst.b   dj_hid
    beq.b   du_out
    clr.b   dj_hid
    move.b  PEND_PAT,%d0
    cmp.b   ACT_PAT,%d0
    bne.b   du_out
    move.b  PEND_BANK,%d0
    cmp.b   ACT_BANK,%d0
    bne.b   du_out
    move.b  dj_armpat,%d0
    move.b  %d0,PEND_PAT
    move.b  dj_armbank,%d0
    move.b  %d0,PEND_BANK
    move.b  ACT_PAT,%d0                | the wrap's {0x11, pattern, 1} again: the UI repaints the cue
    move.b  %d0,MSG_PAT_ARG
    pea     MSG_PAT
    pea     UI_QUEUE
    jsr     KPOST
    addq.l  #8,%sp
du_out:
    rts

| dl_commit: the landing tick.  Registers are free (saved by the caller).
dl_commit:
    tst.b   dj_spn
    beq.b   1f
    bsr.w   dj_spflush                 | V7.2: a new jump publishes the last one's pending tracks at once
1:
    .ifdef DJ_SELFHOOK
    move.l  dj_selfvec,%d0             | [2]: Clyps puts a self-jump's pattern + Part back now,
    beq.b   dc_nself                   | before the parameters and the hand-off below read them
    movea.l %d0,%a0                    | (it clears its request either way)
    movea.l 8(%a0),%a0
    jsr     (%a0)
dc_nself:
    .endif
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
    move.l  dj_tpsM,%d3
    move.l  dj_rsm,%d0                 | V7.3: in the last restart's frame (dj_swres): + dj_rsm master
    muls.l  %d3,%d0                    | steps (0 unless the arranger started the pattern later); t_L may
    add.l   %d0,%d7                    | be < 0 (just before the restarted pattern's first boundary); u >= 0 (dl_arm)
    move.l  %d7,dj_tland
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
    addq.l  #2,%d5                     | d5 = the boundary's t' = t'(t_L) + 1 (>= 0, 0 mod L: dl_arm)
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
|   V7.1: the landing is one tick before the boundary.  Stock's loader (just above, 0x400a1fd0-
|   0x400a2072) set every reload to tps - 1 and the master tick to tps_M - 1 (fire at once); one
|   less each: phase E's first fire is scheduled a tick ahead (ahead 2), on the boundary, exactly
|   where the outgoing boundary event would have sounded; the master steps on the boundary too.
    move.l  %a0,-(%sp)
    move.l  %d1,-(%sp)
    lea     RELOAD,%a0
    moveq   #16,%d1
dn_rl:
    move.b  (%a0),%d0                  | (ColdFire: subq is long-only)
    subq.l  #1,%d0
    move.b  %d0,(%a0)+
    subq.l  #1,%d1
    bne.b   dn_rl
    move.b  TICK_CTR,%d0
    subq.l  #1,%d0
    move.b  %d0,TICK_CTR
    move.l  (%sp)+,%d1
    movea.l (%sp)+,%a0
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
    move.l  %d4,dj_silA                | V7.2: START SILENT tracks publish on the boundary tick
    move.l  SCLK,%d0                   | stock: sclk + tps_M * TICK_A (a master step ahead)
    addi.l  #TICK_A,%d0                | V7.1: the boundary is the NEXT tick (V7.0.x: "now")
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
    move.l  %d4,dj_silM
|   MIDI switch times, 0x400a470a-0x400a47b2 (stock's d5 = ticks ahead; V7.1: 1, the boundary is the
|   next tick -- V7.0.x: 0): the offsets depend on the MIDI clock settings exactly as in stock
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
    addi.l  #TICK_M,%d0                | V7.1: d5 = 1 tick ahead
    tst.l   %d5
    bne.b   ho_mt1
    addi.l  #12600,%d0
ho_mt1:
    move.l  %d0,ENG_MTIME1
    moveq   #1,%d0
    move.l  %d0,ENG_MFLAG
    move.l  MCLK,%d0
    addi.l  #TICK_M,%d0                | V7.1: d5 = 1 tick ahead
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
|   V7.0.2 (2026-11-13, the user's rule from Clyps, scope §1.29 C): the trig conditions stand where
|   a never-switched incoming pattern would have them -- stock's switch (and V7.0.1) restarted them
|   with COND_RESET(-1) 0x400a539c here.  dj_cond (below) sets every track's A:B pass counter.
|   (V7.3: "never switched" = since the last restart; a jump itself is not a restart and never runs
|   stock's switch block, so dj_swres never fires for it.)
    bsr.w   dj_sparm                   | V7.2: every track's Part publish waits for its first trig
    bra.w   dj_cond

| dj_cond: every track's trig-condition state at the landing tick t_L (dj_tland), as a reference run
| that had played the incoming pattern since START holds it (REF-LOCK: tools/cmp_reflock.py --cond).
|   A:B pass counter 0x46107918[t] = F(t_L): the passes track t would have begun since the last
|     restart, in the incoming pattern's model (dj_bparams' tps_M / C / tps_t / len_t; time = dj_tland,
|     the restart's frame: PLAY = 0, the master cycle starting at 0 mod C -- dj_tprime).  V7.3: after a
|     stock switch the frame's 0 is the switch's audible boundary, one OUTGOING master step after it
|     (dj_swres); COND_RESET(-1) zeroed every counter at the switch and no pass starts before that
|     boundary, so a landing before it (t_L < 0: a jump cued just after the switch) is F(0) = 0.
|     The measured stock facts (Clyps M1-M3,
|     reference/handoffs/RELOAD_CLYPS_PORT.md rule 3): a pass starts at each own wrap (0x400a536c,
|     t' = j*c - tps, c = len*tps) and at the master's restart (the wrap body, t' = C - tps_M), once
|     when they coincide.  Per master cycle K = J + (rem != 0), J = (C - tps_M + tps) / c (rem its
|     remainder); F(x) = q*K + min((u + tps - 1) / c, J) + (rem && u > C - tps_M), q = x / C,
|     u = x mod C.  INF (C = 0): F(x) = (x + tps - 1) / c.  F(0) = 0, so nothing to subtract.
|   PRE latch 0x46107979[t] = 1, as COND_RESET sets it: the incoming pattern's own last condition
|     result is unknown here; 1 is what the reference holds while none has been evaluated.
|   FILL latches 0x46107959 / 69 [t]: KEPT.  They hold the performer's FILL press (0x400a5460),
|     which a reference run would hold as well; COND_RESET(-1) used to drop a latched FILL.
|   Every register is free (dl_commit's caller, dj_land, saved them all); a2 is no longer needed.
dj_cond:
    move.l  dj_tland,%d7               | x = t_L
    bpl.b   1f
    moveq   #0,%d7                     | V7.3: before the restarted pattern's first boundary -> F(0) = 0
1:  tst.l   dj_C
    beq.b   cn_init                    | INF: no master cycle
    move.l  dj_C,%d6
    move.l  %d6,%d0
    sub.l   dj_tpsM,%d0
    movea.l %d0,%a6                    | a6 = C - tps_M: the master restart's t'
    move.l  %d7,%d0
    divu.l  %d6,%d0
    movea.l %d0,%a5                    | a5 = q = x / C
    muls.l  %d6,%d0
    move.l  %d7,%d1
    sub.l   %d0,%d1
    movea.l %d1,%a2                    | a2 = u = x - q*C
cn_init:
    lea     dj_tps,%a3
    lea     dj_len,%a4
    lea     0x46107918,%a0             | A:B pass counters, long[16]
    lea     0x46107979,%a1             | PRE latch, byte[16]
    moveq   #16,%d5
cn_loop:
    moveq   #0,%d4
    move.b  (%a3)+,%d4                 | tps
    moveq   #0,%d3
    move.b  (%a4)+,%d3                 | len
    bne.b   1f
    moveq   #1,%d3                     | (a length of 0 never plays: count it as 1)
1:  muls.l  %d4,%d3                    | d3 = c = len * tps (> 0)
    tst.l   dj_C
    bne.b   cn_cyc
    move.l  %d7,%d0                    | INF: F = (x + tps - 1) / c
    add.l   %d4,%d0
    subq.l  #1,%d0
    divu.l  %d3,%d0
    bra.b   cn_store
cn_cyc:
    move.l  %a6,%d0
    add.l   %d4,%d0                    | C - tps_M + tps
    move.l  %d0,%d1
    divu.l  %d3,%d1                    | d1 = J: own wraps up to the wrap body
    move.l  %d1,%d2
    muls.l  %d3,%d2
    sub.l   %d2,%d0                    | d0 = rem (!= 0: the master's restart is a pass start of its own)
    move.l  %d1,%d2
    tst.l   %d0
    beq.b   2f
    addq.l  #1,%d2                     | d2 = K: pass starts per master cycle
2:  move.l  %a5,%d6
    muls.l  %d2,%d6                    | d6 = q * K
    move.l  %a2,%d2
    add.l   %d4,%d2
    subq.l  #1,%d2
    divu.l  %d3,%d2                    | own wraps before u ...
    cmp.l   %d1,%d2
    bls.b   3f
    move.l  %d1,%d2                    | ... at most J
3:  tst.l   %d0
    beq.b   4f
    cmpa.l  %a6,%a2
    bls.b   4f
    addq.l  #1,%d2                     | the master's restart before u
4:  move.l  %d6,%d0
    add.l   %d2,%d0                    | F(x)
cn_store:
    move.l  %d0,(%a0)+
    move.b  #1,(%a1)+
    subq.l  #1,%d5
    bne.w   cn_loop
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
    .ifdef DJ_SELFHOOK
| dj_selfblob: a self-jump requested -> a2 = Clyps' copy of the pattern as loaded ([1] -> d0), so
| the landing tick is computed from the lengths / scales the jump will land with
dj_selfblob:
    move.l  dj_selfvec,%d0
    beq.b   ds_out
    move.l  %a2,-(%sp)
    movea.l %d0,%a0
    movea.l (%a0),%a0
    jsr     (%a0)
    movea.l (%sp)+,%a2
    tst.l   %d0
    beq.b   ds_out
    movea.l dj_selfvec,%a0
    movea.l 4(%a0),%a0
    jsr     (%a0)
    movea.l %d0,%a2
ds_out:
    rts
    .endif

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
    moveq   #SCALE_MAX,%d0
    cmp.l   %d0,%d1
    bls.b   1f
    moveq   #SCALE_1X,%d1              | out of range: 1x
1:  move.l  (%a0,%d1.l*4),%d3          | tps_M
    move.l  #P_LEN_BYTE,%d0
    moveq   #0,%d4
    move.b  (%a2,%d0.l),%d4            | mlen
    bra.b   bp_c
bp_pt:
    move.l  #P_MSCALE,%d0
    move.b  (%a2,%d0.l),%d1
    moveq   #SCALE_MAX,%d0
    cmp.l   %d0,%d1
    bls.b   1f
    moveq   #SCALE_1X,%d1              | out of range: 1x
1:  move.l  (%a0,%d1.l*4),%d3
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
    moveq   #SCALE_MAX,%d0
    cmp.l   %d0,%d1
    bls.b   1f
    move.l  dj_tpsM,%d2                | out of range: the master's
    bra.b   2f
1:  move.l  (%a0,%d1.l*4),%d2          | tps_t
2:
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

| dj_tprime: d0 = tick t (dj_T's count) -> d0 = t' = ((x + tps_M - 1) mod C) - (tps_M - 1)  (signed), with
| x = t + dj_rsm * tps_M, the tick in the last restart's frame (V7.3; dj_rsm = 0 but after an arranger
| start).  Right after a stock switch x can be as low as 1 - tps_old: u = x + tps_M - 1 < 0 is a t' before the
| restarted pattern's first boundary -- negative, no mod.  Uses d1-d3.
dj_tprime:
    move.l  dj_tpsM,%d3
    move.l  dj_rsm,%d1
    muls.l  %d3,%d1
    add.l   %d1,%d0                    | x
    add.l   %d3,%d0
    subq.l  #1,%d0                     | u
    bmi.b   tp_noc                     | V7.3: before the first boundary since the restart
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

| dj_purge: cancel every pending event of the outgoing pattern from the boundary on in the two
| audio tables and the MIDI table, with stock's own cancellation (0x400a43b6-0x400a4464): clear the
| record long and the slot's bit in the track mask; the fire time itself is left alone.
| V7.1 (2026-11-13, the user: Clyps CL26's fix): the landing is one tick BEFORE the boundary, so an
| event is the outgoing pattern's from the boundary on when it fires half a tick or more from now.
| The boundary events sit a whole tick ahead and events due on this tick stay: half a tick of margin
| either way (V7.0.x purged on the boundary tick itself with fire - now >= 0, where the boundary
| events tied the sample clock exactly -- measured +0.0000 tick).
dj_purge:
    move.l  SCLK,%d5
    move.l  #TICK_A/2,%d3              | half an audio tick
    lea     0x80001904,%a0
    lea     0x46c7e998,%a1
    lea     0x46c7fe44,%a3
    bsr.b   pg_table
    lea     0x80001984,%a0
    lea     0x46c7faa4,%a1
    lea     0x46c7fe8c,%a3
    bsr.b   pg_table
    move.l  MCLK,%d5
    move.l  #TICK_M/2,%d3              | half a MIDI tick
    lea     0x46c76a26,%a0
    lea     0x46c769c0,%a1
    lea     0x46c77be2,%a3
|   fall through
| pg_table: a0 = times[t + slot*8] (longs), a1 = records (same layout), a3 = mask[8], d5 = now,
| d3 = half a tick in this table's clock
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
    cmp.l   %d3,%d2
    blt.b   pg_next                    | fires before the boundary: the outgoing pattern's, leave it
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

| dj_relsil (V7.2.2, 2026-11-15, hardware A/B; the user's SILENCE TRACKS pop): the switch silences every
| audio track whose START SILENT / SILENCE TRACKS bit the hand-off set (dj_silA bits 8..15) with a HARD kill
| (0x40006820 from 0x4000d45a, measured: no fade). Stock's change masks it with the new pattern's step-0
| trigs; a jump landing on a step without a trig left the cut bare (ot_emu render, OT DEMO A05 -> A03: 2nd
| difference 0.169 at the switch vs 0.028 without one). Release those tracks first with stock's note-off --
| the release STOP and MUTE_MODES OTFX-T use, the DSP's own declick fade -- so the kill lands on faded voices.
| Called on the tick after the landing (the boundary tick's phase D): the sequencer runs about a tick ahead
| of the audio, so this is about one tick before the audible boundary (the landing tick itself would be two:
| measured, the outgoing sound then went quiet ~2 ticks early). Render: switch transient 0.018, the outgoing
| sound kept until then. Nothing when no track is silenced. Registers: dj_land saved them all; 0x40008f84
| keeps d2-d7/a2-a6.
dj_relsil:
    move.l  dj_silA,%d4
    moveq   #0,%d5
rs_l:
    move.l  %d5,%d0
    addq.l  #8,%d0
    btst    %d0,%d4
    beq.b   1f
    move.l  %d5,-(%sp)
    jsr     NOTE_OFF
    addq.l  #4,%sp
1:  addq.l  #1,%d5
    moveq   #8,%d0
    cmp.l   %d5,%d0
    bne.b   rs_l
    rts

| ================= V7.3: dj_swres @ 0x400a4850 -- stock's switch is a RESTART =================
| The author's decision (2026-11-16, option (b)): DIRECT JUMP's time origin is the last restart -- PLAY or
| any stock pattern switch -- for the landing position and the trig conditions alike, as RELOAD_FROM_PROJECT
| (rl_creset) and Clyps (cl_creset) already count.  Until V7.2.2 dj_T ran from PLAY: after PLAY on A, a
| normal change to X and a jump to Y, Y landed at its PLAY phase and its A:B counters counted from PLAY.
| The site: stock's switch block (phase G, the wrap body with d6 = PEND != ACT) `pea -1 ; jsr COND_RESET`
| (0x400a484c / 0x400a4850), right after it restarted the master: MASTER_STEP = 0x8000662a (0x400a483a; 0
| unless the arranger starts the pattern later), tick 0 (0x400a4842).  Only that block runs it: a plain wrap
| (d6 = 0, also dj_hide's held cue) skips it, and a DIRECT JUMP jump never runs the switch block at all
| (its landing is phase D's re-landing; COND_RESET is not called since V7.0.2).
| The frame (measured, tools/diag_reflock.py: a stock switch straight to the pattern, out/djr f1-f4): the
| wrap body runs one master step before the cycle's audible boundary, and that first step of the new pattern
| still runs at the OUTGOING master rate (SCALE_IX follows a step later) -- so the new pattern's cycle starts
| (t' = 0, PLAY's t = 0) tps_old ticks after the switch, whatever the incoming pattern's own rate.  Hence
| dj_T = -tps_old now (the next tick counts 1 - tps_old; the boundary tick 0), and dj_rsm = N, the step stock
| started the pattern on (MASTER_STEP, 0 unless the arranger), so x = dj_T + dj_rsm * tps_M (dj_tprime,
| dl_commit).  A reload stays 0 until the new pattern's first master wrap, as after PLAY (dl_fixup).  Then the
| TAIL JUMP: COND_RESET -- and RELOAD's / Clyps' detour at its entry -- sees the caller's return address
| 0x400a4856 at (sp) and the -1 at 4(sp), as stock.  Uses d0 / a0 only (COND_RESET is a C function: d0-d1 /
| a0-a1 are the caller's scratch).
    .global dj_swres
dj_swres:
    moveq   #0,%d0
    move.b  SCALE_IX,%d0               | the master rate still in force (the outgoing pattern's)
    cmpi.l  #SCALE_MAX,%d0
    bls.b   1f
    moveq   #SCALE_1X,%d0              | out of range: 1x (as everywhere here)
1:  lea     LEN_TBL,%a0
    move.l  (%a0,%d0.l*4),%d0
    neg.l   %d0
    move.l  %d0,dj_T                   | -tps_old: the new cycle starts tps_old ticks from now
    moveq   #0,%d0
    move.w  MASTER_STEP,%d0            | N: where stock just started the pattern (0x400a483a)
    move.l  %d0,dj_rsm
    jmp     COND_RESET                 | (sp) = 0x400a4856, 4(sp) = -1: stock's own call

| dl_fixup: the tick after a landing.  Stock's landing leaves reload = tps_t - 1 (it drives
| the landing's immediate first fire); the reference holds 0 until the first master wrap
| since START, then the wrap-change catch-up max(0, tps_t - tps_M).  V7.3: the same since a stock
| switch (measured: stock's switch leaves every reload 0 until the new pattern's first wrap), with
| dj_tland in the restart's frame.  Nothing reads reload
| between here and the next wrap (cntdn idle, first-fire mask consumed), so this is for the
| state-equality proof -- and it makes the next wrap start from the reference's value.
dl_fixup:
    lea     LEN_TBL,%a0
    moveq   #0,%d0
    move.b  SCALE_IX,%d0
    moveq   #SCALE_MAX,%d1
    cmp.l   %d1,%d0
    bls.b   1f
    moveq   #SCALE_1X,%d0              | out of range: 1x
1:  move.l  (%a0,%d0.l*4),%d3          | tps_M (live, as loaded by the landing)
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
    move.l  %d3,%d1                    | out of range: the master's
    cmpi.l  #SCALE_MAX,%d0             | (no scratch register: d2 is the caller's)
    bhi.b   1f
    move.l  (%a0,%d0.l*4),%d1
1:  sub.l   %d3,%d1                    | tps_t - tps_M
    bpl.b   fx_store
    moveq   #0,%d1
fx_store:
    move.b  %d1,(%a2,%d6.l)
    addq.l  #1,%d6
    moveq   #16,%d0
    cmp.l   %d6,%d0
    bne.b   fx_loop
    rts


| ================= V7.2: the incoming Part per track, at its first SOUNDING trig =================
| The user (2026-11-13, Clyps' FULL-load rule): a performer should never hear the incoming sequence's track
| settings applied to the sound being changed away from.  Until V7.1 the engine's light Part apply
| 0x40009e00 (from the hand-off's switch, 0x4000b1d8) applied the incoming Part on the boundary: the
| Part-wide items (published bank / Part 0x80001828/29 -- what each new trig's voice reads --, the scene
| table 0x800010e4..e7, the UI's 0x46c7d6d4 block and its two posts) and, with LFO AUTO CHANGE
| (0x80000050), every track's LFO setup -- under a sample still ringing from the outgoing pattern.
| V7.2: the switch keeps the Part-wide items (dj_lfoq skips the per-track part of that one apply) and each
| track gets its own Part (TRK_APPLY / dj_mapply, as Clyps' cl_sppub and RELOAD's rl_pub1; only with LFO
| AUTO CHANGE on, see dj_sparm) on the tick where
| a pending event of the new sequence with record bit 2 (the builder's 29 / 61: a sample / note trig; 25 is
| a trigless trig, 1 an empty step) fires within half a tick -- micro-timing and trig conditions honoured
| (a trig whose condition fails is never built).  A sequence without any sample trig, and a START SILENT
| track (stock silences it at the switch: nothing rings), publish on the boundary tick.  STOP, DJ off and a
| new jump publish everything still pending at once.  The engine's own voice code restarts a machine
| that differs from the voice's Part when it triggers (0x4000c9e8: it compares the voice's bank / Part
| with the published one), so no restart bit is needed here.

| dj_lfoq: the light Part apply's `tst.b 0x80000050` (LFO AUTO CHANGE, 0x40009ebe, jsr, 6 B; stock's
| beq.w 0x4000a138 follows on its Z flag).  The one apply after a jump's hand-off sees Z = 1: its per-track
| LFO loops are skipped (each track's publish brings them).  Keeps every register.
    .global dj_lfoq
dj_lfoq:
    tst.b   dj_defer
    beq.b   lq_stock
    clr.b   dj_defer
    cmp.l   %d0,%d0                    | Z = 1
    rts
lq_stock:
    tst.b   0x80000050                 | displaced original
    rts

| dj_sparm (the landing tick, from dj_handoff; a2 = the incoming blob): every track's publish waits.
| Measured (tools/check_dj_part.py, 2026-11-13): the light apply's ONLY per-track part is the LFO setup, and
| only with LFO AUTO CHANGE on (0x80000050, the project's CONTROL > SEQUENCER setting); every other track
| setting of the new Part reaches the voice through the published bank / Part at its trigs.  So with LFO
| AUTO CHANGE off there is nothing per track to defer, and nothing is armed: a TRK_APPLY would impose the
| new Part's LFOs, which stock never does then.  Uses d0-d7/a0-a1 (dj_land saved them).
dj_sparm:
    tst.b   0x80000050
    bne.b   1f
    rts                                | LFO AUTO CHANGE off: the switch's light apply is all there is
1:
    move.b  ACT_BANK,%d0
    move.b  %d0,dj_spbk
    move.l  #P_PART,%d1
    move.b  (%a2,%d1.l),%d0
    move.b  %d0,dj_sppt
    move.l  SCLK,%d5
    addi.l  #TICK_A/2,%d5              | d5 = audio: a new-sequence event fires at or after (dj_purge's line)
    move.l  MCLK,%d4
    addi.l  #TICK_M/2,%d4              | d4 = MIDI
    moveq   #0,%d6                     | t
sa_l:
    moveq   #2,%d7                     | default: the boundary tick
    move.l  dj_silA,%d0
    cmpi.l  #8,%d6
    bcs.b   1f
    move.l  dj_silM,%d0
1:  move.l  %d6,%d1
    andi.l  #7,%d1
    addq.l  #8,%d1
    btst    %d1,%d0
    bne.b   sa_set                     | START SILENT: stock silences it at the switch
|   any sample trig in the incoming sequence (under its length)?
    move.l  %d6,%d0
    bsr.w   dj_tmask
    tst.l   %d0
    beq.b   sa_set                     | no sample trig: the boundary tick
    move.l  #0xfffe,%d7                | wait for the first sounding one
sa_set:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     dj_spd,%a0
    move.w  %d7,(%a0,%d0.l)
    add.l   %d0,%d0
    lea     dj_sptm,%a0
    move.l  %d5,(%a0,%d0.l)
    cmpi.l  #8,%d6
    bcs.b   6f
    move.l  %d4,(%a0,%d0.l)
6:  addq.l  #1,%d6
    moveq   #16,%d0
    cmp.l   %d6,%d0
    bne.w   sa_l
    moveq   #1,%d0
    move.b  %d0,dj_spn
    move.b  %d0,dj_defer               | the switch's light apply: Part-wide only
    rts

| dj_tmask (a2 = a pattern blob, d0 = t) -> d0 = t's trig mask (sample / note trigs, the record's first 8
| bytes, big-endian, bit s = step s) under its length, the two halves OR-ed (0 = no sample trig).  The
| length as stock's landing loads it: NORMAL the pattern's, PER-TRACK the record's.  Uses d0-d3/a0.
dj_tmask:
    move.l  %d0,%d3                    | t
    cmpi.l  #8,%d0
    bcc.b   1f
    move.l  #A_STRIDE,%d1
    muls.l  %d1,%d0
    lea     (%a2,%d0.l),%a0            | audio record
    moveq   #A_LEN,%d1
    bra.b   2f
1:  subq.l  #8,%d0
    move.l  #M_STRIDE,%d1
    muls.l  %d1,%d0
    addi.l  #M_REC,%d0
    lea     (%a2,%d0.l),%a0            | MIDI record
    move.l  #M_LEN-M_REC,%d1
2:  moveq   #0,%d0
    move.b  (%a0,%d1.l),%d0            | PER-TRACK length
    move.l  #P_SCALE_MODE,%d1
    tst.b   (%a2,%d1.l)
    bne.b   3f
    move.l  #P_LEN_BYTE,%d1
    moveq   #0,%d0
    move.b  (%a2,%d1.l),%d0            | NORMAL: the pattern's
3:  move.l  4(%a0),%d2                 | steps 0..31
    move.l  (%a0),%d3                  | steps 32..63
    moveq   #32,%d1
    cmp.l   %d1,%d0
    bcc.b   4f
    moveq   #0,%d3                     | len < 32: no high steps
    moveq   #1,%d1
    lsl.l   %d0,%d1
    subq.l  #1,%d1
    and.l   %d1,%d2                    | steps < len
    bra.b   5f
4:  subi.l  #32,%d0
    cmpi.l  #32,%d0
    bcc.b   5f
    moveq   #1,%d1
    lsl.l   %d0,%d1
    subq.l  #1,%d1
    and.l   %d1,%d3
5:  or.l    %d3,%d2
    move.l  %d2,%d0
    rts

| dj_hastrig (d6 = t) -> d0 != 0 when the sequence now playing t has a sample trig.  Keeps all but d0.
dj_hastrig:
    lea     -24(%sp),%sp
    movem.l %d1-%d3/%a0-%a2,(%sp)
    moveq   #0,%d0
    move.b  ACT_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    bsr.w   dj_blob
    move.l  %d6,%d0
    bsr.w   dj_tmask
    movem.l (%sp),%d1-%d3/%a0-%a2
    lea     24(%sp),%sp
    rts

| dj_spdo (every tick, dj_land's saved context): count down / look for the sounding trig; publish.
dj_spdo:
    moveq   #0,%d6
    moveq   #0,%d3                     | d3 = one is still pending
so_l:
    move.l  %d6,%d1
    add.l   %d1,%d1
    lea     dj_spd,%a0
    moveq   #0,%d0
    move.w  (%a0,%d1.l),%d0
    beq.b   so_n
    cmpi.l  #0xfffe,%d0
    bne.b   so_dec
    bsr.w   dj_sptrig
    tst.l   %d0
    bne.b   so_go
|   2026-11-14 (the overlap test, KYOTI-with-Clyps): Clyps may have loaded a sequence without any sample trig
|   onto the track since the jump -- then no trig will ever come: the boundary rule, now (it was left
|   pending until the next jump / STOP).
    bsr.w   dj_hastrig
    tst.l   %d0
    beq.b   so_go
    moveq   #1,%d3
    bra.b   so_n
so_dec:
    subq.l  #1,%d0
    move.w  %d0,(%a0,%d1.l)
    beq.b   so_go
    moveq   #1,%d3
    bra.b   so_n
so_go:
    bsr.w   dj_pub1
so_n:
    addq.l  #1,%d6
    moveq   #16,%d0
    cmp.l   %d6,%d0
    bne.b   so_l
    move.b  %d3,dj_spn
    rts

| dj_spflush: every pending publish now (a new jump, STOP, DJ off).  Uses d0-d1/d6/a0-a1.
dj_spflush:
    moveq   #0,%d6
sf_l:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     dj_spd,%a0
    tst.w   (%a0,%d0.l)
    beq.b   sf_n
    bsr.w   dj_pub1
sf_n:
    addq.l  #1,%d6
    moveq   #16,%d0
    cmp.l   %d6,%d0
    bne.b   sf_l
    clr.b   dj_spn
    clr.b   dj_defer
    rts

| dj_pub1 (d6 = t): t's Part to the engine.  Keeps d2-d7/a2-a6.
dj_pub1:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     dj_spd,%a0
    clr.w   (%a0,%d0.l)
    move.l  %d6,%d0
    cmpi.l  #8,%d0
    bcs.b   1f
    subq.l  #8,%d0
1:  move.l  %d0,-(%sp)                 | t (audio) / m (MIDI)
    moveq   #0,%d0
    move.b  dj_sppt,%d0
    move.l  %d0,-(%sp)
    move.b  dj_spbk,%d0
    move.l  %d0,-(%sp)
    cmpi.l  #8,%d6
    bcc.b   2f
    jsr     TRK_APPLY
    bra.b   3f
2:  bsr.w   dj_mapply
3:  lea     12(%sp),%sp
    rts

| dj_tpub(bank, part, t): one track's publish as dj_pub1 makes it (C ABI; tools/check_dj_part.py calls it).
    .global dj_tpub
dj_tpub:
    move.l  12(%sp),%d0
    cmpi.l  #8,%d0
    bcc.b   1f
    jmp     TRK_APPLY
1:  subq.l  #8,%d0
    move.l  %d0,12(%sp)
    bra.w   dj_mapply

| dj_pwide(bank, part): the Part-wide items alone -- stock's light apply with its per-track part skipped,
| exactly what the jump's switch now applies (C ABI; tools/check_dj_part.py calls it).
    .global dj_pwide
dj_pwide:
    moveq   #1,%d0
    move.b  %d0,dj_defer
    move.l  8(%sp),-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     0x40009e00
    addq.l  #8,%sp
    rts

| dj_sptrig (d6 = t, waiting) -> d0 = 1 when one of t's pending events is a sounding trig (record bit 2) of
| the new sequence (fire time >= dj_sptm[t]) firing within half a tick from now (or past: a negative
| micro).  Audio: the primary table vs the sample clock; MIDI: its table vs the MIDI clock (Clyps'
| cl_sptrig).  Keeps d1-d7/a2-a6.
dj_sptrig:
    lea     -28(%sp),%sp
    movem.l %d1-%d5/%a2-%a3,(%sp)
    move.l  %d6,%d0
    lsl.l   #2,%d0
    lea     dj_sptm,%a0
    move.l  (%a0,%d0.l),%d4            | d4 = the new sequence's first possible fire time
    move.l  %d6,%d3
    cmpi.l  #8,%d6
    bcc.b   st_m
    move.l  SCLK,%d2
    move.l  #TICK_A/2,%d5
    movea.l #0x46c7fe44,%a2
    movea.l #0x80001904,%a0
    movea.l #0x46c7e998,%a1
    bra.b   st_go
st_m:
    subq.l  #8,%d3
    move.l  MCLK,%d2
    move.l  #TICK_M/2,%d5
    movea.l #0x46c77be2,%a2
    movea.l #0x46c76a26,%a0
    movea.l #0x46c769c0,%a1
st_go:
    moveq   #0,%d1                     | slot
st_l:
    moveq   #0,%d0
    move.b  (%a2,%d3.l),%d0
    btst    %d1,%d0
    beq.b   st_n
    move.l  %d1,%d0
    lsl.l   #3,%d0
    add.l   %d3,%d0
    movea.l %d0,%a3                    | idx = track + slot * 8
    move.l  (%a1,%d0.l*4),%d0
    btst    #2,%d0
    beq.b   st_n                       | not a sounding trig
    move.l  %a3,%d0
    move.l  (%a0,%d0.l*4),%d0          | its fire time
    movea.l %d0,%a3
    sub.l   %d4,%d0
    bmi.b   st_n                       | the outgoing pattern's
    move.l  %a3,%d0
    sub.l   %d2,%d0
    cmp.l   %d5,%d0
    blt.b   st_yes
st_n:
    addq.l  #1,%d1
    moveq   #3,%d0
    cmp.l   %d1,%d0
    bne.b   st_l
    moveq   #0,%d0
    bra.b   st_out
st_yes:
    moveq   #1,%d0
st_out:
    movem.l (%sp),%d1-%d5/%a2-%a3
    lea     28(%sp),%sp
    rts

| dj_mapply(bank, part, m): one MIDI track's Part values -> the engine.  Clyps' cl_mapply (stock's whole-
| Part apply 0x40009094 does this for every m, 0x400094b0..0x400095e0), RAM writes only.
dj_mapply:
    lea     -20(%sp),%sp
    movem.l %d2-%d4/%a2-%a3,(%sp)
    move.l  24(%sp),%d0                | bank
    move.l  28(%sp),%d1                | part
    move.l  32(%sp),%d2                | m
    move.l  #BANK_STRIDE,%d3
    muls.l  %d0,%d3
    movea.l #PAT_BASE+PART_OFF,%a2
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

    .align 2
    .ifdef DJ_SELFHOOK
    .align 2
    .global dj_selfvec
dj_selfvec: .long 0                    | KYOTI: Clyps' {request?, its originals' slab, put them back}
    .endif
dj_state:  .byte ST_IDLE               | 0 idle / 1 armed (we own LAND_CNTDN) / 2 landing / 3 fixup
dj_pcpat:  .byte -1                    | cued pattern the PC was last sent for
dj_zero:   .byte 0                     | constant 0 for Hook N's flag trick
dj_pcbank: .byte -1                    | V7.0.1: bank the last PC was sent for
dj_armpat: .byte -1                    | V7.0.1: the cue this arm is for
dj_armbank: .byte -1
dj_hid:    .byte 0                     | V7.1.1: 1 = dj_hide held the armed cue back this tick
dj_spn:    .byte 0                     | V7.2: a track's Part publish is pending
dj_defer:  .byte 0                     | V7.2: the next light Part apply skips its per-track LFO part
dj_spbk:   .byte 0                     | V7.2: the bank / Part the pending publishes apply
dj_sppt:   .byte 0
    .align 2
dj_silA:   .long 0                     | V7.2: the hand-off's audio / MIDI flags (START SILENT bits 8..15)
dj_silM:   .long 0
dj_spd:    .space 32                   | V7.2: per track (word) 0 none, 0xfffe waiting for a sounding trig,
                                       |       else ticks to go (2 = the boundary tick)
dj_sptm:   .space 64                   | V7.2: per track (long) the clock a new-sequence event fires at or after
    .align 2
    .ifdef DJ_MODE_IN_CAVE
| The combined image (tools/build_kyoti.py) carries MUTE MODE, whose ANDY restore
| is widened to 0x800000df -- it would restore 0x800000d8 from battery SRAM, so
| DIRECT JUMP could come up ON (reference/MERGE.md B1).  Here the word is part of
| the OS image, re-loaded from flash at every boot: power-on is 0 by construction,
| the same guarantee the stock re-image gives the standalone build.
DJ_MODE:   .long 0                     | 0 = OFF/stock, 1 = ON
    .endif
dj_T:      .long 0                     | V7: running clock ticks since START (0 while stopped); V7.3: since the
                                       |     last restart (PLAY, or a stock switch: dj_swres; < 0 until its boundary)
dj_rsm:    .long 0                     | V7.3: the last restart's start step N (PLAY 0; a stock switch: the step
                                       |     it started the pattern on), x = dj_T + dj_rsm * tps_M
dj_tland:  .long 0                     | V7: t of the last landing (V7.3: x, the restart's frame; < 0 before its
                                       |     first boundary)
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
