; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
;
; OT-303 Phase 0b -- a cycle-burn knob on DJ EQ (diagnostic image only).
; reference/handoffs/OT303_SCOPE.md §8 Phase 0, §10.
;
; Reached instead of DJ EQ's process routine: the dispatch table X:$235[$0d] points here, and
; the last instruction branches to DJ EQ's stock proc, whose rts returns to the dispatcher.
; DJ EQ's proc reads r0, r6, n7 and loads a/b/x0/y1 itself before using them (disassembled,
; both payloads), so this body may use a, x0 and y1 and must leave every address register.
;
; burn = 24 * BURN cycles/sample: (8 * BURN * n7) iterations of a three-word body over the n7
; samples of this call. The body, its scaling and the zero guard are octabam's RIG BURN probe
; (dsp/burn_send.inc, Sam Banks et al., MIT; hardware-proven 13 Sep 2026): mpy is fractional,
; so n7 (an integer, x0) times the raw knob word p<<16 (y1) leaves n7*p*2^17 in A[47:0], and
; A1 = A[47:24] shifted by #$a is 8*p*n7 exactly (max 16256).
; THE ZERO GUARD IS LOAD-BEARING: DO with a count of 0 loops 65536 times. asl sets Z.
;
; BURN is DJ EQ page-2 slot 6 = x:(r6+$c) bits 16-23 (octabam PARAM_PAGES §6; the slot SEND's
; BURN used). DJ EQ's own page 2 is empty on stock (enable nibbles p6..p11 = 0).
zbburn:
        move    x:(r6+$c),a             ; BURN: page-2 slot 6, bits 16-23
        and     #>$7f0000,a
        move    a1,y1
        move    n7,x0                   ; frames on THIS call
        mpy     x0,y1,a
        asl     #$a,a,a                 ; A1 = 8 * BURN * n7; Z if either is 0
        beq     zbnob
        do      a1,zbend
        nop
        nop
        nop
zbend:
zbnob:
zbout:
        dc      $0d10c0,0               ; bra >DJ EQ's stock proc (long form): the builder
                                        ; writes the displacement and checks it by disassembly
