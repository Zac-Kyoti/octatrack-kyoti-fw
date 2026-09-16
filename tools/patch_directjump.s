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
    .equ G_STEP,    0x80006a41          | master step to resume at
    .equ G_PCPAT,   0x80006a42          | pending pattern the PC was last sent for

|   stock symbols
    .equ ACT_PAT,   0x800065be
    .equ ACT_BANK,  0x800065bd
    .equ PEND_PAT,  0x800065c0
    .equ PEND_BANK, 0x800065bf
    .equ STEP,      0x800065b6
    .equ SCALE_IX,  0x8000663d
    .equ STOPFLAG,  0x8000667e
    .equ RUNNING,   0x800065b8
    .equ ARR_ACT,   0x460d1aec          | FUN_40033968 return (arranger active)
    .equ CHAIN_ACT, 0x80006546
    .equ LEN_TBL,   0x400aba50          | [scaleIdx] -> pattern length (long)
    .equ PAT_SCALE, 0x400eb034          | [bank*0x9b340 + pat*0x8ed8] -> scale idx byte
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

| ================= Hook C @ 0x400a4840 =================
| detour replaces `clr.b %d0 ; move.b %d0,(0x800065b6).l` (8 B) -> jsr dj_c + nop.
| Not armed: just do DAT_800065b6 = 0.  Armed: set DAT_800065b6 to (savedStep % newLen)
| so the master step resumes at the playhead.  D6/D7 are live here; D0-D2/A0 are free.
|
| ** Session 61 fix: this hook must NOT touch D7. ** The earlier build wrote the resume
| step into D7 too ("per-track positions derive from D7"), on the theory that the
| per-track tick-phase loops just below this hook site (0x400a4884.. / 0x400a4a14..,
| the ones computing 0x800065e4[track]/0x80006604[track] via `remsl`) read their
| position from D7.  Re-disassembly (Session 61) of the code BEFORE this hook site
| (0x400a47f6-0x400a4834, still stock, unmodified, runs every step==0 regardless of
| DIRECT JUMP) shows D7 is already correctly set there to `LEN_TBL[newScale] *
| DAT_80006628` -- a TICK count, not a step index -- and BOTH per-track loops consume
| that D7 directly afterward.  Overwriting D7 here with a raw, unscaled step index
| (0-63) fed the tick-phase math completely wrong units, corrupting every track's own
| phase accumulator on every manual jump -- this is what actually caused "the pattern
| jump doesn't respect the playhead": it's not that DAT_800065b6 (the master step,
| which this hook DOES set correctly) was wrong, it's that the phase accumulators
| driving each track's own next-tick scheduling were fed garbage.  D7 is left alone.

    .global dj_c
dj_c:
    tst.b   G_ARMED
    bne.b   djc_fix
    clr.b   STEP
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
    move.b  (%a0,%d0.l),%d1            | d1 = scale index
    lea     LEN_TBL,%a0
    move.l  (%a0,%d1.l*4),%d1         | d1 = newLen
    moveq   #0,%d0
    move.b  G_STEP,%d0                 | saved master step
    tst.l   %d1
    ble.b   djc_store                 | guard: bad length -> just use savedStep
djc_mod:
    cmp.l   %d1,%d0
    blt.b   djc_store
    sub.l   %d1,%d0
    bra.b   djc_mod
djc_store:
    move.b  %d0,STEP                   | master step -- D7 is left untouched (see above)
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
