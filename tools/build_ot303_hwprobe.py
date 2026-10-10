#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
OT-303 hardware probe, DIAGNOSTIC 10 (DIAG10): the OT-303 DSP engine on the unit, hosted in DJ EQ
(reference/handoffs/OT303_SCOPE.md §11). DIAG9 on the unit: its host-DMA-yielding riff crashed at 48;
with T6 muted the tone and the tone + BURN leave the master silent, the riff leaks. DIAG10 asks
which kind of work breaks core 0's mix: 303 >= 64 runs a ~400-cycle/sample workload before the
tone (mode (303 - 64) >> 3: div, mac, Y reads, Y writes, X:Y reads, mac + X:Y reads, the engine,
X reads; safest first). The meter and the yielding riff are gone; 32-63 is the plain riff.

Stock 1.40C plus exactly this:
  * DJ EQ page 2: slot 6 BURN (24 cycles/sample a step, after the render; before DJ EQ when 303
    is 0), slot 7 303. 303 bands: 1-31 TONE, 32-63 RIFF, 64-127 STRESS + TONE.
    One engine per core.
  * SPRING REV is removed (its words hold the engine, the wrapper and the packed table data);
    DARK REV's helper inside SPRING's module is untouched. Nothing on the ColdFire but data.

Usage:   python3 tools/build_ot303_hwprobe.py      (WIP: KYOTI_ALLOW_WIP=1)
Outputs: out/mainos_ot303_hwprobe_diag10.bin, out/OCTATRACK_OS1.40C_OT303_DIAG10.syx,
         out/OCTATRACK_OT303_DIAG10.bin
"""
import importlib.util, os, pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "ot303"))
import hwprobe_image

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
OUT = ROOT / "out/mainos_ot303_hwprobe_diag10.bin"
ELEK = ROOT / "out/elek_ot303_hwprobe_diag10.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_OT303_DIAG10.syx"
OUT_BIN = ROOT / "out/OCTATRACK_OT303_DIAG10.bin"
VERSTR = "140C_303DA"      # the field takes 10 characters

DJEQ_ID = 0x0d
SPRING_ID = 0x15
# per payload, every value read off our own image (tools/ot303 session notes, scope §10):
#   spring_init/proc  X:$215[$15] / X:$235[$15] stock -> also the burn routine's origin
#   djeq_proc         X:$235[$0d] stock (DJ EQ's process routine)
#   stub_init/proc    the shared empty-FX passthrough (18 unused ids already point there)
#   dark_helper       first word of DARK REV's helper inside SPRING's module: must stay stock
DSP = {
    "A": dict(va=0x400e2324, ln=0x136cb, spring_init=0x01252, spring_proc=0x012be,
              djeq_proc=0x01d7d, stub_init=0x007c8, stub_proc=0x007c9, dark_helper=0x01586),
    "B": dict(va=0x400f59ef, ln=0x12d05, spring_init=0x01012, spring_proc=0x0107e,
              djeq_proc=0x01b3d, stub_init=0x00588, stub_proc=0x00589, dark_helper=0x01346),
}
SPRING_SIG = [0x22ee00, 0x0140c0, 0x000040]      # SPRING's stock init, both payloads
DJEQ_SIG = [0x221e00, 0x61f400, 0x000140]        # DJ EQ's stock proc: move r0,n6 / move #>$140,r1

# ColdFire tables (memory-map.md; SIDECHAIN_COMPRESSOR uses the same)
FX_BUSES = (
    dict(tag="FX1", lst=0x400d6060, id2pos=0x400d60d0, id2e=0x400d5f58),
    dict(tag="FX2", lst=0x400d6090, id2pos=0x400d6150, id2e=0x400d5fdc),
)
SPRING_P = 0x400d5726 + 0x38
NONE_P = 0x400d45e0 + 0x38
DJEQ_P = 0x400d4dba + 0x38          # DJ EQ's descriptor pointer as the tables store it (E + 0x38)
BURN_SLOT, T303_SLOT = 6, 7


def w3(v):
    return v.to_bytes(3, "little")


def rd3(img, off):
    return int.from_bytes(img[off:off + 3], "little")


def modmap():
    spec = importlib.util.spec_from_file_location("mm", ROOT / "refs/octabam/tools/build/dsp_modmap.py")
    mm = importlib.util.module_from_spec(spec); spec.loader.exec_module(mm)
    return mm


def p_off(mm, img, va, ln, p_addr):
    mods, _ = mm.modules(bytes(img), va, ln)
    for sp, addr, cnt, data in mods:
        if sp == 0 and addr <= p_addr < addr + cnt:
            return (va - BASE) + data + (p_addr - addr) * 3, addr, cnt
    sys.exit(f"P:0x{p_addr:05x} not in any P module of payload @0x{va:08x}")


def x_off(mm, img, va, ln, x_addr):
    mods, _ = mm.modules(bytes(img), va, ln)
    for sp, addr, cnt, data in mods:
        if sp == 1 and addr == x_addr:
            return (va - BASE) + data
    sys.exit(f"X:0x{x_addr:05x} module not found in payload @0x{va:08x}")


def disasm(words, org):
    tmp = ROOT / "out/ot303_hwprobe_check.bin"
    tmp.write_bytes(b"".join(w3(w) for w in words))
    return subprocess.run([str(DIS), "-in", str(tmp), "-pc", f"{org:x}", "-le"],
                          capture_output=True, text=True).stdout


def main():
    for t in (STOCK_SECT, DIS):
        if not pathlib.Path(t).exists():
            sys.exit(f"missing {t}")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)
    mm = modmap()

    def o(a):
        return a - BASE

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    def wr32(a, v):
        img[o(a):o(a) + 4] = v.to_bytes(4, "big")

    # ---------------- DSP, both payloads ----------------
    print("=== DSP: engine + wrapper in SPRING REV's words and X records; DJ EQ proc -> wrapper ===")
    for tag, d in DSP.items():
        b = hwprobe_image.build(tag)
        org, words = b["org"], b["words"]
        assert org == d["spring_init"]
        so, mod_a, mod_c = p_off(mm, img, d["va"], d["ln"], org)
        assert [rd3(img, so + 3 * i) for i in range(3)] == SPRING_SIG, f"payload {tag}: SPRING init"
        assert mod_a == org and mod_c == 1063, f"payload {tag}: SPRING's module is not 1063 words at its init"
        dark = d["dark_helper"]
        dark_stock = [rd3(img, so + 3 * (dark - org + i)) for i in range(hwprobe_image.DARK_N)]
        assert org + len(words) <= dark, f"payload {tag}: code reaches DARK REV's helper"
        for i, wv in enumerate(words):
            img[so + 3 * i: so + 3 * i + 3] = w3(wv)
        eorg, ew = b["p2"]
        assert eorg == dark + hwprobe_image.DARK_N and eorg + len(ew) <= org + mod_c
        for i, wv in enumerate(ew):
            img[so + 3 * (eorg - org + i): so + 3 * (eorg - org + i) + 3] = w3(wv)
        assert [rd3(img, so + 3 * (dark - org + i)) for i in range(hwprobe_image.DARK_N)] == dark_stock, \
            f"payload {tag}: DARK REV's helper changed"
        print(f"  payload {tag}: {len(words)} words @ P:0x{org:05x}, events {len(ew)} @ P:0x{eorg:05x} "
              f"(SPRING's module {mod_c} w; DARK REV's helper P:0x{dark:05x} kept); entry P:0x{b['entry']:05x}")
        # X: SPRING's five records, address and length asserted, every word rewritten
        mods, _ = mm.modules(bytes(img), d["va"], d["ln"])
        runs = hwprobe_image.PAYLOAD[tag]["xrun1"] + hwprobe_image.PAYLOAD[tag]["xrun2"]
        for addr, cnt in runs:
            rec = [m for m in mods if m[0] == 1 and m[1] == addr]
            assert len(rec) == 1 and rec[0][2] == cnt, f"payload {tag}: no {cnt}-word X record at X:0x{addr:05x}"
            xo = (d["va"] - BASE) + rec[0][3]
            for k in range(cnt):
                img[xo + 3 * k: xo + 3 * k + 3] = w3(b["x"][addr + k])
        print(f"    X: {sum(c for _, c in runs)} words over SPRING's records "
              + ", ".join(f"0x{a:05x}x{c}" for a, c in runs))

        xt = x_off(mm, img, d["va"], d["ln"], 0x215)
        si, sp = xt + SPRING_ID * 3, xt + (0x20 + SPRING_ID) * 3
        di = xt + (0x20 + DJEQ_ID) * 3
        assert rd3(img, si) == d["spring_init"] and rd3(img, sp) == d["spring_proc"], \
            f"payload {tag}: SPRING dispatch {rd3(img, si):06x} {rd3(img, sp):06x}"
        assert rd3(img, di) == d["djeq_proc"] == b["djeq_proc"], f"payload {tag}: DJ EQ proc entry {rd3(img, di):06x}"
        dj, _, _ = p_off(mm, img, d["va"], d["ln"], d["djeq_proc"])
        assert [rd3(img, dj + 3 * i) for i in range(3)] == DJEQ_SIG, f"payload {tag}: DJ EQ proc"
        img[si:si + 3] = w3(d["stub_init"])
        img[sp:sp + 3] = w3(d["stub_proc"])
        img[di:di + 3] = w3(b["entry"])
        print(f"    X:$215[$15] -> passthrough stub; X:$235[$0d] -> P:0x{b['entry']:05x}")

    # ---------------- ColdFire: SPRING out of both choosers, NONE page for old projects ----
    print("\n=== ColdFire: SPRING REV removed from the FX choosers ===")
    for bus in FX_BUSES:
        entries = []
        while (v := u32(bus["lst"] + 4 * len(entries))):
            entries.append(v)
            assert len(entries) < 0x20
        if SPRING_P in entries:
            pos = entries.index(SPRING_P)
            del entries[pos]
            for i, v in enumerate(entries):
                wr32(bus["lst"] + 4 * i, v)
            wr32(bus["lst"] + 4 * len(entries), 0)
            wr32(bus["id2pos"] + SPRING_ID * 4, 0)
            for idv in range(0x20):
                p = u32(bus["id2pos"] + idv * 4)
                if idv != SPRING_ID and p > pos:
                    wr32(bus["id2pos"] + idv * 4, p - 1)
            print(f"  {bus['tag']}: dropped row {pos}; {len(entries)} entries")
        else:
            print(f"  {bus['tag']}: SPRING not offered on this bus")
        assert u32(bus["id2e"] + SPRING_ID * 4) in (SPRING_P, NONE_P)
        wr32(bus["id2e"] + SPRING_ID * 4, NONE_P)
        assert u32(bus["id2e"] + DJEQ_ID * 4) == DJEQ_P, f"{bus['tag']}: DJ EQ descriptor moved"

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
