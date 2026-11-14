#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# BLACKPYRAMIDS_303's voice in its Modwerk-base form: one DSP engine for both cores, placed by the base on the per-track
# source site's hook chain (Modwerk sdk/machines/octatrack/dsp-sites.json, site 5), instead of being written over
# SPRING REV's words by the card build (hwprobe_image.py, host=True). The same host.asm and ot303_engine.asm, with four
# changes made here, so the card FINAL's words stay as they are:
#   * no RELOC: run 1 (the engine's X block and the wrapper's words, 216 words at X:$7b24) is the X claim's initial
#     words, so nothing is copied from SPRING's records and XD is 0 on both cores;
#   * the raw-path test (payload A's RAWCHK, folded out of payload B at build time) reads RAWF, X:$7b05, at run time:
#     the claim starts it at 1 on core 0 (payload A) and 0 on core 1 (B);
#   * the exit is `jmp CONT` with CONT left as @CONT@: the base's engine tools write each core's exit (a long branch);
#   * the Y image ($7a5-$feb, the tables and the state block) is the Y claim's initial words.
# The chain's contract is the card seam's: the engine replays `move a,x:>$20e` itself, returns (rts) for a track that
# is not its own and drops the seam's return (move ssh,x0) before its exit.
#
#   python3 tools/ot303/base_engine.py            write octabam-modules/blackpyramids-303/bp_base_*.{asm,py}
#   build(tag)                                    the form assembled at payload `tag`'s own org (host_check.py's
#                                                 OT303_BASE=1): its words, syms, X at run-time addresses, Y
import hashlib, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'ot303'))
import asm_macros  # noqa: E402
import dsp_xasm  # noqa: E402
import hwprobe_image as H  # noqa: E402

OUT = ROOT / 'octabam-modules' / 'blackpyramids-303'
X_LO, X_N = 0x7b04, 0xf8            # the X claim: SIGA .. run 1's end ($7b04-$7bfb)
Y_LO, Y_N = 0x7a5, 0x847            # the Y claim: TH .. the state block's end ($7a5-$feb)
RAWF = 0x7b05


def _one(text, old, new, what):
    if text.count(old) != 1:
        raise ValueError(f'host.asm: {what} no longer matches exactly once')
    return text.replace(old, new)


def _wrap():
    wrap = (ROOT / 'tools/ot303/host.asm').read_text()
    start = wrap.index('        move    x:>SIGA,a\n')
    end = wrap.index('hq_rldone:\n') + len('hq_rldone:\n')
    if wrap.count('hq_rldone:\n') != 1 or 'hq_rl' in wrap[:start] + wrap[end:].replace('hq_rldone', ''):
        raise ValueError('host.asm: RELOC is no longer one block')
    wrap = wrap[:start] + '; (the base form: run 1 is the X claim\'s initial words, nothing is copied)\n' + wrap[end:]
    wrap = _one(wrap, 'SIGA    equ     XB-$3c', 'RAWF    equ     XB-$3b          ; X:$7b05: 1 on core 0 (the raw '
                'path\'s test), 0 on core 1 (the claim\'s initial words)\nSIGA    equ     XB-$3c', 'SIGA')
    body = re.search(r'^RAWCHK\s+macro\n(.*?)^\s+endm\n', wrap, flags=re.M | re.S)
    if not body:
        raise ValueError('host.asm: RAWCHK macro not found')
    wrap = wrap.replace(body.group(1), '        move    x:>RAWF,b\n        tst     b\n        beq     sg_ring\n' + body.group(1))
    wrap = _one(wrap, '        dc      $0c0000+CONT                    ; jmp <CONT: CONT is below $1000 (checked by disassembly)\n',
                '        jmp     CONT                            ; the site\'s exit: the base writes it per core\n', 'the exit')
    return wrap


def source(cont=None):
    """The engine text, the same on both cores but CONT (an address, or None: @CONT@). -> (text, ysyms)"""
    d = H.PAYLOAD['A']
    xb = d['xrun1'][0][0] + 0x1c - d['xd']
    assert xb == H.PAYLOAD['B']['xrun1'][0][0] + 0x1c - H.PAYLOAD['B']['xd'], 'the X block differs between the cores'
    eng = (ROOT / 'tools/ot303/ot303_engine.asm').read_text()
    lay = dict(XD=0, NXD=0, CONT=cont or 0, RAWP=1)
    text = asm_macros.layout(eng, XB=xb, YS=H.YS, LT=H.LT, TH=H.TH) + asm_macros.layout(_wrap(), **lay)
    if cont is None:
        text = _one(text, 'CONT    equ     $0 ', 'CONT    equ     @CONT@ ', 'the CONT line')
    return asm_macros.expand(text), asm_macros.yspace(eng)


def claims(tag):
    """The X and Y claims' initial words on payload `tag`'s core, from the card form's own placement."""
    card = H.build(tag, host=True)
    pb = card['syms']['PB']
    x = [0] * X_N
    for a, v in card['x'].items():
        if pb + card['xd'] <= a < pb + card['xd'] + 216:
            x[a - card['xd'] - X_LO] = v
        elif v:
            raise ValueError(f'payload {tag}: X:{a:x} = {v:x} is outside run 1')
    x[RAWF - X_LO] = card['rawp']
    y = [v & 0xffffff for v in card['y']]          # yimage: YBEG ($7a5, TH) .. YEND
    if card['syms']['YBEG'] != Y_LO or len(y) != Y_N:
        raise ValueError(f'payload {tag}: the Y image is not exactly the Y claim')
    return x, y


def build(tag):
    """The base form at payload `tag`'s own org, exit to its CONT: what host_check.py runs on the bench."""
    d = H.PAYLOAD[tag]
    text, ysyms = source(d['cont'])
    H.labels_ok(text)
    words, syms = dsp_xasm.assemble(text, d['org'], short_branches=dsp_xasm.STOCK_SHORT)
    dis = dsp_xasm.disassemble(words, d['org'])
    if [a for a, l in dis.items() if l[0].split()[:1] == ['rep']]:
        raise ValueError('a REP in the base form')
    consts = {}
    for line in text.splitlines():
        m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+(.+)$', line.split(';', 1)[0].rstrip())
        if m:
            consts[m.group(1)] = int(eval(m.group(2).replace('$', '0x'), {}, dict(consts)))
    S = dict(consts); S.update(syms)
    x, y = claims(tag)
    return dict(org=d['org'], words=words, syms=S, ysyms=ysyms, x={X_LO + i: v for i, v in enumerate(x)},
                y={Y_LO + i: v for i, v in enumerate(y)}, xd=0, seam_entry=S['sg_entry'], seam=d['seam'],
                cont=d['cont'], rawp=d['rawp'])


def main():
    text, _ = source()
    xa, ya = claims('A')
    xb, yb = claims('B')
    if ya != yb or [v for i, v in enumerate(xa) if i != RAWF - X_LO] != [v for i, v in enumerate(xb) if i != RAWF - X_LO]:
        raise ValueError('the claims differ between the cores beyond RAWF')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'bp_base_engine.asm').write_text(
        '; BLACKPYRAMIDS_303\'s voice, the Modwerk-base form (one engine for both cores; CONT = @CONT@, the site\'s exit).\n'
        '; GENERATED by tools/ot303/base_engine.py from tools/ot303/{ot303_engine.asm,host.asm}, macros expanded. Do not edit.\n'
        + text)
    sha = lambda w: hashlib.sha256(b''.join(v.to_bytes(3, 'big') for v in w)).hexdigest()
    (OUT / 'bp_base_data.py').write_text('\n'.join([
        '# BLACKPYRAMIDS_303\'s voice, the Modwerk-base form: the claims\' initial words. GENERATED by',
        '# tools/ot303/base_engine.py from the card form\'s placement (hwprobe_image.py, host=True). Do not edit.',
        f'X_START, Y_START, RAWF = 0x{X_LO:05x}, 0x{Y_LO:05x}, 0x{RAWF:05x}',
        'X = {',
        f'    "A": (' + ','.join(f'0x{v:06x}' for v in xa) + '),',
        f'    "B": (' + ','.join(f'0x{v:06x}' for v in xb) + '),',
        '}',
        'Y = (' + ','.join(f'0x{v:06x}' for v in ya) + ')',
        f'X_SHA256 = {{"A": {sha(xa)!r}, "B": {sha(xb)!r}}}',
        f'Y_SHA256 = {sha(ya)!r}',
    ]) + '\n')
    for tag in ('A', 'B'):
        b = build(tag)
        print(f'  payload {tag}: {len(b["words"])} words at its own org P:{b["org"]:x} (card form '
              f'{len(H.build(tag, host=True)["words"])}), X claim {X_N} words, Y claim {Y_N}')


if __name__ == '__main__':
    main()
