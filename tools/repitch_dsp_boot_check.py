#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
REPITCH_REPEAT98_KYOTI rev 17: the table copy at boot (zqboot), checked.

For each payload, runs the boot path -- entry P:0x40, the one-time memory clear,
to the head of the frame loop (P:0x4b) -- of a built image, and of the same image
with REPITCH's two boot-hook words put back (`do b,LA`: the boot as it would run
without zqboot; octabam's own image patches the clear's operands, so stock is not
that baseline), on dsp56kEmu (tools/repitch_dsp_boot_probe.cpp), from identical
garbage, and requires:
  * every memory word the probe dumps (X and Y 0..0xffff, Y in the shared
    window) equal after the boot, except Y:0xa00..0xfff (REPITCH's own);
  * Y:TABTAG = TAGVAL and the copied tables equal to the reference model's
    (tools/repitch_engine_model.py via tools/repitch_dsp_src.py), word for word.

    python3 tools/repitch_dsp_boot_check.py [out/mainos_repitch_repeat98_kyoti.bin]
"""
import pathlib
import struct
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dsp_modmap as mm                    # noqa: E402
import repitch_dsp_src as dsrc             # noqa: E402
import repitch_engine_model as m           # noqa: E402

VEND = ROOT / "vendor/dsp56300"
WORK = ROOT / "out/repitch_dsp_boot"
PROBE = WORK / "repitch_dsp_boot_probe"
STOP = 0x4b                                # both payloads: the frame loop's head
BOOT_HOOK = {"A": (0x46, (0x06cf00, 0x000049)), "B": (0x47, (0x06cf00, 0x00004a))}


def build_probe():
    WORK.mkdir(parents=True, exist_ok=True)
    inc = [f"-I{VEND}/source", f"-I{VEND}/source/asmjit/src", "-DDSP56300_DEBUGGER=0", "-DASMJIT_STATIC"]
    libs = [f"{VEND}/build/source/dsp56kEmu/libdsp56kEmu.a",
            f"{VEND}/build/source/dsp56kBase/libdsp56kBase.a",
            f"{VEND}/build/source/asmjit/libasmjit.a"]
    r = subprocess.run(["c++", "-std=c++17", "-O2", *inc, str(ROOT / "tools/repitch_dsp_boot_probe.cpp"),
                        *libs, "-o", str(PROBE)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"probe build failed:\n{r.stderr[-3000:]}")


def mem_file(img, tag, path):
    for t, va, ln in mm.PAYLOADS:
        if t == tag:
            mods, b = mm.modules(img, va, ln)
            with open(path, "wb") as fh:
                for sp, addr, cnt, data in mods:
                    fh.write(struct.pack("<BII", sp, addr, cnt))
                    for i in range(cnt):
                        fh.write(struct.pack("<I", mm.w24(b, data + i * 3)))
                fh.write(struct.pack("<BII", 0xff, 0, 0))
            return


def loaded(img, tag):
    """{(space, address): word} the payload loads."""
    for t, va, ln in mm.PAYLOADS:
        if t == tag:
            mods, b = mm.modules(img, va, ln)
            return {(sp, addr + i): mm.w24(b, data + i * 3) for sp, addr, cnt, data in mods for i in range(cnt)}


def unhooked(img):
    """The image with both payloads' boot-hook words back to stock."""
    out = bytearray(img)
    for tag, va, ln in mm.PAYLOADS:
        site, words = BOOT_HOOK[tag]
        mods, _ = mm.modules(img, va, ln)
        rec = [md for md in mods if md[0] == 0 and md[1] <= site < md[1] + md[2]]
        if len(rec) != 1:
            sys.exit(f"payload {tag}: no P record holds P:0x{site:x}")
        sp, addr, cnt, data = rec[0]
        off = (va - mm.BASE) + data + 3 * (site - addr)
        for i, w in enumerate(words):
            out[off + 3 * i:off + 3 * i + 3] = w.to_bytes(3, "little")
    return bytes(out)


def boot(img, tag, name):
    mf, out = WORK / f"{name}_{tag}.mem", WORK / f"{name}_{tag}.bin"
    mem_file(img, tag, mf)
    r = subprocess.run([str(PROBE), str(mf), f"{STOP:x}", str(out)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"boot probe ({name} {tag}): {r.stdout} {r.stderr}")
    d = np.frombuffer(out.read_bytes(), dtype="<u4").astype(np.int64)
    n = int([l for l in r.stdout.splitlines() if l.startswith("BOOT_INSTR ")][0].split()[1])
    return n, {"P": d[:0x2000], "X": d[0x2000:0x12000], "Y": d[0x12000:0x22000],
                                      "YS": d[0x22000:0x32000]}


def expected_y():
    """{Y address: word} of what zqinit must leave."""
    c = dsrc.constants("A")
    want = {c["TABTAG"]: c["TAGVAL"]}
    for mode, base in ((m.MODE_RPSP, c["SPTAB"]), (m.MODE_RPS9, c["R9TAB"])):
        q = m.fir_q23(mode) & 0xFFFFFF
        for i, w in enumerate(q.reshape(-1)):
            want[base + i] = int(w)
    T, D = m.render_q23()
    L, R = m.RENDER["L"], m.RENDER["R"]
    for j in range(R):
        for mm_ in range(L):
            k = (L - 1 - mm_) * R + j
            want[c["BTAB"] + 2 * (L * j + mm_)] = int(T[k]) & 0xFFFFFF
            want[c["BTAB"] + 2 * (L * j + mm_) + 1] = (int(T[k + 1]) - int(T[k])) & 0xFFFFFF
    return want


def main():
    built = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out/mainos_repitch_repeat98_kyoti.bin"
    img = built.read_bytes()
    base = unhooked(img)
    if base == img:
        sys.exit(f"{built}: no boot hook at A P:0x46 / B P:0x47 (the words are already stock)")
    build_probe()
    want = expected_y()
    ok = True
    for tag in ("A", "B"):
        n0, s = boot(base, tag, "unhooked")
        n1, p = boot(img, tag, "built")
        bad = []
        for sp, space, off in (("X", 1, 0), ("Y", 2, 0), ("YS", 2, 0x30000)):
            for a in np.nonzero(s[sp] != p[sp])[0]:
                a = int(a) + off
                if space == 2 and 0xa00 <= a < 0x1000:
                    continue
                bad.append(f"{sp[0]}:{a:05x}")
        tab = [a for a, w in want.items() if p["Y"][a] != w]
        print(f"payload {tag}: boot {n0:,} instructions without the hook, {n1:,} with zqboot (+{n1 - n0:,}); "
              f"memory outside Y:0xa00-0xfff {'identical' if not bad else 'DIFFERS ' + ' '.join(bad[:8])}; "
              f"tables + tag {'as the model' if not tab else f'{len(tab)} words DIFFER, first Y:{tab[0]:05x}'}")
        ok &= not bad and not tab
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
