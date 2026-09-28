; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; repitch-kyoti -- DSP side: the RPS9 and RPSP character modes.
; Scope: reference/handoffs/REPITCH_KYOTI_SCOPE.md (gates 3 and 4).
;
; WHERE IT RUNS. The stock voice engine (payload A P:0x3a1, payload B
; P:0x1a4 -- identical code, relocated by 0x1fd) is detoured at its kernel
; prologue, A P:0x40b / B P:0x20e: the pair
;       move x:(r5),n6          ; 76e500
;       move y:(r5)+,a          ; 5edd00
; becomes `bsr zqrp`, and both moves run at this routine's tail. The site is
; inside the per-voice outer `do #2` loop but NOT at its end (that is the NOP
; at A P:0x41b, where a branch would be illegal), so this runs once per voice,
; after the fraction table and the source ring are complete and before the
; stock kernel reads either. THE STOCK KERNEL IS NEVER MODIFIED.
;
; STATE ON ENTRY (measured from the module, not assumed):
;   r5  = $80, start of the per-output table: x:$80+i = ring offset,
;         y:$80+i = raw phase fraction (the kernel halves it with lsr)
;   r7  = entries in that table (>= 1: stock's own `do r7` is unguarded)
;   r6  = r2 = this voice's ring base, m6 = $7f (a 128-word modulo ring)
;   l:$40 = this voice's increment as Q24, so y:$40 = its fraction word.
;
; THE MODE. The ColdFire puts it in Q26 bits 2-3 of the increment
; (tools/patch_repitch_kyoti.s, rate_hook). The voice engine rebuilds Q24 as a
; net >>2 (P:0x3bd/0x3bf), so those bits arrive as y:$40 bits 0-1:
;       0 RPCH  stock 2-tap linear         -> nothing to do
;       1 RPS9  linear over 12-bit samples -> truncate the ring
;       2 RPSP  ZOH over 12-bit samples    -> truncate the ring, zero fractions
; The ColdFire clears bits 2-3 on EVERY increment it emits, and every other
; increment writer stores the literal 0x04000000, so a nonzero mode can only
; come from a tagged repitch track. (3 is never emitted; it would act as 1.)
;
; WHY TRUNCATE THE RING, NOT THE OUTPUT. The S950 and the SP-1200 STORED
; 12-bit samples and played them back; quantizing the stored samples is the
; faithful model, and it needs no hook after the kernel (whose loop end is
; that illegal-for-branches NOP). Samples in the ring are MSB-aligned 24-bit
; fractions -- the kernel's mac results are stored straight from a1/b1 -- so
; 12 bits is `and #$fff000`.
;
; WHY ZERO THE FRACTIONS. With f = 0 the stock kernel's own arithmetic is
;       a = L0*(1-0) + L1*0 = L0,   b = R0*(1-0) + R1*0 = R0
; exactly: a zero-order hold, i.e. drop/repeat, which is the SP-1200.
;
; LABELS: no label may be a PREFIX of another. With the entry named `rpd`,
; `beq rpd9` assembled as `beq -$69` -- a backwards branch to a forward label
; -- and was rejected; renaming only the entry fixed it with `rpd9` intact, so
; dsp_asm's label lookup matches on prefix. (Not the leading register letter:
; `rpd9` itself assembled fine once `rpd` was gone.) The zq names avoid it.
; Also: `bsr >$1000` takes $1000 as a literal DISPLACEMENT, not a target --
; hooks are encoded with build_sidechain3.bsr_long (target - site), the
; convention SIDECHAIN3_CROSS's hardware-confirmed hooks use.
;
; REGISTERS. Uses a, b, x1, r1 -- all reloaded by stock before their next
; use (the kernel sets a/b/x1 per sample; r1 is reset at P:0x3f9). r6 walks
; the ring 128 times under m6 = $7f and so ends where it started. r0, r2, r3,
; r4, r5, r7, m6, n2, n4 are untouched.
; ===========================================================================

zqrp:
        clr     a                       ; a2 = a0 = 0 before the load, so the
        move    y:>$40,a1               ; mask and the tests see a1 alone
        and     #>3,a                   ; a1 = mode
        tst     a
        beq     zq9                    ; RPCH: stock, untouched
        move    #>$fff000,x1
        do      #<$80,>zq1             ; the whole ring: 128 steps under
        move    x:(r6),b                ; m6 = $7f return r6 to its start
        and     x1,b
        move    b1,x:(r6)+
zq1:
        cmp     #>2,a
        bne     zq9                    ; RPS9 stops here
        move    r5,r1                   ; RPSP: f = 0 on every entry
        clr     b
        do      r7,>zq9
        move    b1,y:(r1)+
zq9:
        move    x:(r5),n6               ; displaced from the hook site
        move    y:(r5)+,a               ; displaced from the hook site
        rts
