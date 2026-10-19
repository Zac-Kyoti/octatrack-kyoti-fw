| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| VARISPEED as a STORE client (octabam): the PART menu's CLEAR holds and forgets through
| STORE's events instead of a detour of its own at 0x4004a9d0, the site STORE owns. Stock
| Part Clear ends in a tail jump to Part Save (0x4004aaae: bra 0x4004a908), whose only exit
| is 0x4004a9c4, where STORE fires partsaved. So partclear (before the clear) and the
| partsaved that ends it bracket the clear as vh_partclear's call does in the standalone.
| A partsaved with no partclear before it (SAVE PART) does nothing. STORE saves every
| register around its handlers (store.s, fire); vh_enter / vh_leave rts to STORE.
        .text
        .global vs_st_partclear
        .global vs_st_partsaved
vs_st_partclear:                        | d0 = the part
        lea     vs_clearing(%pc),%a0
        moveq   #1,%d1
        move.b  %d1,(%a0)
        jmp     vh_enter                | HOLD (counted)
vs_st_partsaved:                        | d0 = the part
        lea     vs_clearing(%pc),%a0
        tst.b   (%a0)
        beq.s   1f
        clr.b   (%a0)
        jmp     vh_leave                | the clear is done: forget, so the next poll adopts
1:      rts
vs_clearing:
        .byte   0
        .balign 2
