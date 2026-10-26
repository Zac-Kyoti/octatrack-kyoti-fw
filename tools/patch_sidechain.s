| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
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
| key_step: KEY's step handler (descriptor P+0x12a + 4*8). Stock's generic handler
|  (0x4003240c) multiplies a turn by 7 while the encoder is held down; this one asks the
|  unscaled tally (0x4003249c, as stock's SRC SETUP editor does) for the steps and adds them
|  to the value, so a pressed turn moves KEY one position per detent, like a plain one.
|  handler(enc, delta, value) -> new value (the caller clamps it). d0/d1/a0/a1 only.
    .equ STEP_TALLY, 0x4003249c

    .balign 2
    .global key_step
key_step:
    move.l  8(%sp),-(%sp)               | delta
    move.l  8(%sp),-(%sp)               | enc
    jsr     STEP_TALLY
    addq.l  #8,%sp
    add.l   12(%sp),%d0                 | + the current value
    rts

    .equ FMT_ONOFF, 0x4003c14c          | stock "OFF" / "ON"
    .equ SWITCH_FN, 0x40046f10          | stock 2-position switch, (.., value at 16(%sp), ..)

    .balign 2
    .global mon_step
mon_step:                               | as key_step, then kept on 2..3
    move.l  8(%sp),-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     STEP_TALLY
    addq.l  #8,%sp
    add.l   12(%sp),%d0
    moveq   #2,%d1
    cmp.l   %d1,%d0
    bge.s   ms_lo
    move.l  %d1,%d0
ms_lo:
    moveq   #3,%d1
    cmp.l   %d1,%d0
    ble.s   ms_hi
    move.l  %d1,%d0
ms_hi:
    rts

    .balign 2
    .global mon_fmt
mon_fmt:
    moveq   #1,%d0
    and.l   8(%sp),%d0
    move.l  %d0,8(%sp)                  | bit 0: 2 -> OFF, 3 -> ON
    jmp     FMT_ONOFF

    .balign 2
    .global mon_widget
mon_widget:
    moveq   #1,%d0
    and.l   16(%sp),%d0
    move.l  %d0,16(%sp)                 | bit 0: 2 -> left, 3 -> right
    jmp     SWITCH_FN

    .balign 2
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
|  Page 2 since the major version (2026-10-19): RMS · MON · KEY · KGN · KBAS · KWID.
|
|  MON (slot 7): 2 = OFF (left), 3 = ON (right), default 2. 0 and 1 are what a compressor
|  saved before holds (stock's hidden 1, or the inverted MON of 2026-10-19..25), so sc_norm
|  turns them into OFF. The count is 4 (octabam writes min 0); mon_step keeps a turn on 2..3,
|  and mon_fmt / mon_widget show bit 0 (the switch reads the raw value: 2 = left).
|
|  hp_fmt: KBAS, the HP's frequency on the DSP's grid f = 20 Hz * 2^(g/16)
|  (tools/sc_keyfilt.py): 0 = OFF, n = g round((n-1) * 159/126). Shown as "20".."990",
|  "1.0k".."9.9k", "10k".."19k" (4 characters at most). F10 = f * 10 =
|  200 * 2^(g/16) = (200 * HZT[g & 15]) >> (15 - g/16), HZT[i] = 2^(i/16) * 32768.
|  lp_fmt: KWID, the LP's distance above KBAS in octaves, "0.5".."9.9", 127 = OFF:
|  tenths = round(5 + m * 151/126 * 10/16) = (3068 m + 22528) >> 12 (equal for every m).
|  A-array callbacks: void fmt(char *buf, int value). d0/d1/a0/a1 only.
| =====================================================================
    .balign 2
    .global hp_fmt
hp_fmt:
    move.l  8(%sp),%d0
    beq.w   hz_off
    subq.l  #1,%d0
    mulu.w  #323,%d0
    addi.l  #128,%d0
    lsr.l   #8,%d0                      | g = round((n - 1) * 159 / 126)
    bra.s   hz_go

    .balign 2
    .global lp_fmt
lp_fmt:
    move.l  8(%sp),%d1
    cmpi.l  #127,%d1
    beq.w   hz_off
    mulu.w  #3068,%d1
    addi.l  #22528,%d1
    moveq   #12,%d0
    lsr.l   %d0,%d1                     | tenths of an octave
    movea.l 4(%sp),%a1                  | buf
    lea     wd_d,%a0
    bra.s   hz_tenths
hz_go:
    move.l  %d0,%d1
    andi.l  #15,%d1
    lea     hzt,%a0
    move.w  (0,%a0,%d1.l*2),%d1         | HZT[g & 15]
    mulu.w  #200,%d1                    | 200 * HZT (< 2^24)
    lsr.l   #4,%d0                      | octave 0..9
    neg.l   %d0
    addi.l  #15,%d0
    lsr.l   %d0,%d1                     | d1 = F10 = 10 * f
    movea.l 4(%sp),%a1                  | buf
    cmpi.l  #10000,%d1
    bcc.s   hz_k
    addq.l  #5,%d1
    divu.w  #10,%d1
    andi.l  #0xffff,%d1                 | f in Hz
    move.l  %d1,-(%sp)
    pea     hz_d
    bra.s   hz_print2
hz_k:
    cmpi.l  #100000,%d1
    bcc.s   hz_kk
    addi.l  #500,%d1
    divu.w  #1000,%d1
    andi.l  #0xffff,%d1                 | tenths of a kHz
    lea     hz_dk,%a0
hz_tenths:                              | d1 = tenths, a0 = "%d.%d..." format, a1 = buf
    divu.w  #10,%d1                     | low word units, high word tenths
    move.l  %d1,%d0
    swap    %d0
    andi.l  #0xffff,%d0
    move.l  %d0,-(%sp)
    andi.l  #0xffff,%d1
    move.l  %d1,-(%sp)
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    jsr     SPRINTF
    lea     16(%sp),%sp
    rts
hz_kk:
    addi.l  #5000,%d1
    move.l  #10000,%d0
    divu.l  %d0,%d1                     | kHz (F10 / 10000, F10 < 2^18)
    move.l  %d1,-(%sp)
    pea     hz_k1
hz_print2:
    move.l  %a1,-(%sp)
    jsr     SPRINTF
    lea     12(%sp),%sp
    rts
hz_off:
    move.l  #S_OFF,%d1
    move.l  %d1,8(%sp)
    jmp     SPRINTF                     | sprintf(buf, "OFF"), as key_fmt does

    .balign 2
hzt:
    .word   0x8000, 0x85ab, 0x8b96, 0x91c4, 0x9838, 0x9ef5, 0xa5ff, 0xad58, 0xb505, 0xbd09, 0xc567, 0xce25, 0xd745, 0xe0cd, 0xeac1, 0xf525
hz_d:
    .asciz  "%d"
hz_dk:
    .asciz  "%d.%dk"
wd_d:
    .asciz  "%d.%d"
hz_k1:
    .asciz  "%dk"

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

| a1 -> a page-2 block (slot 6).  KEY > 8 -> the major version's defaults: MON OFF (2),
| KEY OFF, KGN 64, KBAS OFF (0), KWID OFF (127).  KEY 0..8 is the user's own setting; only a
| MON other than 2/3 (saved before 2026-10-25) is set OFF.
sn_fix:
    moveq   #0,%d1
    move.b  (2,%a1),%d1
    cmpi.l  #8,%d1
    bhi.s   sn_reset
    move.b  (1,%a1),%d1
    subq.l  #2,%d1
    cmpi.l  #1,%d1
    bls.s   sn_done                     | 2 or 3: this version's MON
    move.b  #2,(1,%a1)
    rts
sn_reset:
    move.b  #2,(1,%a1)
    clr.b   (2,%a1)
    move.b  #64,(3,%a1)
    clr.b   (4,%a1)
    move.b  #127,(5,%a1)
sn_done:
    rts
