# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""BLACKPYRAMIDS_303's DSP voice in an OT image: octabam's integrate step for a DSP source machine
(build_bus.py calls integrate() last, after every DSP pass has written both payloads).

For each payload, every stock word asserted before it is replaced (the standalone's
tools/ot303/dsp_patch.py, the same edits ANALOG BD's tools/build/ab_image.py makes):

  1. the voice (tools/ot303/ot303_engine.asm + host.asm: 1,027 words, bp_dsp_data.py) over SPRING
     REV's P words -- the remix does not list SPRING REV, so it is on neither chooser;
  2. DARK REV's 35-word helper, which lies inside SPRING's module, moved to the module's last 35
     words and its three outside callers retargeted (its digest is ANALOG BD's SHARED_SHA256);
  3. the source seam, `move a,x:>$20e` (A P:0x39c, B P:0x1a2), -> jsr the host;
  4. SPRING's five X records (716 words, unread by stock at runtime) rewritten: the engine's X
     block (copied to X:$7b24 at the first frame) and its constants;
  5. SPRING's dispatch (id 0x15) -> the passthrough stub, so a Part naming SPRING runs no code.

The payloads keep their size, so they stay in the OS image (no pre-boot upload). The voice's Y
($7a5-$feb) is streamed from the ColdFire, never in an upload.
"""
import hashlib
import importlib.util
import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
BASE = 0x40000400


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DATA = _load("bp_dsp_data", _HERE / "bp_dsp_data.py")

SPRING_ID = 0x15
SPRING_N, DARK_N = 1063, 35
DSP = {
    "A": dict(va=0x400E2324, ln=0x136CB, spring_init=0x01252, spring_proc=0x012BE, stub_init=0x007C8,
              stub_proc=0x007C9, dark_helper=0x01586, dark_calls=(0x017B3, 0x01998, 0x019C2),
              xruns=((0x89A4, 72), (0x89EC, 72), (0x8A34, 72), (0x8AFC, 116), (0x8B70, 384))),
    "B": dict(va=0x400F59EF, ln=0x12D05, spring_init=0x01012, spring_proc=0x0107E, stub_init=0x00588,
              stub_proc=0x00589, dark_helper=0x01346, dark_calls=(0x01573, 0x01758, 0x01782),
              xruns=((0x8464, 72), (0x84AC, 72), (0x84F4, 72), (0x85BC, 116), (0x8630, 384))),
}
SPRING_SIG = [0x22EE00, 0x0140C0, 0x000040]     # SPRING's stock init, both payloads
SEAM_SIG = [0x567000, 0x00020E]                 # move a,x:>$20e
JSR = 0x0BF080
DARK_SHA = "c411c03ac315959374f7f16b8cc3558f65dbcd60dcdaa912ff0a39dcea53752a"


def _w3(v):
    return (v & 0xFFFFFF).to_bytes(3, "little")


def _rd3(img, off):
    return int.from_bytes(img[off:off + 3], "little")


def _die(msg):
    sys.exit(f"blackpyramids-303: {msg}")


def integrate(img, stock):
    """Write the voice into both payloads of `img` in place. -> (pre-boot payloads, pokes, log):
    nothing pre-boot and no ColdFire pokes (the module's manifest declares those)."""
    mm = _load("dsp_modmap", pathlib.Path.cwd() / "tools/build/dsp_modmap.py")
    log = []
    for tag, d in DSP.items():
        p = DATA.PAYLOAD[tag]
        words = list(p["words"])
        got = hashlib.sha256(b"".join(w.to_bytes(3, "big") for w in words)).hexdigest()
        if got != p["words_sha256"]:
            _die(f"payload {tag}: bp_dsp_data.py's words are not the generated ones")
        mods = mm.modules(bytes(img), d["va"], d["ln"])[0]

        def p_off(addr):
            for sp, a, cnt, data in mods:
                if sp == 0 and a <= addr < a + cnt:
                    return (d["va"] - BASE) + data + (addr - a) * 3, a, cnt
            _die(f"payload {tag}: P:0x{addr:05x} is in no P module")

        org = p["org"]
        if org != d["spring_init"]:
            _die(f"payload {tag}: the voice's org P:0x{org:05x} is not SPRING's")
        so, mod_a, mod_c = p_off(org)
        if [_rd3(img, so + 3 * i) for i in range(3)] != SPRING_SIG or (mod_a, mod_c) != (org, SPRING_N):
            _die(f"payload {tag}: SPRING REV's P module is not stock (another module took it?)")
        # DARK REV's helper -> the module's last 35 words, its outside callers retargeted
        dark, new = d["dark_helper"], org + SPRING_N - DARK_N
        helper = [_rd3(img, so + 3 * (dark - org + i)) for i in range(DARK_N)]
        norm = helper.copy()
        norm[6] -= dark
        if hashlib.sha256(b"".join(w.to_bytes(3, "big") for w in norm)).hexdigest() != DARK_SHA:
            _die(f"payload {tag}: DARK REV's helper is not the stock routine")
        helper[6] += new - dark
        callers = []
        for sp, a, cnt, data in mods:
            if sp != 0:
                continue
            off = (d["va"] - BASE) + data
            for k in range(1, cnt):
                if (_rd3(img, off + 3 * k) == dark and _rd3(img, off + 3 * (k - 1)) == JSR
                        and not org <= a + k < org + SPRING_N):
                    callers.append(a + k - 1)
        if tuple(callers) != d["dark_calls"]:
            _die(f"payload {tag}: DARK REV's helper is called from {[hex(c) for c in callers]}")
        if len(words) > new - org:
            _die(f"payload {tag}: {len(words)} words reach the helper's new place")
        for i, w in enumerate(words):
            img[so + 3 * i:so + 3 * i + 3] = _w3(w)
        for i, w in enumerate(helper):
            img[so + 3 * (new - org + i):so + 3 * (new - org + i) + 3] = _w3(w)
        for c in callers:
            co, _, _ = p_off(c + 1)
            img[co:co + 3] = _w3(new)
        log.append(f"  blackpyramids-303 {tag}: voice {len(words)} words at P:0x{org:05x} (SPRING REV's "
                   f"{SPRING_N}); DARK REV's helper P:0x{dark:05x} -> P:0x{new:05x}, "
                   + ", ".join(f"P:0x{c:05x}" for c in callers) + " retargeted")
        # the source seam -> jsr the host
        sm, _, _ = p_off(p["seam"])
        if [_rd3(img, sm + 3 * i) for i in range(2)] != SEAM_SIG or p_off(p["seam"] + 1)[0] != sm + 3:
            _die(f"payload {tag}: the source seam P:0x{p['seam']:05x} is not stock")
        img[sm:sm + 3] = _w3(JSR)
        img[sm + 3:sm + 6] = _w3(p["seam_entry"])
        log.append(f"    P:0x{p['seam']:05x} move a,x:>$20e -> jsr P:0x{p['seam_entry']:05x} "
                   f"(continues at P:0x{p['cont']:05x})")
        # SPRING's five X records, every word rewritten
        x = dict(p["x"])
        for a, cnt in d["xruns"]:
            rec = [m for m in mods if m[0] == 1 and m[1] == a]
            if len(rec) != 1 or rec[0][2] != cnt:
                _die(f"payload {tag}: no {cnt}-word X record at X:0x{a:05x}")
            xo = (d["va"] - BASE) + rec[0][3]
            for k in range(cnt):
                img[xo + 3 * k:xo + 3 * k + 3] = _w3(x.pop(a + k))
        if x:
            _die(f"payload {tag}: X words outside SPRING's records: {sorted(x)[:4]}")
        # SPRING's dispatch -> the passthrough stub
        xrec = [m for m in mods if m[0] == 1 and m[1] == 0x215]
        if len(xrec) != 1:
            _die(f"payload {tag}: no dispatch table record at X:0x215")
        xt = (d["va"] - BASE) + xrec[0][3]
        si, sp_ = xt + SPRING_ID * 3, xt + (0x20 + SPRING_ID) * 3
        if (_rd3(img, si), _rd3(img, sp_)) != (d["spring_init"], d["spring_proc"]):
            _die(f"payload {tag}: SPRING's dispatch is not stock")
        img[si:si + 3] = _w3(d["stub_init"])
        img[sp_:sp_ + 3] = _w3(d["stub_proc"])
        log.append(f"    X: {sum(c for _, c in d['xruns'])} words over SPRING's records; "
                   f"id 0x15 -> stub {d['stub_init']:05x}/{d['stub_proc']:05x}")
    return (), [], log


if __name__ == "__main__":
    print(os.path.basename(__file__), "is called by octabam's build_bus.py")
