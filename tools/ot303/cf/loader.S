| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti; derived from octabam's tools/remix/loader.S (Sam Banks,
| MIT), whose design is Em's Octakit loader (emuyia/ems-octakit, runtime/loader.S).
|
| OT-303's boot loader: appended after the stock OS image (0x4010fdf0, the byte after it) and
| reached from the boot site 0x4000050c, whose `jsr 0x40001e50` (boot continue) the builder
| retargets here. It replays that call first, exactly as octabam's loader does, then copies the
| OT-303 runtime (the ColdFire code, linked at its arena reserve) from this append into the
| reserve through the uncached alias, and hash-gates the copy (rolling x33, octabam's function).
| A mismatch hangs the boot visibly (`bra fatal`): a half-loaded runtime is worse than a stuck
| boot, and the unit's own boot loader can still take a new OS.
| --defsym: DST (the reserve, uncached), LEN (bytes), HASH (x33 over the runtime).

        .set    BOOT_CONTINUE, 0x40001e50

        .text
        .global ot_loader
ot_loader:
        jsr     (BOOT_CONTINUE).l
        lea     (-24,%sp),%sp
        movem.l %d0-%d3/%a0-%a1,(%sp)
        lea     runtime(%pc),%a0
        move.l  #DST,%a1
        move.l  #LEN,%d0
copy:
        move.b  (%a0)+,(%a1)+
        subq.l  #1,%d0
        bne.s   copy
        move.l  #DST,%a0
        move.l  #LEN,%d0
        moveq   #0,%d1
hash:
        move.l  %d1,%d2
        lsl.l   #5,%d1
        add.l   %d2,%d1
        moveq   #0,%d2
        move.b  (%a0)+,%d2
        add.l   %d2,%d1
        subq.l  #1,%d0
        bne.s   hash
        cmp.l   #HASH,%d1
        bne.s   fatal
        movem.l (%sp),%d0-%d3/%a0-%a1
        lea     (24,%sp),%sp
        rts
fatal:
        bra.s   fatal

        .balign 4
runtime:
        .incbin "ot303_runtime.bin"
