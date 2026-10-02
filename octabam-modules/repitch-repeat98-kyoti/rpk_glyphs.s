| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| rpk_glyphs -- the seven TSTR position glyphs of REPITCH_REPEAT98_KYOTI's 7-position
| selector, as the octabam module links them (the standalone builder generates the same
| bytes in tools/build_repitch_repeat98_kyoti.py, make_glyphs()). Stock's visual
| language: a 17x7 bordered box, a dithered field, and a clear cell at the selected
| position (stride 2 for 7 positions).
|
|   rpk_glyph_tab   7 x u32  -> the records
|   record k        5 x u32  = width 17, height 7, 1, -> bitmap k, 0x400c89a6 (the
|                              fifth long every stock icon record carries)
|   bitmap k       17 x u32  = one column per long, pixels in the top byte
    .text
    .align 2
    .global rpk_glyph_tab
rpk_glyph_tab:
    .long   rpk_glyph_rec0
    .long   rpk_glyph_rec1
    .long   rpk_glyph_rec2
    .long   rpk_glyph_rec3
    .long   rpk_glyph_rec4
    .long   rpk_glyph_rec5
    .long   rpk_glyph_rec6
rpk_glyph_rec0:
    .long   17, 7, 1, rpk_glyph_data0, 0x400c89a6
rpk_glyph_rec1:
    .long   17, 7, 1, rpk_glyph_data1, 0x400c89a6
rpk_glyph_rec2:
    .long   17, 7, 1, rpk_glyph_data2, 0x400c89a6
rpk_glyph_rec3:
    .long   17, 7, 1, rpk_glyph_data3, 0x400c89a6
rpk_glyph_rec4:
    .long   17, 7, 1, rpk_glyph_data4, 0x400c89a6
rpk_glyph_rec5:
    .long   17, 7, 1, rpk_glyph_data5, 0x400c89a6
rpk_glyph_rec6:
    .long   17, 7, 1, rpk_glyph_data6, 0x400c89a6
rpk_glyph_data0:                      | position 1
    .long   0xfe000000, 0x82000000, 0x82000000, 0x82000000, 0xfe000000, 0xaa000000
    .long   0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000
    .long   0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xfe000000
rpk_glyph_data1:                      | position 2
    .long   0xfe000000, 0xaa000000, 0xfe000000, 0x82000000, 0x82000000, 0x82000000
    .long   0xfe000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000
    .long   0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xfe000000
rpk_glyph_data2:                      | position 3
    .long   0xfe000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xfe000000, 0x82000000
    .long   0x82000000, 0x82000000, 0xfe000000, 0xaa000000, 0xd6000000, 0xaa000000
    .long   0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xfe000000
rpk_glyph_data3:                      | position 4
    .long   0xfe000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000
    .long   0xfe000000, 0x82000000, 0x82000000, 0x82000000, 0xfe000000, 0xaa000000
    .long   0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xfe000000
rpk_glyph_data4:                      | position 5
    .long   0xfe000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000
    .long   0xd6000000, 0xaa000000, 0xfe000000, 0x82000000, 0x82000000, 0x82000000
    .long   0xfe000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xfe000000
rpk_glyph_data5:                      | position 6
    .long   0xfe000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000
    .long   0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xfe000000, 0x82000000
    .long   0x82000000, 0x82000000, 0xfe000000, 0xaa000000, 0xfe000000
rpk_glyph_data6:                      | position 7
    .long   0xfe000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000
    .long   0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000, 0xd6000000, 0xaa000000
    .long   0xfe000000, 0x82000000, 0x82000000, 0x82000000, 0xfe000000
