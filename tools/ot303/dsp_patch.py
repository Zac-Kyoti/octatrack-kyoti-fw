#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303: the image edits both OT-303 builders share (tools/build_ot303_hwprobe.py, the DIAG probe;
# tools/build_blackpyramids_303.py, the machine), every one asserting the stock words it replaces:
#   patch_dsp     both DSP payloads: the engine + wrapper over SPRING REV's P words, DARK REV's
#                 35-word helper moved to the module's end (its three outside callers retargeted),
#                 the source seam -> jsr the wrapper, SPRING's five X records rewritten, SPRING's
#                 dispatch -> the passthrough stub (and, for the probe, DJ EQ's proc -> its remote)
#   remove_spring SPRING REV out of both FX choosers; old projects naming it get the NONE page
import hashlib, importlib.util, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "ot303"))
import hwprobe_image  # noqa: E402

BASE = 0x40000400
DJEQ_ID = 0x0d
SPRING_ID = 0x15
# per payload, every value read off our own image (tools/ot303 session notes, scope §10):
#   spring_init/proc  X:$215[$15] / X:$235[$15] stock -> also the burn routine's origin
#   djeq_proc         X:$235[$0d] stock (DJ EQ's process routine)
#   stub_init/proc    the shared empty-FX passthrough (18 unused ids already point there)
#   dark_helper       first word of DARK REV's helper inside SPRING's module (moved to its end)
#   dark_calls        the three stock jsr's into it from outside SPRING (PLATE / DARK REV)
DSP = {
    "A": dict(va=0x400e2324, ln=0x136cb, spring_init=0x01252, spring_proc=0x012be,
              djeq_proc=0x01d7d, stub_init=0x007c8, stub_proc=0x007c9, dark_helper=0x01586,
              dark_calls=(0x017b3, 0x01998, 0x019c2)),
    "B": dict(va=0x400f59ef, ln=0x12d05, spring_init=0x01012, spring_proc=0x0107e,
              djeq_proc=0x01b3d, stub_init=0x00588, stub_proc=0x00589, dark_helper=0x01346,
              dark_calls=(0x01573, 0x01758, 0x01782)),
}
SPRING_SIG = [0x22ee00, 0x0140c0, 0x000040]      # SPRING's stock init, both payloads
DJEQ_SIG = [0x221e00, 0x61f400, 0x000140]        # DJ EQ's stock proc: move r0,n6 / move #>$140,r1
SEAM_SIG = [0x567000, 0x00020e]                  # move a,x:>$20e (both payloads)
JSR = 0x0bf080
# DARK REV's helper with its one absolute word (word 6, the DO's end) made relative: octabam's digest
# of the same routine (tools/build/ab_image.py SHARED_SHA256), checked against our own image
DARK_SHA = "c411c03ac315959374f7f16b8cc3558f65dbcd60dcdaa912ff0a39dcea53752a"

# ColdFire tables (memory-map.md; SIDECHAIN_COMPRESSOR uses the same)
FX_BUSES = (
    dict(tag="FX1", lst=0x400d6060, id2pos=0x400d60d0, id2e=0x400d5f58),
    dict(tag="FX2", lst=0x400d6090, id2pos=0x400d6150, id2e=0x400d5fdc),
)
SPRING_P = 0x400d5726 + 0x38
NONE_P = 0x400d45e0 + 0x38
DJEQ_P = 0x400d4dba + 0x38          # DJ EQ's descriptor pointer as the tables store it (E + 0x38)


def w3(v):
    return v.to_bytes(3, "little")


def rd3(img, off):
    return int.from_bytes(img[off:off + 3], "little")


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




def modmap():
    spec = importlib.util.spec_from_file_location("mm", ROOT / "refs/octabam/tools/build/dsp_modmap.py")
    mm = importlib.util.module_from_spec(spec); spec.loader.exec_module(mm)
    return mm


def patch_dsp(img, mm, host):
    """-> the two payloads' hwprobe_image.build() results"""
    # ---------------- DSP, both payloads ----------------
    print("=== DSP: engine + wrapper in SPRING REV's words and X records; the source seam -> the wrapper ===")
    out = []
    for tag, d in DSP.items():
        b = hwprobe_image.build(tag, host)
        org, words = b["org"], b["words"]
        assert org == d["spring_init"]
        so, mod_a, mod_c = p_off(mm, img, d["va"], d["ln"], org)
        assert [rd3(img, so + 3 * i) for i in range(3)] == SPRING_SIG, f"payload {tag}: SPRING init"
        assert mod_a == org and mod_c == hwprobe_image.SPRING_N, f"payload {tag}: SPRING's module is not 1063 words at its init"
        # DARK REV's helper: from inside SPRING's module to its last 35 words, its outside callers retargeted
        dark, n = d["dark_helper"], hwprobe_image.DARK_N
        new = org + mod_c - n
        helper = [rd3(img, so + 3 * (dark - org + i)) for i in range(n)]
        norm = helper.copy(); norm[6] -= dark
        assert hashlib.sha256(b"".join(w.to_bytes(3, "big") for w in norm)).hexdigest() == DARK_SHA, \
            f"payload {tag}: DARK REV's helper is not the stock routine"
        helper[6] += new - dark
        callers = []
        for sp, addr, cnt, data in mm.modules(bytes(img), d["va"], d["ln"])[0]:
            if sp != 0:
                continue
            off = (d["va"] - BASE) + data
            for k in range(1, cnt):
                if rd3(img, off + 3 * k) == dark and rd3(img, off + 3 * (k - 1)) == JSR and not org <= addr + k < org + mod_c:
                    callers.append(addr + k - 1)
        assert tuple(callers) == d["dark_calls"], f"payload {tag}: helper callers {[hex(c) for c in callers]}"
        assert len(words) <= new - org, f"payload {tag}: code reaches the helper's new place"
        for i, wv in enumerate(words):
            img[so + 3 * i: so + 3 * i + 3] = w3(wv)
        for i, wv in enumerate(helper):
            img[so + 3 * (new - org + i): so + 3 * (new - org + i) + 3] = w3(wv)
        for c in callers:
            co, _, _ = p_off(mm, img, d["va"], d["ln"], c + 1)
            img[co:co + 3] = w3(new)
        print(f"  payload {tag}: {len(words)} words @ P:0x{org:05x}; DARK REV's helper P:0x{dark:05x} -> P:0x{new:05x}, "
              f"callers {', '.join(f'P:0x{c:05x}' for c in callers)} retargeted; seam entry P:0x{b['seam_entry']:05x}"
              + (f", DJ EQ entry P:0x{b['entry']:05x}" if b['entry'] is not None else ""))
        # the source seam -> jsr the glue
        sm, _, _ = p_off(mm, img, d["va"], d["ln"], b["seam"])
        assert [rd3(img, sm + 3 * i) for i in range(2)] == SEAM_SIG, f"payload {tag}: seam P:0x{b['seam']:05x} not stock"
        assert p_off(mm, img, d["va"], d["ln"], b["seam"] + 1)[0] == sm + 3
        img[sm:sm + 3] = w3(JSR)
        img[sm + 3:sm + 6] = w3(b["seam_entry"])
        print(f"    P:0x{b['seam']:05x} move a,x:>$20e -> jsr >P:0x{b['seam_entry']:05x}; continues at P:0x{b['cont']:05x}")
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
        if b["entry"] is not None:                        # the probe: DJ EQ's proc -> the remote
            img[di:di + 3] = w3(b["entry"])
        print(f"    X:$215[$15] -> passthrough stub" + (f"; X:$235[$0d] -> P:0x{b['entry']:05x}" if b["entry"] is not None else ""))
        out.append(b)

    return out


def remove_spring(img):
    def o(a):
        return a - BASE

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    def wr32(a, v):
        img[o(a):o(a) + 4] = v.to_bytes(4, "big")
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

