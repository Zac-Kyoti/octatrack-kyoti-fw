#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
diag_reload3_diagtoast -- gate for the RELOAD3 DIAG build (build_reload3.py --diag).

Session 98, reference/handoffs/RELOAD3_SEQFAIL_HANDOFF.md section 4. On hardware a
[PTN]+[TRACK n] reload frequently leaves the EDITED sequence playing while the toast says
RELOADED and the rl_done self-verify stays silent. The emulator has never reproduced it
(section 6), so the diag build makes the toast print the raw bytes and indices the worker
used, and hardware decides. THIS script only proves the instrument: that the four lines
are drawn, that they read correctly in the clean case, and -- the part that matters --
that each failure signature the handoff predicts actually appears on the toast when that
failure is injected. A gate that cannot fail is not a gate (section 7).

THE FOUR LINES (patch_reload3.s, the RL_DIAG block near RDRAW)
    P pppppppp S ssssssss   live record BEFORE the copy / rl_vsnap (SCRATCH after copy)
    L llllllll K kkkkkkkk   live record at doneFn / the 0x1001614e live-cache copy
    C bptm W bptm D bp      bank,pat,trk,midi as the CHORD armed / the WORKER read /
                            PLAY_BANK,ACT_PAT as DONEFN saw them
    Mn Vn Kn R rr           message code / verify 0,1,2 / G_KIND as read / last PARSEPAT

THREE SCENARIOS, ONE BOOT (sequential; stage_project is not concurrency-safe)
  clean        empty the pattern (gated on HAS_CONTENT == 0), chord, wait for the worker.
               Expect P = 00000000, S = L = K = the CF-saved bytes, C == W == D, M1 V1 K3,
               LED ON.
  wrongtrack   same, but G_TRK (0x80006a54) is poked to another track from the rl_job
               ENTRY hook -- i.e. after the chord armed it and before the worker reads it
               in rlj_trk. (A first version poked after the key calls returned; in the
               emulator the storage task drains the job INSIDE those calls, so the poke
               landed after the read and the scenario's own gate caught it.) This is
               what a clobber of the 0x80006a5x scratch (kb/caves.md, Sessions 94-96)
               would look like. Expect: line 2 shows C.trk != W.trk, the verify still
               PASSES (V1 -- it checks the slice the worker wrote), and the TARGET track's
               masks are still empty. I.e. the shipping toast would have said RELOADED.
  scratch      same, but the 16 mask bytes at the memcpy SOURCE are zeroed just before
               FWMEMCPY runs from our worker -- "SCRATCH held the edited data", hypothesis
               A. Expect P = S = L = K = 00000000 with V1: the vacuous-verify signature.
               Target masks empty, LED OFF.

Usage: python3 tools/diag_reload3_diagtoast.py [--track N] [--chord ptn|bank]
Reads out/mainos_reload3_diag.bin + out/patch_reload3_diag.elf (build with --diag first).
"""
import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
sys.path.insert(0, str(ROOT / "tools"))
import emu_reload as erl          # noqa: E402
from cave_syms import syms        # noqa: E402
er = erl.er

DIAG_IMAGE = ROOT / "out" / "mainos_reload3_diag.bin"
DIAG_ELF = ROOT / "out" / "patch_reload3_diag.elf"

SET_KEY_STATE = 0x40031734
PTN_CODE, BANK_CODE, TRACK0 = 0x2E, 0x2F, 0x10
PRESS, RELEASE = 1, 0
HAS_CONTENT = 0x4009A464
DRAWTEXT = 0x40012BD8
WIN_NEW = 0x4005829C
FWMEMCPY = 0x40020898
TOAST_CD = 0x460D1E6C
TOAST_SLOT = 0x460D1E70

BLOB = 0x400E21E0
BANKSTRIDE, PATSTRIDE = 0x9B340, 0x8ED8
TRAC_A, MIDI_BASE, TRAC_M = 0x91A, 0x48D0, 0x8B0
MASK_LEN = 0x10
OLD_SCRATCH = 0x80006A50   # where the request bytes lived before Session 98's fix
PLAY_BANK, ACT_PAT = 0x800065BD, 0x800065BE
DIAG_DUR = 0x168


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", type=int, default=3)
    ap.add_argument("--chord", choices=("ptn", "bank"), default="ptn")
    a = ap.parse_args(argv)

    if not DIAG_IMAGE.exists() or not DIAG_ELF.exists():
        sys.exit("build the diag image first: python3 tools/build_reload3.py --diag")
    S = syms(str(DIAG_ELF))
    for k in ("rl3_diag_show", "rl_dtext", "rl_job", "rlj_setflag", "rl_done"):
        S[k]  # KeyError = fail loud
    CAVE_LO, CAVE_HI = 0x400D6500, S["rl_dtext"] + 96
    G_KIND, G_TRK = S["G_KIND"], S["G_TRK"]   # Session 98: in the cave now
    TEXT_LO, TEXT_HI = S["rl_dtext"], S["rl_dtext"] + 96

    erl.OUR_IMAGE = DIAG_IMAGE
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    ok, detail = er.eb.emac_selftest()
    if not ok:
        sys.exit("refusing to run on a stock (un-fixed) Unicorn EMAC: " + detail[:150])

    card, staged = er.stage_project(str(erl.DEMO), "OCTABAM", None)
    r, rt = er.attach(str(erl.OUR_IMAGE), card, ips=3990.0, pit_clock_hz=264e6,
                      quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    rt.load_project_live("OCTABAM", staged, run_ms=6000, mount_ms=3000)
    P = rt.uc.mem_read(er.CUR_PATTERN, 1)[0]
    b0 = rt.uc.mem_read(0x80000002, 1)[0]
    rt.seq_select_live(b0, P)
    rt.internal_clock(); rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD; rt.exact_clock()
    rt.start_transport_live()
    for _ in range(10):
        rt.run(ms=60)

    bank, pat = rt.uc.mem_read(PLAY_BANK, 1)[0], rt.uc.mem_read(ACT_PAT, 1)[0]
    slab = BLOB + bank * BANKSTRIDE + pat * PATSTRIDE
    tmask = slab + a.track * TRAC_A
    saved = bytes(rt.uc.mem_read(tmask, MASK_LEN))
    print(f"load : bank={bank} pattern={pat} track={a.track+1} chord={a.chord}")
    print(f"   CF-saved trig masks for this track = {saved.hex()}")
    if saved[:4] == b"\x00" * 4:
        sys.exit("GATE FAIL: the first 4 CF-saved mask bytes are EMPTY, so the toast's "
                 "S/L/K bytes could not differ from the emptied state. Pick another --track.")
    windows = [slab + t * TRAC_A for t in range(8)]
    windows += [slab + MIDI_BASE + t * TRAC_M for t in range(8)]

    # ---- hooks ----
    C = {"job": 0, "setflag": 0, "show": 0, "memcpy_ours": 0}
    draws, wins = [], []
    inject = {"scratch": False, "trk": None, "old": False}

    def bump(k):
        return lambda u, ad, sz, x: C.__setitem__(k, C[k] + 1)
    def on_job(u, ad, sz, x):
        C["job"] += 1
        if inject["old"]:
            # the HARDWARE failure, replayed: the unit's W 005B came from these bytes being
            # overwritten between chord and worker. Garbage that decodes as kind 3, a
            # different pattern, track 5 (0x55 & 7) and a MIDI flag of 0x5B.
            u.mem_write(OLD_SCRATCH, bytes([0x03, 0x07, 0x55, 0x55, 0x55, 0x5B]))
        if inject["trk"] is not None:
            # a clobber of the 0x80006a5x scratch between the chord and the worker's read
            u.mem_write(G_TRK, bytes([inject["trk"]]))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_job, begin=S["rl_job"], end=S["rl_job"])
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, bump("setflag"),
                   begin=S["rlj_setflag"], end=S["rlj_setflag"])
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, bump("show"),
                   begin=S["rl3_diag_show"], end=S["rl3_diag_show"])

    def on_draw(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        font, winptr, xx, yy, ln, txt = struct.unpack(">6I", u.mem_read(sp + 4, 24))
        if TEXT_LO <= txt < TEXT_HI:
            draws.append((xx, yy, txt))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_draw, begin=DRAWTEXT, end=DRAWTEXT)

    def on_win(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        w, h, _, _, style, _ = struct.unpack(">6I", u.mem_read(sp + 4, 24))
        wins.append((w, h, style))
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_win, begin=WIN_NEW, end=WIN_NEW)

    def on_memcpy(u, ad, sz, x):
        sp = u.reg_read(er.eb.UC_M68K_REG_A7)
        ret, dst, src, n = struct.unpack(">4I", u.mem_read(sp, 16))
        if CAVE_LO <= ret < CAVE_HI:
            C["memcpy_ours"] += 1
            if inject["scratch"]:
                # "SCRATCH held the edited data": the source's mask bytes are the
                # emptied state, not the card's
                u.mem_write(src, b"\x00" * MASK_LEN)
    rt.uc.hook_add(er.eb.UC_HOOK_CODE, on_memcpy, begin=FWMEMCPY, end=FWMEMCPY)
    rt.uc.ctl_flush_tb()

    def spin():
        rt.run(until=lambda s: s.pc == er.MAIN_SPIN)

    def has_content():
        spin()
        return rt.call_as_main(HAS_CONTENT, args=(pat & 0xFFFFFFFF, bank & 0xFFFFFFFF))

    def key(c, e):
        spin()
        rt.call_as_main(SET_KEY_STATE, args=(c, e), budget=4_000_000)

    def txt(ptr):
        out = b""
        while len(out) < 40:
            c = rt.uc.mem_read(ptr + len(out), 1)
            if c == b"\x00":
                break
            out += c
        return out.decode("latin1")

    def u32(ad):
        return struct.unpack(">I", rt.uc.mem_read(ad, 4))[0]

    hold = PTN_CODE if a.chord == "ptn" else BANK_CODE
    fails = []

    def chk(cond, msg):
        print(f"   [{'ok ' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    def parse(lines):
        """-> dict of the toast's fields, or None if the shape is wrong."""
        if len(lines) != 4:
            return None
        try:
            l0, l1, l2, l3 = lines
            f = {}
            assert l0[:2] == "P " and l0[10:13] == " S ", l0
            f["P"], f["S"] = l0[2:10], l0[13:21]
            assert l1[:2] == "L " and l1[10:13] == " K ", l1
            f["L"], f["K"] = l1[2:10], l1[13:21]
            assert l2[:2] == "C " and l2[6:9] == " W " and l2[13:16] == " D ", l2
            f["C"], f["W"], f["D"] = l2[2:6], l2[9:13], l2[16:18]
            assert l3[0] == "M" and l3[2:4] == " V" and l3[5:7] == " K" and l3[8:11] == " R ", l3
            f["M"], f["V"], f["Kk"], f["R"] = l3[1], l3[4], l3[7], l3[11:13]
            return f
        except AssertionError as e:
            print(f"   toast line shape unexpected: {e}")
            return None

    def scenario(name, trk=None, scratch=False, old=False):
        print(f"\n--- {name} ---")
        for w in windows:
            rt.uc.mem_write(w, b"\x00" * MASK_LEN)
        if has_content():
            fails.append(f"{name}: GATE -- firmware still reports content after emptying")
            return None
        draws.clear(); wins.clear()
        inject["scratch"], inject["trk"], inject["old"] = scratch, trk, old
        j0, s0, sh0, m0 = C["job"], C["setflag"], C["show"], C["memcpy_ours"]
        key(hold, PRESS)
        key(TRACK0 + a.track, PRESS)
        key(TRACK0 + a.track, RELEASE)
        key(hold, RELEASE)
        for _ in range(300):
            rt.run(ms=20)
            if C["show"] > sh0:
                break
        for _ in range(4):
            rt.run(ms=60)
        inject["scratch"], inject["trk"], inject["old"] = False, None, False
        chk(C["job"] - j0 == 1, f"rl_job entered once (x{C['job']-j0})"
            + (" -- the G_TRK poke landed there, before the worker's read" if trk is not None else ""))
        chk(C["setflag"] - s0 == 1, f"worker reached rlj_setflag once (x{C['setflag']-s0})")
        chk(C["show"] - sh0 == 1, f"rl3_diag_show ran once (x{C['show']-sh0})")
        chk(C["memcpy_ours"] - m0 >= 1,
            f"our worker's FWMEMCPY was observed (x{C['memcpy_ours']-m0})")
        # the toast: 4 lines, drawn from rl_dtext, top to bottom by y
        ordered = sorted(draws, key=lambda d: -d[1])
        lines = [txt(t) for _, _, t in ordered]
        for ln in lines:
            print(f"   | {ln}")
        chk(len(lines) == 4, f"four lines drawn from rl_dtext (n={len(lines)})")
        chk(all(len(ln) <= 21 for ln in lines),
            f"every line within stock's 21-char toast width ({[len(l) for l in lines]})")
        tw = [w for w in wins if w[2] == 0xA]
        chk(bool(tw) and tw[-1][1] == 0x12 + 21,
            f"block window height 0x12+21 for four lines (wins={wins})")
        chk(u32(TOAST_CD) == DIAG_DUR and u32(TOAST_SLOT) != 0,
            f"toast up with the diag countdown (cd={u32(TOAST_CD):#x}, slot={u32(TOAST_SLOT):#x})")
        f = parse(lines)
        chk(f is not None, "toast lines parse into the documented fields")
        if f:
            f["target"] = bytes(rt.uc.mem_read(tmask, MASK_LEN)).hex()
            f["led"] = has_content()
            print(f"   fields: {f}")
        return f

    exp_M = "1" if a.chord == "ptn" else None   # bank chord: 2 or 3, depends on Part state
    sv = saved[:4].hex().upper()
    tdig = f"{a.track:X}"

    # ================= 1. clean =================
    f = scenario("clean: empty -> chord -> the toast must read the restore")
    if f:
        chk(f["P"] == "00000000", f"P (live before copy) is the emptied state: {f['P']}")
        chk(f["S"] == sv, f"S (snapshot) is the CF-saved bytes: {f['S']} == {sv}")
        chk(f["L"] == sv, f"L (live at doneFn) is the CF-saved bytes: {f['L']}")
        chk(f["K"] == sv, f"K (live cache) is the CF-saved bytes: {f['K']}")
        chk(f["C"] == f["W"], f"chord and worker agree on bank/pat/trk/midi: C {f['C']} W {f['W']}")
        chk(f["C"][2] == tdig and f["C"][3] == "0",
            f"chord armed track {tdig}, audio: C {f['C']}")
        chk(f["C"][:2] == f["D"] and f["D"] == f"{bank:X}{pat:X}",
            f"doneFn bank/pat match the chord and the sequencer: D {f['D']}")
        chk(f["V"] == "1", f"verify passed (V{f['V']})")
        chk(f["Kk"] == "3", f"worker read G_KIND 3 (K{f['Kk']})")
        chk(exp_M is None or f["M"] == exp_M, f"message code M{f['M']}")
        chk(f["target"] == saved.hex(), "target track's masks restored to the CF-saved bytes")
        chk(bool(f["led"]), f"LED ON (HAS_CONTENT={f['led']})")

    # ================= 1b. THE FIX: the hardware clobber, replayed =================
    f = scenario("oldscratch: 0x80006a50-55 overwritten with 03 07 55 55 55 5B between chord "
                 "and worker (the unit's W 005B) -- the fixed build must not care", old=True)
    if f:
        chk(f["C"] == f["W"] == f"{bank:X}{pat:X}{tdig}0",
            f"worker still read the chord's request: C {f['C']} W {f['W']}")
        chk(f["S"] == sv and f["L"] == sv, f"S/L are the CF-saved bytes: S {f['S']} L {f['L']}")
        chk(f["target"] == saved.hex(), "target track restored to the CF-saved bytes")
        chk(bool(f["led"]), f"LED ON (HAS_CONTENT={f['led']})")
        chk(f["V"] == "1" and f["Kk"] == "3", f"verify passed, kind 3 (V{f['V']} K{f['Kk']})")

    # ================= 2. wrong track =================
    other = (a.track + 1) & 7
    f = scenario("wrongtrack: G_TRK clobbered between chord and worker -- a scratch-RAM "
                 "clobber must be VISIBLE on line 2",
                 trk=other)
    if f:
        chk(f["C"][2] == tdig and f["W"][2] == f"{other:X}",
            f"line 2 exposes the mismatch: chord trk {f['C'][2]} vs worker trk {f['W'][2]}")
        chk(f["V"] == "1", f"the verify STILL passes on the slice the worker wrote (V{f['V']}) "
                           f"-- the shipping toast would have said RELOADED")
        chk(f["target"] == "00" * MASK_LEN,
            f"the TARGET track was NOT restored (masks {f['target']})")

    # ================= 3. scratch held the edited data =================
    f = scenario("scratch: memcpy source masks zeroed before the copy -- hypothesis A's "
                 "vacuous-verify signature must appear on lines 0/1", scratch=True)
    if f:
        chk(f["P"] == "00000000" and f["S"] == "00000000",
            f"P == S == emptied state: P {f['P']} S {f['S']}")
        chk(f["L"] == "00000000" and f["K"] == "00000000",
            f"L == K == emptied state: L {f['L']} K {f['K']}")
        chk(f["V"] == "1", f"the verify passes VACUOUSLY (V{f['V']}) -- exactly the "
                           f"hardware shape: toast, no LOST, stale playback")
        chk(f["C"] == f["W"], f"targeting agreed (C {f['C']} W {f['W']}) -- so line 0/1, "
                              f"not line 2, is what names this failure")
        chk(f["target"] == "00" * MASK_LEN and not f["led"],
            f"target masks empty and LED OFF (masks {f['target']}, LED={f['led']})")

    print()
    if fails:
        print(f"   {len(fails)} FAIL(S):")
        for x in fails:
            print(f"     - {x}")
        return 1
    print("   ALL GOOD -- the old-scratch clobber no longer redirects the reload; the diag toast draws, reads the clean restore correctly, and shows "
          "both injected failure signatures (wrong-track on line 2, SCRATCH-clobber on lines 0/1) "
          "while the verify passes. Flash out/OCTATRACK_OS1.40C_RELOAD3_DIAG.syx and read the "
          "hex with the handoff's section 4 table.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
