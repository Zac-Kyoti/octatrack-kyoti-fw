| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
|
| repitch-kyoti: stock RELOAD PART (FUN_4004aab4(part)) as a Part apply.
|
| rp_swap (patch_repitch_kyoti.s) polls each track's repitch gate every frame and
| treats a change as a LIVE edit -- SETUP TSTR or ATTR under AUTO -- swapping the
| PTCH/QUAN values and marking the Part edited. The two Part-apply routines it
| hooks (0x40009094, 0x40009e00) reset that bookkeeping; RELOAD PART applies
| through neither (it copies the saved Part in and calls 0x40009848 +
| 0x400972fc), so after a reload whose saved Part differs in some track's TSTR,
| rp_swap saw a "live edit" and swapped values that were already right
| (Session 119, reproduced in ot_emu; the hardware symptom was the Spatializer
| that the swap's flag write planted in saved Part 1).
|
| Forgetting only at the entry or only at the exit is not enough: the frame ISR
| runs rp_swap while the Part is being copied in. So every track is put on HOLD
| (rp_prev = RP_HOLD, which rp_swap leaves alone) for the whole call, then
| forgotten (0xff: the next poll adopts the reloaded state).
|
| Two pieces so the combined image can place them in small pads.
| RP_PREV / RP_FORGET come from the main cave's link (--defsym).
| Detour: 0x4004aab4, 8 B `lea -32(sp),sp ; movem.l d2-d5/a2-a3,(sp)` -> jmp rp_reload.

        .section .rp_rl,"ax"
        .global rp_reload
rp_reload:
        lea     (RP_PREV).l,%a1
        move.l  #0xfefefefe,%d0         | RP_HOLD in all eight tracks' bytes
        move.l  %d0,(%a1)+
        move.l  %d0,(%a1)
        move.l  4(%sp),-(%sp)           | the part argument, again
        jsr     rp_reload_body          | stock RELOAD PART; its rts returns here
        addq.l  #4,%sp
        jmp     (RP_FORGET).l           | forget, then rts to our caller -- rp_forget
                                        | uses d1/a0 only, so the verdict in d0 survives

        .section .rp_rb,"ax"
        .global rp_reload_body
rp_reload_body:
        lea     -32(%sp),%sp            | displaced
        movem.l %d2-%d5/%a2-%a3,(%sp)   | displaced
        jmp     (0x4004aabc).l
