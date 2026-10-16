#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Build VARISPEED on TOP OF STOCK 1.40C (WIP).

VARISPEED is VARI with QUAN and nothing emulated (spec §7): STATIC / FLEX TSTR gets a fifth
position, VARI; a VARI track plays dry at (project BPM x p) / (sample BPM x q), p/q the QUAN
ratio on the PTCH knob, exact in integers, an octave fold above 2x, RATE still applying; a
sample or project tempo outside 30..300 BPM plays as TSTR OFF. The audio editor's ATTR
TIMESTRETCH gains VARI. PTCH <-> QUAN swap with per-machine parks, the paste / clear / undo
and RELOAD PART holds, rp_sync. A VARI track's increment is VARISPEED_EMUS's on EMUS = OT,
bit for bit. No EMUS (TSNS stays TSNS), no engine tag or latch, no mask on stock tracks'
increments, no load guard, and no DSP change: SPRING REVERB stays, both FX choosers stock.
Spec: reference/handoffs/VARISPEED_SPEC.md §7; this build: VARISPEED_IMPL.md §14.

  ColdFire: octabam-modules/varispeed-emus/varispeed_emus.s -- the VARISPEED_EMUS source,
            assembled with VEM_EMUS = 0 (one source, so a fix lands in both); one unit at
            the classic cave's proven start (0x400d6500), the shared sites, pokes and splice
            of tools/varispeed_buildlib.py (17 detours, 10 descriptor pokes).
  DSP:      none. The builder refuses to write any byte that is not the unit's, a detour's
            or a poke's, so the DSP payloads and the FX choosers are stock by construction.

    out/mainos_varispeed.bin                   patched MAIN OS
    out/OCTATRACK_OS1.40C_VARISPEED.syx        MIDI DIN
    out/OCTATRACK_VARISPEED.bin                CF card
    out/elek_varispeed.bin                     the EFT container (make_bin's input)
    out/varispeed_syms.json                    unit symbols, hooks, pokes (the tests read it)

The octabam module (octabam-modules/varispeed/) assembles the same source through a
two-line wrapper (`.equ VEM_EMUS, 0` + `.include "remix.inc"`, the remix.inc being the
shared source's text): this builder assembles that wrapper too and refuses unless it gives
the same bytes, then checks the module's `reference`.

Usage:  KYOTI_ALLOW_WIP=1 python3 tools/build_varispeed.py [VERSTR]   (default 140C_VARI1)
"""
import hashlib, json, os, pathlib, shutil, sys
from kyoti_status import gate, seal

gate(__file__, note="VARISPEED: VARI + QUAN, nothing emulated (spec §7). Not on hardware yet.")

import varispeed_buildlib as L

ROOT = L.ROOT
STOCK_SECT = L.STOCK_SECT
SRC = L.SRC
WRAPPER = ROOT / "octabam-modules/varispeed/varispeed.s"
MANIFEST = ROOT / "octabam-modules/varispeed/manifest.py"
OUT = ROOT / "out/mainos_varispeed.bin"
ELEK = ROOT / "out/elek_varispeed.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_VARISPEED.syx"
OUT_BIN = ROOT / "out/OCTATRACK_VARISPEED.bin"
SYMS_JSON = ROOT / "out/varispeed_syms.json"
WORK = ROOT / "out/vari_build"
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_VARI1"
# A TEST variant (deliberately wrong builds for the tests): VARI_VARIANT=<tag> and
# VARI_VARIANT_SRC=<.s> build out/vari_variants/mainos_varispeed_<tag>.bin from that source,
# with every check, and no wrap. Never a flash candidate.
VARIANT = os.environ.get("VARI_VARIANT")
if VARIANT:
    SRC = pathlib.Path(os.environ["VARI_VARIANT_SRC"]).resolve()
    OUT = ROOT / f"out/vari_variants/mainos_varispeed_{VARIANT}.bin"
    SYMS_JSON = ROOT / f"out/vari_variants/varispeed_{VARIANT}_syms.json"
    WORK = ROOT / f"out/vari_variants/build_{VARIANT}"
    OUT.parent.mkdir(parents=True, exist_ok=True)

SWITCH = (("VEM_EMUS", 0),)
# VARISPEED_EMUS's own symbols: none may be in this unit (nothing emulated, no guard)
EMUS_ONLY = ("emus_widget", "emus_fmt", "emus_p2step", "emus_open", "emus_idx", "emus_stops",
             "vg_tick", "vg_fix", "vg_scan", "vg_sig", "vh_fx1", "vh_fx2", "vg_note",
             "str_emu_limit", "em_tally")


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    stock = STOCK_SECT.read_bytes()
    img = bytearray(stock)

    print("=== ColdFire: varispeed_emus.s, VEM_EMUS = 0 (VARISPEED) ===")
    blob, syms, end = L.build_unit(SRC, WORK, SWITCH)
    left = [s for s in EMUS_ONLY if s in syms]
    if left:
        sys.exit(f"the VARISPEED unit carries VARISPEED_EMUS symbols {left} -- the switch failed")
    written = L.splice(img, blob, syms, L.CORE_DETOURS, L.CORE_POKES, L.CORE_CONTEXT, L.CORE_RETURNS)

    # Nothing else: every byte that differs from stock is the unit's, a detour's or a poke's.
    # So the DSP payloads, SPRING REVERB and both FX choosers are stock.
    stray = [i for i in range(len(stock)) if stock[i] != img[i] and i not in written]
    if stray:
        sys.exit(f"{len(stray)} changed byte(s) belong to no detour, poke or the unit, first at "
                 f"0x{L.BASE + stray[0]:08x} -- refusing")
    print("  every changed byte is the unit's, a detour's or a poke's: the DSP payloads, "
          "SPRING REVERB and the FX choosers are stock")

    OUT.write_bytes(bytes(img))
    seal(__file__, OUT)
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    sha = hashlib.sha256(bytes(img)).hexdigest()
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock, sha256 {sha}")
    SYMS_JSON.write_text(json.dumps(dict(
        cave=L.CAVE, end=end, size=len(blob), unit_sha256=hashlib.sha256(blob).hexdigest(),
        syms={k: v for k, v in sorted(syms.items())},
        detours={f"0x{k:08x}": [v[1], v[2], len(v[0]) // 2] for k, v in L.CORE_DETOURS.items()},
        pokes={f"0x{k:08x}": [v[0], syms[v[1]] if isinstance(v[1], str) else v[1], v[2]]
               for k, v in L.CORE_POKES.items()},
        mainos_sha256=sha), indent=1))
    print(f"  octabam reference: unit linked at 0x{L.CAVE:08x}, {len(blob)} B, sha256 "
          f"{hashlib.sha256(blob).hexdigest()}")
    if VARIANT:
        print(f"  test variant {VARIANT}: no wrap")
        return

    # the octabam module's form: the wrapper + remix.inc (the shared source's text)
    inc = WORK / "octabam_inc"
    inc.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC, inc / "remix.inc")
    for cpu in ("5407", "54455"):        # the ROM-cave form and the DRAM form's chip
        wb, wsyms = L.link_unit(WRAPPER, WORK, cpu, L.CAVE, f"octabam_{cpu}", incdir=inc)
        if wb != blob or wsyms != syms:
            sys.exit(f"{WRAPPER.relative_to(ROOT)} (+ remix.inc, -mcpu={cpu}) does not assemble "
                     "to this unit -- refusing")
    print(f"  = {WRAPPER.relative_to(ROOT)} + remix.inc (the octabam form): the same bytes")
    L.check_manifest_reference(MANIFEST, blob)

    L.wrap(OUT, ELEK, OUT_SYX, OUT_BIN, VERSTR)


if __name__ == "__main__":
    main()
