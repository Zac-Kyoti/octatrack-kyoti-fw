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
|  7, right after RMS).  Value semantics:
|      0        = OFF  (stock behaviour: the compressor keys off its own
|                       track, unchanged)
|      1 .. 4   = one of the four audio tracks that share this track's
|                 DSP core -- rendered "T1".."T4" while the edited track
|                 (0x100b14cc) is 1..4, "T5".."T8" while it is 5..8, so
|                 the chooser can never point at a track the compressor
|                 is not wired to.
|
|  Everything except this formatter is a data poke done by
|  build_sidechain.py (name / value-count 2->5 / default 1->0 / the
|  A-array formatter pointer / zero the stale B-array widget pointer).
| =====================================================================

    .equ CUR_TRACK, 0x100b14cc      | u8, 0..7  -- current / edited audio track
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
    move.l  8(%sp),%d0             | d0 = value (0..4)
    bne.b   kf_track

|  value 0 -> "OFF": rewrite the two stack args in place and tail-jump to
|  sprintf, exactly as FUN_4003c14c does.
    move.l  #S_OFF,%d1
    move.l  %d1,8(%sp)             | arg2 := "OFF"
    move.l  %a1,4(%sp)            | arg1 := buf  (unchanged)
    jmp     SPRINTF                | tail: sprintf(buf, "OFF")

|  value 1..4 -> "T<n>", n = coreBase + value - 1
|      coreBase = 1  when CUR_TRACK in 0..3
|      coreBase = 5  when CUR_TRACK in 4..7
kf_track:
    clr.l   %d1
    move.b  CUR_TRACK,%d1           | d1 = current track 0..7
    cmpi.l  #4,%d1
    bcc.b   kf_hi                   | unsigned >= 4  -> high core (T5..T8)
    moveq   #1,%d1
    bra.b   kf_num
kf_hi:
    moveq   #5,%d1
kf_num:
    add.l   %d0,%d1                 | d1 = coreBase + value
    subq.l  #1,%d1                  | d1 = track number 1..8
    move.l  %d1,-(%sp)             | sprintf arg: n
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
|  (0x40046450, list-style "OFF"/"T1".."T4" renderer, see build_sidechain3.py's
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
