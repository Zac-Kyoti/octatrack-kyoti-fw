#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 knob -> host-word compiler: regenerate tools/ot303/cf/params_const.h from Open303 and hold
# tools/ot303/cf/params.c against Open303 (tools/ot303/params_check.cpp).
#   python3 tools/ot303/params_check.py [--check-only]   (--check-only: fail if params_const.h is stale)
import pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SRC = ROOT / 'out/ot303/refs/Open303/Source/DSPCode'
OUT = ROOT / 'out/ot303/params'
CF = ROOT / 'tools/ot303/cf'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        subprocess.run(['sh', str(ROOT / 'tools/ot303/build_voice_study.sh')], check=True)
    cpps = sorted(str(p) for p in SRC.glob('*.cpp'))
    gen = OUT / 'params_gen'
    subprocess.run(['clang++', '-O2', '-std=c++17', '-w', '-DOT_GEN_ONLY', f'-I{SRC}', f'-I{CF}',
                    str(ROOT / 'tools/ot303/params_check.cpp'), *cpps, '-o', str(gen)], check=True)
    hdr = OUT / 'params_const.h'
    subprocess.run([str(gen), 'gen', str(hdr)], check=True)
    dst = CF / 'params_const.h'
    if '--check-only' in sys.argv:
        if not dst.exists() or dst.read_text() != hdr.read_text():
            sys.exit('stale: tools/ot303/cf/params_const.h')
    else:
        dst.write_text(hdr.read_text())
    obj = OUT / 'params.o'
    subprocess.run(['clang', '-O2', '-std=c99', '-Wall', '-Wextra', '-Werror', f'-I{CF}', '-c', str(CF / 'params.c'), '-o', str(obj)], check=True)
    chk = OUT / 'params_check'
    subprocess.run(['clang++', '-O2', '-std=c++17', '-w', f'-I{SRC}', f'-I{CF}', str(ROOT / 'tools/ot303/params_check.cpp'),
                    str(obj), *cpps, '-o', str(chk)], check=True)
    return subprocess.run([str(chk), 'check']).returncode


if __name__ == '__main__':
    sys.exit(main())
