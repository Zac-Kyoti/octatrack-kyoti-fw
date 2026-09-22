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
    .equ SH_DJ,     0x100fff68          | its 'ANDY' battery-SRAM shadow
    .equ CKSUM,     0x4001f23c          | FUN_4001f23c -- recompute the ANDY block checksum
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
    .equ G_ABSTICK, 0x80006a46          | absolute step-tick counter (long) since transport
                                        | started -- NEVER reset or wrapped by a pattern
                                        | switch, unlike DAT_800065b6 (which is bounded to
                                        | the CURRENTLY ACTIVE pattern's own length and so
                                        | has already lost the information needed to resume
                                        | a DIFFERENT-length pattern correctly once it has
                                        | wrapped even once)
    .equ G_JUST_COMMITTED, 0x80006a4a   | one-shot: dj_c sets this; Hook F (below) consumes
                                        | it once, after BOTH per-track loops have finished
                                        | for this tick, then clears it
    .equ ACT_PAT,   0x800065be
    .equ ACT_BANK,  0x800065bd
    .equ PEND_PAT,  0x800065c0
    .equ PEND_BANK, 0x800065bf
    .equ STEP,      0x800065b6
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
    .equ STEP_IN_PAT, 0x800064f0        | per-track step-within-pattern counter, 1 byte per
                                        | track. Stock: ++ at 0x400a3ce2 every step tick,
                                        | wrapped to 0 at 0x400a3cf6 on reaching the track's
                                        | length, and force-reset to 0 for all 8 tracks by
                                        | the switch-commit tail at 0x400a4bf0. Reading 0 is
                                        | the sole gate (0x400a2d28) for DAT_80001904's
                                        | table-arm write -- see dj_pertrack_fix.
    .equ BAR_CTR,   0x800065b2          | "which bar/loop repetition" counter (word),
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
    move.l  %d0,SH_DJ                  | battery-SRAM shadow
    jsr     CKSUM                      | re-checksum the ANDY block (bypasses the menu path)

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

| ================= Hook E @ 0x400a3fe4 =================
| detour replaces `move.b %d0,(0x800065b6).l` (6 B) -- the STORE half of the UNCONDITIONAL
| per-tick master-step increment (`0x400a3fdc: moveb STEP,d0 ; addq#1,d0 ; moveb d0,STEP`),
| which runs every step tick regardless of DIRECT JUMP mode, before hook A even gets
| control. Session 70 (7th pass): replays the displaced store (d0 must survive unclobbered
| -- the caller re-uses it at 0x400a3fea/3ff8 for the wrap check) then unconditionally bumps
| `G_ABSTICK`. Deliberately NOT gated on `DJ_MODE` -- the counter needs to reflect true
| elapsed ticks whenever DIRECT JUMP is next armed, not just while it happens to be on;
| the cost is one extra long add per tick, always.

    .global dj_abstick
dj_abstick:
    move.b  %d0,STEP                   | displaced original (d0 must stay unclobbered)
    lea     -4(%sp),%sp
    movem.l %d1,(%sp)
    move.l  G_ABSTICK,%d1
    addq.l  #1,%d1
    move.l  %d1,G_ABSTICK
    movem.l (%sp),%d1
    lea     4(%sp),%sp
    rts

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
    move.b  %d0,G_STEP                 | always keep the resume step fresh
    tst.b   G_ARMED
    bne.b   dja_commit
    moveq   #-1,%d0
    move.b  %d0,G_ARMED                | tick 1: arm only (1 step of PC lead)
    bra.b   dja_ret
dja_commit:
    clr.b   STEP                       | tick 2: force the step==0 body this tick
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

| ================= Hook T @ 0x4009c3d4 =================
| detour replaces `move.l %d0,(0x800065b8).l` (6 B, bytes 23c0800065b8) -- the store that
| sets TRANSPORT = 1, immediately after `moveq #1,D0` at 0x4009c3d2. Unambiguously "the
| transport just started".
|
| Session 79 cont.34. G_ABSTICK was incremented at dj_abstick and cleared NOWHERE, so it
| counted from power-on. Hook H turns it into DIRECT JUMP's resume offset, and the rebuild
| loop stores that offset's quotient as a WORD read back sign-extended, so the usable range
| is ~32767 master steps -- about 68 minutes at 120 BPM with 16th steps. Counting from
| power-on made that reachable in one sitting; counting from transport start makes it
| reachable only in a single unbroken 68-minute take.
|
| It is also the semantically correct origin. The user's model for the feature is that every
| pattern behaves as if it had been playing silently since the transport started -- not since
| the machine was switched on -- so resetting here is what the feature actually means, and
| the range improvement is a consequence rather than the justification.
|
| Not gated on DJ_MODE: G_ABSTICK is our own scratch global that no stock code reads, so
| clearing it cannot change stock behaviour with the feature off. dj_abstick's increment is
| ungated for the same reason.
|
| The displaced store is replayed verbatim rather than assuming D0 == 1, so if any other
| path reaches this instruction with a different value it still behaves exactly as stock.
| (Clearing the counter on such a path would be harmless in any case.)

    .global dj_tstart
dj_tstart:
    clr.l   G_ABSTICK                  | absolute tick origin = transport start
    move.l  %d0,TRANSPORT_L            | displaced original
    rts

| ================= Hook H @ 0x400a47f6 =================
| detour replaces `lea (0x400eb034).l,%a0` (6 B, bytes 41f9400eb034).
|
| Session 79 (cont.21/26/27). The whole thread up to here treated DIRECT JUMP as something
| that must REBUILD per-track state after the fact -- hence Hooks D/E/F, each repairing one
| per-track global that the commit had left stale. That was backwards. Stock already
| contains AR's per-track rebuild, at 0x400a4884-0x400a49e2 (audio) and its MIDI twin from
| 0x400a49e6, inside a 1586-byte region Ghidra had never decoded (cont.21). Per track it
| does, using that track's OWN scale and OWN length:
|
|     tps_t        = LEN_TBL[scale_t]                        ticks per step
|     q            = (D7 - 1 + tps_t) / tps_t                0x400a4912
|     NEXT_STEP[t] = q mod length_t                          0x400a4976, stored 0x400a497a
|     PAIR[t]      = D7 - q*tps_t                            0x400a4920, stored 0x400a4924
|
| and the boundary body then seeds STEP[t] from NEXT_STEP[t] at 0x400a4be6. Its ONLY
| position input is D7, built at 0x400a4812/0x400a4826 as
| `LEN_TBL[masterScale] * *(long)0x80006628` -- so 0x80006628 is a START OFFSET IN MASTER
| STEPS, and it is normally 0, which is why every commit restarts every track at step 0.
|
| MEASURED, not inferred (cont.27, tools/diag_d7_inject.py, which overrides the D7 register
| in the emulator and compares the arrays the loop actually produces against that model):
|   - stock, natural boundary, D7 = 0            -> 16/16 tracks match (all zero)
|   - stock, D7 = 48 forced, switching INTO the SCALE_MODE=1 pattern -> 16/16 match, with
|     tps=6/len=16 tracks landing on 8, the SCALE=0 (tps=3) track landing on 0 because
|     48/3 = 16 steps is a full cycle of its length, and the LEN=12 track landing on 8.
| So a non-zero D7 distributes coherently across BOTH differing scales and differing
| lengths. cont.23's earlier reading of 0x80006628 as "pattern length" was refuted by the
| same measurement and must not be reintroduced.
|
| Therefore DIRECT JUMP needs no per-track machinery of its own: give the loop the right
| offset and stock does the rest. The right offset is G_ABSTICK, not G_STEP -- see Hook C's
| own Session 70 (7th pass) comment: once STEP has wrapped against the outgoing pattern's
| length the elapsed-time information is gone, and modulo against a different length cannot
| recover it. G_ABSTICK never resets, so
|     D7 = LEN_TBL[masterScale] * G_ABSTICK  = absolute ticks
|     NEXT_STEP[t] = (absTicks / tps_t) mod length_t
| which is exactly the user's stated model: every pattern behaves as if it had been playing
| silently the whole time at ITS OWN length, and switching only changes which one you hear.
|
| Site choice: 0x80006628 is READ at 0x400a4812/0x400a4826, so the write must land before
| them; 0x400a47f6 is the last 6-byte instruction on the commit path that precedes both.
| D0 holds the pattern-blob offset here (built 0x400a47c4-0x400a47e4) and is indexed by the
| very next instruction at 0x400a4802 -- it MUST survive, so only D1 is used, saved and
| restored. Flags are free: the displaced `lea` sets none and 0x400a4802 sets its own.
| Gated on G_ARMED so natural boundaries keep 0x80006628 exactly as stock leaves it.
|
| Side effect to keep in view: BAR_CTR is loaded at 0x400a483a from 0x8000662a, the LOW
| WORD of this same long (cont.23), so an armed commit now also seeds BAR_CTR from
| G_ABSTICK's low word instead of 0. Session 79's BAR_CTR experiment (951e2ed) measured
| overriding BAR_CTR as having literally no effect, so this is expected to be inert, but it
| is a deliberate change and not an accident.
|
| Bound not yet checked: D7 = tps * G_ABSTICK is a 32-bit muls.l, so it overflows once
| G_ABSTICK exceeds ~2^31/tps (~357M step-ticks at tps=6). Long before that matters in
| practice, but it is unverified and must not be assumed harmless.

    .global dj_d7
dj_d7:
    tst.b   G_ARMED
    beq.w   djd7_orig
    lea     -40(%sp),%sp
    movem.l %d0-%d7/%a1-%a2,(%sp)
    move.l  %d0,%d6                    | d6 = pattern blob offset (caller's D0 -- preserved
                                       | by the movem, and restored before we return)
|   ---- EXACT RANGE REDUCTION (Session 79 cont.36) ----
|   Every track's landing position is  (G * tps_master / tps_t) mod len_t, which is PERIODIC
|   in G. Reducing G by that period changes nothing about where any track lands -- it is an
|   identity, not an approximation. Working in ticks, the period is
|       P = LCM( tps_master*masterLen , tps_t*len_t for every track )
|   and the master cycle is included so dj_c's master step stays consistent too. Because
|   tps_master*masterLen divides P, we have tps_master | P, so reducing G by M = P/tps_master
|   is exactly equivalent to reducing D7 = tps_master*G by P.
|   For DJTEST2 A07 (lengths 16/16/12/7/16, multipliers 1x/2x/1x/1x/1/2x) P = 4032 -> M = 672,
|   worst-case quotient ~1344 against the 32767 ceiling: 24x headroom, and the ~68-minute
|   limit disappears. Patterns whose P will not fit fall through to the zero fallback below.
|   ---- master tempo multiplier -> d5, master length -> d4 ----
    lea     PAT_SMODE,%a1
    tst.b   (%a1,%d6.l)
    beq.b   djd7_unif
    lea     PAT_MSCALE,%a1             | per-track mode: MASTER SCALE (+0x8e52)
    moveq   #0,%d1
    move.b  (%a1,%d6.l),%d1
    lea     PAT_MLEN,%a1               |                 MASTER LENGTH (+0x8e51)
    moveq   #0,%d4
    move.b  (%a1,%d6.l),%d4
    bra.b   djd7_gotm
djd7_unif:
    lea     PAT_SCALE,%a1              | uniform mode: pattern multiplier (+0x8e54)
    moveq   #0,%d1
    move.b  (%a1,%d6.l),%d1
    lea     PAT_LEN,%a1                |               pattern length (+0x8e53)
    moveq   #0,%d4
    move.b  (%a1,%d6.l),%d4
djd7_gotm:
    cmpi.l  #11,%d1
    bhi.w   djd7_zero
    lea     LEN_TBL,%a1
    move.l  (%a1,%d1.l*4),%d5          | d5 = tps_master
    tst.l   %d4
    ble.w   djd7_zero
    move.l  %d5,%d7
    muls.l  %d4,%d7                    | d7 = P = tps_master * masterLen
|   In uniform mode every track uses the pattern's own length and multiplier, which the
|   master cycle above already covers -- so the per-track fold is only needed in per-track
|   mode.
    lea     PAT_SMODE,%a1
    tst.b   (%a1,%d6.l)
    beq.w   djd7_gotp
|   ---- fold in each AUDIO track's own cycle ----
    moveq   #0,%d0
    movea.l %d0,%a2                    | a2 = track index (helpers clobber d0-d4, so the
                                       | loop counter lives in an address register)
djd7_al:
    move.l  %a2,%d0
    move.l  #0x91a,%d1
    muls.l  %d1,%d0
    add.l   %d6,%d0                    | d0 = blob offset + t*0x91a
    lea     TRK_BLOB,%a1
    moveq   #0,%d2
    move.b  (0x50,%a1,%d0.l),%d2       | this track's LENGTH
    moveq   #0,%d1
    move.b  (0x51,%a1,%d0.l),%d1       | this track's TEMPO MULTIPLIER index
    bsr     dj_foldcyc
    addq.l  #1,%a2
    move.l  %a2,%d0
    cmpi.l  #8,%d0
    blt.b   djd7_al
|   ---- and each MIDI track's ----
    moveq   #0,%d0
    movea.l %d0,%a2
djd7_ml:
    move.l  %a2,%d0
    move.l  #0x8b0,%d1
    muls.l  %d1,%d0
    add.l   %d6,%d0
    add.l   #0x48f8,%d0                | d0 = blob offset + 0x48f8 + t*0x8b0
    lea     TRK_BLOB,%a1
    moveq   #0,%d2
    move.b  (%a1,%d0.l),%d2            | MIDI track LENGTH  (+0)
    moveq   #0,%d1
    move.b  (0x1,%a1,%d0.l),%d1        | MIDI track MULTIPLIER (+1)
    bsr     dj_foldcyc
    addq.l  #1,%a2
    move.l  %a2,%d0
    cmpi.l  #8,%d0
    blt.b   djd7_ml
djd7_gotp:
    tst.l   %d7
    ble.b   djd7_zero
    cmpi.l  #98301,%d7                 | P itself must leave D7 inside the signed-word
    bhi.b   djd7_zero                  | quotient ceiling; pathological length sets do not
|   ---- M = P / tps_master ; G' = G_ABSTICK mod M ----
    move.l  %d7,%d0
    move.l  %d5,%d1
    bsr     dj_div32                   | d0 = M
    tst.l   %d0
    ble.b   djd7_zero
    move.l  %d0,%d1                    | d1 = M
    move.l  G_ABSTICK,%d0
    bsr     dj_mod32                   | d0 = G mod M -- exact, positions unchanged
    move.l  %d0,%d2
    bra.b   djd7_store
djd7_zero:
    moveq   #0,%d2                     | unrepresentable -> 0 = restart at step 0, which is
                                       | what stock puts here at a natural boundary
djd7_store:
    move.l  %d2,MASTER_STEPS           | start offset (master steps) for stock's own rebuild
    movem.l (%sp),%d0-%d7/%a1-%a2
    lea     40(%sp),%sp
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
    lea     PAT_SCALE,%a0
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
|   Session 79 cont.28: this USED to be `LEN_TBL[scaleIdx]`, on the belief that LEN_TBL
|   maps a scale index to a pattern length. cont.20 measured that it does not -- it is a
|   TICKS-PER-STEP table (3,4,6,8,12,24,48,96,... = the OT's 2x/1.5x/1x/0.75x/... scale
|   list, and the same table AR uses for the same purpose). So the modulus below was 6,
|   not 16, and the resume step came out as `absoluteTicks mod 6` -- a value in 0..5,
|   unrelated to any musical position. Measured on the emulator (cont.28): G_ABSTICK=26
|   gave STEP=2 and D7=12. Use the pattern's real LENGTH field instead.
    lea     PAT_LEN,%a0
    moveq   #0,%d1
    move.b  (%a0,%d0.l),%d1           | d1 = master pattern LENGTH in steps
|   Session 70 (7th pass): STILL wrong on real hardware after the SCALE_IX fix -- the
|   user's own report reframed the whole feature. `G_STEP` (the OUTGOING pattern's master
|   step, bounded 0..outgoingLen-1) is the WRONG source for the resume position entirely,
|   not just imprecise: once STEP has wrapped even once against the outgoing pattern's own
|   length, the "how many ticks total have elapsed" information is GONE -- modulo against
|   a DIFFERENT (incoming) length afterward does not recover it. The user's own worked
|   example (16-step pattern <-> 8-step pattern, several rapid switches) makes the actually
|   -wanted model explicit: every pattern behaves as if it had been silently, continuously
|   playing in the background the whole time since transport start, at ITS OWN length --
|   switching just changes which one you're listening to. That is exactly `absoluteTicks
|   mod newLen`, using a counter that NEVER resets on a switch -- not the outgoing
|   pattern's own bounded position re-wrapped. `G_ABSTICK` (new, see its own .equ comment)
|   is that counter; Hook E below increments it unconditionally every step tick, completely
|   independent of DIRECT JUMP's own arm/commit state. Neither `divul.l`/`divsl.l` form
|   assembles under this toolchain's `-mcpu=5407` (tried both the Dr:Dq and the Dr==Dq
|   quotient-only syntax stock's OWN code uses elsewhere -- GAS rejects both here as
|   "needs 68020..."), so this is a hand-rolled 32-iteration binary long division
|   (shift-and-subtract, standard restoring-division shape) instead -- bounded, fixed
|   cost regardless of how large G_ABSTICK has grown. D3 clobbered here is safe: the
|   per-track loop right after dj_c returns reloads it fresh (ACT_BANK) before ever
|   reading it, confirmed by inspection of the code between dj_c's `rts` and that reload.
|   Session 79 cont.35: read the offset HOOK H ACTUALLY STORED, not G_ABSTICK directly.
|   Hook H (0x400a47f6) runs earlier on this same commit path and may have substituted 0
|   for an out-of-range counter. Taking G_ABSTICK here regardless made the master step
|   disagree with every per-track step in exactly that case -- MEASURED: with the counter
|   forced past the bound, the per-track arrays all held 0 while the master held 4, a
|   four-step split that would make the master wrap early and produce one short bar. That
|   is the same master-vs-per-track disagreement class that caused the original desync.
|   Reading MASTER_STEPS makes the two consistent by construction: identical to G_ABSTICK
|   in the normal case, and 0 whenever Hook H's guard fired.
    move.l  MASTER_STEPS,%d0           | d0 = the offset Hook H stored (master steps)
    tst.l   %d1
    ble.b   djc_store                 | guard: bad length -> just use the raw tick count
    moveq   #0,%d2                     | d2 = remainder accumulator
    moveq   #32,%d3                    | d3 = bit counter
djc_divloop:
    add.l   %d0,%d0                    | shift dividend left 1; MSB -> X (carry)
    addx.l  %d2,%d2                    | d2 = d2*2 + that carry bit
    cmp.l   %d1,%d2
    blt.b   djc_divskip
    sub.l   %d1,%d2                    | remainder >= newLen -> subtract (this bit is a 1)
djc_divskip:
    subq.l  #1,%d3
    bne.b   djc_divloop
    move.l  %d2,%d0                    | d0 = resumeStep = absoluteTicks mod newLen
djc_store:
    move.b  %d0,STEP                   | master step (resumeStep, already wrapped to newLen)
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

| ================= Hook F @ 0x400a4d36 =================
| Session 70 (9th pass, HARDWARE BUG confirmed via a targeted test, not just theory):
| the shared-D7 trick (djc_store, above) only produces the correct resume position for
| tracks whose OWN length matches the pattern's default -- confirmed dynamically: gave a
| genuinely per-track-scaled track (its own length 8, inside a 16-step pattern) a
| quotient of 16 -- a nonsensical value bigger than the track's own length, bearing no
| relation to real elapsed time for that track at all. This is Session 15's item #4,
| finally confirmed as a real bug (this project spent Sessions 70.6-70.8 assuming it was
| a secondary, lower-priority gap; the user's own hardware reports -- cumulative drift,
| restarts tied to switch timing -- are fully consistent with this, once you have a track
| whose own SCALE genuinely differs from its pattern's default).
|
| Fix: after BOTH per-track loops (audio 0x400a4bb6-4c62, MIDI 0x400a4c82-4d32) have
| fully run for this tick -- this is the very next instruction stock executes afterward,
| confirmed via disassembly -- recompute each AUDIO track's OWN correct resume position
| independently (G_ABSTICK mod that track's OWN length, not the pattern's) and overwrite
| REFILL_TBL directly, one final time, undoing whatever the shared-D7 mechanism seeded.
| Gated on G_JUST_COMMITTED (set once by dj_c) so this only overrides REFILL_TBL on the
| exact tick a switch commits -- every ordinary tick is left alone, so the fast
| dispatcher's own subsequent increments aren't fought.
|
| MIDI tracks (8-15) NOT covered this pass -- confirmed via stock disassembly that their
| own per-track-scale-override table lives at a different absolute base (0x400e6adc, not
| BLOB-relative like audio's TRAC+0x51) which hasn't been mapped with the same confidence
| yet. Flagged as the one remaining known gap.
|
| detour replaces `tst.l (0x46107568).l` (6 B) -- replayed as the LAST instruction before
| rts so its flags are exactly what the caller's very next `bne.w` expects; every register
| this hook uses is saved/restored around the fixed work (D6 as the loop counter is
| deliberately NOT among the registers `dj_mod32` clobbers, so it survives the bsr calls
| untouched).

    .global dj_pertrack_fix
dj_pertrack_fix:
    tst.b   G_JUST_COMMITTED
    beq.w   dpf_done
    clr.b   G_JUST_COMMITTED
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    moveq   #0,%d6                      | d6 = track index t (0..7, audio only)
dpf_loop:
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  #0x8ed8,%d1
    muls.l  %d1,%d0
    moveq   #0,%d1
    move.b  ACT_BANK,%d1
    move.l  #0x9b340,%d2
    muls.l  %d2,%d1
    add.l   %d1,%d0                     | d0 = bank*0x9b340 + pat*0x8ed8 (pattern block)
    lea     0x400e21e0,%a1
    adda.l  %d0,%a1                     | a1 = this pattern's own block base
    move.l  %d6,%d2
    move.l  #0x91a,%d1
    muls.l  %d1,%d2                     | d2 = t * 0x91a (this track's offset within it)
    lea     0x400e21e0,%a0
    adda.l  %d0,%a0
    adda.l  %d2,%a0                     | a0 = this track's own TRAC block base
|   0x8e54/0x8e55 exceed the +-32767 range a plain d16(An) displacement can encode --
|   same indexed-addressing idiom stock's own code uses for these exact offsets
|   (an immediate loaded into a data register, then (An,Dn.L) with zero base
|   displacement) instead of a d16(An) form.
    moveq   #0,%d1
    move.w  #0x8e55,%d1
    tst.b   (%a1,%d1.l)                 | SCALE_MODE (pattern-level, from a1)
    beq.b   dpf_normal
    moveq   #0,%d1
    move.b  0x51(%a0),%d1               | per-track scale index (SCALE_MODE != 0)
    bra.b   dpf_gotidx
dpf_normal:
|   Session 79 ("continued an eighteenth time") -- HARDWARE REGRESSION, root cause:
|   this used to be `moveq #0,%d1 ; move.w #0x8e54,%d1 ; move.b (%a1,%d1.l),%d1`, i.e. it
|   reused %d1 as BOTH the 0x8e54 offset and the destination. `move.b` into a data register
|   writes only the low 8 bits, so %d1 came out as 0x8e00|scaleByte instead of the scale
|   index -- and the LEN_TBL lookup below then read ~0x8e02*4 bytes PAST the table, i.e.
|   garbage, as this track's length. Whether that garbage is <=0 (caught by the guard
|   below, fix silently skipped) or >0 (used as a real length) is pure data-dependent luck:
|   in the emulator it came out <=0, on the user's own hardware it did not, and
|   `G_ABSTICK mod garbage` then landed a value larger than the real wrap length in
|   STEP_IN_PAT[t] -- so the counter wrapped EVERY tick, firing every trig continuously
|   (audible as very short clicks) with the step position frozen. Only reachable when
|   SCALE_MODE == 0; both validation runs happened to target SCALE_MODE == 1 patterns,
|   which is exactly why this shipped. Use a separate scratch register for the offset so
|   the destination is genuinely zero-extended.
    moveq   #0,%d2
    move.w  #0x8e54,%d2                 | d2 = offset only -- NOT the destination
    moveq   #0,%d1
    move.b  (%a1,%d2.l),%d1             | pattern-default scale index (SCALE_MODE == 0)
dpf_gotidx:
|   Session 79 (NOTES.md, "continued a seventeenth time"): d1 holds this track's scale
|   index for the incoming pattern right here, chosen by the SAME SCALE_MODE test stock
|   itself uses -- for the one instant before the LEN_TBL lookup below overwrites it with
|   the length. That index is exactly what the step-counter wrap check reads live out of
|   TRK_SCALE_IX[t] (0x400a3ce6/0x400a3cee), and stock only reloads that cache AFTER a
|   wrap, so a mid-pattern DIRECT JUMP commit leaves the OUTGOING pattern's index in place
|   for one full cycle: measured on the user's own DJTESTxxx export, a track at trackLen 3
|   ran 6 ticks after the commit (wrapping at frame 805 instead of 633), missed one
|   DAT_80001904 anchor write, then self-corrected once stock's own post-wrap reload
|   finally ran. Refresh it here instead of waiting for that wrap -- same principle as
|   Hook D (dj_scaleix_fix), which already undoes the identical staleness for the MASTER
|   scale index; this is its per-track counterpart, and the long-open Session 15 #4 gap.
|   Costs nothing extra: the value is already computed, and %a0 is reloaded on the very
|   next line anyway.
|   FAIL-SAFE BOUNDS GUARD (Session 79, "continued an eighteenth time"). LEN_TBL at
|   0x400aba50 has exactly TWELVE real entries -- [0..11] = 3,4,6,8,12,24,48,96,48,24,12,6;
|   [12] is 0 and [13+] is an unrelated table (2646000, the per-step increment constant).
|   The regression that reached hardware came from indexing this table out of bounds and
|   using whatever came back as a track length. Anything outside 0..11 is therefore not a
|   scale index at all, and the only safe action is to leave this track completely alone --
|   including NOT writing TRK_SCALE_IX, since stock's own wrap check reads that cache and a
|   bogus index there would corrupt stock too. Guard first, write second.
    cmpi.l  #11,%d1
    bhi.b   dpf_skip                    | not a real scale index -> touch nothing
    lea     TRK_SCALE_IX,%a0
    move.b  %d1,(%a0,%d6.l)             | TRK_SCALE_IX[t] = the INCOMING pattern's index
    lea     0x400aba50,%a0
    move.l  (%a0,%d1.l*4),%d1           | d1 = this track's OWN trackLen
    move.l  G_ABSTICK,%d0                | d0 = absolute tick count
    tst.l   %d1
    ble.b   dpf_skip                    | guard: bad length -> leave REFILL_TBL alone
    bsr     dj_mod32                    | d0 = G_ABSTICK mod trackLen[t]
    lea     0x800064d0,%a0
    move.b  %d0,(%a0,%d6.l)             | REFILL_TBL[t] = this track's own correct position
|   Session 79 (NOTES.md, "continued a fifteenth time"): STEP_IN_PAT (0x800064f0[t]) is the
|   per-track step-within-pattern counter -- stock increments it once per step tick at
|   0x400a3ce2 and wraps it to 0 at 0x400a3cf6 on reaching the track's length. Reading 0
|   ("we are at step 0") is the ONLY thing that makes the DAT_80001904 table-arm write
|   run: measured, the write path's last gate is `tst.b (A0) ; bne.w 0x400a3574` at
|   0x400a2d28/0x400a2d2a with A0 == 0x800064f0+t (same-run trace diff, tick 9 vs tick 10,
|   both step boundaries). Stock's commit tail resets this counter to 0 for every track at
|   0x400a4bf0 -- correct for an ORDINARY switch, which only ever commits at a loop
|   boundary where the counter was wrapping to 0 anyway, but DIRECT JUMP commits
|   mid-pattern, so the reset PERMANENTLY re-phases it (measured: ground truth reads 0 at
|   ticks 6/12/18, a DIRECT JUMP run at 6/9/15 -- three ticks early, forever, never
|   resyncing). That is the whole "extra out-of-cycle table-arm write + permanent cadence
|   shift" symptom this thread has chased since Session 70's 13th pass; Hooks G/G2 below
|   could only suppress the one visible write, never the phase. Fix: this hook already runs
|   AFTER 0x400a4bf0 on the same commit (measured by write order at frame 461) and has
|   already computed exactly the right value -- `G_ABSTICK mod trackLen[t]`, which lands at
|   3 here, matching ground truth's own counter at that instant, because Hook E's
|   G_ABSTICK increment (0x400a3fe4) has already happened by this point in the tick. So
|   just store the SAME d0 to STEP_IN_PAT[t] as well, undoing stock's reset-to-0 with the
|   "as if this pattern had been playing continuously all along" position -- the identical
|   principle dj_c already applies to STEP and D7, and the Analog Rytm's own
|   fresh-per-request recompute invariant (ar-kyoti-fw/MECHANISM.md).
    lea     STEP_IN_PAT,%a0
    move.b  %d0,(%a0,%d6.l)             | STEP_IN_PAT[t] = same correct position
dpf_skip:
    addq.l  #1,%d6
    cmpi.l  #8,%d6
    blt.w   dpf_loop
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
dpf_done:
    tst.l   0x46107568                  | displaced original (sets Z for the caller's bne.w)
    rts

| d0 = d0 mod d1 (both unsigned 32-bit); clobbers d2,d3; preserves d1 and everything else.
| Same hand-rolled binary long division as djc_store above (neither divul.l nor divsl.l,
| in any form, assembles under this toolchain's -mcpu=5407) -- factored out here since
| dj_pertrack_fix needs it 8 times per commit instead of djc_store's one.
| ---- unsigned 32-bit helpers for Hook H's range reduction (Session 79 cont.36) ----
| dj_div32 : d0 = d0 / d1 (unsigned), clobbers d2-d4. Restoring shift-subtract, same shape
|            as dj_mod32 below, but accumulating the quotient as well as the remainder.
|            Uses bcs (unsigned) rather than dj_mod32's blt -- our operands are small enough
|            that it never matters, but signed compares on a division are wrong in principle.
dj_div32:
    moveq   #0,%d2                     | remainder
    moveq   #0,%d4                     | quotient
    moveq   #32,%d3
dj_div32_loop:
    add.l   %d0,%d0                    | shift dividend left, MSB -> X
    addx.l  %d2,%d2                    | remainder = remainder*2 + that bit
    add.l   %d4,%d4                    | quotient <<= 1
    cmp.l   %d1,%d2
    bcs.b   dj_div32_skip              | remainder < divisor -> this quotient bit stays 0
    sub.l   %d1,%d2
    addq.l  #1,%d4
dj_div32_skip:
    subq.l  #1,%d3
    bne.b   dj_div32_loop
    move.l  %d4,%d0
    rts

| dj_gcd32 : d0 = gcd(d0, d1) by Euclid, clobbers d1-d4.
dj_gcd32:
    tst.l   %d1
    beq.b   dj_gcd32_ret
dj_gcd32_loop:
    move.l  %d1,%d4                    | remember b
    bsr     dj_mod32                   | d0 = a mod b   (dj_mod32 leaves d1 alone)
    move.l  %d0,%d1                    | b' = a mod b
    move.l  %d4,%d0                    | a' = b
    tst.l   %d1
    bne.b   dj_gcd32_loop
dj_gcd32_ret:
    rts

| dj_foldcyc : fold one track's cycle into the period accumulator.
|              in  d1 = tempo-multiplier index, d2 = track length, d7 = P so far
|              out d7 = LCM(P, LEN_TBL[d1] * d2)
|              A track with a bad index or zero length contributes nothing rather than
|              poisoning the accumulator. Bails out by leaving P too large if it would
|              overflow, which the caller's ceiling check then catches.
dj_foldcyc:
    cmpi.l  #11,%d1
    bhi.b   dj_foldcyc_ret
    tst.l   %d2
    ble.b   dj_foldcyc_ret
    move.l  %d2,-(%sp)
    lea     LEN_TBL,%a1
    move.l  (%a1,%d1.l*4),%d0
    muls.l  (%sp)+,%d0                 | d0 = tps_t * len_t = this track's cycle in ticks
    tst.l   %d0
    ble.b   dj_foldcyc_ret
    move.l  %d0,-(%sp)                 | keep the cycle
    move.l  %d7,%d0
    move.l  (%sp),%d1
    bsr     dj_gcd32                   | d0 = gcd(P, cycle)
    move.l  %d0,%d1
    move.l  %d7,%d0
    bsr     dj_div32                   | d0 = P / gcd
    muls.l  (%sp)+,%d0                 | d0 = (P/gcd) * cycle = LCM
    move.l  %d0,%d7
dj_foldcyc_ret:
    rts

dj_mod32:
    moveq   #0,%d2
    moveq   #32,%d3
dj_mod32_loop:
    add.l   %d0,%d0
    addx.l  %d2,%d2
    cmp.l   %d1,%d2
    blt.b   dj_mod32_skip
    sub.l   %d1,%d2
dj_mod32_skip:
    subq.l  #1,%d3
    bne.b   dj_mod32_loop
    move.l  %d2,%d0
    rts

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
