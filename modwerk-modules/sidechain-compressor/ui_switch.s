| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| ui_switch.s -- two panel drawings shared by SIDECHAIN_COMPRESSOR and VARISPEED(_EMUS).
|
| 1. The rotary switch (Spectrum's LADR, stock CHORUS TAPS) with up to nine positions.
|    Stock draws it with the 5-position widget SW5 (0x40047254): a 17x11 glyph per value
|    from the table SW_TAB (0x400bde2a, entry value + 1; seven glyphs, a 270-degree sweep
|    in 45-degree steps; SW5 uses entries 1..5, 9:00 to 3:00, and draws nothing above
|    value 4). Nine positions keep that arc in 22.5-degree steps: an even position 2k is
|    stock's glyph for value k, an odd one 2k+1 a glyph of ours between k and k+1. The
|    drawing stays stock's: SW5 is called with value k, and for an odd position its table
|    entry k+1 is lent our glyph for the call and given back after it (the panel draws
|    from the UI task only). SW5 hands its formatter the value it was given, so it gets
|    sw_fmt, which calls the caller's formatter with the caller's value.
|    Three positions are the stock 3-position widget SW3 (0x40047424, SPRING TYPE:
|    entries 1/3/5, 9:00 / 12:00 / 3:00) behind the same formatter pass-through.
|
|      sw9_widget  a descriptor's widget (B) column: (x, y, idx, value, flags, fmt, canvas),
|                  position = value (0..8)
|      sw9_draw    the same arguments on the stack; d0 = position 0..8, d1 = the value the
|                  formatter a1 prints. A position out of range draws the empty cell.
|      sw3_draw    the same for positions 0..2
|    d0/d1/a0/a1 scratch; the rest kept (C ABI).
|
| 2. The link clip in the FX SETUP window. Stock draws the clip (glyph 0x400baabe, the
|    bracket between two linked knobs, enable-nibble bit 1) on main pages only: the main
|    drawer (FUN_4004d948) blits it after the knob on the right, at (x - 4, y + 15) of that
|    knob (0x4004e81c). The FX SETUP window draws its six knobs in its own loop
|    (0x400377f8..0x4003791c), which has no clip code. clip_knob is a widget (B) column:
|    the stock knob, then the clip where the main drawer puts it relative to the labels:
|    (x - 4, y + 14) of the knob here (the main drawer's y + 15 lands one row high). (A hook in that
|    loop was the other way; its widget return 0x40037890 is next to a branch target,
|    0x40037894, so it cannot take a 6-byte jsr.)
|
|      clip_knob   (x, y, idx, value, flags, fmt, canvas): the knob with the clip on its left
|
| An includer that needs neither sets UIS_NO_SW3 / UIS_NO_CLIP before including this file
| (VARISPEED: no sw3_draw, no clip_knob; VARISPEED_EMUS: no clip_knob), and UIS_LOCAL to keep
| its copy's symbols local (octabam links DRAM units together: SIDECHAIN's sc_ui exports them).

        .equ    SW5,      0x40047254    | stock 5-position switch widget
        .equ    SW3,      0x40047424    | stock 3-position switch widget
        .equ    SW_TAB,   0x400bde2a    | its glyph pointers: entry value + 1
        .equ    SW_MASK,  0x400c7bd6    | stock glyph 0's mask (17 x 0xffe00000, every glyph's)
        .equ    BLIT,     0x400128a8    | blit(glyph, canvas, x, y)
        .equ    CLIP,     0x400baabe    | the link clip glyph
        .equ    KNOB,     0x400479b4    | stock knob widget
        .equ    SPRINTF,  0x40013a08
        .equ    STR_D,    0x400b465d    | "%d"

        .ifndef UIS_LOCAL               | an includer's private copy exports nothing
        .global sw9_widget
        .global sw9_draw
        .ifndef UIS_NO_SW3
        .global sw3_draw
        .endif
        .ifndef UIS_NO_CLIP
        .global clip_knob
        .endif
        .endif

        .text
        .balign 2
sw9_widget:
        move.l  16(%sp),%d0             | position = the value
        move.l  %d0,%d1
        movea.l 24(%sp),%a1             | the descriptor's formatter
sw9_draw:
        lea     sw_st(%pc),%a0
        move.l  %d1,(%a0)               | +0 the formatter's value
        move.l  %a1,4(%a0)              | +4 the formatter
        clr.l   8(%a0)                  | +8 the table entry lent (none)
        moveq   #8,%d1
        cmp.l   %d1,%d0
        bhi.s   .sw_none                | unsigned: negatives too
        asr.l   #1,%d0                  | stock's value k; C = odd
        bcc.s   .sw_call5
        move.l  %d0,%d1                 | odd: lend entry k + 1 our glyph k
        lsl.l   #2,%d1
        lea     (SW_TAB+4).l,%a1
        adda.l  %d1,%a1
        move.l  %a1,8(%a0)
        move.l  (%a1),12(%a0)           | +12 its own glyph
        move.l  %d1,%d0
        add.l   %d1,%d1
        add.l   %d1,%d1
        add.l   %d0,%d1                 | 20k
        lea     sw_g1(%pc),%a0
        adda.l  %d1,%a0
        move.l  %a0,(%a1)
        lsr.l   #2,%d0
        bra.s   .sw_call5
.sw_none:
        moveq   #-1,%d0
.sw_call5:
        lea     (SW5).l,%a1
        .ifndef UIS_NO_SW3
        bra.s   .sw_call
sw3_draw:
        lea     sw_st(%pc),%a0
        move.l  %d1,(%a0)
        move.l  %a1,4(%a0)
        clr.l   8(%a0)
        moveq   #2,%d1
        cmp.l   %d1,%d0
        bls.s   1f
        moveq   #-1,%d0
1:      lea     (SW3).l,%a1
        .endif
.sw_call:
        move.l  28(%sp),-(%sp)          | canvas
        pea     sw_fmt(%pc)             | the formatter pass-through
        move.l  28(%sp),-(%sp)          | flags
        move.l  %d0,-(%sp)              | the stock widget's value
        move.l  28(%sp),-(%sp)          | idx
        move.l  28(%sp),-(%sp)          | y
        move.l  28(%sp),-(%sp)          | x
        jsr     (%a1)
        lea     28(%sp),%sp
        lea     sw_st(%pc),%a0
        move.l  8(%a0),%d0
        beq.s   1f
        movea.l %d0,%a1                 | give the lent entry back
        move.l  12(%a0),(%a1)
1:      rts

| sw_fmt(buf, v): the caller's formatter with the caller's value (none: "%d", as stock).
sw_fmt:
        lea     sw_st(%pc),%a0
        move.l  (%a0),8(%sp)
        move.l  4(%a0),%d0
        beq.s   1f
        movea.l %d0,%a0
        jmp     (%a0)
1:      move.l  8(%sp),-(%sp)
        pea     (STR_D).l
        move.l  12(%sp),-(%sp)
        jsr     (SPRINTF).l
        lea     12(%sp),%sp
        rts

        .ifndef UIS_NO_CLIP
clip_knob:
        move.l  28(%sp),-(%sp)          | the stock knob, same arguments
        move.l  28(%sp),-(%sp)
        move.l  28(%sp),-(%sp)
        move.l  28(%sp),-(%sp)
        move.l  28(%sp),-(%sp)
        move.l  28(%sp),-(%sp)
        move.l  28(%sp),-(%sp)
        jsr     (KNOB).l
        lea     28(%sp),%sp
        moveq   #14,%d0
        add.l   8(%sp),%d0
        move.l  %d0,-(%sp)              | y + 14: the main drawer's y + 15 put the clip one
                                        | row too high here (2026-10-23, measured on the LCD
                                        | against FILTER's BASE/WDTH clip: two clear rows
                                        | under the labels; this blit's y grows upward)
        moveq   #-4,%d0
        add.l   8(%sp),%d0
        move.l  %d0,-(%sp)              | x - 4
        move.l  36(%sp),-(%sp)          | canvas
        pea     (CLIP).l
        jsr     (BLIT).l
        lea     16(%sp),%sp
        rts
        .endif

        .balign 4
sw_st:  .long   0, 0, 0, 0              | value, formatter, entry lent, its glyph
| Our four glyphs, stock's format: width 17, height 11, 1, pixels, mask.
sw_g1:  .long   17, 11, 1, sw_px1, SW_MASK
        .long   17, 11, 1, sw_px3, SW_MASK
        .long   17, 11, 1, sw_px5, SW_MASK
        .long   17, 11, 1, sw_px7, SW_MASK
| The four glyphs' pixels, one long per column (bit 31 = the bottom row: the panel blits
| bottom-up), 17 columns each; columns 0-2 and 14-16 are blank, so each glyph's last three
| are the next one's first three.
sw_px1:                                 | position 1: the pointer at 9:45
        .long   0, 0, 0
        .long   0x0e000000, 0x31800000, 0x4ac00000, 0x48c00000, 0x90a00000, 0x91200000
        .long   0xa1200000, 0x62400000, 0x62400000, 0x31800000, 0x0e000000
sw_px3:                                 | position 3: the pointer at 11:15
        .long   0, 0, 0
        .long   0x0e000000, 0x31800000, 0x43c00000, 0x4c400000, 0xb0a00000, 0x80200000
        .long   0x81a00000, 0x46400000, 0x78400000, 0x31800000, 0x0e000000
sw_px5:                                 | position 5: the pointer at 12:45
        .long   0, 0, 0
        .long   0x0e000000, 0x31800000, 0x78400000, 0x46400000, 0x81a00000, 0x80200000
        .long   0xb0a00000, 0x4c400000, 0x43c00000, 0x31800000, 0x0e000000
sw_px7:                                 | position 7: the pointer at 2:15
        .long   0, 0, 0
        .long   0x0e000000, 0x31800000, 0x62400000, 0x62400000, 0xa1200000, 0x91200000
        .long   0x90a00000, 0x48c00000, 0x4ac00000, 0x31800000, 0x0e000000
        .long   0, 0, 0
