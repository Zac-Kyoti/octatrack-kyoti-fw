#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 Phase 2b: the DSP engine against the integer twin, bit for bit, on dsp56kEmu.
#   python3 tools/ot303/engine_check.py [SCENE ...]
# Assembles tools/ot303/ot303_engine.asm (tools/dsp_xasm.py, every word disassembled and checked),
# builds tools/ot303/engine_probe.cpp, has voice_study's twin log each scene's host segments, and
# replays them through the twin and the emulated DSP. Reports instructions per sample.
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import dsp_xasm  # noqa: E402

OUT = os.path.join(ROOT, 'out', 'ot303', 'engine')
VEND = os.path.join(ROOT, 'vendor', 'dsp56300')
ASM = os.path.join(ROOT, 'tools', 'ot303', 'ot303_engine.asm')
ORG, STUBORG = 0x200, 0x100
LEAN = 'hb2:43,hbfp:16,hb1:15,hb1fp:18,meg48:1,frame:16'
SCENES = ['sweep', 'hot', 'squelch', 'accents', 'square']


def w24(words):
    return b''.join(w.to_bytes(3, 'little') for w in words)


def equs(src):
    consts = {}
    for raw in src.splitlines():
        m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+(.+)$', raw.split(';', 1)[0].rstrip())
        if m:
            consts[m.group(1)] = int(eval(m.group(2).replace('$', '0x'), {}, dict(consts)))
    return consts


def main():
    os.makedirs(OUT, exist_ok=True)
    src = open(ASM).read()
    words, syms = dsp_xasm.assemble(src, ORG)
    assert syms['ot303'] < 0x1000
    stub = [0x0d0000 | syms['ot303'], 0x000000]           # jsr <ot303 (short absolute) ; nop = the stop
    d = dsp_xasm.disassemble(stub, STUBORG)
    assert d[STUBORG][0] == f'jsr     func_{syms["ot303"]:06x}', d
    open(os.path.join(OUT, 'engine.bin'), 'wb').write(w24(words))
    open(os.path.join(OUT, 'stub.bin'), 'wb').write(w24(stub))
    allsyms = dict(equs(src)); allsyms.update(syms)
    with open(os.path.join(OUT, 'syms.txt'), 'w') as f:
        for k, v in sorted(allsyms.items()):
            f.write(f'{k} {v:x}\n')
    print(f'engine: {len(words)} words at P:${ORG:x}')
    probe = os.path.join(OUT, 'engine_probe')
    inc = [f'-I{VEND}/source', f'-I{VEND}/source/asmjit/src', f'-I{ROOT}/tools/ot303', '-DDSP56300_DEBUGGER=0', '-DASMJIT_STATIC']
    libs = [f'{VEND}/build/source/dsp56kEmu/libdsp56kEmu.a', f'{VEND}/build/source/dsp56kBase/libdsp56kBase.a',
            f'{VEND}/build/source/asmjit/libasmjit.a']
    r = subprocess.run(['c++', '-std=c++17', '-O2', '-w', *inc, os.path.join(ROOT, 'tools/ot303/engine_probe.cpp'), *libs, '-o', probe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('probe build failed:\n' + r.stderr[-3000:])
    vs = os.path.join(ROOT, 'out', 'ot303', 'voice_study')
    fails = 0
    for sc in (sys.argv[1:] or SCENES):
        log = os.path.join(OUT, f'{sc}.log')
        subprocess.run([vs, 'twin', sc, f'{LEAN},log:{log}', os.path.join(OUT, f'{sc}.f32')], check=True, capture_output=True)
        p = subprocess.run([probe, os.path.join(OUT, 'engine.bin'), f'{ORG:x}', os.path.join(OUT, 'stub.bin'), f'{STUBORG:x}',
                            os.path.join(OUT, 'syms.txt'), log], capture_output=True, text=True, errors='replace')
        lines = [l for l in p.stdout.splitlines() if not re.match(r'^\w+@\d+:', l)]
        print(f'{sc:8} ' + '\n         '.join(lines[-20:]))
        fails += p.returncode != 0
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
