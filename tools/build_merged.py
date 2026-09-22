#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
build_merged.py -- the combined OT Kyoti FW: every final-scoped mod in ONE image.

    stock 1.40C
      + Bug-1 MIDI manual-trig fix           (patch_trigscale)
      + Bug-2 pattern-LED "only p-locks -> shows empty" fix  (patch_pattern_led)
      + MUTE MODE  OT / OT+FX / DT            (patch_softmute + patch_mutemode, DT_MODE=1)
      + DIRECT JUMP  [PTN]+[YES]  (v3 overlay) (patch_directjump, DJ_V3=1)
      + SIDE-CHAIN compressor  KEY/KFLT/KGAIN/MON + DSP  (patch_sidechain + patch_sc_dsp3)
      + RELOAD FROM PROJECT  hold [PTN]  (2-item)  (patch_reload2, MERGE=1)
      + QUANTIZE LIVE REC front-panel toggle  [REC]+[PLAY]x2  (patch_qlrec)

This is the NO-FLASH merge-prep build (NOTES.md "Session 45").  It exists to prove the
five mods compose -- caves relocated to disjoint slots, the one shared key handler
([YES] @ 0x4005e4c8) resolved by a trampoline, every displaced-byte guard re-checked,
round-trip + checksum through Elektron's own tool.  It is NOT a substitute for the
per-feature hardware passes still queued (FLASHING.md); flash those first, in order,
THEN this.

Cave conflict resolution
------------------------
* Standalone, MUTE MODE / DIRECT JUMP / RELOAD2 each link their cave at 0x400d7400.
  Here every ColdFire cave is auto-packed from 0x400d7000 upward; patch_trigscale
  stays pinned at 0x400d7b00 (so its bytes are identical to build_trigscale_only.py).
* The [YES] handler @ 0x4005e4c8 is wanted by BOTH DIRECT JUMP ([PTN]+[YES] toggle)
  and RELOAD2 ([YES] answers the picker).  Only RELOAD2 installs the detour; its
  "not the picker" path is compiled (--defsym MERGE=1) to `jmp dj_toggle` instead of
  replaying the prologue, so DIRECT JUMP's check runs next and either toggles or
  replays the prologue itself.  See patch_reload2.s "merged-firmware [YES] chaining".
* SIDE-CHAIN's DSP work is in a different address space entirely and its ColdFire
  footprint (COMPRESSOR descriptor + FX choosers) is a region no other mod touches.
* MUTE MODE and DIRECT JUMP both need the 'ANDY' restore extended pea 0x64 -> pea 0x70
  at 3 sites -- identical, idempotent; done once here.
* patch_pattern_led (Bug-2) detours ONE site (FUN_4009a464) nothing else touches;
  patch_qlrec detours two ([PLAY] press 0x40061778, [REC] release 0x4004883a) that
  nothing else touches.  Neither shares a global with the other four.
* FREE_START was lowered to 0x400d6500 in S48 to fit QLREC (the whole
  0x400d64da..0x400d7c3c span is zero in stock).  patch_sidechain no longer lands at
  0x400d7000, so the COMPRESSOR descriptor's per-slot formatter pointers now differ
  from build_sidechain3.py -- their VALUES are still asserted against sc_syms; the
  stray-byte check exempts those 4-byte pointer slots (section 8).

Usage:   python3 tools/build_merged.py [VERSTR]        (default "KYOTI_V1.0")
Outputs: out/mainos_merged.bin, out/elek_merged.bin,
         out/OCTATRACK_OS1.40C_KYOTI_ALL.syx, out/OCTATRACK_KYOTI_ALL.bin
"""
import os, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_sidechain3 as sc3            # reuse its DSP helpers + descriptor constants

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_merged.bin"
ELEK = ROOT / "out/elek_merged.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_KYOTI_ALL.syx"
OUT_BIN = ROOT / "out/OCTATRACK_KYOTI_ALL.bin"
# The merged image is the shipping build -- it carries its own branding, not the
# 140C_KYOTI used by the per-feature test images (reference/MERGE.md).  Boot splash
# and SYSTEM STATUS -> OS VERSION both read this.  Exactly 10 chars (ELEK field cap).
VERSTR = sys.argv[1] if len(sys.argv) > 1 else "KYOTI_V1.0"

FREE_START = 0x400d6500                   # widened below the old 0x400d7000 in S48 (QLREC added);
                                         # the whole 0x400d64da..0x400d7c3c span is zero in stock.
TRIGSCALE_AT = 0x400d7b00                 # pinned -- byte-identical to build_trigscale_only.py
FREE_END = 0x400d7c3c

# --- ColdFire stubs, in pack order.  (name, defsym, [ (site, sym, expect_hex, n, kind) ]) ---
#     addr is assigned by the packer; detours are wired after every stub has an address.
#     kind: "jmp" = replace a whole instruction (stub returns via its own jmp);
#           "jsr" = 4eb9 <stub> + nop pad, stub does work then rts to the next insn.
CF_STUBS = [
    ("patch_sidechain", None, []),                       # KEY/KFLT formatters -- no detours
    ("patch_softmute", "DT_MODE=1", [
        (0x40004dc6, "pre",   "2a3980000008",     6, "jmp"),
        (0x40005178, "pre_v", "4feffff448d7001c", 8, "jmp"),
    ]),
    ("patch_mutemode", "DT_MODE=1", []),                 # menu stub -- refs wired below
    ("patch_directjump", "DJ_V3=1", [
        # v3 overlay: FUN_4005a2b8 self-timing toast -- no 0x400522ca splice (v2), no
        # borrowed SELECT-window handle (v1), no FUN_4005a0e0/0x460d1e64 shared with
        # RELOAD's picker (v2).  reference/MERGE.md "DIRECT JUMP: use v3".
        # NOTE: 0x4005e4c8 (dj_toggle) is NOT hooked here -- RELOAD2 owns that detour and
        #       chains into dj_toggle.  Only the three sequencer hooks are installed.
        (0x400a4006, "dj_a", "4a398000667e",     6, "jsr"),
        (0x400a42fa, "dj_b", "203c00008e56",     6, "jsr"),
        (0x400a4840, "dj_c", "420013c0800065b6", 8, "jsr"),
    ]),
    ("patch_reload2", "MERGE=1", [
        (0x4005a044, "rl_ptn",  "202f00087201",     6, "jmp"),
        (0x4005e25c, "rl_no",   "202f00086714",     6, "jmp"),
        (0x4005e4c8, "rl_yes",  "222f0004202f0008", 8, "jmp"),   # the single [YES] hook
        (0x4004b970, "rl_arr_a", "4feffff448d7040c", 8, "jmp"),
        (0x400491a0, "rl_arr_b", "2f02206f0008",     6, "jmp"),
        (0x40085864, "rl_job",  "2d4afd762f2a0004", 8, "jmp"),
    ]),
    ("patch_pattern_led", None, [                        # grid-LED "has content" predicate
        (0x4009a464, "cave", "2f02202f0008", 6, "jmp"),  # FUN_4009a464 prologue -> cave
    ]),
    ("patch_qlrec", None, [                              # QUANTIZE LIVE REC front-panel toggle
        (0x40061778, "qlr_play",   "4eb94009b5c0", 6, "jmp"),   # [PLAY] press
        (0x4004883a, "qlr_recrel", "42b9460d1726", 6, "jmp"),   # [REC] release
    ]),
]

# --- MUTE MODE PERSONALIZE menu (identical recipe to build_mutemode_dt.py) ---
OLD_LBL, OLD_GET, OLD_SET, N_OLD = 0x400b2a34, 0x400b2a74, 0x400b2ac0, 16
SPLICE_AT = 2
REFS = [(0x40068efe, OLD_LBL), (0x40068f0a, OLD_GET),
        (0x40069022, OLD_SET), (0x4006903e, OLD_SET), (0x40069056, OLD_SET)]
COUNT_AT = 0x40068fb2

# --- shared 'ANDY' restore extension (MUTE MODE + DIRECT JUMP) ---
RESTORE_SITES = (0x4001f322, 0x4001f3be, 0x4001fb24)


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


def jsr(t):
    return b"\x4e\xb9" + t.to_bytes(4, "big")


def assemble(name, at, defsym):
    """assemble tools/<name>.s at load addr `at`; return (blob, {sym: addr})."""
    out = f"merged_{name}"
    aso = ["m68k-elf-as", "-mcpu=5407"]
    for d in (defsym.split(",") if defsym else []):
        aso += ["--defsym", d]
    aso += ["-o", f"out/{out}.o", f"tools/{name}.s"]
    subprocess.run(aso, check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{out}.elf", f"out/{out}.o"],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{out}.elf", f"out/{out}.bin"],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", f"out/{out}.elf"], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return (ROOT / f"out/{out}.bin").read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh && ./analyze.sh")
    for t in (sc3.DSP_ASM, sc3.DIS):
        if not pathlib.Path(t).exists():
            sys.exit(f"missing {t} -- build the DSP toolchain (scratchpad build_dsp_asm.sh)")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)

    def o(a):
        return a - BASE

    spans = []      # (lo, hi, tag)   ColdFire only
    detour_sites = {}

    # ================= 1. two-phase assemble: size, then pack, then place =================
    # Pass A assembles every stub at a throwaway address just to measure it.
    sizes = {}
    for name, defsym, _ in CF_STUBS:
        ds = defsym
        if name == "patch_reload2" and defsym and "MERGE=1" in defsym:
            ds = defsym + ",MERGE_DJ_TOGGLE=0x40000000"       # placeholder, size only
        blob, _ = assemble(name, 0x40000000, ds)
        sizes[name] = len(blob)

    addr = FREE_START
    placement = {}
    for name, _, _ in CF_STUBS:
        addr = (addr + 3) & ~3
        placement[name] = addr
        addr += sizes[name]
    if addr > TRIGSCALE_AT:
        sys.exit(f"ColdFire stubs overflow the pre-trigscale zone: 0x{addr:x} > 0x{TRIGSCALE_AT:x}")
    # The relocated PERSONALIZE arrays (pure data) go AFTER patch_trigscale --
    # patch_trigscale is 62 B (18-B detour cave, pinned) and there is 254 B free
    # from 0x400d7b3e to FREE_END.  This keeps the growing stub region (RELOAD2 in
    # particular) clear of the pin.
    TRIGSCALE_END = TRIGSCALE_AT + 62
    menu_at = (TRIGSCALE_END + 3) & ~3
    menu_end = menu_at + (N_OLD + 1) * 4 * 3
    if menu_end > FREE_END:
        sys.exit(f"PERSONALIZE menu arrays overflow the free zone: 0x{menu_end:x} > 0x{FREE_END:x}")

    print("=== ColdFire cave layout ===")
    for name, _, _ in CF_STUBS:
        a = placement[name]
        print(f"  {name:17s} 0x{a:08x} .. 0x{a + sizes[name] - 1:08x}  ({sizes[name]} B)")
    print(f"  {'patch_trigscale':17s} 0x{TRIGSCALE_AT:08x}  (pinned, 62 B)")
    print(f"  {'menu arrays x3':17s} 0x{menu_at:08x} .. 0x{menu_end - 1:08x}  ({menu_end - menu_at} B, after trigscale)")
    print(f"  free: 0x{addr:x}..0x{TRIGSCALE_AT:x} ({TRIGSCALE_AT - addr} B) + "
          f"0x{menu_end:x}..0x{FREE_END:x} ({FREE_END - menu_end} B)")

    # ================= 2. SIDE-CHAIN: ColdFire descriptor + FX choosers + CF cave =========
    print("\n=== SIDE-CHAIN: ColdFire (descriptor slots 8..11 + FX choosers) ===")
    sc_blob, sc_syms = assemble("patch_sidechain", placement["patch_sidechain"], None)
    co = o(placement["patch_sidechain"])
    if any(img[co:co + len(sc_blob)]):
        sys.exit("patch_sidechain cave not free")
    img[co:co + len(sc_blob)] = sc_blob
    spans.append((placement["patch_sidechain"], placement["patch_sidechain"] + len(sc_blob), "patch_sidechain"))

    E = sc3.E
    for slot, name, cnt, dflt, fmt, cur in sc3.SLOTS:
        na, ca, da, aa, ba = (E + 0x4e + 6 * slot, E + 0xd2 + 4 * slot, E + 0x96 + slot,
                              E + 0x102 + 4 * slot, E + 0x132 + 4 * slot)
        assert bytes(img[o(na):o(na) + 6]).hex() == cur["name"], f"slot {slot} name"
        assert f"{int.from_bytes(img[o(ca):o(ca)+4],'big'):08x}" == cur["cnt"], f"slot {slot} count"
        assert f"{img[o(da)]:02x}" == cur["dflt"], f"slot {slot} default"
        assert f"{int.from_bytes(img[o(ba):o(ba)+4],'big'):08x}" == cur["b"], f"slot {slot} B"
        assert int.from_bytes(img[o(aa):o(aa) + 4], "big") == 0, f"slot {slot} A not zero"
        img[o(na):o(na) + 6] = name
        img[o(ca):o(ca) + 4] = cnt.to_bytes(4, "big")
        img[o(da)] = dflt
        img[o(ba):o(ba) + 4] = (0).to_bytes(4, "big")
        a_val = sc_syms[fmt] if isinstance(fmt, str) else fmt
        img[o(aa):o(aa) + 4] = a_val.to_bytes(4, "big")
        print(f"  slot {slot:2d}  {name.rstrip(bytes([0])).decode():5s}  count {cnt:3d}  "
              f"default {dflt:3d}  A 0x{a_val:08x}")

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    def wr32(a, v):
        img[o(a):o(a) + 4] = v.to_bytes(4, "big")

    for base, ln, tag in ((sc3.FX1_LIST, sc3.FX1_LEN, "FX1"), (sc3.FX2_LIST, sc3.FX2_LEN, "FX2")):
        entries = [u32(base + i * 4) for i in range(ln)]
        assert u32(base + ln * 4) == 0, f"{tag} terminator"
        assert entries[sc3.SPAT_POS] == sc3.SPAT_P, f"{tag}[{sc3.SPAT_POS}] != SPATIALIZER"
        new = entries[:sc3.SPAT_POS] + entries[sc3.SPAT_POS + 1:]
        for i, v in enumerate(new):
            wr32(base + i * 4, v)
        wr32(base + len(new) * 4, 0)
        print(f"  {tag}: {ln} -> {len(new)} entries")
    wr32(sc3.ID2POS + 0x05 * 4, 0)
    for idv in range(0x20):
        pos = u32(sc3.ID2POS + idv * 4)
        if idv != 0x05 and pos > sc3.SPAT_POS:
            wr32(sc3.ID2POS + idv * 4, pos - 1)
    print("  ID2POS rebuilt (SPATIALIZER id 0x05 -> 0)")

    # ================= 3. SIDE-CHAIN: DSP (both payloads) ================================
    print("\n=== SIDE-CHAIN: DSP (SPATIALIZER donor + sctap/scdet/sctail, payloads A+B) ===")
    for tag, d in sc3.DSP.items():
        words, sctap, scdet, sctail = sc3.sc_assemble(d["kadj"], d["cave_org"])
        spat_off = sc3.dsp_module_fileoff(img, d["va"], d["ln"], d["cave_org"])
        assert sc3.rd3(img, spat_off) == 0x250000, f"payload {tag} SPATIALIZER anchor"
        for i, wv in enumerate(words):
            img[spat_off + i * 3: spat_off + i * 3 + 3] = sc3.w3(wv)

        hk = sc3.dsp_module_fileoff(img, d["va"], d["ln"], d["disp_hook"])
        assert (sc3.rd3(img, hk), sc3.rd3(img, hk + 3)) == (0x66f000, 0x000208), f"payload {tag} disp hook"
        img[hk:hk + 3] = sc3.w3(sc3.jsr_short(sctap)); img[hk + 3:hk + 6] = sc3.w3(sc3.NOP)

        cp = sc3.dsp_module_fileoff(img, d["va"], d["ln"], d["comp_proc"])
        assert (sc3.rd3(img, cp), sc3.rd3(img, cp + 3)) == (0x221e00, 0x346100), f"payload {tag} comp proc+0"
        img[cp:cp + 3] = sc3.w3(sc3.jsr_short(scdet)); img[cp + 3:cp + 6] = sc3.w3(sc3.NOP)

        ct = sc3.dsp_module_fileoff(img, d["va"], d["ln"], d["comp_tail"])
        assert (sc3.rd3(img, ct), sc3.rd3(img, ct + 3)) == (0x0a77a0, 0x00000f), f"payload {tag} comp tail"
        img[ct:ct + 3] = sc3.w3(sc3.jsr_short(sctail)); img[ct + 3:ct + 6] = sc3.w3(sc3.NOP)

        xt = sc3.dsp_xtable_fileoff(img, d["va"], d["ln"], 0x215)
        ini_off, prc_off = xt + 5 * 3, xt + (0x20 + 5) * 3
        assert sc3.rd3(img, ini_off) == d["cave_org"] and sc3.rd3(img, prc_off) == d["cave_org"] + 0xa, \
            f"payload {tag} disp entry 5"
        img[ini_off:ini_off + 3] = sc3.w3(d["stub_init"])
        img[prc_off:prc_off + 3] = sc3.w3(d["stub_proc"])
        print(f"  payload {tag}: {len(words)}/{sc3.DONOR_WORDS} donor words; "
              f"sctap=0x{sctap:x} scdet=0x{scdet:x} sctail=0x{sctail:x}; SPATIALIZER -> passthrough")

    # ================= 4. patch_trigscale (pinned) ======================================
    print("\n=== Bug-1 manual-trig fix (pinned @ 0x400d7b00) ===")
    ts_blob, ts_syms = assemble("patch_trigscale", TRIGSCALE_AT, None)
    co = o(TRIGSCALE_AT)
    if any(img[co:co + len(ts_blob)]):
        sys.exit("patch_trigscale cave not free")
    img[co:co + len(ts_blob)] = ts_blob
    spans.append((TRIGSCALE_AT, TRIGSCALE_AT + len(ts_blob), "patch_trigscale"))
    site, exp = 0x4009b6f2, bytes.fromhex("203c0000091a")
    assert bytes(img[o(site):o(site) + len(exp)]) == exp, "trigscale detour"
    img[o(site):o(site) + 18] = jmp(ts_syms["cave"]) + b"\x4e\x71" * 6
    detour_sites[site] = ("patch_trigscale", 18)
    print(f"  0x{site:08x} -> jmp 0x{ts_syms['cave']:08x} + 6x nop")

    # ================= 5. MUTE MODE / DIRECT JUMP / RELOAD2 caves + detours ==============
    print("\n=== MUTE MODE + DIRECT JUMP + RELOAD2: caves + detours ===")
    syms = {"patch_trigscale": ts_syms, "patch_sidechain": sc_syms}
    # DIRECT JUMP must be placed before RELOAD2 so dj_toggle's address is known.
    dj_toggle_addr = None
    for name, defsym, detours in CF_STUBS:
        if name == "patch_sidechain":
            continue
        ds = defsym
        if name == "patch_reload2":
            assert dj_toggle_addr is not None, "patch_directjump must precede patch_reload2"
            ds = (defsym + f",MERGE_DJ_TOGGLE=0x{dj_toggle_addr:x}") if defsym else \
                 f"MERGE_DJ_TOGGLE=0x{dj_toggle_addr:x}"
        at = placement[name]
        blob, s = assemble(name, at, ds)
        syms[name] = s
        if name == "patch_directjump":
            dj_toggle_addr = s["dj_toggle"]
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free")
        img[co:co + len(blob)] = blob
        spans.append((at, at + len(blob), name))
        print(f"  {name:17s} {len(blob):4d} B @ 0x{at:08x}"
              + (f"   [--defsym {ds}]" if ds else ""))
        for site, sym, exp_hex, n, kind in detours:
            exp = bytes.fromhex(exp_hex)
            if site in detour_sites:
                sys.exit(f"DETOUR COLLISION: 0x{site:08x} wanted by {name}:{sym} "
                         f"and {detour_sites[site][0]}")
            if bytes(img[o(site):o(site) + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} ({name}:{sym}) unexpected: "
                         f"{bytes(img[o(site):o(site)+len(exp)]).hex()} != {exp_hex}")
            branch = jsr(s[sym]) if kind == "jsr" else jmp(s[sym])
            img[o(site):o(site) + n] = branch + b"\x4e\x71" * ((n - 6) // 2)
            detour_sites[site] = (name, n)
            print(f"    0x{site:08x} -> {name}:{sym} 0x{s[sym]:08x}  ({kind}, {n} B)")

    print(f"  DIRECT JUMP dj_toggle @ 0x{dj_toggle_addr:08x}  (reached via rl_yes chain, not a detour)")

    # ================= 6. MUTE MODE PERSONALIZE menu (relocate 3 arrays) =================
    print("\n=== MUTE MODE PERSONALIZE menu ===")
    new_entry = {OLD_LBL: syms["patch_mutemode"]["lbl_mutemode"],
                 OLD_GET: syms["patch_mutemode"]["get_mutemode"],
                 OLD_SET: syms["patch_mutemode"]["set_mutemode"]}
    dst = {OLD_LBL: menu_at, OLD_GET: menu_at + (N_OLD + 1) * 4, OLD_SET: menu_at + (N_OLD + 1) * 8}
    for old in (OLD_LBL, OLD_GET, OLD_SET):
        ents = [int.from_bytes(img[o(old + i * 4):o(old + i * 4) + 4], "big") for i in range(N_OLD)]
        ents = ents[:SPLICE_AT] + [new_entry[old]] + ents[SPLICE_AT:]
        d = dst[old]
        if any(img[o(d):o(d + len(ents) * 4)]):
            sys.exit(f"menu array cave 0x{d:08x} not free")
        for i, v in enumerate(ents):
            img[o(d + i * 4):o(d + i * 4) + 4] = v.to_bytes(4, "big")
        spans.append((d, d + len(ents) * 4, f"menu@{d:08x}"))
        print(f"  array 0x{d:08x}: {len(ents)} entries (MUTE MODE @ idx {SPLICE_AT})")
    for a, old in REFS:
        if bytes(img[o(a):o(a) + 4]) != old.to_bytes(4, "big"):
            sys.exit(f"menu ref 0x{a:08x} is not 0x{old:08x}")
        img[o(a):o(a) + 4] = dst[old].to_bytes(4, "big")
    print(f"  repointed {len(REFS)} refs")
    if bytes(img[o(COUNT_AT):o(COUNT_AT) + 2]) != b"\x72\x0f":
        sys.exit(f"count 0x{COUNT_AT:08x} not moveq #15")
    img[o(COUNT_AT):o(COUNT_AT) + 2] = b"\x72\x10"
    print(f"  count 0x{COUNT_AT:08x}  moveq #15 -> #16")

    # ================= 7. shared 'ANDY' restore extension ===============================
    print("\n=== PERSONALIZE persistence (MUTE MODE + DIRECT JUMP) ===")
    for s in RESTORE_SITES:
        so = o(s)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{s:08x}: {bytes(img[so:so+4]).hex()} != 48780064")
        img[so + 3] = 0x70
        print(f"  restore 0x{s:08x}  pea 0x64 -> pea 0x70")

    # ================= 8. verification =================================================
    print("\n=== verify ===")
    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"CAVE OVERLAP: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[0][0] < FREE_START or spans[-1][1] > FREE_END:
        sys.exit("cave outside the free zone")
    print(f"  {len(spans)} ColdFire caves, disjoint, 0x{spans[0][0]:x}..0x{spans[-1][1]:x} "
          f"within 0x{FREE_START:x}..0x{FREE_END:x}")
    print(f"  {len(detour_sites)} detour sites, all distinct")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"  {OUT.name}: {changed} bytes changed vs stock")

    # trigscale must be byte-identical to the standalone fix
    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        hs = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in hs)
        print(f"  Bug-1 fix bytes identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("  BUG-1 FIX DIVERGED")

    # every non-cave, non-detour change must be one MUTE MODE / DIRECT JUMP / SIDE-CHAIN
    # already makes on its own (menu refs, count, restore pea, descriptor, choosers, DSP)
    mm = ROOT / "out/mainos_mutemode_dt.bin"
    dj = ROOT / "out/mainos_directjump.bin"
    sc = ROOT / "out/mainos_sidechain3.bin"
    pl = ROOT / "out/mainos_patternled.bin"
    ql = ROOT / "out/mainos_qlrec.bin"
    if all(p.exists() for p in (mm, dj, sc, pl, ql)):
        union = set()
        for p in (mm, dj, sc, pl, ql, ts):
            b = p.read_bytes()
            union |= {i for i in range(len(b)) if b[i] != stock[i]}
        cave = set()
        for a, bb, _ in spans:
            cave |= set(range(o(a), o(bb)))
        det = set()
        for site, (_, n) in detour_sites.items():
            det |= set(range(o(site), o(site) + n))
        # menu-array ref repoints + the count byte target relocated caves, exactly as
        # build_mutemode_dt.py lists them in its own allowed-divergence set
        for a, _ in REFS:
            det |= set(range(o(a), o(a) + 4))
        det |= set(range(o(COUNT_AT), o(COUNT_AT) + 2))
        # the COMPRESSOR descriptor's per-slot formatter pointer (E+0x102+4*slot)
        # points INTO patch_sidechain's cave -- its *value* is asserted against
        # sc_syms in section 2, but its bytes diverge from build_sidechain3.py
        # whenever the merge packs that cave at a different address (it does now
        # that FREE_START moved).  Allow the 4-byte pointer slots to differ.
        for slot, _n, _c, _d, fmt, _cur in sc3.SLOTS:
            if isinstance(fmt, str):
                det |= set(range(o(E + 0x102 + 4 * slot), o(E + 0x102 + 4 * slot) + 4))
        stray = [i for i in range(len(img)) if img[i] != stock[i] and i not in union
                 and i not in cave and i not in det]
        print(f"  changes outside {{feature diffs, relocated caves, detours}}: {len(stray)}")
        if stray:
            sys.exit(f"  UNEXPECTED CHANGES: {[hex(BASE + i) for i in stray[:12]]}")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT / stock syx missing -- skipping the wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if any(k in l for k in ("version", "emitted", "wrote", "checksum", "round-trip"))))
    if "too long" in r.stdout:
        sys.exit(f'  version "{VERSTR}" ({len(VERSTR)}) does not fit the 10-char field')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)
    print(f"\n  {OUT_SYX.name}  (MIDI DIN)  +  {OUT_BIN.name}  (CF card)")
    print(f"  OS VERSION reads: {VERSTR}")
    print("  PERSONALIZE -> MUTE MODE: OT / OT+FX / DT")
    print("  [PTN]+[YES] (quick): DIRECT JUMP toggle    |    hold [PTN]: RELOAD picker")
    print("  COMPRESSOR FX page 2: RMS (gap) KEY KFLT KGAIN MON;  SPATIALIZER passes through")
    print("  A p-lock-only pattern (MIDI locks / audio trigless locks) now lights its grid LED")
    print("  [REC] held + [PLAY] x2: toggles the global live-record quantize (QUANTIZE LIVE REC)")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")
    print("\n  NOT hardware-tested as a combined image -- flash the per-feature builds first")
    print("  (FLASHING.md), in order, then this.  See reference/MERGE.md.")


if __name__ == "__main__":
    main()
