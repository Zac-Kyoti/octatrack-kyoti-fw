| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
    .cpu 5407
    .text
| =====================================================================
|  SIDE-CHAIN COMPRESSOR  --  step 1 of 4: menu only (the DSP still
|  ignores every new parameter; this proves the ColdFire control-surface
|  side + the dynamic KEY formatter on real hardware).
|
|  Adds  KEY  to the COMPRESSOR effect page 2 (parameter-descriptor slot
|  7, right after RMS).  Value semantics (Session 77, cross-core SIDECHAIN --
|  widened from the original 0..4 "same-core siblings only" range once the
|  DSP side could reach any track, see NOTES.md "Session 77"):
|      0        = OFF  (stock behaviour: the compressor keys off its own
|                       track, unchanged)
|      1 .. 8   = track T1..T8, ANY of the eight tracks, flat -- same value
|                 on both payloads, no longer relative to the edited track's
|                 own DSP core. Value count 5->9 in build_sidechain_compressor.py's own
|                 SLOTS table.
|
|  Everything except this formatter is a data poke done by
|  build_sidechain.py (name / value-count 2->5 / default 1->0 / the
|  A-array formatter pointer / zero the stale B-array widget pointer).
| =====================================================================

    .equ SPRINTF,   0x40013a08      | int sprintf(char *buf, const char *fmt, ...)
    .equ S_OFF,     0x400b4e78      | stock "OFF" string literal

| ---- KEY formatter  --  A-array callback: void fmt(char *buf, int value) ----
|  No link frame (matches the stock per-slot formatters, e.g. FUN_4003c14c
|  ON/OFF and FUN_4003c718 "%d").  Stack on entry:
|      0(%sp) = return addr   4(%sp) = buf   8(%sp) = value
|  Convention: %d0/%d1/%a0/%a1 are scratch; %d2+ must be preserved
|  (FUN_4003c7a0 saves %d2), so this routine touches only %d0/%d1/%a1.
    .global key_fmt
key_fmt:
    move.l  4(%sp),%a1             | a1 = buf
    move.l  8(%sp),%d0             | d0 = value (0..8)
    bne.b   kf_track

|  value 0 -> "OFF": rewrite the two stack args in place and tail-jump to
|  sprintf, exactly as FUN_4003c14c does.
    move.l  #S_OFF,%d1
    move.l  %d1,8(%sp)             | arg2 := "OFF"
    move.l  %a1,4(%sp)            | arg1 := buf  (unchanged)
    jmp     SPRINTF                | tail: sprintf(buf, "OFF")

|  value 1..8 -> "T<n>", n = value directly -- Session 77 dropped the old
|  CUR_TRACK/coreBase indirection entirely: KEY is now a flat absolute track
|  picker, so the value on the stack already IS the track number to print.
kf_track:
    move.l  %d0,-(%sp)             | sprintf arg: n = value
    pea     kf_fmt                  | sprintf arg: "T%d"
    move.l  %a1,-(%sp)            | sprintf arg: buf
    jsr     SPRINTF
    lea     12(%sp),%sp
    rts

    .balign 2
kf_fmt:
    .asciz  "T%d"

| =====================================================================
|  KEY FLT formatter  --  step 3 scaffolding (DSP filter not built yet).
|  Bipolar key-filter select on COMPRESSOR page 2:
|      < 64  ->  "LP"   (low-pass -- isolate a kick from a full loop)
|      = 64  ->  "OFF"
|      > 64  ->  "HP"   (classic detector high-pass)
|  Type only for now; the cutoff number is added once the DSP filter's
|  value->Hz mapping is fixed.  A-array callback: void fmt(buf, value).
| =====================================================================
    .balign 2
    .global kfilt_fmt
kfilt_fmt:
    move.l  4(%sp),%a1             | a1 = buf
    move.l  8(%sp),%d0             | d0 = value 0..127
    cmpi.l  #64,%d0
    blt.b   kfl_lp
    beq.b   kfl_off
    move.l  #kfl_hp_s,%d1
    bra.b   kfl_go
kfl_lp:
    move.l  #kfl_lp_s,%d1
    bra.b   kfl_go
kfl_off:
    move.l  #S_OFF,%d1
kfl_go:
    move.l  %d1,8(%sp)            | arg2 := "LP" / "HP" / "OFF"
    move.l  %a1,4(%sp)           | arg1 := buf
    jmp     SPRINTF

    .balign 2
kfl_lp_s:
    .asciz  "LP"
kfl_hp_s:
    .asciz  "HP"

| =====================================================================
|  KEY list-widget trampoline  --  forces LFO TRIG's own B-callback
|  (0x40046450, list-style "OFF"/"T1".."T4" renderer, see build_sidechain_compressor.py's
|  LIST_FN) into its simple single-centered-value mode instead of its
|  3-row scroll-preview mode.
|
|  Disassembled 0x40046450 in full (Session 76 continued yet again (8)):
|  its 5th stack argument (a caller-supplied flags word, read into %d5 at
|  the callee's own +68(%sp) after its own -48 frame -- i.e. at +20(%sp)
|  as seen from HERE, before that frame exists) has bit 1 as an internal
|  mode switch:
|      bit1 SET    -> measuretext once, drawtext the formatted value
|                      (from the SAME buffer key_fmt already filled)
|                      CENTERED on one line. Exactly "name + value", no
|                      icon -- this is what real stock LFO TRIG must get
|                      from its own (unlocated) caller.
|      bit1 CLEAR  -> a second branch that formats/measures/draws THREE
|                      separate rows (a fresh, uninitialised second
|                      buffer at one of them) -- this is the garbage
|                      3-line render COMPRESSOR's own generic per-slot
|                      dispatcher drives us into, for reasons not fully
|                      traced (its caller-context builder was not found
|                      despite two dedicated passes -- background agent +
|                      direct).
|  Two dedicated tracing passes couldn't find WHERE that flags word
|  originates, so rather than reproduce the caller's own setup, this
|  trampoline just patches the one bit we need on the stack in place
|  before falling straight into the real function -- same return address,
|  same argument layout, LIST_FN re-reads its own (now-corrected) copy.
|  d0/d1/a0/a1 scratch per the same convention key_fmt/kfilt_fmt rely on
|  (LIST_FN's own %moveml saves d2-d6/a2-a5, not d0/d1/a0/a1).
| =====================================================================
    .equ LIST_FN, 0x40046450

    .balign 2
    .global key_list_fix
key_list_fix:
    move.l  20(%sp),%d0
    or.l    #2,%d0
    move.l  %d0,20(%sp)
    jmp     LIST_FN

| =====================================================================
|  sc_norm  --  a COMPRESSOR saved before SIDE-CHAIN existed comes up with
|  its side-chain OFF (the user's rule, 2026-10-08).
|
|  Stock COMPRESSOR uses page-2 slots 6/7 only; its descriptor still gives
|  slots 8..11 the defaults 0x7f/0/0/0 and selecting the effect writes them.
|  SIDE-CHAIN reads those four bytes as KEY/KFLT/KGN/MON, so every
|  compressor made on stock firmware would load keyed from KEY 127 (the DSP
|  reads unrelated memory as the key), the key filter shut and the key gain
|  at -24 dB.  A SIDE-CHAIN-era compressor can only hold KEY 0..8 (count 9),
|  so: KEY > 8 = never set up here -> KEY OFF, KFLT 64 (OFF), KGN 64 (0 dB),
|  MON OFF.  An in-range KEY is the user's setting and is left alone.
|
|  Called (jsr) from both copies of the per-frame page-2 copier, in place of
|  their first instruction `lea 0x80000a50,%a3`, which is replayed at the
|  end:  0x4000cae8 (the frame builder, every frame, transport running or
|  stopped) and 0x40003d1c (its twin, no static caller).  Every register is
|  preserved; no kernel or UI calls, no private state.
|
|  Two copies are checked, EACH ONLY AGAINST ITSELF -- its own FX id and its
|  own KEY -- so a copy caught mid-update (a Part change refreshes the live
|  ids and the lane at different moments) is never judged by another copy:
|    1. the current part's working store, which the page shows and the card
|       saves:  [0x46c82456] + 0x8ed80 + p*0x18b2  (p = byte 0x80000003),
|       FX ids at +0 (FX1) / +8 (FX2) + t, page 2 at +0x2f2 + t*30 + 12/18
|       (stock's editor, 0x4003a5b4);
|    2. the live lane the copier ships to the DSP right after this returns:
|       0x80000810 + t*72 + 0x32/0x38, live ids 0x80000ec4 / 0x80000ecc + t.
|  The saved copy and the battery-SRAM copy are not written: whenever they
|  come back (Part reload, power-up, the transport start's re-apply) they
|  land in one of these two and are caught there.  No "edited" flags.
| =====================================================================
    .equ LANE,     0x80000810           | live lane, 72 B per track
    .equ LIVE_IDS, 0x80000ec4           | live FX1 ids [8], FX2 ids at +8
    .equ CUR_PART, 0x80000003           | current part (byte)
    .equ DBPTR,    0x46c82456           | -> the current bank's blob
    .equ COMP_ID,  0x18

    .balign 2
    .global sc_norm
sc_norm:
    lea     (-24,%sp),%sp
    movem.l %d0-%d2/%a0-%a2,(%sp)
    moveq   #0,%d1
    move.b  CUR_PART,%d1
    mulu.w  #0x18b2,%d1
    movea.l DBPTR,%a2
    adda.l  %d1,%a2
    adda.l  #0x8ed80,%a2                | a2 = the current part's working store
    lea     LIVE_IDS,%a0
    lea     LANE,%a1
    moveq   #0,%d0                      | d0 = track 0..7
sn_track:
    move.b  (0,%a2,%d0.l),%d1           | store: FX1 id
    cmpi.b  #COMP_ID,%d1
    bne.s   sn_s2
    moveq   #12,%d2
    bsr.s   sn_store
sn_s2:
    move.b  (8,%a2,%d0.l),%d1           | store: FX2 id
    cmpi.b  #COMP_ID,%d1
    bne.s   sn_l1
    moveq   #18,%d2
    bsr.s   sn_store
sn_l1:
    move.b  (0,%a0,%d0.l),%d1           | lane: live FX1 id
    cmpi.b  #COMP_ID,%d1
    bne.s   sn_l2
    moveq   #0x32,%d2
    bsr.s   sn_lane
sn_l2:
    move.b  (8,%a0,%d0.l),%d1           | lane: live FX2 id
    cmpi.b  #COMP_ID,%d1
    bne.s   sn_next
    moveq   #0x38,%d2
    bsr.s   sn_lane
sn_next:
    lea     (72,%a1),%a1                | next track's lane
    addq.l  #1,%d0
    cmpi.l  #8,%d0
    bne.s   sn_track
    movem.l (%sp),%d0-%d2/%a0-%a2
    lea     (24,%sp),%sp
    lea     0x80000a50,%a3              | displaced
    rts

| store: page 2 at a2 + 0x2f2 + d0*30 + d2.  Uses d1/d2; a1 saved around.
sn_store:
    move.l  %a1,-(%sp)
    move.l  %d0,%d1
    mulu.w  #30,%d1
    add.l   %d1,%d2
    addi.l  #0x2f2,%d2
    lea     (0,%a2,%d2.l),%a1
    bsr.s   sn_fix
    movea.l (%sp)+,%a1
    rts

| lane: page 2 at a1 (this track's lane) + d2.
sn_lane:
    move.l  %a1,-(%sp)
    adda.l  %d2,%a1
    bsr.s   sn_fix
    movea.l (%sp)+,%a1
    rts

| a1 -> a page-2 block (slot 6).  KEY > 8 -> KEY 0, KFLT 64, KGN 64, MON 0.
sn_fix:
    moveq   #0,%d1
    move.b  (2,%a1),%d1
    cmpi.l  #8,%d1
    bls.s   sn_done                     | 0..8: the user's own setting
    moveq   #64,%d1
    clr.b   (2,%a1)
    move.b  %d1,(3,%a1)
    move.b  %d1,(4,%a1)
    clr.b   (5,%a1)
sn_done:
    rts
