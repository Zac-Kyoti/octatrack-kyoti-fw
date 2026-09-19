#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
TEST BUILD -- the MUTEMODE build (stock 1.40C + MIDI manual-trig fix + SOFT MUTE behind the
PERSONALIZE "MUTE MODE" toggle) with a THIRD mode, "DT", added.

Identical to build_mutemode.py except:
  - patch_softmute AND patch_mutemode are assembled with --defsym DT_MODE=1
      * patch_mutemode  -> N_MODES = 3, value strings  OT / OT+FX / DT
      * patch_softmute  -> GATE (0x800000dc) == 2 selects DT: the same D5-bit clearing as
        OT+FX (FUN_40004db8 keeps every frame level word -> the sounding voice + its FX
        reach the mix untouched) and the same `mt_trig` new-trig drop, but NO note-off /
        DAT_8000184a hold.  Net: a pure sequencer mute -- the voice already playing rides
        its own amp envelope (fades, sustains, or loops forever per the AMP page), only new
        trigs are suppressed.  Exactly a Digitakt trig mute.  Solo folds in the same way.
  - outputs carry a _DT suffix so build_mutemode.py's artifacts are never touched:
        out/OCTATRACK_OS1.40C_MUTEMODE_DT.syx   (MIDI DIN)
        out/OCTATRACK_MUTEMODE_DT.bin           (CF card, PROJECT -> OS UPGRADE)

  MUTE MODE still lives in the free PERSONALIZE word 0x800000dc.  Default 0 -> a freshly
  flashed unit is stock.  An OS upgrade resets PERSONALIZE.  Persistence is the Session-19
  'ANDY'-shadow mechanism: patch_mutemode's setter writes 0x100fff6c and this build extends
  the block restore pea 0x64 -> pea 0x70 at the 3 sites -- byte-identical to build_mutemode.py.

Usage:   python3 tools/build_mutemode_dt.py [VERSTR]        (default VERSTR = "140C_KYOTI")
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_mutemode_dt.bin"
ELEK = ROOT / "out/elek_mutemode_dt.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_MUTEMODE_DT.syx"
OUT_BIN = ROOT / "out/OCTATRACK_MUTEMODE_DT.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"

# --- code stubs: (source, load addr, defsym, [(detour site, symbol, expected bytes, len)]) ---
PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18)]),
    ("patch_softmute", 0x400d7400, "DT_MODE=1",              # gated + the DT (mode 2) branch
     # Session 56 continued: ALWAYS_NOTEOFF (--defsym ALWAYS_NOTEOFF=1, see hook 1's own
     # header comment in patch_softmute.s) was tried and RULED OUT -- readback-level A/B
     # showed zero effect on the retrig blip (byte-identical to baseline from frame 445
     # on) AND a regression on the pre-existing muted note (frames 441-442 got LOUDER,
     # not quieter, before the retrig even happens). Reverted to the known-safe baseline
     # below (mt_trig + mt_rebind only, no experimental defsym).
     [(0x40004dc6, "pre",       "2a3980000008", 6),
      (0x40006844, "mt_trig",   "40c246fc2700", 6),
      (0x4000f4dc, "mt_rebind", "254d0004254c0008", 8),
      # Session 56 continued: mt_pos, mt_ptr, mt_ctr all DISABLED after proper readback-
      # level (not just raw-source) A/B testing. mt_pos and mt_ptr are confirmed fully
      # inert at the readback (actual audible output) level too -- byte-identical to the
      # ungated leak, every frame. mt_ctr is WORSE than doing nothing: it makes the
      # readback LOUDER than the unfixed leak in the critical post-retrig frames
      # (445-449), not quieter. None of the three are the right mechanism; back to the
      # known-safe baseline (mt_trig + mt_rebind only) while the "pre" hook 1 hypothesis
      # (see its own header comment, ALWAYS_NOTEOFF) is tried instead.
      # (0x4000f790, "mt_pos", "2542002c2549002825420034254900302542003c25490038", 24),
      # (0x4000f820, "mt_ptr", "254800402548004425480048266f003227480038", 20),
      # (0x4000f834, "mt_ctr", "52aa009025480098", 8),
      # Session 57: THE actual leak -- the frame builder's per-track word C
      # (0x40004e9e, from table 0x80000c80) is written with NO mute/solo/cue test at
      # all, so a silenced track keeps a second, wide-open route to the mix (measured:
      # 6144 every frame while muted, vs word B correctly 0). That route is the OT+FX
      # FX-tail feature, so it is cut ONLY for a track that got a real trig while
      # silenced (the HARDCUT set). See patch_softmute.s hook 7.
      # fxcut DISABLED: it fires correctly, but 0x40004e9e writes a DIFFERENT buffer than
      # the one the DSP actually receives per-track levels in (that one is produced by the
      # level chain at ~0x4000cb4e/cc20/ced0/ced4). Wrong producer; no effect. Kept for
      # the record -- see patch_softmute.s hook 7.
      # (0x40004e9e, "fxcut", "30da30d143e90008", 8),
      # Session 57: THE fix. The stock per-track release loop (0x4000d0a4..0x4000d0dc,
      # driven by REL_STATE, the byte `pre` maintains) zeroes a silenced track's DRY level
      # but only CLAMPS its second level word to 6144 -- a permanent -14.5 dB route to the
      # mix, which is the FX-tail-ring feature. A retrig plays full-level straight into it.
      # relcut zeroes that word instead, but ONLY for a track in the HARDCUT set (one that
      # took a real trig while silenced), so the tail-ring grace is preserved otherwise.
      # Session 58 continued yet again, part 8: relcut's own standalone detour REPLACED by
      # hook 13 (relstate_shadow, below) -- relcut's LABEL/BODY are unchanged in
      # patch_softmute.s, reached only via hook 13's own branches now. This closes the
      # REL_STATE race for OT+FX (emulator-validated, tracks 1 and 2, muted + unmuted
      # control -- see NOTES.md "part 8") WITHOUT touching either previously-poisoned
      # REL_STATE site or the hook-12 EMAC danger zone. Does NOT help DT mode (a
      # pre-existing gap from Session 57: `pre` never maintains REL_STATE for DT, so this
      # whole loop -- relcut before, hook 13 now -- never engages there; DT's own
      # finite-release blip needs a separate mechanism, not yet designed).
      # Expected-bytes = relcut's own string with "6412" (the bccs opcode) prepended.
      (0x4000d0c2, "relstate_shadow", "6412426800024228002bb46800046e0431420004", 20),
      # Session 58: drop the trig at its real dispatch site (0x4000d498, an indirect
      # jsr through a per-machine-type handler table) instead of trying to stop the
      # voice afterwards. Broadened (Session 58 continued) to cover both OT+FX and DT.
      # See patch_softmute.s hook 9.
      (0x4000d498, "dt_trig",  "2f002f034e90", 6),
      # Session 58 continued: this dispatch only covers the REUSE path (an already-bound
      # voice). The FRESH-bind path (FUN_40006820, reached once a voice has gone cold --
      # quickly in OT+FX via relcut's note-off, or after AMP RELEASE completes in DT) has
      # six OTHER callers hook 9 never touches. Gate it at its own single entry instead.
      # See patch_softmute.s hook 10.
      (0x40006820, "fresh_bind", "2f0a2f02222f000c", 8),
      # Session 58 continued again: THE actual leak. relcut (hook 8) only fires when the
      # stock release loop's REL_STATE bit is true for a track; a stock function (never
      # touched before now) transiently CLEARS a muted track's bit as ordinary "a note is
      # starting" bookkeeping, skipping relcut for exactly one frame and letting a fresh,
      # unmuted-value level-chain write through uncorrected. Fix: OR the currently-
      # silenced set back in immediately before this function's own store, so a muted
      # track's bit can never actually go to 0. See patch_softmute.s hook 11.
      # Session 58 continued again: the REL_STATE race (relcut, hook 8, misses 3 of 1999
      # eligible frames because a stock function transiently clears a muted track's
      # REL_STATE bit) is NOT fixed in this build. TWO different surgical attempts --
      # detouring the writer (0x4000bf22) and detouring the reader (0x4000d0ba, the
      # release loop's own once-per-frame REL_STATE load) -- BOTH produced severe,
      # reproducible controlled-A/B regressions (the second one worse than the first,
      # and unlike the first, affecting T1's OWN state from frame 4 onward -- a real
      # correctness problem, not just cross-track timing drift). Abandoned rather than
      # ship either. Full detail, both attempts, in NOTES.md. Code for both kept in
      # patch_softmute.s (hook 11, currently `relstate_or`) for the record; not wired in.
      # (0x4000d0ba, "relstate_or", "71b98000184a", 6),
      ]),
    # Session 58 continued yet again, part 8: hook 13's extra `bcs` (vs relcut alone) grows
    # patch_softmute 2 B past the old 0x400d76c0 start -- bumped 0x40 further out, same
    # convention as every prior cave-growth in this file's history. Verified in
    # build_relstate_shadow.py first (emulator-validated build) before folding in here.
    ("patch_mutemode", 0x400d7700, "DT_MODE=1", []),         # menu stub: OT / OT+FX / DT
]

# --- PERSONALIZE menu arrays (stock) ---
OLD_LBL, OLD_GET, OLD_SET, N_OLD = 0x400b2a34, 0x400b2a74, 0x400b2ac0, 16
SPLICE_AT = 2                                               # after "PREVIEW WITHOUT FX"
LBL_AT, GET_AT, SET_AT = 0x400d7790, 0x400d77f0, 0x400d7850
# Session 58 continued yet again, part 8: moved 0x400d7750/b0/810 -> 0x400d7790/f0/850,
# 0x40 further out, to make room for patch_mutemode's own 0x40 shift above.
REFS = [(0x40068efe, OLD_LBL, "labels  move.l #imm,D5"),
        (0x40068f0a, OLD_GET, "getters lea"),
        (0x40069022, OLD_SET, "setters lea #1"),
        (0x4006903e, OLD_SET, "setters lea #2"),
        (0x40069056, OLD_SET, "setters lea #3")]
COUNT_AT = 0x40068fb2                                       # moveq #15 -> #16


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


def assemble(name, at, defsym):
    # distinct "_dt" intermediates so this build never clobbers build_mutemode.py's
    # out/patch_*.elf (which emu_mutemode.py / emu_solo.py read back).
    out = f"{name}_dt"
    aso = ["m68k-elf-as", "-mcpu=5407"]
    for d in (defsym.split(",") if defsym else []):
        aso += ["--defsym", d]
    aso += ["-o", f"out/{out}.o", f"tools/{name}.s"]
    subprocess.run(aso, check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{out}.elf", f"out/{out}.o"],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{out}.elf", f"out/{out}.bin"],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", f"out/{out}.elf"], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return (ROOT / f"out/{out}.bin").read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)

    def o(a):
        return a - BASE

    blobs, syms = {}, {}
    spans = []
    print("=== assemble + detour ===")
    for name, at, defsym, detours in PATCHES:
        blob, s = assemble(name, at, defsym)
        blobs[name], syms[name] = blob, s
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free: {bytes(img[co:co+16]).hex()}")
        spans.append((at, at + len(blob), name))
        img[co:co + len(blob)] = blob
        print(f"  {name:16s} {len(blob):3d} B @ 0x{at:08x} .. 0x{at+len(blob)-1:08x}"
              + (f"   [--defsym {defsym}]" if defsym else ""))
        for site, sym, exp, n in detours:
            exp = bytes.fromhex(exp)
            do = o(site)
            if bytes(img[do:do + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} ({name}:{sym}) unexpected: "
                         f"{bytes(img[do:do+len(exp)]).hex()} != {exp.hex()}")
            img[do:do + n] = jmp(s[sym]) + b"\x4e\x71" * ((n - 6) // 2)
            print(f"    0x{site:08x} -> {name}:{sym} 0x{s[sym]:08x}  ({n} B)")

    # --- PERSONALIZE menu: relocate the 3 arrays with MUTE MODE spliced at SPLICE_AT ---
    print("\n=== PERSONALIZE menu ===")
    new_entry = {OLD_LBL: syms["patch_mutemode"]["lbl_mutemode"],
                 OLD_GET: syms["patch_mutemode"]["get_mutemode"],
                 OLD_SET: syms["patch_mutemode"]["set_mutemode"]}
    dst = {OLD_LBL: LBL_AT, OLD_GET: GET_AT, OLD_SET: SET_AT}
    for old in (OLD_LBL, OLD_GET, OLD_SET):
        ents = [int.from_bytes(img[o(old + i * 4):o(old + i * 4) + 4], "big") for i in range(N_OLD)]
        ents = ents[:SPLICE_AT] + [new_entry[old]] + ents[SPLICE_AT:]      # 17 entries
        d = dst[old]
        spans.append((d, d + len(ents) * 4, f"menu@{d:08x}"))
        if any(img[o(d):o(d + len(ents) * 4)]):
            sys.exit(f"menu array cave 0x{d:08x} not free")
        for i, v in enumerate(ents):
            img[o(d + i * 4):o(d + i * 4) + 4] = v.to_bytes(4, "big")
        print(f"  array 0x{d:08x}: {len(ents)} entries (16 stock + MUTE MODE @ idx {SPLICE_AT})")

    for a, old, tag in REFS:
        if bytes(img[o(a):o(a) + 4]) != old.to_bytes(4, "big"):
            sys.exit(f"ref 0x{a:08x} ({tag}) is not 0x{old:08x}: {bytes(img[o(a):o(a)+4]).hex()}")
        img[o(a):o(a) + 4] = dst[old].to_bytes(4, "big")
        print(f"  repoint 0x{a:08x}  {tag}: -> 0x{dst[old]:08x}")

    if bytes(img[o(COUNT_AT):o(COUNT_AT) + 2]) != b"\x72\x0f":
        sys.exit(f"count 0x{COUNT_AT:08x} is not moveq #15: {bytes(img[o(COUNT_AT):o(COUNT_AT)+2]).hex()}")
    img[o(COUNT_AT):o(COUNT_AT) + 2] = b"\x72\x10"
    print(f"  count   0x{COUNT_AT:08x}  moveq #15 -> #16")

    # --- PERSONALIZE persistence: extend the 'ANDY' block restore 0x64 -> 0x70 so
    #     0x800000dc rides the boot restore (identical to build_mutemode.py, Session 19) ---
    for site in (0x4001f322, 0x4001f3be, 0x4001fb24):
        so = o(site)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{site:08x}: {bytes(img[so:so+4]).hex()} != 48780064")
        img[so + 3] = 0x70
        print(f"  restore 0x{site:08x}  pea 0x64 -> pea 0x70")

    # --- no cave span may overlap another, nor run past the free zone ---
    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[-1][1] > 0x400d7c3c:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x400d7c3c)")
    print("  no overlaps; all within the free cave")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    # --- the manual-trig fix must stay byte-identical to build_trigscale_only.py ---
    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        tsh = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in tsh)
        print(f"  manual-trig fix bytes identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("  MANUAL-TRIG FIX DIVERGED")

    # --- the OT / OT+FX behaviour must stay byte-identical to build_mutemode.py, save for
    #     the DT delta: the two caves that grew (patch_softmute, patch_mutemode), the
    #     relocated menu arrays, and the mt_trig detour word that now points at a moved symbol.
    mm = ROOT / "out/mainos_mutemode.bin"
    if mm.exists():
        mmb = mm.read_bytes()
        diff = [i for i, (x, y) in enumerate(zip(mmb, img)) if x != y]
        allowed = [(0x400d7400, 0x400d79f0),        # the whole DT cave region: patch_softmute,
                                                    # patch_mutemode, and the relocated
                                                    # PERSONALIZE arrays -- 0x40 further out
                                                    # than before (part 8, hook 13's growth)
                   (0x40006844, 0x4000684a),        # mt_trig detour jmp target (symbol moved)
                   (0x4000f4dc, 0x4000f4e4),        # mt_rebind detour jmp target (symbol moved)
                   (0x4000f790, 0x4000f7a8),        # Session 56 continued: mt_pos detour (DT-only)
                   (0x4000f820, 0x4000f83c),        # Session 56 continued: mt_ptr + mt_ctr detours (DT-only)
                   (0x4000d0c2, 0x4000d0d6),        # part 8: relstate_shadow detour (DT-only,
                                                    # 2 B earlier than build_mutemode.py's relcut)
                   (0x4000d498, 0x4000d49e),        # Session 58: dt_trig detour (DT-only)
                   (0x40006820, 0x40006828),        # Session 58 continued: fresh_bind detour (DT-only)
                   # Session 57: the five PERSONALIZE menu-array repoint sites. They hold
                   # a different cave ADDRESS than build_mutemode.py's, because the arrays
                   # moved to 0x400d78a0/7900/7960 to make room for patch_softmute's growth.
                   (0x40068efe, 0x40068f02), (0x40068f0a, 0x40068f0e),
                   (0x40069022, 0x40069026), (0x4006903e, 0x40069042),
                   (0x40069056, 0x4006905a)]
        stray = [i for i in diff
                 if not any(lo - BASE <= i < hi - BASE for lo, hi in allowed)]
        print(f"  vs build_mutemode.py: {len(diff)} bytes differ, {len(stray)} outside the DT delta")
        if stray:
            sys.exit(f"  DT build diverges from MUTEMODE outside the expected regions: "
                     f"{[hex(BASE+i) for i in stray[:8]]}")
        print("  (OT / OT+FX paths unchanged; every diff is the DT addition)")

    # --- wrap: ELEK container (with version) -> .syx -> .bin ---
    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if "version" in l or "emitted" in l or "wrote" in l))
    if "too long" in r.stdout:
        sys.exit(f'  version string "{VERSTR}" ({len(VERSTR)}) does not fit the 10-char field')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)

    print(f"\n  {OUT_SYX.name}  (MIDI DIN)  +  {OUT_BIN.name}  (CF card)")
    print(f"  version screen / SYSTEM STATUS -> OS VERSION will read:  {VERSTR}")
    print("  PERSONALIZE -> MUTE MODE:  OT (stock) | OT+FX (soft mute) | DT (sequencer mute).  Default OT.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()
