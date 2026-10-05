#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
OT-303 Phase 0b -- DIAGNOSTIC image: a cycle-burn knob on DJ EQ, to measure on hardware how much
DSP time each core has left (reference/handoffs/OT303_SCOPE.md §8 Phase 0, §10).

Stock 1.40C plus exactly this:
  * DJ EQ page 2 gets one knob, BURN (slot 6, 0..127, default 0). Each step burns 24 cycles
    per sample on that track's core (octabam's RIG BURN body, tools/ot303/burn_djeq.asm).
    At 0 it costs ~9 instructions per call (per 16-sample frame), nothing per sample.
  * SPRING REV is removed (its DSP words hold the 16-word burn routine): absent from both FX
    choosers, an old project that uses it loads the NONE page, and its dispatch entry is the
    shared empty-FX passthrough. The recipe is SIDECHAIN_COMPRESSOR's donor path, unchanged.
    DARK REV's helper routine inside SPRING's module (A P:0x1586, B P:0x1346) is untouched.
  * Nothing on the ColdFire but data: one descriptor name, one enable nibble, the chooser
    tables. No ColdFire code, no cave.

How it is used (FLASHING-style steps print at the end): every track DJ EQ on FX1 and FX2
(the heaviest legal stock configuration), audio playing; raise BURN on one track of 1-4 until
the audio breaks; the last clean value x 24 = spare cycles per sample on core 1 (tracks 1-4).
The same on a track of 5-8 for core 0. Then once more with only that one DJ EQ (all other FX
NONE): the difference prices 7 DJ EQ instances in real cycles (calibration).

Usage:   python3 tools/build_ot303_burnprobe.py      (WIP: KYOTI_ALLOW_WIP=1)
Outputs: out/mainos_ot303_burnprobe.bin, out/OCTATRACK_OS1.40C_OT303_BURNPROBE.syx,
         out/OCTATRACK_OT303_BURNPROBE.bin
"""
import importlib.util, os, pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dsp_xasm

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
SRC = ROOT / "tools/ot303/burn_djeq.asm"
OUT = ROOT / "out/mainos_ot303_burnprobe.bin"
ELEK = ROOT / "out/elek_ot303_burnprobe.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_OT303_BURNPROBE.syx"
OUT_BIN = ROOT / "out/OCTATRACK_OT303_BURNPROBE.bin"
VERSTR = "140C_303BP"      # the field takes 10 characters

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
BURN_SLOT = 6


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
    tmp = ROOT / "out/ot303_burn_check.bin"
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
    print("=== DSP: burn routine in SPRING REV's words; DJ EQ proc -> burn -> stock DJ EQ ===")
    for tag, d in DSP.items():
        org = d["spring_init"]
        try:
            words, syms = dsp_xasm.assemble(SRC.read_text(), org)
        except dsp_xasm.AsmError as e:
            sys.exit(f"payload {tag}: {e}")
        bra = syms["zbout"]
        assert words[bra - org] == 0x0d10c0 and words[bra - org + 1] == 0, "bra placeholder moved"
        words[bra - org + 1] = (d["djeq_proc"] - bra) & 0xffffff
        dis = disasm(words, org)
        line = next((l for l in dis.splitlines() if l.startswith(f"{bra:06x}:")), "")
        if f"bra     func_{d['djeq_proc']:06x}" not in line:
            sys.exit(f"payload {tag}: exit branch disassembles as {line!r}")
        if org + len(words) > d["dark_helper"]:
            sys.exit(f"payload {tag}: routine reaches DARK REV's helper at P:{d['dark_helper']:05x}")

        so, mod_a, mod_c = p_off(mm, img, d["va"], d["ln"], org)
        assert [rd3(img, so + 3 * i) for i in range(3)] == SPRING_SIG, f"payload {tag}: SPRING init"
        assert mod_a == org, f"payload {tag}: SPRING's module does not start at its init"
        for i, wv in enumerate(words):
            img[so + 3 * i: so + 3 * i + 3] = w3(wv)
        print(f"  payload {tag}: {len(words)} words @ P:0x{org:05x} (SPRING's module, {mod_c} w); "
              f"exit bra @ P:0x{bra:05x} -> DJ EQ proc P:0x{d['djeq_proc']:05x}")

        dj, _, _ = p_off(mm, img, d["va"], d["ln"], d["djeq_proc"])
        assert [rd3(img, dj + 3 * i) for i in range(3)] == DJEQ_SIG, f"payload {tag}: DJ EQ proc"

        xt = x_off(mm, img, d["va"], d["ln"], 0x215)
        si, sp = xt + SPRING_ID * 3, xt + (0x20 + SPRING_ID) * 3
        di = xt + (0x20 + DJEQ_ID) * 3
        assert rd3(img, si) == d["spring_init"] and rd3(img, sp) == d["spring_proc"], \
            f"payload {tag}: SPRING dispatch {rd3(img, si):06x} {rd3(img, sp):06x}"
        assert rd3(img, di) == d["djeq_proc"], f"payload {tag}: DJ EQ proc entry {rd3(img, di):06x}"
        img[si:si + 3] = w3(d["stub_init"])
        img[sp:sp + 3] = w3(d["stub_proc"])
        img[di:di + 3] = w3(org)
        print(f"    X:$215[$15] -> passthrough stub; X:$235[$0d] -> P:0x{org:05x}")

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

    # ---------------- ColdFire: the BURN knob on DJ EQ page 2 ----------------
    print("\n=== ColdFire: DJ EQ page 2 slot 6 = BURN ===")
    E = DJEQ_P - 0x38
    na, ca, da = E + 0x4e + 6 * BURN_SLOT, E + 0xd2 + 4 * BURN_SLOT, E + 0x96 + BURN_SLOT
    aa, ba = E + 0x102 + 4 * BURN_SLOT, E + 0x132 + 4 * BURN_SLOT
    assert bytes(img[o(na):o(na) + 6]) == b"\0" * 6, "slot 6 name not empty"
    assert u32(ca) == 128 and img[o(da)] == 0 and u32(aa) == 0 and u32(ba) == 0, \
        "slot 6 is not a blank 0..127 knob"
    img[o(na):o(na) + 6] = b"BURN\0\0"
    en = E + 0x38 + 0x18e                      # params 0-7, one nibble each, low nibble first
    assert u32(en) == 0x00111101, f"DJ EQ enable word 0x{u32(en):08x}"
    wr32(en, 0x00111101 | 1 << (4 * BURN_SLOT))
    print(f"  name 'BURN', 0..127 (stock count/default/formatter), enable 0x{u32(en):08x}")

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
