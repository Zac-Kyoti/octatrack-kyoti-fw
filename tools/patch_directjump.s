| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
|
| patch_directjump -- "DIRECT JUMP" front-panel toggle + the sequencer hooks.
|
|   [PTN] + [YES]   toggles DIRECT JUMP  0 <-> 1, flashing "DIRECT JUMP ON" / "DIRECT
|                   JUMP OFF" for ~0.7 s.  No PERSONALIZE entry (Session 21 re-scope).
|
|   Overlay -- three builds:
|     v1 (build_directjump.py)     FUN_40059f8c: text + 4 draining countdown boxes,
|                                  styled as the SELECT-BANK/PTN window, borrows its
|                                  handle 0x460d1e5c for < 1 s.
|     v2 (build_directjump_v2.py, --defsym DJ_V2=1)   FUN_4005a0e0: bare 18px text box,
|                                  NO boxes, private handle 0x460d1e64; auto-dismiss via
|                                  dj_tick2 spliced into the engine per-frame handler.
|     v3 (build_directjump_v3.py, --defsym DJ_V3=1)   FUN_4005a2b8(text, dur): the OS's
|                                  OWN self-timing notification -- the call stock uses for
|                                  "PART n RELOADED" (= ems-octakit GK_STOCK_NOTIFICATION_
|                                  SHOW), also what patch_reload2 uses.  No boxes, no
|                                  borrowed/shared handle, NO extra hook.  This is the
|                                  right primitive; the countdown boxes in v1 were only
|                                  ever inherited chrome from reusing the SELECT window.
|                                  ** preferred for build_merged.py. **
|
|   DIRECT JUMP  0 = "OFF"  -> stock: a cued pattern switches at the CHAIN AFTER point
|                              (PLEN by default), restarting at step 1.
|                1 = "ON"   -> a manually cued pattern switches on the NEXT step tick
|                              (stays in time -- NOT the instant the key is pressed) and
|                              playback CONTINUES from the current step position; the new
|                              pattern's Part loads at once; the MIDI Program Change goes
|                              out ~1 step ahead.  Arranger + pattern chains are untouched.
|
| STATE = 0x800000d8 (Session 21; was 0x800000a8).  Zero stock refs (image-wide scan),
| and NOT in the stock PERSONALIZE word set (0x8c..0xd0).  It is volatile DSP shared RAM,
| so persistence works like MUTE MODE's (NOTES Session 19): the setter also writes the
| checksummed 'ANDY' battery-SRAM shadow 0x100fff68 (= 0x100fff00 + DJ_MODE - 0x80000070),
| build_directjump.py extends the block restore pea 0x64 -> pea 0x70 at 3 sites, and --
| because we DON'T go through the PERSONALIZE dispatcher's `jmp 0x4001f23c @ 0x40069074` --
| the toggle stub re-checksums the block itself (jsr FUN_4001f23c).  Default 0 = stock.
|
| ---- the combo (RE: NOTES "Session 21") ----
| PTN handler FUN_4005a044(keycode@4, event@8): press (event 1) sets 0x460d1742 = 1
| ("PTN held") and clears 0x460d173e; on RELEASE the SELECT PATTERN chooser opens only if
| 0x460d173e == 0.  No other key handler reads 0x460d1742, so [PTN]+X is entirely free.
| We hook the YES handler 0x4005e4c8 (keycode 0x31): if event==press AND 0x460d1742 == 1
| AND not-arranger AND no popup -> toggle + popup + set 0x460d173e (suppress the chooser)
| + swallow YES.  Otherwise replay the displaced prologue and resume at 0x4005e4d0.
|
| ---- how the stock per-step switch works (FUN_400a1eea, see NOTES "Session 15") ----
|   0x400a3fdc  DAT_800065b6 (master step, byte) ++ ; wraps to 0 at pattern length
|   0x400a4006  branch: 8000667e!=0 -> "stop after pattern"; else -> step dispatch
|   step==2     FUN_4009e884(pendBank,pendPat) = send Bank Select CC + Program Change
|   step==0     0x400a4220..: bar ctr, ping-pong, CHAIN-AFTER gate, then on a
|               switch-point THE COMMIT @0x400a44d0
|                 DAT_800065be = DAT_800065c0   (pending pattern -> active)
|                 DAT_800065bd = DAT_800065bf   (pending bank    -> active)
|               then per-track step recompute from D7 = patternLen * DAT_80006628,
|               DAT_800065b6 = 0 @0x400a4842, common tail LAB_400a4ba0 (fires trigs)
|
| ---- what DIRECT JUMP does (3 hooks, all gated on DJ_MODE, all inert when 0) ----
|   Hook A @0x400a4006  every step tick while running:
|     * arranger active (0x460d1aec) or chain active (0x80006546) -> disarm, bail
|     * a real pending manual switch (0x800065c0 != -1, != active):
|         - send the Program Change once per distinct pending pattern (FUN_4009e884)
|         - save the current step; tick 1 -> just arm; tick 2 -> force the switch:
|           clr DAT_800065b6 so the step==0 body runs THIS tick
|   Hook B @0x400a42fa  inside the step==0 body: if armed, skip the CHAIN-AFTER gate
|     (overwrite the jsr return address with 0x400a43a0, the "switch confirmed" label)
|     and set D6=1 ("real change") the way the gate would have
|   Hook C @0x400a4840  replaces `DAT_800065b6 = 0`: if armed, instead set D7 and
|     DAT_800065b6 to (savedStep % newPatternLen) so every per-track position that the
|     switch body derives from D7 resumes at the playhead; clear the arm flag

    .equ DJ_MODE,   0x800000d8          | state word (0 = OFF/stock, 1 = ON)
|   Session 83: SH_DJ (0x100fff68) and CKSUM (0x4001f23c) are GONE -- DIRECT JUMP no longer
|   persists. See dj_toggle for why the power-on default is 0 without them.
    .equ PTN_MODE,  0x460d1742          | 1 = [PTN] currently held (set by FUN_4005a044 press)
    .equ PTN_USED,  0x460d173e          | !=0 on [PTN] release -> the chooser does NOT open
    .equ POPUP,     0x460e5cd0          | !=0 = a modal popup is up (skip our combo then)
    .equ SHOW_MSG,  0x40059f8c          | FUN_40059f8c(text, ticks, enable, on_timeout)
    .equ YES_RESUME,0x4005e4d0          | back into the stock YES handler after the 2 moves

|   ---- v3 overlay (build_directjump_v3.py: --defsym DJ_V3=1) ----
|   FUN_4005a2b8(text, dur) -- the OS notification/toast primitive (ems-octakit
|   GK_STOCK_NOTIFICATION_SHOW).  Self-timing: pass a frame duration, it draws the line
|   and tears itself down.  No handle to manage, no follow-up tick -> no dj_tick2, no
|   0x400522ca splice.  patch_reload2's rl_yes uses the identical call (pea DUR ; text).
    .equ NOTIFY,    0x4005a2b8          | FUN_4005a2b8(char *text, int dur_frames)
    .equ NOTIFY_CLOSE,    0x40056bec    | tears down the FUN_4005a2b8 toast (jsr'd only by
                                        | stock's own per-frame tick below -- see Session 62
                                        | in dj_ptnrel's comment for why we never jsr it ourselves)
    .equ NOTIFY_HANDLE,    0x460d1e70   | nonzero while a FUN_4005a2b8 toast is open
    .equ NOTIFY_COUNTDOWN, 0x460d1e6c   | frames left; stock's tick (0x40056c28) closes it at 0
    .equ PTN_LAYER_REL_RESUME, 0x4004341e | FUN_40043418+6 -- resumed via jmp, not rts (see
                                          | dj_ptnrel's comment: the displaced `pea` must
                                          | survive on the stack as FUN_3146c's argument)
    .ifndef DJ_TOAST_DUR
    .equ DJ_TOAST_DUR, 0x44             | same dwell patch_reload2 uses for its toast
    .endif

|   ---- v2 overlay (build_directjump_v2.py: --defsym DJ_V2=1) ----
|   v1 uses SHOW_MSG = the SELECT-BANK/PTN timed window -> text PLUS 4 draining boxes,
|   styled as that window, borrowing its handle 0x460d1e5c for < 1 s.  v2 uses the
|   dead-code bare-text popup FUN_4005a0e0 (own handle 0x460d1e64, small 18px box, NO
|   boxes) and its own frame countdown: dj_tick2, spliced into the engine per-control-
|   frame handler (fn @ 0x40052200, the one that decrements the SOFT MUTE release
|   watchdog 0x46c7dfba), closes the popup via FUN_40056bc0 when G_TOAST hits 0.
    .equ POPUP2,    0x4005a0e0          | FUN_4005a0e0(text) -- bare text popup, no timeout
    .equ CLOSE_CB,  0x40056bc0          | FUN_40056bc0 -- close the 0x460d1e64 popup
    .ifndef TOAST_FRAMES
    .equ TOAST_FRAMES, 0xc0             | ~0.6 s @ the 0x40052200 frame rate (HW-tunable)
    .endif
    .equ G_TOAST,   0x80006a44          | v2 frame countdown for the toast (4 B, volatile)

|   free battery-backed scratch (this build has no lazypart/scene stubs to collide with)
    .equ G_ARMED,   0x80006a40          | 0 = idle, !=0 = a direct jump is armed
    .equ G_STEP,    0x80006a41          | master step to resume at (Session 70 7th pass: no
                                        | longer used for the resume computation -- see
                                        | G_ABSTICK -- kept written for now, harmless)
    .equ G_PCPAT,   0x80006a42          | pending pattern the PC was last sent for
|   Session 70 (7th pass): word-aligned, in the documented-but-unclaimed gap between this
|   block (0x80006a40-44, see patch_qlrec.s's own cross-reference comment) and RELOAD2's
|   block (0x80006a50+).
    .equ TRANSPORT_L, 0x800065b8        | long: 1 while the transport is running
    .equ MASTER_STEPS, 0x80006628       | long: START OFFSET in MASTER STEPS for stock's
                                        | own per-track rebuild loop (0x400a4884). D7 at
                                        | 0x400a4812/0x400a4826 is LEN_TBL[masterScale]
                                        | * this. Normally 0 -> every track restarts at
                                        | step 0. Its low word (0x8000662a) is BAR_CTR's
                                        | source at 0x400a483a. See Hook H.
|   Session 83: G_ABSTICK (was 0x80006a46) is GONE. It was a second position counter running
|   alongside stock's own 0x800065b2, and deriving the resume position from it while the
|   metronome ran from 0x800065b2 is what made every switch land on a different step. The AR
|   port reads 0x800065b2 directly -- see Hook H. Do not reintroduce a private counter here.
    .equ G_JUST_COMMITTED, 0x80006a4a   | one-shot: dj_c sets this; Hook F (below) consumes
                                        | it once, after BOTH per-track loops have finished
                                        | for this tick, then clears it
    .equ ACT_PAT,   0x800065be
    .equ ACT_BANK,  0x800065bd
    .equ PEND_PAT,  0x800065c0
    .equ PEND_BANK, 0x800065bf
    .equ STEP,      0x800065b6      | *** NOT a step counter. *** Session 82, MEASURED
                                    | (tools/diag_tick_domain.py): this is the master
                                    | TICKS-WITHIN-STEP counter -- it is incremented once
                                    | per CLOCK TICK at 0x400a3fdc and wrapped to 0 at
                                    | 0x400a3ffc against LEN_TBL[SCALE_IX], i.e. against
                                    | TICKS PER STEP (3..96), so it only ever holds
                                    | 0..tps-1 (observed 0..5 at tps 6). The step body at
                                    | 0x400a4220 is gated on it being 0 and the PC block
                                    | at 0x400a413e on it being 2. The real master STEP
                                    | counter is MASTER_STEP below. The name is kept only
                                    | because the displaced stock instructions reference
                                    | it; do NOT write a step index here -- that is what
                                    | unstuck the grid from the master clock on hardware.
    .equ MASTER_STEP, 0x800065b2     | the actual master STEP index (word), ++ once per
                                    | master step at 0x400a423a, previous value kept at
                                    | 0x800065b4. Seeded at every switch commit from
                                    | 0x8000662a (MASTER_STEPS' low word) at 0x400a483a --
                                    | which is how an armed DIRECT JUMP resumes the master
                                    | position. Same role as AR's 0x405666e4.
    .equ TRK_SCALE_IX, 0x8000663e       | LIVE per-track scale index, 1 byte per track
                                        | (stride 1, measured: 0x400a3dbc addq.l #1,A3 in
                                        | the per-track loop). The step-counter wrap check
                                        | at 0x400a3cee compares STEP_IN_PAT[t] against
                                        | LEN_TBL[TRK_SCALE_IX[t]] -- so THIS is what
                                        | decides each track's own loop length. Stock only
                                        | refreshes it from the pattern blob immediately
                                        | AFTER a wrap (0x400a3d08 per-track / 0x400a3d0e
                                        | pattern-default), so after a mid-pattern commit
                                        | it still holds the OUTGOING pattern's index for
                                        | one whole cycle -- see dj_pertrack_fix.
                                        | (An identical MIDI-track pair exists at
                                        | 0x80006646 / counter 0x80006508, 0x400a3dd2
                                        | onward -- untouched: no measured symptom.)
    .equ TICKS_IN_STEP, 0x800064f0      | per-track TICKS-WITHIN-STEP counter, 1 byte per
                                        | track. Session 82 correction: the old name
                                        | STEP_IN_PAT was wrong. Stock ++'s it at 0x400a3ce2
                                        | every CLOCK TICK and wraps it at 0x400a3cf6
                                        | against LEN_TBL[TRK_SCALE_IX[t]] -- that track's
                                        | TICKS PER STEP, not its length. Only on that wrap
                                        | does the track's real step index (the byte at
                                        | sp@(152), ++ at 0x400a3d78) advance and get
                                        | wrapped against the track's LENGTH at 0x400a3d8c.
                                        | Force-reset to 0 for all 8 tracks by the
                                        | switch-commit tail at 0x400a4bf0 -- harmless at a
                                        | natural boundary, but it re-phases any track whose
                                        | tps differs from the master's when a DIRECT JUMP
                                        | commits mid-cycle. OPEN, see NOTES Session 82.
                                        | Reading 0 is the sole gate (0x400a2d28) for
                                        | DAT_80001904's table-arm write.
    .equ STEP_IN_PAT, 0x800064f0        | the pre-Session-82 (wrong) name, kept only so the
                                        | unbuilt dj_pertrack_fix below still assembles.
    .equ BAR_CTR,   0x800065b2          | == MASTER_STEP above; Session 82 measured this as
                                        | the master STEP counter, not a bar counter. The
                                        | "bar" reading came from 0x400a4264-0x400a42a0,
                                        | which merely masks it against tables at
                                        | 0x400abae4/0x400abacc and tests step mod 3 to
                                        | derive beat flags. Old comment kept below for the
                                        | history it records:
                                        | "which bar/loop repetition" counter (word),
                                        | Session 79 (NOTES.md): copied from 0x8000662a
                                        | (the pending switch's own "loop region start",
                                        | normally 0) at every switch commit, stock,
                                        | unmodified, immediately before dj_c runs.
                                        | Kept (unused by any hook currently) as a pointer
                                        | for future sessions -- deriving it fresh from
                                        | G_ABSTICK was tried and dynamically DISPROVEN as
                                        | a fix for the table-arm schedule ("continued a
                                        | thirteenth/fourteenth time"); the real driver is
                                        | very likely CNTDN_TBL, not this.
    .equ SCALE_IX,  0x8000663d
    .equ STOPFLAG,  0x8000667e
    .equ RUNNING,   0x800065b8
    .equ ARR_ACT,   0x460d1aec          | FUN_40033968 return (arranger active)
    .equ CHAIN_ACT, 0x80006546
    .equ LEN_TBL,   0x400aba50          | [scaleIdx] -> pattern length (long)
    .equ PAT_SCALE, 0x400eb034          | [bank*0x9b340 + pat*0x8ed8] -> scale idx byte
    .equ PAT_MLEN,  0x400eb031          | pattern +0x8e51 -- MASTER LENGTH in steps
    .equ TRK_BLOB,  0x400e21e0          | pattern blob base (track records from +0)
    .equ PAT_MSCALE,0x400eb032          | pattern +0x8e52 -- MASTER scale when SCALE_MODE=1
    .equ PAT_SMODE, 0x400eb035          | pattern +0x8e55 -- SCALE_MODE flag
    .equ PAT_LEN,   0x400eb033          | same indexing -> pattern LENGTH in STEPS
                                        | (pattern +0x8e53). Session 79 cont.20: LEN_TBL
                                        | is TICKS PER STEP, not a length, so THIS is the
                                        | modulus a master step position needs.
    .equ PC_SEND,   0x4009e884          | FUN_4009e884(bank, pat) -> Bank Sel CC + PC
    .equ SW_LABEL,  0x400a43a0          | "switch confirmed" label inside the step==0 body

    .text

| ================= [PTN] + [YES] toggle =================
| ** v1/v2/v3 are DEAD ON HARDWARE (DIRECTJUMP_V3 flashed 2026-09-14: nothing happens). **
| [PTN] press (FUN_4005a044 -> 0x4004346c) pushes the "PTN held" keymap layer 0x400bf0f2
| onto the layer list 0x460d165c (FUN_40031494 -> rebuild 0x4003125c).  Its 26-byte records
| (@0x400bef04): trig 0x00-0x0f -> select pattern, NO 0x32 -> 0x40056aa8, and YES 0x31 @
| 0x400bf0be with press/release/hold all = 0.  The rebuild overwrites a slot unless the
| field is -1, and the dispatcher (0x40031734) skips NULL -- so while [PTN] is held [YES]
| is swallowed and the stock YES handler (our detour below) is never called.  The layer
| is popped by 0x40043418 on [PTN] release / chooser close.
|
| v4 (build_directjump_v4.py, --defsym DJ_KEYMAP=1): no detour at 0x4005e4c8 at all --
| the build writes dj_toggle into that NULL press slot (0x400bf0c0), so dj_toggle is
| called as press(keycode, event) ONLY while the PTN layer is up.  PTN_MODE == 1 still
| gates it (the layer also stays up through the 4 s chooser window, PTN_MODE == 2), and
| "not our combo" is a plain rts: stock does nothing with [YES] in this layer.
|
| v1-v3: detour replaces the first 8 bytes of the YES handler 0x4005e4c8:
|     0x4005e4c8  222f 0004   move.l 4(%sp),%d1     ; keycode
|     0x4005e4cc  202f 0008   move.l 8(%sp),%d0     ; event
| with `jmp dj_toggle` + nop.  On entry the stack is exactly what the stock handler saw:
| 0(%sp) = return addr, 4(%sp) = keycode, 8(%sp) = event (1 press / 0 release / 2 hold).
| Only D0/D1/A0 are touched; the stock resume path restores nothing, so that's fine.

    .global dj_toggle
dj_toggle:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0                 | event == press ?
    bne.w   djt_stock
    move.l  PTN_MODE,%d0
    subq.l  #1,%d0
    bne.w   djt_stock                  | [PTN] not held -> stock YES
    tst.l   ARR_ACT
    bne.w   djt_stock                  | arranger up -> don't shadow arranger-YES
    tst.l   POPUP
    bne.w   djt_stock                  | a modal popup is open -> stock

|   --- our combo: flip DIRECT JUMP ---
    move.l  DJ_MODE,%d0
    eori.l  #1,%d0
    andi.l  #1,%d0
    move.l  %d0,DJ_MODE
|   Session 83: NO battery-SRAM shadow, NO re-checksum. DIRECT JUMP is a performance
|   feature -- the user turns it on when it is wanted and it must come up OFF on every
|   power-on, never remembered per project or per session.
|
|   That is stock's own behaviour for this address, not something we add. kb/memory-map.md:
|   `FUN_4000f938` (sole caller 0x40000512) re-images the DSP shared-RAM window from ROM at
|   boot -- 0x401086f4 -> 0x80000000, 0x3e88 bytes -- then zero-fills to 0x80004000. DJ_MODE
|   at 0x800000d8 is offset 0xd8, inside that span, and the ROM seed at 0x401087cc reads
|   00000000 (verified against the stock image). So every power-on writes 0 here.
|
|   The only thing that could override that was OUR OWN patch: stock's ANDY restore is
|   `memcpy(0x80000070, 0x100fff00, 0x64)`, covering 0x80000070..0x800000d3 -- it does NOT
|   reach 0x800000d8. build_directjump_v4.py used to widen it to 0x70 at all three restore
|   sites precisely so this word WOULD be restored. That widening is removed, so the stale
|   shadow value in battery SRAM from earlier builds is now inert: nothing reads it.
|
|   ** MERGE HAZARD ** -- MUTE MODE's own shadow is at 0x800000dc (offset 0x6c) and DOES
|   need the 0x70 widening. Any build that combines the two (build_merged.py) will therefore
|   restore offset 0x68 as well and DIRECT JUMP would start persisting again. If DIRECT JUMP
|   is ever merged with MUTE MODE, DJ_MODE must move outside 0x80000070..0x800000df first.
|   Recorded in reference/MERGE.md.

    move.l  DJ_MODE,%d0
    lea     dj_msg_off,%a0
    tst.l   %d0
    beq.b   djt_show
    lea     dj_msg_on,%a0
djt_show:
    .ifdef DJ_V3
    pea     DJ_TOAST_DUR               | dur (frames)
    move.l  %a0,-(%sp)                 | text
    jsr     NOTIFY                     | FUN_4005a2b8(text, dur) -- self-timing OS toast
    addq.l  #8,%sp
    .else
    .ifdef DJ_V2
    move.l  %a0,-(%sp)                 | text
    jsr     POPUP2                     | FUN_4005a0e0(text) -- box-free popup @ 0x460d1e64
    addq.l  #4,%sp
    move.l  #TOAST_FRAMES,%d0
    move.l  %d0,G_TOAST                | arm dj_tick2's frame countdown
    .else
    clr.l   -(%sp)                     | on_timeout = 0
    pea     1                          | enable = 1
    pea     0x28                       | ticks (~0.66 s -> 4 boxes drain fast)
    move.l  %a0,-(%sp)                 | text
    jsr     SHOW_MSG
    lea     16(%sp),%sp
    .endif
    .endif

    moveq   #1,%d0
    move.l  %d0,PTN_USED               | so [PTN] release does NOT open the chooser
    rts                                | swallow the YES key

djt_stock:
    .ifdef DJ_KEYMAP
    rts                                | the PTN-held layer's stock [YES] slot is NULL: nothing
    .else
    move.l  4(%sp),%d1                 | displaced: move.l 4(%sp),%d1
    move.l  8(%sp),%d0                 | displaced: move.l 8(%sp),%d0
    jmp     YES_RESUME
    .endif

dj_msg_on:
    .asciz "DIRECT JUMP ON"
    .align 2
dj_msg_off:
    .asciz "DIRECT JUMP OFF"
    .align 2

    .ifdef DJ_V2
| ================= v2 toast countdown -- Hook @ 0x400522ca =================
| Detour replaces `lea 0x46c7dfba,%a2` (6 B) inside the engine per-control-frame
| handler (fn @ 0x40052200, called from 0x40061e8e; decrements the SOFT MUTE release
| watchdog immediately after this).  On the path here D0 = 119 (from the bge) and is
| dead (reloaded at 0x400522de); D2/A2..A4 are loaded fresh below.  FUN_40056bc0 goes
| through kernel post (0x40000c3c) which clobbers D0-D1/A0-A1, so save those around it.
    .global dj_tick2
dj_tick2:
    move.l  G_TOAST,%d0
    ble.b   dtk_done                   | 0 (or stale-negative) -> no toast up
    subq.l  #1,%d0
    move.l  %d0,G_TOAST
    bne.b   dtk_done
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    jsr     CLOSE_CB                    | G_TOAST hit 0 -> close the popup (0x460d1e64)
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
dtk_done:
    lea     0x46c7dfba,%a2             | displaced original
    rts
    .endif

| Hook E (`dj_abstick` @0x400a3fe4) DELETED in Session 83 -- it maintained
| `G_ABSTICK`, the parallel position counter the AR port removes. The site is stock
| again. See Hook H's comment for the full reasoning.

| ================= Hook A @ 0x400a4006 =================
| detour replaces `tst.b (0x8000667e).l` (6 B).  Runs every step tick.  The step engine
| keeps live values in D5-D7 / A3-A6 (pattern-blob ptr etc.) and FUN_4009e884 only saves
| D2-D4/A2, so the stub save/restores ALL regs.  The restore does not touch flags, so the
| trailing `tst.b (0x8000667e).l` still sets Z for the caller's `beq.w 0x400a412e`.
|   ColdFire has no `movem -(An)` -> lea a frame, movem into it.

    .global dj_a
dj_a:
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    move.l  DJ_MODE,%d0
    beq.b   dja_disarm                 | OFF -> also clear any stale arm
    tst.l   ARR_ACT
    bne.b   dja_disarm                 | arranger running -> leave it alone
    tst.l   CHAIN_ACT
    bne.b   dja_disarm                 | pattern chain running -> leave it alone
    move.b  PEND_PAT,%d0
    cmpi.b  #-1,%d0
    beq.b   dja_disarm                 | nothing cued
    move.b  ACT_PAT,%d1
    cmp.b   %d1,%d0
    bne.b   dja_real
    move.b  PEND_BANK,%d0
    move.b  ACT_BANK,%d1
    cmp.b   %d1,%d0
    bne.b   dja_real
dja_disarm:
    clr.b   G_ARMED                    | 0 = idle
    moveq   #-1,%d1
    move.b  %d1,G_PCPAT                | 0xff = "no PC sent yet"
    bra.b   dja_ret
dja_real:
|   send the Program Change once per distinct pending pattern
    move.b  PEND_PAT,%d0
    cmp.b   G_PCPAT,%d0
    beq.b   dja_armstep
    move.b  %d0,G_PCPAT
    moveq   #0,%d0
    move.b  PEND_PAT,%d0
    move.l  %d0,-(%sp)                 | arg1: pending pattern
    moveq   #0,%d0
    move.b  PEND_BANK,%d0
    move.l  %d0,-(%sp)                 | arg0: pending bank
    jsr     PC_SEND
    addq.l  #8,%sp
dja_armstep:
    move.b  STEP,%d0
    move.b  %d0,G_STEP                 | diagnostic only: the TICK-within-step at arm time
|   Session 82: ARM ONLY. Never force the step body.
|
|   This function runs once per CLOCK TICK, not once per master step -- MEASURED
|   (tools/diag_tick_domain.py, stock, DJTEST2 A07): 0x800065b6 takes only the values
|   0..5 with LEN_TBL[SCALE_IX] == 6, and the per-track step advance at 0x400a3d78 fires
|   once every 6 of these for a 1x track and once every 3 for the 2x track. So
|   0x800065b6 is the master TICKS-WITHIN-STEP counter (wrapping at ticks-per-step), the
|   step body at 0x400a4220 is gated on it being 0, and the Program Change block at
|   0x400a413e is gated on it being 2.
|
|   The old code here cleared it to force the step body to run on THIS tick -- i.e. at
|   whatever sub-step instant the pattern change happened to be requested. That did not
|   just commit early: it moved the grid, because the very same counter is the phase of
|   every subsequent step. Reported on hardware as patterns drifting off the master clock
|   by a FRACTION of a step, the fraction depending on when the change was pressed.
|
|   AR never does this. `FUN_4009905c` counts `DAT_405667e4` down to the next
|   step/resolution boundary and commits THERE; nothing in its path writes the tick
|   phase. Arming and waiting is the whole of AR's timing discipline.
|
|   Stock's step body runs every master step anyway, and Hook B already bypasses the
|   CHAIN-AFTER gate whenever we are armed -- so simply staying armed commits on the next
|   natural step boundary, which is exactly AR's rule, with the grid untouched.
    moveq   #-1,%d0
    move.b  %d0,G_ARMED                | arm; the next natural step boundary commits
dja_ret:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
    tst.b   STOPFLAG                   | displaced original (sets Z for the beq.w)
    rts

| ================= Hook B @ 0x400a42fa =================
| detour replaces `move.l #0x8e56,%d0` (6 B), inside the step==0 body, just before the
| CHAIN-AFTER gate.  If armed: bypass the gate straight to the "switch confirmed" label.

    .global dj_b
dj_b:
    tst.b   G_ARMED
    beq.b   djb_orig
    move.l  #SW_LABEL,(%sp)            | return into 0x400a43a0 instead of 0x400a4300
    moveq   #1,%d6                     | D6 = "pending is a real change" (gate would set it)
    rts
djb_orig:
    move.l  #0x8e56,%d0               | displaced original
    rts

| Hook T (`dj_tstart` @0x4009c3d4) DELETED in Session 83 -- it existed only to reset
| `G_ABSTICK` at transport start. With the playhead read straight from stock's own
| `0x800065b2` there is no counter of ours to zero, and the site is stock again.

| ================= Hook H @ 0x400a47f6 -- THE WHOLE FEATURE =================
| detour replaces `lea (0x400eb034).l,%a0` (6 B, bytes 41f9400eb034).
|
| Session 83: PORTED FROM ANALOG RYTM, replacing the absolute-time model outright.
|
| ---- why the old model was wrong ----
| OT has exactly ONE position counter and we had built a SECOND one. `0x800065b2` (the word
| incremented once per master step at 0x400a423a) is what the whole machine runs on:
|     metronome / beat+bar flags   0x400a4264-0x400a42ca, masking it against 1,3,7,15,31,
|                                  63,127,255 (0x400abae4) and 1,3,7,15,31,63 (0x400abacc),
|                                  plus a `mod 3` test at 0x400a4292
|     CHAIN-AFTER switch point     0x400a4352, masterStep mod chainLen == 0
|     stock's Program Change lead  0x400a41aa, (masterStep + 1) mod chainLen == 0
| `G_ABSTICK` was a parallel counter on a different hook with a different origin. We derived
| the resume position from OURS, and stock then reseeded 0x800065b2 from 0x8000662a -- the
| low word of the very long this hook writes -- so every commit YANKED THE METRONOME to
| wherever our separate counter happened to be. The two agreed only by coincidence, a
| different coincidence each switch. Reported on hardware exactly so: "no matter when a
| switch occurs both should be on step X; they are not, and they get offset relative to the
| steady 1 2 3 4 of the metronome. Each switch offsets to a different step."
|
| AR cannot have this bug, and the reason is structural, not clever: it has one counter and
| the commit derives the new position from that same counter.
|
| ---- AR's model, measured (ar-kyoti-fw/MECHANISM.md 5, AR_DIRECT_JUMP.md 2) ----
|     new_step = DIRECT START ? 0 : (masterStep mod newPatternLen)     ; 0x40099252-0x4009927a
|     pos_t    = new_step mod trackLen_t                               ; 0x4009927c-0x400992d2
| where AR's masterStep `DAT_405666e4` is BOUNDED -- it wraps at the pattern length
| (0x40099b8a-0x40099ba6).
|
| ---- OT's equivalent, MEASURED (tools/diag_playhead.py, stock) ----
| `0x800065b2` cycles 1,2,...,15,0,1,... with MASTER LENGTH 16 -- range 0..15, period 16,
| confirmed on DJTEST2 A07 (tps 6) AND A08 (tps 3), so the period is in STEPS and is the
| master length, not an artefact of one scale. It is the direct analogue of AR's
| `DAT_405666e4`: a bounded playhead index.
|
| So the port is one modulo:
|
|     0x80006628 = 0x800065b2 mod newMasterLen
|
| Stock does everything else. It multiplies that up into D7 at 0x400a4812/0x400a4826, its
| own rebuild loop at 0x400a4884 distributes it per track against each track's own length,
| and it reseeds 0x800065b2 itself from our low word at 0x400a483a -- which now feeds the
| metronome THE SAME NUMBER the patterns got, by construction. One counter again.
|
| Site: 0x80006628 is read at 0x400a4812/0x400a4826 and 0x800065b2 is reseeded at
| 0x400a483a, so this hook must land before both. 0x400a47f6 is the last 6-byte instruction
| on the commit path that does. D0 holds the pattern-blob offset here (built
| 0x400a47c4-0x400a47e4) and is indexed by the very next instruction at 0x400a4802, so it
| MUST survive. Flags are free: the displaced `lea` sets none.
|
| DELETED with this change, all of it scaffolding for the second clock: `G_ABSTICK`, Hook E
| (`dj_abstick` @0x400a3fe4), Hook T (`dj_tstart` @0x4009c3d4), the master-cycle tick
| reduction, and the `dj_div32`/`dj_mod32` long-division helpers. Both operands here are
| bounded by the master length (<= 64), so a subtract loop is exact and terminates fast.
|
| Difference from AR that remains, and is deliberate: stock's rebuild loop divides by each
| track's OWN ticks-per-step, so a track at a different multiplier gets rate-corrected where
| AR's flat `new_step mod trackLen` would not. That is OT machinery we would have to replace
| the loop to remove. Everything running at the master rate is AR-exact.

    .global dj_d7
dj_d7:
    tst.b   G_ARMED
    beq.b   djd7_orig
    lea     -20(%sp),%sp
    movem.l %d0-%d3/%a1,(%sp)
    move.l  %d0,%d3                    | d3 = pattern blob offset (caller's D0, preserved by
                                       | the movem and restored before we return)
|   ---- newMasterLen -> d1 ----
    lea     PAT_SMODE,%a1
    tst.b   (%a1,%d3.l)                | SCALE_MODE
    beq.b   djd7_unif
    lea     PAT_MLEN,%a1               | per-track mode -> MASTER LENGTH (+0x8e51)
    bra.b   djd7_gotlen
djd7_unif:
    lea     PAT_LEN,%a1                | uniform mode  -> pattern LENGTH (+0x8e53)
djd7_gotlen:
    moveq   #0,%d1
    move.b  (%a1,%d3.l),%d1
    tst.l   %d1
    ble.b   djd7_zero                  | unreadable length -> restart at 0, exactly as stock
                                       | leaves 0x80006628 at a natural boundary
|   ---- d0 = masterStep mod newMasterLen ----
    moveq   #0,%d0
    move.w  MASTER_STEP,%d0            | the LIVE playhead; stock reseeds it from our low
                                       | word at 0x400a483a, i.e. AFTER this hook
djd7_mod:
    cmp.l   %d1,%d0
    blt.b   djd7_store                 | already < newMasterLen -> done
    sub.l   %d1,%d0
    bra.b   djd7_mod
djd7_zero:
    moveq   #0,%d0
djd7_store:
    move.l  %d0,MASTER_STEPS           | resume position, in master steps
    movem.l (%sp),%d0-%d3/%a1
    lea     20(%sp),%sp
djd7_orig:
    lea     0x400eb034,%a0             | displaced original
    rts


| ================= Hook C @ 0x400a4840 =================
| detour replaces `clr.b %d0 ; move.b %d0,(0x800065b6).l` (8 B) -> jsr dj_c + nop.
| Not armed: just do DAT_800065b6 = 0.  Armed: set DAT_800065b6 to (savedStep % newLen)
| so the master step resumes at the playhead.  D6/D7 are live here; D0-D2/A0 are free.
|
| ** Session 69 continued: back to raw D7 = resumeStep, this time with the actual
| divsl targets confirmed via `m68k-elf-objdump` (r2's m68k analyzer misdecodes divsl.l/
| remsl.l here as `invalid` and was silently misleading every prior static read of this
| region). Ground truth for BOTH per-track loops (audio @0x400a4884, MIDI @0x400a4a14):
|
|   0x800065e4[t] / 0x800065f4[t]  =  QUOTIENT of (D7-1+trackLen[t]) / trackLen[t]
|   0x80006604[t] / 0x80006614[t]  =  REMAINDER  =  D7 mod trackLen[t]  (floor-corrected)
|
| i.e. 0x800065e4/f4 is a loop-REPEAT counter (0 = "first pass", not a bug when it reads
| 0), and 0x80006604/14 -- the array dj_c has targeted since Session 60 -- IS the real
| per-track step/phase position, exactly as originally intended. Session 69's Finding
| (4b) ("0x800065e4[t] resets to 0, matches the HW symptom") was most likely a
| misattribution: that array reading 0 is expected/correct for an ordinary jump; it is
| NOT what FUN_400a3ca6 (the per-tick trig-fire dispatcher, self-increments this exact
| counter and fires when it wraps past trackLen) reads.
|
| D7's role: stock's own boundary-commit sets D7 = LEN_TBL[newScale] * DAT_80006628
| (loop-region-start-in-bars * patternLen) -- both terms already in STEP units, same
| units as trackLen -- so D7 is just "how many absolute steps has this loop-region
| played so far", normally 0. Session 65's `resumeStep * DAT_80006628` fix computed 0
| whenever DAT_80006628 is 0 (i.e. always, absent a custom LOOP FROM/TO region) --
| exactly Session 69's dynamically-confirmed neutering. Since D7 is already in the same
| step units as trackLen (no conversion needed), the fix is Session 60's ORIGINAL raw
| value: D7 = resumeStep directly. Session 61's revert (D7 "is a TICK count, stomping
| it with a raw step index feeds garbage units") does not hold up against this
| disassembly -- both quantities are step counts, dimensionally compatible as-is.
| Whatever actually broke on Session 60's hardware attempt is not explained by a unit
| mismatch; NOT YET RE-TESTED on real hardware, this build only re-tries it under
| tools/emu_directjump_dynamic.py before any flash is proposed.

    .global dj_c
dj_c:
    tst.b   G_ARMED
    bne.b   djc_fix
|   Session 79 ("continued a nineteenth time"): the 8 displaced bytes here are TWO stock
|   instructions -- `clr.b %d0` (0x4200) THEN `move.b %d0,STEP` (0x13c0 800065b6) -- so
|   stock leaves D0 == 0 on the way out. This path replayed only the STEP write and left D0
|   holding whatever it had, a real (if probably harmless) deviation from stock on EVERY
|   commit, DIRECT JUMP on or off: the stock code immediately after reads D6 and then
|   reloads registers, so D0 looks dead there, but "looks dead in the disassembly I could
|   read" is exactly the standard of evidence that has burned this thread before. Replay
|   both instructions exactly and the question stops mattering.
    clr.b   %d0                         | displaced original #1 (stock leaves D0 = 0)
    move.b  %d0,STEP                    | displaced original #2 (STEP = D0 = 0)
    rts
djc_fix:
    clr.b   G_ARMED
|   newLen = LEN_TBL[ PAT_SCALE[ newBank*0x9b340 + newPat*0x8ed8 ] ]
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  #0x8ed8,%d1
    muls.l  %d1,%d0                    | d0 = pat * 0x8ed8
    moveq   #0,%d1
    move.b  ACT_BANK,%d1
    move.l  #0x9b340,%d2
    muls.l  %d2,%d1                    | d1 = bank * 0x9b340
    add.l   %d1,%d0
|   Session 82: branch on SCALE_MODE, exactly as dj_scaleix_fix (Hook D) already does and as
|   stock's own D7 setup does at 0x400a4802-0x400a4826. This hook read PAT_SCALE (+0x8e54)
|   UNCONDITIONALLY -- cont.33 found and fixed that bug in Hook D and left the identical bug
|   here, where it survived because nothing measured the tick RATE after a commit until
|   tools/diag_grid_lock.py.
|
|   MEASURED (grid_lock, DJTEST2 A07 -> A08, whose fields were chosen to separate the two:
|   +0x8e52 = 0 (2x, tps 3) against +0x8e54 = 2 (1x, tps 6)): the commit wrote index 2, so
|   the master wrap check ran the FIRST step of the incoming pattern at 6 ticks instead of 3,
|   and Hook D then healed it on the next step body. One step at the outgoing pattern's rate
|   after every jump between patterns of differing MASTER SCALE -- visible in the boundary
|   trace as a single 6-tick gap before the 3-tick gaps begin.
    lea     PAT_SMODE,%a0
    tst.b   (%a0,%d0.l)                | SCALE_MODE
    beq.b   djc_uniform
    lea     PAT_MSCALE,%a0             | per-track mode -> MASTER SCALE at +0x8e52
    bra.b   djc_gotscale
djc_uniform:
    lea     PAT_SCALE,%a0              | uniform mode  -> pattern multiplier at +0x8e54
djc_gotscale:
    moveq   #0,%d1
    move.b  (%a0,%d0.l),%d1            | d1 = scale index (of the pattern that's NOW active)
|   Session 70 (4th pass, hardware bug): stock's own commit-tail (0x400a4220, unmodified,
|   runs unconditionally on every switch commit whether or not DIRECT JUMP is on) writes
|   SCALE_IX from a register computed BEFORE the ACT_PAT=PEND_PAT copy at 0x400a44d0 -- i.e.
|   it stores the OUTGOING pattern's scale index, not the incoming one. Confirmed via a
|   double-switch dynamic test with two differently-scaled patterns (idx2/len6 <-> idx5/
|   len24): SCALE_IX read 0x2 (still pattern0's) right after committing TO pattern1, and
|   0x5 (still pattern1's) right after committing back to pattern0 -- in both cases the
|   PREVIOUS pattern's index, one commit stale. The master-step wrap check
|   (LEN_TBL[SCALE_IX], 0x400a3ff8) then uses the WRONG pattern's length until the next
|   commit, letting STEP run past its real length before wrapping -- reproduces the user's
|   HW report exactly (plays past its own length, e.g. to "step 16", before restarting).
|   Not introduced by any dj_a/b/c hook (0x400a4220 is untouched stock code) -- normally
|   masked because stock's own CHAIN-AFTER gate rarely lets two commits land back-to-back;
|   DIRECT JUMP's whole point is fast switching, so it hits this every time. Fix: SCALE_IX
|   already needs recomputing here for `d1` (LEN_TBL lookup) -- just also store the raw
|   scale index (before the LEN_TBL indirection overwrites d1) back into the live register,
|   undoing stock's stale write.
    move.b  %d1,SCALE_IX
|   Session 82: the resume-position computation that used to live here is GONE, and with
|   it the whole hand-rolled 32-bit division (djc_divloop) and the PAT_LEN lookup that fed
|   it. It wrote its result into 0x800065b6 -- which MEASUREMENT (tools/diag_tick_domain.py)
|   shows is not a master STEP counter at all but the master TICKS-WITHIN-STEP counter,
|   range 0..LEN_TBL[SCALE_IX]-1. Writing a step index (0..63) into a counter that wraps at
|   ticks-per-step (typically 6) meant the wrap check at 0x400a3ff8 fired on the very next
|   clock tick, so the first step after every armed commit was ONE TICK long instead of six:
|   a second, independent way the grid came unstuck from the master clock.
|
|   The resume position was never this counter's job anyway. Hook H (0x400a47f6) supplies it
|   as a master-step offset in 0x80006628, from which stock builds D7 and its own per-track
|   rebuild loop derives every track's position -- AND from whose low word (0x8000662a) stock
|   seeds the real master step counter BAR_CTR (0x800065b2) at 0x400a483a, one instruction
|   before this hook runs. 0x800065b2 is measured incrementing once per master step at
|   0x400a423a, so that seeding is what actually resumes the master position. Stock's own
|   `STEP = 0` here is a tick-phase reset that is a no-op at a step boundary -- which, now
|   that Hook A only arms and never forces, is the only place an armed commit can land.
|
|   So: replay stock exactly on both paths. The SCALE_IX correction above stays -- it fixes a
|   real latent stock bug (stale scale index for one cycle after a commit) and is unrelated
|   to the tick phase.
    clr.b   %d0                        | displaced original #1 (stock leaves D0 = 0)
    move.b  %d0,STEP                   | displaced original #2 -- tick phase, 0 at a boundary
|   Session 70 (3rd pass): raw D7=resumeStep only nudges the REAL fire-gate counter
|   (0x800064d0/8[t], "REFILL_TBL") coarsely -- confirmed dynamically that REFILL_TBL is
|   reloaded every step from the QUOTIENT array (0x800065e4/f4[t] low byte), computed by
|   stock's own per-track loop below as floor((D7-1+trackLen)/trackLen); raw D7=resumeStep
|   makes that quotient 0 or 1 (whether resumeStep>=1), not resumeStep itself. Since D7 is
|   otherwise free (only consumed by that same formula, for every track against ITS OWN
|   trackLen), scaling by newLen (the just-computed MASTER pattern length, still in d1)
|   makes the quotient come out to resumeStep exactly for any unscaled track (trackLen ==
|   newLen): floor((resumeStep*newLen - 1 + newLen)/newLen) = resumeStep. Per-track-SCALEd
|   tracks (trackLen != newLen) are not made exactly right by this (same open item as
|   Session 15's #4, still unresolved), but no worse than the raw-D7 version for them either.
|   Session 79 cont.28: the D7 override that used to live here is GONE. It set
|   D7 = resumeStep * LEN_TBL[scale], which -- given the LEN_TBL correction above -- was
|   resumeStep * ticksPerStep, and it ran at 0x400a4840, i.e. AFTER stock builds D7 at
|   0x400a4812/0x400a4826 and BEFORE the per-track rebuild loop reads it at 0x400a4884.
|   So it silently replaced the correct absolute offset with a small wrong one on every
|   armed commit. Hook H (0x400a47f6) now seeds 0x80006628 = G_ABSTICK so stock builds
|   the right D7 itself; overriding it here would undo exactly that. Measured: with both
|   present, D7 was 156 at 0x400a4834 and 12 by the time the loop ran.
|   Session 79 (NOTES.md, "continued a thirteenth/fourteenth time"): tried deriving
|   BAR_CTR (0x800065b2) fresh from G_ABSTICK here, on the theory that its mid-loop
|   reset (copied from 0x8000662a immediately before this hook runs) was the driver of
|   the permanently-shifted table-arm write schedule Hooks G/G2 (below) can only
|   suppress one write at a time, not correct. Built and dynamically re-tested:
|   BYTE-IDENTICAL table-arm write cadence and final mismatch count (19/64) with and
|   without this fix -- proves BAR_CTR is NOT the schedule driver. Reverted rather than
|   left in: zero measured benefit, and forcing BAR_CTR away from its stock value on
|   every DIRECT JUMP commit carries unquantified regression risk for whatever else
|   reads it. The real driver is very likely CNTDN_TBL (0x800065c3[t]) being armed to
|   0x1 at commit and firing (idling) exactly at the extra write's own frame -- see
|   NOTES.md, "continued a fifth/seventh time" (found and retracted as a DIFFERENT
|   branch's cause earlier this thread) and "continued a fourteenth time" (re-confirmed
|   as the timing match against this session's own Hooks-G-suppressed re-test). Not
|   re-attempted this pass; the `dj_quot32` helper this fix used has been removed along
|   with it (dead code, nothing else called it).
    moveq   #1,%d0
    move.b  %d0,G_JUST_COMMITTED        | tell Hook F a real commit happened this tick
    rts

| ================= Hook D @ 0x400a4220 =================
| Session 70 (5th pass, HARDWARE BUG): dj_c's SCALE_IX correction (Hook C, above) only
| lasts ONE tick -- confirmed dynamically (a double-switch test between two DIFFERENTLY
| SCALED patterns, forced idx2/len6 vs idx5/len24): the master STEP register correctly
| wrapped at 6 on the FIRST post-switch tick (dj_c's fix working), then on the VERY NEXT
| ordinary (non-switching) step==0 tick climbed all the way to 24 before wrapping --
| SCALE_IX had been overwritten AGAIN, back to the wrong pattern's value, by stock's own
| unmodified code at 0x400a4220.
|
| Root cause (found via `m68k-elf-objdump` static read + a live A4/D2 register-dump probe
| at 0x400a4220, since r2 + guesswork kept giving wrong answers here): 0x400a4220 is
| `moveb D2,(0x8000663d).l`, where D2 was computed WAY back at the very top of this whole
| per-step handler (~0x400a3fc8) as `*(A4 + (SCALE_MODE(A4) ? 0x8e52 : 0x8e54))` -- i.e.
| SCALE_IX gets refreshed from a byte inside the pattern blob A4 POINTS TO. Confirmed live:
| **A4 never changes across the whole test** (stays at bank0/pattern0's blob, 0x400e21e0,
| even while pattern1 is the ACTUALLY active pattern) -- this per-step handler's "current
| pattern" pointer is simply never reloaded on a plain manual switch (Session 3-6's own
| notes: the 3 big "pattern-reload blocks" that DO refresh it are for arranger/chained-list/
| immediate-reload paths only; "a plain manual pattern change while running does NOT use
| them"). This is a LATENT STOCK QUIRK, not something any dj_a/b/c hook introduces --
| 0x400a4220 and its D2 source are untouched stock code, reached by BOTH a stock
| CHAIN-AFTER-gated switch and a DIRECT JUMP one identically. It's presumably unnoticed on
| real hardware because stock's own gate rarely lands two switches close enough together,
| and most users don't rely on manual pattern-key switches between differently-scaled
| patterns; DIRECT JUMP's whole point is fast, frequent switching, so it hits this hard.
|
| Fix: detour 0x400a4220 itself (6 B, exactly `jsr <cave>` sized, no nop needed) to
| unconditionally recompute SCALE_IX fresh from the LIVE, always-correct ACT_BANK/ACT_PAT
| globals (same formula dj_c already uses for newLen) instead of storing stale D2. This
| runs on EVERY step==0 tick, switching or not:
|   - an ORDINARY tick (no switch pending): ACT_PAT is already stable/correct at this
|     point (0x400a4220 runs before any commit only matters when a REAL switch commits
|     this same tick) -- this hook alone fixes the "frame 633" self-heal-fails regression.
|   - a SWITCHING tick: this hook runs BEFORE the ACT_PAT=PEND_PAT commit (0x400a44d0),
|     same as stock's own broken D2, so it still writes the OUTGOING pattern's index here
|     -- but Hook C (dj_c, above) ALREADY runs AFTER the commit and re-corrects it within
|     the SAME tick. The two hooks compose: Hook D fixes every ordinary tick from here on,
|     Hook C fixes the one tick a switch actually lands on.
| Not yet re-verified dynamically as of writing this comment -- see the build/test
| immediately following in NOTES.md before trusting this without checking.

    .global dj_scaleix_fix
dj_scaleix_fix:
|   ColdFire has no `movem -(An)` -- lea a frame, movem into it (same idiom as dj_a).
    lea     -16(%sp),%sp
    movem.l %d0-%d2/%a0,(%sp)
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  #0x8ed8,%d1
    muls.l  %d1,%d0                    | d0 = pat * 0x8ed8
    moveq   #0,%d1
    move.b  ACT_BANK,%d1
    move.l  #0x9b340,%d2
    muls.l  %d2,%d1                    | d1 = bank * 0x9b340
    add.l   %d1,%d0
|   Session 79 cont.33: this used to read PAT_SCALE (+0x8e54) unconditionally. Measured on
|   the DJTEST2 fixture, which was built specifically to separate the two fields: stock's own
|   D7 setup at 0x400a4802-0x400a4826 selects +0x8e52 (MASTER SCALE) when SCALE_MODE is set
|   and +0x8e54 (the pattern TEMPO MULTIPLIER) only when it is clear. DJTEST2 A08 has
|   +0x8e52 = 0 (2x) against +0x8e54 = 2 (1x), and stock built D7 = 78 = 3 * 26 from the
|   MASTER SCALE -- so writing +0x8e54 into SCALE_IX left the master wrap check using 6
|   ticks/step where the pattern actually runs at 3. That is Session 70's original
|   "pattern plays past its own length" symptom, still present in the fix meant to cure it.
    lea     PAT_SMODE,%a0
    tst.b   (%a0,%d0.l)                | SCALE_MODE
    beq.b   djs_uniform
    lea     PAT_MSCALE,%a0             | per-track mode -> MASTER SCALE at +0x8e52
    bra.b   djs_got
djs_uniform:
    lea     PAT_SCALE,%a0              | uniform mode  -> pattern multiplier at +0x8e54
djs_got:
    move.b  (%a0,%d0.l),%d1            | d1 = the scale index stock's own D7 code would use
    move.b  %d1,SCALE_IX
    movem.l (%sp),%d0-%d2/%a0
    lea     16(%sp),%sp
    rts

| Hook F (`dj_pertrack_fix` @0x400a4d36) DELETED in Session 83, together with the
| `dj_div32` / `dj_mod32` long-division helpers that only it and the old tick-domain Hook H
| used. It had already been unhooked in Session 79 cont.29 after being measured clobbering
| 7 of 8 audio tracks (it computed `G_ABSTICK mod LEN_TBL[scale]`, i.e. modulo
| TICKS-PER-STEP, and wrote it into the per-track STEP array -- audio/MIDI desync on every
| armed commit). It is removed outright now rather than left as unbuilt source, because it
| referenced `G_ABSTICK`: dead code depending on a counter nothing maintains is a trap for
| a later session. The full account is in NOTES.md Session 79 cont.29 and Session 83.

    .ifdef DJ_KEYMAP
| ================= [PTN] release -- close the toast almost immediately =================
| detour replaces the first 6 bytes of FUN_40043418 (`pea 0x400bf0f2`), the stock
| "tear down the PTN-held overlay" cleanup.  Confirmed the ONLY jsr caller of
| FUN_40043418 image-wide is 0x4005a0c4, inside FUN_4005a044's own RELEASE branch --
| i.e. this runs on every [PTN] release, whether or not our combo fired (a quick tap
| alone reaches it too).  Matches the user's ask: "the toast needs to disappear
| immediately if the user releases PTN, just like we did with REC on QLREC."
|
| ** Session 62 tried `jsr NOTIFY_CLOSE` here and the unit threw EXCEPTION VEC:04 at
| ADDR 0x400BF0F2. Session 63's fix (below, touching only two data words, no jsr at
| all) threw the IDENTICAL exception -- proving the Session 62 diagnosis (a bad
| interaction with NOTIFY_CLOSE's own list surgery) was WRONG. The real bug was
| always in this hook's OWN stack discipline, present in every version:
|
|   `pea 0x400bf0f2` is not an inert instruction to "replay" -- it's a stock PUSH,
|   and the value it pushes is MEANT TO STAY on the stack as an argument for
|   FUN_40043418's own later `jsr FUN_3146c` (0x4004341e) and `jsr FUN_7e81c`
|   (0x40043424..2a), both of which read it without popping -- FUN_40043418 only
|   cleans it up once, at the very end (`addql #8,%sp` @0x40043440, for it AND a
|   second pushed pointer together).  This build's detour is kind=jsr, so entering
|   dj_ptnrel ALREADY has a correct return address (0x4004341e, auto-pushed by the
|   `jsr dj_ptnrel` planted at the detour site) sitting on top of the stack.  Every
|   earlier version of this hook then did `pea 0x400bf0f2 ; rts` -- but that `pea`
|   pushes 0x400bf0f2 ON TOP OF that return address, so the following `rts` pops
|   THE PEA'D VALUE, not the real return address, and "returns" by jumping straight
|   to 0x400bf0f2 -- exactly the crash address, on literally every single call
|   (matching djt_stock in this same file, which replays two register-only moves
|   then `jmp`s a literal address -- NOT `rts` -- for exactly this reason: `rts`
|   after a stub that itself pushes something is only safe when that stub's push is
|   ALSO what the caller-side kind=jsr auto-return machinery expects, which a `pea`
|   whose value must survive as an outgoing argument never is).
|
| Fix: this detour is now kind=jmp (see build_directjump_v4.py), so entering
| dj_ptnrel pushes NOTHING -- the stack is exactly what stock would have at this
| point.  `pea 0x400bf0f2` then pushes the one, correct, surviving argument, and
| a literal `jmp 0x4004341e` (not `rts`) falls through to the untouched rest of
| FUN_40043418's body, matching djt_stock's own idiom exactly.
|
| The toast-close mechanism itself (only ever writing two plain data words the
| stock per-frame tick @0x40056c28 already reads, closing the toast via NOTIFY_CLOSE
| from the OS's own safe context one frame later, never called by us directly) is
| unchanged and was never the problem.
    .global dj_ptnrel
dj_ptnrel:
    tst.l   NOTIFY_HANDLE               | 0x460d1e70 -- is a toast actually open?
    beq.b   dpr_done
    moveq   #1,%d0
    move.l  %d0,NOTIFY_COUNTDOWN        | 0x460d1e6c -- stock's own tick closes it next frame
dpr_done:
    pea     0x400bf0f2                  | displaced original -- the value MUST survive on
                                        | the stack, so no rts (see kind=jmp note above)
    jmp     PTN_LAYER_REL_RESUME        | 0x4004341e -- resume FUN_40043418's own body
    .endif
