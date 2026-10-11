#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 hardware probe (DIAG14) on the bench: both payloads' placements (tools/ot303/hwprobe_image.py)
# run on dsp56kEmu as the firmware enters them (tools/ot303/hwprobe_probe.cpp: the source seam and
# the DJ EQ remote, three tracks, a claim handed over), tone and riff, against the integer twin.
# Needs the private toolchain (out/ot303/dsp56300_new).
#   python3 tools/ot303/hwprobe_check.py [FRAMES]
import os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'tools' / 'ot303'))
import hwprobe_image as H  # noqa: E402

OUT = ROOT / 'out' / 'ot303' / 'hwprobe'
VEND = H.NEW


def w24(words):
    return b''.join((w & 0xffffff).to_bytes(3, 'little') for w in words)


def main():
    frames = sys.argv[1] if len(sys.argv) > 1 else '20352'          # 4 bars of the riff
    OUT.mkdir(parents=True, exist_ok=True)
    probe = OUT / 'hwprobe_probe'
    inc = [f'-I{VEND}/source', f'-I{VEND}/source/asmjit/src', f'-I{ROOT}/tools/ot303', '-DDSP56300_DEBUGGER=0', '-DASMJIT_STATIC']
    libs = [f'{VEND}/build/source/dsp56kEmu/libdsp56kEmu.a', f'{VEND}/build/source/dsp56kBase/libdsp56kBase.a',
            f'{VEND}/build/source/asmjit/libasmjit.a']
    r = subprocess.run(['c++', '-std=c++17', '-O2', '-w', *inc, str(ROOT / 'tools/ot303/hwprobe_probe.cpp'), *libs, '-o', str(probe)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('probe build failed:\n' + r.stderr[-3000:])
    fails = 0
    for tag in ('A', 'B'):
        b = H.build(tag)
        d = OUT / tag
        d.mkdir(exist_ok=True)
        (d / 'p1.bin').write_bytes(w24(b['words'])); (d / 'p1.org').write_text(f'{b["org"]:x}\n')
        (d / 'cont.txt').write_text(f'{b["cont"]:x}\n'); (d / 'rawp.txt').write_text(f'{b["rawp"]:x}\n')
        (d / 'djeq.txt').write_text(f'{b["djeq_proc"]:x}\n')
        (d / 'x.txt').write_text(''.join(f'{a:x} {v:x}\n' for a, v in sorted(b['x'].items())))
        (d / 'syms.txt').write_text(''.join(f'{k} {v & 0xffffff:x} {"Y" if k in b["ysyms"] else "X"}\n'
                                            for k, v in sorted(b['syms'].items())))
        for knob, burn, raw in ((8, 0, 0), (32, 0, 0), (32, 20, 0), (127, 0, 0), (40, 0, 1)):
            env = dict(os.environ, HWP_BURN=str(burn))
            env.pop('HWP_RAW', None)
            if raw:
                env['HWP_RAW'] = '1'
            p = subprocess.run([str(probe), str(d), str(knob), frames], capture_output=True, text=True, errors='replace', env=env)
            lines = [l for l in p.stdout.strip().splitlines() if not re.match(r'^\w+@\d+:', l)]
            print(f'payload {tag} 303 = {knob:3d} BURN {burn:2d}{" RAW" if raw else ""}: ' + '\n' + ''.join(f'    {l}\n' for l in lines), end='')
            fails += p.returncode != 0
    print('ALL GOOD' if not fails else f'{fails} FAILED')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
