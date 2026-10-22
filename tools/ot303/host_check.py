#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 machine host (tools/ot303/host.asm) on the bench: both payloads' placements
# (tools/ot303/hwprobe_image.py, host=True) run on dsp56kEmu as the firmware enters the source seam
# (tools/ot303/host_probe.cpp: four tracks, two OT-303 tracks on one core playing lines with ties,
# slides and accents under moving knobs), against the integer twin. The records come from the
# ColdFire's own record.c + params.c, compiled natively. Needs the private toolchain
# (out/ot303/dsp56300_new).
#   python3 tools/ot303/host_check.py [FRAMES]
import os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'tools' / 'ot303'))
import hwprobe_image as H  # noqa: E402

OUT = ROOT / 'out' / 'ot303' / 'host'
VEND = H.NEW


def w24(words):
    return b''.join((w & 0xffffff).to_bytes(3, 'little') for w in words)


def main():
    frames = sys.argv[1] if len(sys.argv) > 1 else '20352'
    OUT.mkdir(parents=True, exist_ok=True)
    probe = OUT / 'host_probe'
    inc = [f'-I{VEND}/source', f'-I{VEND}/source/asmjit/src', f'-I{ROOT}/tools/ot303', '-DDSP56300_DEBUGGER=0', '-DASMJIT_STATIC']
    libs = [f'{VEND}/build/source/dsp56kEmu/libdsp56kEmu.a', f'{VEND}/build/source/dsp56kBase/libdsp56kBase.a',
            f'{VEND}/build/source/asmjit/libasmjit.a']
    cf = ROOT / 'tools/ot303/cf'
    body = []                                   # (the voice's DSP constants: hwprobe_image reads them at import)
    H.write_ytab(OUT / 'ytab.c')
    objs = []
    for src in (cf / 'params.c', cf / 'record.c', OUT / 'ytab.c'):
        obj = OUT / (src.stem + '.o')
        r = subprocess.run(['cc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', *body, f'-I{cf}', '-c', str(src), '-o', str(obj)],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit(f'{src.name} build failed:\n' + r.stderr[-3000:])
        objs.append(str(obj))
    r = subprocess.run(['c++', '-std=c++17', '-O2', '-w', *body, *inc, f'-I{cf}', str(ROOT / 'tools/ot303/host_probe.cpp'), *objs, *libs,
                        '-o', str(probe)], capture_output=True, text=True)
    if r.returncode:
        sys.exit('probe build failed:\n' + r.stderr[-3000:])
    fails = 0
    for tag in ('A', 'B'):
        b = H.build(tag, host=True)
        d = OUT / tag
        d.mkdir(exist_ok=True)
        (d / 'p1.bin').write_bytes(w24(b['words'])); (d / 'p1.org').write_text(f'{b["org"]:x}\n')
        (d / 'cont.txt').write_text(f'{b["cont"]:x}\n'); (d / 'rawp.txt').write_text(f'{b["rawp"]:x}\n')
        (d / 'kp.txt').write_text(''.join(f'{f!r} {m!r}\n' for f, m in (H.KP_PTS or [])))
        (d / 'lt.txt').write_text('%r %r\n' % H.LT_CFG if H.LT_CFG else '')
        (d / 'x.txt').write_text(''.join(f'{a:x} {v:x}\n' for a, v in sorted(b['x'].items())))
        (d / 'syms.txt').write_text(''.join(f'{k} {v & 0xffffff:x} {"Y" if k in b["ysyms"] else "X"}\n'
                                            for k, v in sorted(b['syms'].items())))
        env = dict(os.environ)
        if os.environ.get('OT_PCPROF'):                 # a profile per payload: FILE.A / FILE.B
            env['OT_PCPROF'] = f"{os.environ['OT_PCPROF']}.{tag}"
        p = subprocess.run([str(probe), str(d), frames], capture_output=True, text=True, errors='replace', env=env)
        lines = [l for l in p.stdout.strip().splitlines() if '@' not in l.split(':')[0]]
        print(f'payload {tag}:\n' + ''.join(f'    {l}\n' for l in lines), end='')
        fails += p.returncode != 0
    print('ALL GOOD' if not fails else f'{fails} FAILED')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
