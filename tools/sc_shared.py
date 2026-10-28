# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
SIDECHAIN_COMPRESSOR's shared form: tools/patch_sc_dsp3.asm rewritten so ONE copy of the code
runs on both DSP cores. Opt-in, for octabam's demand loader only (octabam
docs/proposals/SC_DEMAND_LOAD.md): the loader copies one block into the shared window while a
COMPRESSOR is in use and withdraws it when none is, so the code must assemble to the same words
on both payloads and carry its cross-core key window with it.

Nothing else reads this file. tools/patch_sc_dsp3.asm is not edited, and the standalone, KYOTI,
Modwerk and default octabam builds assemble it exactly as before. octabam selects this form with
the module's FORM setting (octabam-modules/sidechain-compressor/manifest.py).

What changes, against the per-core source (every other line is the source's own):

  the per-core tokens  @COREBASE@ / @FCOREBASE@ / @SBASE@ / @FSBASE@ / @FOREIGN_BR@ are not
      used: every value comes from the track, x:$420 (0..7; core A runs 4-7, core B 0-3).
      sctap's "core-local track 0" gate is `track & 3 == 0`; scdet's same/foreign test is
      `(my track xor KEY track) & 4`.
  the key window   follows the tables: 8 tracks x 4 generations x 32 words, indexed by the
      ABSOLUTE track, slot(t, gen) = WIN + t*$80 + gen*$20 (the per-core form has two $200
      halves at fixed addresses). WIN = zzend (the word after the code) + the two tables, which
      octabam's window placement puts right behind the code (the ptable, then the ptable2). The
      manifest appends the window's words to the ptable2 as zeros (SHARED_PTABLE2_TAIL), so the
      loader copies them with the code: the window is clear on every load, and the reverb guard
      keeps reverbs off it with the code. ONLY octabam's window placement lays the tables out
      this way; the form is not for a harvested placement, which puts the tables before the code.
  the generation counters   GCNT moves behind the window: WIN + $400 is core B's (tracks 0-3),
      WIN + $401 core A's (tracks 4-7), zeroed with the window on every load. GSEED is gone:
      the load's zeroing is the seed.
  the foreign read   reads the KEY track's core's counter f and takes generation f - 1, the last
      one that core finished. The per-core form reads its OWN counter minus 2, which is right
      only while both counters advance together (the rate-locked assumption, unverified). Under
      the loader both counters stop while the code is withdrawn and the cores see a load up to a
      frame apart, so they would drift; reading the writer's own counter needs no lock-step.
      Generation f - 1 is not written again until the writer has advanced three more times.

Registers: the same as the per-core source's, plus x1 in scdet's same/foreign test (x1 is
written before it is read on both paths that follow, at the foreign copy and at KEY GAIN).
"""

import importlib.util
import os

_TOOLS = os.path.dirname(os.path.realpath(__file__))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sc = _load("kyoti_sc_tables_shared", "sc_tables.py")
_kf = _load("kyoti_sc_keyfilt_shared", "sc_keyfilt.py")

WINDOW_WORDS = 0x400                    # 8 tracks x 4 generations x 32 words
COUNTER_WORDS = 2                       # WIN + $400 core B, WIN + $401 core A
TABLE_WORDS = _sc.GAIN_N + len(_kf.GT)  # the KEY GAIN table and the key-filter table, behind the code
SHARED_PTABLE2_TAIL = (0,) * (WINDOW_WORDS + COUNTER_WORDS)   # appended to the ptable2 by the manifest

# The per-core tokens the shared form no longer uses. A consumer may still pass them (octabam's
# subst carries every layout token); they then only land in comments.
UNUSED_TOKENS = ("@COREBASE@", "@FCOREBASE@", "@SBASE@", "@FSBASE@", "@GCNT@", "@GSEED@",
                 "@FOREIGN_BR@")


def _lua_steps(reg, dest, n):
    """`lua` lines adding n to reg, the last into dest: lua takes -64..63 (AGENTS.md's lua trap)."""
    steps, out = [], []
    while n > 63:
        steps.append(63)
        n -= 63
    steps.append(n)
    for k, d in enumerate(steps):
        out.append(f"        lua     ({reg}+${d:x}),{dest if k == len(steps) - 1 else reg}")
    return "\n".join(out) + "\n"


def _once(src, old, new, what):
    if src.count(old) != 1:
        raise ValueError(f"sc_shared: {what}: expected exactly one match in patch_sc_dsp3.asm, "
                         f"found {src.count(old)} (the source moved; update tools/sc_shared.py)")
    return src.replace(old, new)


_GATE = """        move    x:>$420,a               ; a1 = track index 0..7
        cmp     #>@COREBASE@,a
        bne     zz30                    ; not this core's local index 0 -> skip
"""
_GATE_SHARED = """        move    x:>$420,a               ; a1 = track index 0..7
        and     #>$3,a                  ; shared form: core-local index 0 is track & 3 == 0
        bne     zz30                    ; not this core's local index 0 -> skip
"""

_SEED_START = "        move    #>@GSEED@,r1\n"
_SEED_END = """        move    a,y:(r1)
zz30:
"""
_ADVANCE_SHARED = """; shared form: this core's counter, zeroed with the window on every load, so no seed
        bsr     zzgo                    ; r1 -> this core's counter
        move    y:(r1),b
        add     #>1,b
        and     #>3,b                   ; wrap 0..3 (masking risk on b)
        move    b1,a                   ; (q3) a = clean wrapped value
        move    a,y:(r1)
zz30:
"""

_OWN = """        move    x:>$420,a
        sub     #>@COREBASE@,a          ; a1 = local index 0..3 (plain subtract,
                                        ; not a masking op -- no staleness risk)
        asl     #2,a,a                  ; a1 = local*4
        move    a1,x0                   ; x0 = local*4 (audited-safe scratch)
        move    #>@GCNT@,r1
        move    y:(r1),b
"""
_OWN_SHARED = """        move    x:>$420,a               ; shared form: the absolute track indexes the window
        asl     #2,a,a                  ; a1 = track*4
        move    a1,x0                   ; x0 = track*4 (audited-safe scratch)
        bsr     zzgo                    ; r1 -> this core's counter (b, n1)
        move    y:(r1),b
"""

_SBASE = """        move    #>@SBASE@,r1
        lua     (r1)+n1,r6              ; r6 -> this track's shared-window slot
"""
_SBASE_SHARED = """        move    #>zzend,r1              ; shared form: the window follows the code and its tables
        lua     (r1)+n1,r1
""" + _lua_steps("r1", "r6", TABLE_WORDS)

_SELECT = """        move    r4,b                   ; b = abs track (fresh reload; a/n1/r1
                                        ; just spent above computing r5)
        and     #>4,b                  ; b = 4 if track's high half is set, else 0
        move    b1,a                  ; (q3) a = clean 4-or-0
        tst     a
        @FOREIGN_BR@                    ; -> zz24 iff this track is on the OTHER
"""
_SELECT_SHARED = """        move    r4,b                   ; b = abs track (fresh reload; a/n1/r1
                                        ; just spent above computing r5)
        move    x:>$420,x1             ; shared form: my track
        eor     x1,b                   ; the two tracks' core bits differ ...
        and     #>4,b                  ; ... iff bit 2 of the xor is set
        move    b1,a                  ; (q3) a = clean 4-or-0
        tst     a
        bne     zz24                    ; -> zz24 iff this track is on the OTHER
"""

_FOREIGN = """        move    r4,a                    ; a = abs track
        sub     #>@FCOREBASE@,a         ; a = foreign-local index 0..3 (plain
                                        ; subtract, no masking risk -- @FOREIGN_BR@
                                        ; already proved this track is on the
                                        ; foreign half, so this is always in range)
"""
_FOREIGN_SHARED = """        move    r4,a                    ; a = abs track (shared form: indexes the window as is)
"""

_FGEN = """        move    #>@GCNT@,r1
        move    y:(r1),b
        add     #>2,b                   ; b = GCNT + 2 (== GCNT - 2 mod 4)
"""
_FGEN_SHARED = f"""        move    r4,b                    ; shared form: the KEY track's core's counter ...
        asr     #2,b,b
        and     #>$1,b
        add     #>${TABLE_WORDS + WINDOW_WORDS:x},b
        move    b1,n1
        move    #>zzend,r1
        lua     (r1)+n1,r1
        move    y:(r1),b
        add     #>3,b                   ; ... minus 1: the last generation that core finished
"""

_FSBASE = """        move    #>@FSBASE@,r1
        lua     (r1)+n1,r1              ; r1 -> foreign track's shared-window slot
"""
_FSBASE_SHARED = """        move    #>zzend,r1              ; shared form: the window follows the code and its tables
        lua     (r1)+n1,r1
""" + _lua_steps("r1", "r1", TABLE_WORDS)

_TAIL = f"""
; ---- shared form: r1 -> the counter of the core that runs track x:$420 (b, n1) ----
zzgo:
        move    x:>$420,b
        asr     #2,b,b                  ; b1 = track / 4 (the remainder in b0 is not read)
        and     #>$1,b                  ; 1 for tracks 4-7 (core A), 0 for 0-3 (core B)
        add     #>${TABLE_WORDS + WINDOW_WORDS:x},b ; the counters follow the tables and the window
        move    b1,n1
        move    #>zzend,r1
        lua     (r1)+n1,r1
        rts
; ---- shared form: the word after the code; the tables, then the window and counters ----
zzend:
"""


def shared_form(src):
    """patch_sc_dsp3.asm's text -> the shared form's (see the module docstring)."""
    out = _once(src, _GATE, _GATE_SHARED, "sctap's core-local gate")
    a, b = out.find(_SEED_START), out.find(_SEED_END)
    if out.count(_SEED_START) != 1 or out.count(_SEED_END) != 1 or not 0 <= a < b:
        raise ValueError("sc_shared: sctap's GSEED/GCNT advance moved; update tools/sc_shared.py")
    out = out[:a] + _ADVANCE_SHARED + out[b + len(_SEED_END):]
    out = _once(out, _OWN, _OWN_SHARED, "sctap's own slot")
    out = _once(out, _SBASE, _SBASE_SHARED, "sctap's window base")
    out = _once(out, _SELECT, _SELECT_SHARED, "scdet's same/foreign select")
    out = _once(out, _FOREIGN, _FOREIGN_SHARED, "the foreign copy's index")
    out = _once(out, _FGEN, _FGEN_SHARED, "the foreign copy's generation")
    out = _once(out, _FSBASE, _FSBASE_SHARED, "the foreign copy's window base")
    for tok in UNUSED_TOKENS:
        code = [l for l in out.split("\n") if tok in l.split(";", 1)[0]]
        if code:
            raise ValueError(f"sc_shared: {tok} is still used by code: {code}")
    return out.rstrip("\n") + "\n" + _TAIL


def window_base(zzend):
    """The window's first word, given the address of zzend (tests, and octabam's records)."""
    return zzend + TABLE_WORDS
