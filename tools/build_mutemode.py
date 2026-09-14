#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
TEST BUILD -- stock 1.40C + the MIDI manual-trig fix + SOFT MUTE, this time with a
PERSONALIZE toggle instead of ALWAYS_ON.

  1. patch_trigscale  -- MIDI manual-trig stall fix.  Byte-identical detour + cave to
                         build_trigscale_only.py / build_softmute.py.
  2. patch_softmute   -- SOFT MUTE (V6) hooks, assembled *gated* (no ALWAYS_ON): both hooks
                         run only when MUTE MODE == 1 ("OT+FX").  MUTE MODE == 0 ("OT") ->
                         the hooks fall straight through to the stock instant post-FX cut.
  3. patch_mutemode   -- the "MUTE MODE" PERSONALIZE entry (multi-value: OT / OT+FX), a
                         getter/setter pair modeled on the stock LED BRIGHTNESS item.

  PERSONALIZE menu surgery (the proven build.py technique): the three parallel 16-entry
  arrays (labels 0x400b2a34, getters 0x400b2a74, setters 0x400b2ac0) are contiguous and
  followed by unrelated data, so they are copied into the free code cave with ONE extra
  entry spliced in at index 2 -- right after "PREVIEW WITHOUT FX":

     [0] QUANTIZE LIVE REC
     [1] PREVIEW WITHOUT FX
     [2] MUTE MODE            <-- new
     [3] MUTE FOCUSES TRK
     ...
     [16] LED BRIGHTNESS      <-- stays last, stays behind the 0x46c8d18c (MKII) gate

  The five array references are repointed from the linker symbol table (never hardcoded),
  and the item count `moveq #15` @0x40068fb2 -> `moveq #16`, which adds exactly one visible
  item on both an MKI (0x46c8d18c==0: 15 -> 16 items, LED BRIGHTNESS still hidden) and an
  MKII (!=0: 16 -> 17).  Nothing in the firmware keys off an absolute PERSONALIZE index
  (every ref to the menu's cursor/scroll/count globals lives in the 0x40068e00..0x40069074
  block), so the splice position is free.

  MUTE MODE lives in the free PERSONALIZE word 0x800000dc (== patch_softmute's GATE).
  Default 0 -> a freshly flashed unit is stock.  An OS upgrade resets PERSONALIZE.

  PERSISTENCE.  0x800000xx is volatile DSP shared RAM (boot re-images it from ROM); the
  durable store is the checksummed 'ANDY' battery-SRAM block at 0x100fff00, restored to
  0x80000070 with memcpy length 0x64 -- one byte short of 0x800000dc.  This build extends
  that length 0x64 -> 0x70 at all three restore sites (0x4001f322 boot / 0x4001f3be
  validate / 0x4001fb24 defaults); set_mutemode writes the shadow at 0x100fff6c and the
  PERSONALIZE key handler re-checksums (jmp 0x4001f23c @ 0x40069074).  From octamax
  c78ff70 (HW-confirmed there).

Usage:   python3 tools/build_mutemode.py [VERSTR]         (default VERSTR = "140C_KYOTI")
Outputs: out/mainos_mutemode.bin, out/elek_mutemode.bin,
         out/OCTATRACK_OS1.40C_MUTEMODE.syx, out/OCTATRACK_MUTEMODE.bin
"""
import os, pathlib, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
OUT = ROOT / "out/mainos_mutemode.bin"
ELEK = ROOT / "out/elek_mutemode.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_MUTEMODE.syx"
OUT_BIN = ROOT / "out/OCTATRACK_MUTEMODE.bin"

VERSTR = sys.argv[1] if len(sys.argv) > 1 else "140C_KYOTI"   # always this brand for KYOTI builds

# --- code stubs: (source, load addr, defsym, [(detour site, symbol, expected bytes, len)]) ---
PATCHES = [
    ("patch_trigscale", 0x400d7b00, None,
     [(0x4009b6f2, "cave", "203c0000091a", 18)]),
    ("patch_softmute", 0x400d7400, None,                    # NB: no ALWAYS_ON -> gated
     [(0x40004dc6, "pre",       "2a3980000008", 6),
      (0x40006844, "mt_trig",   "40c246fc2700", 6),
      (0x4000f4dc, "mt_rebind", "254d0004254c0008", 8)]),
    ("patch_mutemode", 0x400d7600, None, []),               # menu stub, spliced in below
    #  ^ gated patch_softmute V7 is ~330 B @0x400d7400 (ends ~0x400d7542); mutemode clears it

]

# --- PERSONALIZE menu arrays (stock) ---
OLD_LBL, OLD_GET, OLD_SET, N_OLD = 0x400b2a34, 0x400b2a74, 0x400b2ac0, 16
SPLICE_AT = 2                                               # after "PREVIEW WITHOUT FX"
# relocated copies (17 entries * 4 = 68 B; 0x60-byte slots), inside the free cave
LBL_AT, GET_AT, SET_AT = 0x400d7700, 0x400d7760, 0x400d77c0
# ref -> (old base, tag).  The label base is an *immediate* into D5, the rest are lea.
REFS = [(0x40068efe, OLD_LBL, "labels  move.l #imm,D5"),
        (0x40068f0a, OLD_GET, "getters lea"),
        (0x40069022, OLD_SET, "setters lea #1"),
        (0x4006903e, OLD_SET, "setters lea #2"),
        (0x40069056, OLD_SET, "setters lea #3")]
COUNT_AT = 0x40068fb2                                       # moveq #15 -> #16


def jmp(t):
    return b"\x4e\xf9" + t.to_bytes(4, "big")


def assemble(name, at, defsym):
    aso = ["m68k-elf-as", "-mcpu=5407"]
    for d in (defsym.split(",") if defsym else []):
        aso += ["--defsym", d]
    aso += ["-o", f"out/{name}.o", f"tools/{name}.s"]
    subprocess.run(aso, check=True, cwd=ROOT)
    subprocess.run(["m68k-elf-ld", f"-Ttext=0x{at:x}", "-o", f"out/{name}.elf", f"out/{name}.o"],
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["m68k-elf-objcopy", "-O", "binary", f"out/{name}.elf", f"out/{name}.bin"],
                   check=True, cwd=ROOT)
    nm = subprocess.run(["m68k-elf-nm", f"out/{name}.elf"], capture_output=True, text=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return (ROOT / f"out/{name}.bin").read_bytes(), syms


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT} -- run ./fetch-os.sh and ./analyze.sh first")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)

    def o(a):
        return a - BASE

    blobs, syms = {}, {}
    spans = []
    print("=== assemble + detour ===")
    for name, at, defsym, detours in PATCHES:
        blob, s = assemble(name, at, defsym)
        blobs[name], syms[name] = blob, s
        co = o(at)
        if any(img[co:co + len(blob)]):
            sys.exit(f"cave 0x{at:08x} ({name}) not free: {bytes(img[co:co+16]).hex()}")
        spans.append((at, at + len(blob), name))
        img[co:co + len(blob)] = blob
        print(f"  {name:16s} {len(blob):3d} B @ 0x{at:08x} .. 0x{at+len(blob)-1:08x}")
        for site, sym, exp, n in detours:
            exp = bytes.fromhex(exp)
            do = o(site)
            if bytes(img[do:do + len(exp)]) != exp:
                sys.exit(f"detour 0x{site:08x} ({name}:{sym}) unexpected: "
                         f"{bytes(img[do:do+len(exp)]).hex()} != {exp.hex()}")
            img[do:do + n] = jmp(s[sym]) + b"\x4e\x71" * ((n - 6) // 2)
            print(f"    0x{site:08x} -> {name}:{sym} 0x{s[sym]:08x}  ({n} B)")

    # --- PERSONALIZE menu: relocate the 3 arrays with MUTE MODE spliced at SPLICE_AT ---
    print("\n=== PERSONALIZE menu ===")
    new_entry = {OLD_LBL: syms["patch_mutemode"]["lbl_mutemode"],
                 OLD_GET: syms["patch_mutemode"]["get_mutemode"],
                 OLD_SET: syms["patch_mutemode"]["set_mutemode"]}
    dst = {OLD_LBL: LBL_AT, OLD_GET: GET_AT, OLD_SET: SET_AT}
    for old in (OLD_LBL, OLD_GET, OLD_SET):
        ents = [int.from_bytes(img[o(old + i * 4):o(old + i * 4) + 4], "big") for i in range(N_OLD)]
        ents = ents[:SPLICE_AT] + [new_entry[old]] + ents[SPLICE_AT:]      # 17 entries
        d = dst[old]
        spans.append((d, d + len(ents) * 4, f"menu@{d:08x}"))
        if any(img[o(d):o(d + len(ents) * 4)]):
            sys.exit(f"menu array cave 0x{d:08x} not free")
        for i, v in enumerate(ents):
            img[o(d + i * 4):o(d + i * 4) + 4] = v.to_bytes(4, "big")
        print(f"  array 0x{d:08x}: {len(ents)} entries (16 stock + MUTE MODE @ idx {SPLICE_AT})")

    for a, old, tag in REFS:
        if bytes(img[o(a):o(a) + 4]) != old.to_bytes(4, "big"):
            sys.exit(f"ref 0x{a:08x} ({tag}) is not 0x{old:08x}: {bytes(img[o(a):o(a)+4]).hex()}")
        img[o(a):o(a) + 4] = dst[old].to_bytes(4, "big")
        print(f"  repoint 0x{a:08x}  {tag}: -> 0x{dst[old]:08x}")

    if bytes(img[o(COUNT_AT):o(COUNT_AT) + 2]) != b"\x72\x0f":
        sys.exit(f"count 0x{COUNT_AT:08x} is not moveq #15: {bytes(img[o(COUNT_AT):o(COUNT_AT)+2]).hex()}")
    img[o(COUNT_AT):o(COUNT_AT) + 2] = b"\x72\x10"
    print(f"  count   0x{COUNT_AT:08x}  moveq #15 -> #16")

    # --- PERSONALIZE persistence: 0x800000xx is volatile DSP shared RAM.  The durable
    #     store is the checksummed 'ANDY' battery-SRAM block at 0x100fff00, restored to
    #     0x80000070 via memcpy(dst, 0x100fff00, 0x64) at three sites -- and 0x64 ends at
    #     0x800000d3, one short of MUTE MODE (0x800000dc).  Extend each to 0x70 so
    #     0x800000d4..df ride the restore; set_mutemode writes shadow 0x100fff6c and the
    #     key handler re-checksums (jmp 0x4001f23c @ 0x40069074).  octamax c78ff70.
    #     Each site: `pea 0x64 (48780064)` `pea 0x100fff00` `pea 0x80000070` `jsr/lea memcpy`.
    for site in (0x4001f322, 0x4001f3be, 0x4001fb24):
        so = o(site)
        if bytes(img[so:so + 4]) != b"\x48\x78\x00\x64":
            sys.exit(f"restore-length pea 0x{site:08x}: {bytes(img[so:so+4]).hex()} != 48780064")
        img[so + 3] = 0x70
        print(f"  restore 0x{site:08x}  pea 0x64 -> pea 0x70")

    # --- no cave span may overlap another, nor run past the free zone ---
    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if b1 > a2:
            sys.exit(f"cave overlap: {n1} 0x{a1:x}..0x{b1:x} / {n2} 0x{a2:x}..0x{b2:x}")
    if spans[-1][1] > 0x400d7c3c:
        sys.exit(f"cave runs past the free zone end (0x{spans[-1][1]:x} > 0x400d7c3c)")
    print("  no overlaps; all within the free cave")

    OUT.write_bytes(bytes(img))
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    # --- the manual-trig fix must stay byte-identical to build_trigscale_only.py ---
    ts = ROOT / "out/mainos_trigscale_only.bin"
    if ts.exists():
        tsb = ts.read_bytes()
        tsh = [i for i, (x, y) in enumerate(zip(stock, tsb)) if x != y]
        ok = all(img[i] == tsb[i] for i in tsh)
        print(f"  manual-trig fix bytes identical to build_trigscale_only.py: {ok}")
        if not ok:
            sys.exit("  MANUAL-TRIG FIX DIVERGED")

    # --- wrap: ELEK container (with version) -> .syx -> .bin ---
    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT),
                        "-V", VERSTR, "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if "version" in l or "emitted" in l or "wrote" in l))
    if "too long" in r.stdout:
        sys.exit(f'  version string "{VERSTR}" ({len(VERSTR)}) does not fit the 10-char field')
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)

    print(f"\n  {OUT_SYX.name}  (MIDI DIN)  +  {OUT_BIN.name}  (CF card)")
    print(f"  version screen / SYSTEM STATUS -> OS VERSION will read:  {VERSTR}")
    print("  PERSONALIZE -> MUTE MODE:  OT (stock)  |  OT+FX (soft mute).  Default OT.")
    print("  Revert = flash downloads/extracted/OCTATRACK_OS1.40C.syx")


if __name__ == "__main__":
    main()
