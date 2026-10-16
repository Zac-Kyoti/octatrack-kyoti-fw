#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
OT-303 hardware probe, DIAGNOSTIC 14 (DIAG14): the OT-303 DSP engine on the unit, hosted at the
per-track SOURCE seam (octabam ANALOG BD's host; reference/handoffs/OT303_SCOPE.md §11-12). DIAG13
on the unit: the engine in DJ EQ's process routine ran clean on any track and both cores, two at
once, through a soak and the heaviest legal config. DIAG14 moves the voice upstream of AMP, FX1 and
FX2, where the product machine will put it; DJ EQ stays only as the remote control that picks the
track.

Stock 1.40C plus exactly this:
  * Source seam: `move a,x:>$20e` (A P:$39c, B P:$1a2) -> jsr the glue. On the core's claimed track
    the engine renders the frame into X:0 and the stock code continues after the source (A P:$426,
    B P:$221); every other track runs the stock source.
  * DJ EQ page 2: slot 6 BURN (24 cycles/sample a step, before DJ EQ, always), slot 7 303: 0 off,
    1-31 tone, 32-127 riff; 303 up claims the track for its core's voice (first claim wins, one
    voice per core). DJ EQ itself runs as stock on whatever the track carries.
  * SPRING REV is removed (its words hold the engine, the wrapper and the packed table data);
    DARK REV's 35-word helper moves from inside SPRING's module to its last 35 words, its three
    stock callers retargeted (octabam ANALOG BD's layout). Nothing on the ColdFire but data.

Usage:   python3 tools/build_ot303_hwprobe.py      (WIP: KYOTI_ALLOW_WIP=1)
Outputs: out/mainos_ot303_hwprobe_diag14.bin, out/OCTATRACK_OS1.40C_OT303_DIAG14.syx,
         out/OCTATRACK_OT303_DIAG14.bin
"""
import os, pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "ot303"))
import dsp_patch

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_ot303_hwprobe_diag14.bin"
ELEK = ROOT / "out/elek_ot303_hwprobe_diag14.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_OT303_DIAG14.syx"
OUT_BIN = ROOT / "out/OCTATRACK_OT303_DIAG14.bin"
VERSTR = "140C_303DE"      # the field takes 10 characters

DJEQ_P = dsp_patch.DJEQ_P             # DJ EQ's descriptor pointer as the tables store it (E + 0x38)
BURN_SLOT, T303_SLOT = 6, 7


def main():
    for t in (STOCK_SECT,):
        if not pathlib.Path(t).exists():
            sys.exit(f"missing {t}")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)
    mm = dsp_patch.modmap()

    def o(a):
        return a - BASE

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    def wr32(a, v):
        img[o(a):o(a) + 4] = v.to_bytes(4, "big")

    dsp_patch.patch_dsp(img, mm, host=False)
    print()
    dsp_patch.remove_spring(img)

    # ---------------- ColdFire: BURN and 303 on DJ EQ page 2 ----------------
    print("\n=== ColdFire: DJ EQ page 2 slot 6 = BURN, slot 7 = 303 ===")
    E = DJEQ_P - 0x38
    en = E + 0x38 + 0x18e                      # params 0-7, one nibble each, low nibble first
    assert u32(en) == 0x00111101, f"DJ EQ enable word 0x{u32(en):08x}"
    for slot, name in ((BURN_SLOT, b"BURN\0\0"), (T303_SLOT, b"303\0\0\0")):
        na, ca, da = E + 0x4e + 6 * slot, E + 0xd2 + 4 * slot, E + 0x96 + slot
        aa, ba = E + 0x102 + 4 * slot, E + 0x132 + 4 * slot
        assert bytes(img[o(na):o(na) + 6]) == b"\0" * 6, f"slot {slot} name not empty"
        assert u32(ca) == 128 and img[o(da)] == 0 and u32(aa) == 0 and u32(ba) == 0, \
            f"slot {slot} is not a blank 0..127 knob"
        img[o(na):o(na) + 6] = name
        wr32(en, u32(en) | 1 << (4 * slot))
    print(f"  'BURN' slot 6, '303' slot 7, 0..127 (stock count/default/formatter), enable 0x{u32(en):08x}")

    OUT.write_bytes(bytes(img))
    seal(__file__, OUT)
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("  (EFT / stock syx missing -- skipping wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT), "-V", VERSTR,
                        "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if any(k in l for k in ("version", "emitted", "wrote", "checksum", "round-trip"))))
    if r.returncode or "too long" in r.stdout:
        sys.exit(f"wrap failed:\n{r.stdout}\n{r.stderr}")
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)
    print(f"\n  {OUT_SYX.name}  +  {OUT_BIN.name}")


if __name__ == "__main__":
    main()
