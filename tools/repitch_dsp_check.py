#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti DSP oracle driver (rev 10).

SUPERSEDED for the engine itself (Session 110, rev 11): its contracts are rev
10's (12-bit ring truncation + zeroed fractions) and the rev-11 cave does not
meet them by design. The rev-11 check is tools/repitch_dsp_engine_check.py.
This module stays for its helpers (PAYLOADS, IMG, voice_module,
module_words), which the rev-11 tools import.

Extracts the stock voice engine from BOTH payloads of our own image, assembles
tools/patch_repitch_dsp.asm, encodes each payload's prologue hook with
build_sidechain_compressor.bsr_long (the convention SIDECHAIN_COMPRESSOR's hardware-confirmed
hooks use -- NOT dsp_asm's `bsr >$abs`, which takes the operand as a literal
displacement), builds tools/repitch_dsp_probe.cpp against our vendored
dsp56kEmu, and runs it once per payload.

    python3 tools/repitch_dsp_check.py [CAVE_ORG_HEX]

The cave org defaults to a test address; the real one is the donor slot the
builder places it in, and the probe is re-run there by the builder.
"""
import importlib.util, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_sidechain_compressor as sc3   # noqa: E402  (bsr_long)

BASE = 0x40000400
IMG = ROOT / "out/raw/section_3_MAIN_OS.bin"
ASM = ROOT / "vendor/dsp56300/build/source/dsp_host/dsp_asm"
DIS = ROOT / "vendor/dsp56300/build/source/disassemble/dsp56kDisassemble"
SRC = ROOT / "tools/patch_repitch_dsp.asm"
PROBE_SRC = ROOT / "tools/repitch_dsp_probe.cpp"
PROBE = ROOT / "out/repitch_dsp_probe"
VEND = ROOT / "vendor/dsp56300"

# (payload, image va, stream length, voice module P base, hook, stop NOP)
PAYLOADS = [
    ("A", 0x400e2324, 0x136cb, 0x3a1, 0x40b, 0x41b),
    ("B", 0x400f59ef, 0x12d05, 0x1a4, 0x20e, 0x21e),
]
VOICE_WORDS = 125


def modmap():
    spec = importlib.util.spec_from_file_location("mm", ROOT / "refs/octabam/tools/build/dsp_modmap.py")
    mm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mm)
    return mm


def voice_module(img, va, ln, base):
    mods, _ = modmap().modules(img, va, ln)
    for sp, addr, cnt, data in mods:
        if sp == 0 and addr == base:
            if cnt != VOICE_WORDS:
                sys.exit(f"voice module @P:{base:05x} is {cnt} words, expected {VOICE_WORDS}")
            off = (va - BASE) + data
            return img[off:off + cnt * 3], off
    sys.exit(f"no P module at P:{base:05x} in payload @{va:#x}")


def assemble(org):
    out = ROOT / "out/patch_repitch_dsp.bin"
    r = subprocess.run([str(ASM), "-in", str(SRC), "-org", f"{org:x}", "-out", str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"dsp_asm failed:\n{r.stdout}\n{r.stderr}")
    raw = out.read_bytes()
    d = subprocess.run([str(DIS), "-in", str(out), "-pc", f"{org:x}", "-le"],
                       capture_output=True, text=True).stdout
    if " dc " in d or "InvalidInstruction" in d or "mpysu" in d or "macsu" in d:
        sys.exit(f"cave did not round-trip clean:\n{d}")
    return raw, d


def build_probe():
    # the same include set and defines vendor/dsp56300's own dsp_host builds with
    inc = [f"-I{VEND}/source", f"-I{VEND}/source/asmjit/src",
           "-DDSP56300_DEBUGGER=0", "-DASMJIT_STATIC"]
    libs = [f"{VEND}/build/source/dsp56kEmu/libdsp56kEmu.a",
            f"{VEND}/build/source/dsp56kBase/libdsp56kBase.a",
            f"{VEND}/build/source/asmjit/libasmjit.a"]
    r = subprocess.run(["c++", "-std=c++17", "-O1", *inc, str(PROBE_SRC), *libs, "-o", str(PROBE)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"probe build failed:\n{r.stderr[-3000:]}")


def module_words(img, va, ln, p_addr, count):
    """`count` P words starting at p_addr, read out of the payload stream."""
    off = sc3.dsp_module_fileoff(img, va, ln, p_addr)
    return img[off:off + count * 3]


def main():
    """No argument: test the source cave at a scratch org. With a BUILT MAIN OS
    image: test exactly its bytes -- each payload's hook is read from the
    image, decoded, and the probe runs the cave words found at its target."""
    stock = IMG.read_bytes()
    built = pathlib.Path(sys.argv[1]).read_bytes() if len(sys.argv) > 1 else None
    build_probe()
    bad = 0
    for tag, va, ln, base, hook, stop in PAYLOADS:
        mod, off = voice_module(stock, va, ln, base)    # the UNPATCHED reference
        mpath = ROOT / f"out/rp_voice{tag}.bin"
        mpath.write_bytes(mod)
        if built is None:
            org = 0x1000
            cave, _ = assemble(org)
            b0, b1 = sc3.bsr_long(hook, org)
            print(f"\n(source cave at scratch org P:{org:05x})")
        else:
            hw = module_words(built, va, ln, hook, 2)
            b0 = int.from_bytes(hw[0:3], "little")
            b1 = int.from_bytes(hw[3:6], "little")
            if b0 != 0x0D1080:
                sys.exit(f"payload {tag}: the built image's hook P:{hook:05x} is not a bsr ({b0:06x})")
            org = (hook + b1) & 0xFFFFFF
            n = len(assemble(org)[0]) // 3
            cave = module_words(built, va, ln, org, n)
            if cave != assemble(org)[0]:
                sys.exit(f"payload {tag}: image cave at P:{org:05x} != source assembled there")
            print(f"\n(built image: hook P:{hook:05x} -> P:{org:05x}, {n} words, == source)")
        (ROOT / "out/patch_repitch_dsp.bin").write_bytes(cave)
        print(f"\n=== payload {tag}: voice @P:{base:05x} (file 0x{off:x}), hook {hook:05x} -> "
              f"bsr {b0:06x} {b1:06x} ===")
        r = subprocess.run([str(PROBE), str(mpath), f"{base:x}", f"{hook:x}", f"{stop:x}",
                            str(ROOT / "out/patch_repitch_dsp.bin"), f"{org:x}", f"{b0:x}", f"{b1:x}"],
                           capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode:
            print(r.stderr[-2000:])
        bad += r.returncode != 0
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
