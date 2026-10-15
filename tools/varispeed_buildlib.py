# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
The ColdFire half shared by the two builders of one source (spec §7):

    tools/build_varispeed_emus.py   VARISPEED_EMUS   varispeed_emus.s, VEM_EMUS = 1, + the DSP kernel
    tools/build_varispeed.py        VARISPEED        varispeed_emus.s, VEM_EMUS = 0, stock DSP

Not a builder (no gate): it holds the stock sites, pokes and context bytes both use, the
link of the unit, and the guarded splice -- every detour, poke and context span asserted
against stock first; nothing may branch into a displaced span; the cave zero in stock and
inside the classic cave from 0x400d6500; no reference into 0x80006a40..0x80006abf; the unit
the same bytes for -mcpu=5407 and 54455; each body jumping back behind its site. Each
builder adds its own tables (VARISPEED_EMUS: EMUS, the load guard) to CORE_*.
"""
import hashlib, os, pathlib, re, subprocess, sys

BASE = 0x40000400
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
SRC = ROOT / "octabam-modules/varispeed-emus/varispeed_emus.s"

CAVE = 0x400d6500            # the classic cave's proven start (kb/caves.md §2b)
CAVE_END = 0x400d7c3c        # its end (kb/caves.md §1)
SCRATCH = (0x80006a40, 0x80006ac0)   # never ours (CLAUDE.md)

# ---- the VARI core (both builds) -----------------------------------------------------
# detours: site -> (stock bytes, symbol, kind). kind jmp/jsr: `jmp|jsr sym` + nops.
CORE_DETOURS = {
    # the core: the render's increment store (frame ISR, second pass, ST/FL/PU)
    0x40004100: ("a1c0eca027400024", "vem_frame", "jmp"),
    # audio editor ATTR, TIMESTRETCH row: label else, up row 2, down row 2, both tails
    0x4006e71c: ("4879400b94f660000154", "attr_label", "jmp"),
    0x4006ee48: ("202801106608", "attr_up", "jmp"),
    0x4006ef7c: ("20280110b280", "attr_down", "jmp"),
    0x4006eef0: ("245f4ef94006dbdc", "attr_tail", "jmp"),
    0x4006f026: ("245f4ef94006dbdc", "attr_tail", "jmp"),
    # retained: the four SETUP-page dial resolvers
    0x40036698: ("206c00304a88660641f9400479b4", "qdial1", "jmp"),
    0x4003690c: ("206b00304a88660641f9400479b4", "qdial2", "jmp"),
    0x4003786a: ("206b00304a88660641f9400479b4", "qdial3", "jmp"),
    0x40037c06: ("206b00304a88660641f9400479b4", "qdial4", "jmp"),
    # retained: the two Part applies, RELOAD PART
    0x40009094: ("4fefff9848d77cfc", "rp_apply1", "jmp"),
    0x40009e00: ("4fefffb448d77cfc", "rp_apply2", "jmp"),
    0x4004aab4: ("4fefffe048d70c3c", "rp_reload", "jmp"),
    # O2: the bulk writers -- SRC page paste (and its undo), track paste (and its undo),
    # the PART menu's paste core (PASTE and UNDO) and CLEAR
    0x40027e4c: ("4fefffcc48d77cfc", "vh_srcpaste", "jmp"),
    0x4002b654: ("4fefffbc48d77cfc", "vh_trkpaste", "jmp"),
    0x40029a4c: ("4fefffec48d7043c", "vh_partpaste", "jmp"),
    0x4004a9d0: ("4feffff048d70c0c", "vh_partclear", "jmp"),
}
# Each body replays its site's displaced bytes and jumps back here: the splice checks the
# jump target equals site + displaced length.
CORE_RETURNS = {"vb_srcpaste": 0x40027e54, "vb_trkpaste": 0x4002b65c, "vb_partpaste": 0x40029a54,
                "vb_partclear": 0x4004a9d8, "vb_reload": 0x4004aabc}
# descriptor pokes (u32): addr -> (stock value, new value or symbol, what)
CORE_POKES = {
    0x400d30de: (4, 5, "STATIC TSTR count"),
    0x400d3270: (4, 5, "FLEX TSTR count"),
    0x400d313e: (0x40046c28, 0x40046ab4, "STATIC TSTR widget -> stock 5-position select"),
    0x400d32d0: (0x40046c28, 0x40046ab4, "FLEX TSTR widget -> stock 5-position select"),
    0x400d310e: (0x4003b6a4, "tstr_fmt", "STATIC TSTR formatter"),
    0x400d32a0: (0x4003b6a4, "tstr_fmt", "FLEX TSTR formatter"),
    0x400d3116: (0x400479b4, "quant_widget", "STATIC PTCH widget"),
    0x400d32a8: (0x400479b4, "quant_widget", "FLEX PTCH widget"),
    0x400d3146: (0x40032d08, "quant_step", "STATIC PTCH encoder step"),
    0x400d32d8: (0x40032d08, "quant_step", "FLEX PTCH encoder step"),
}
# Stock bytes the code relies on without patching them (asserted, not written):
CORE_CONTEXT = {
    # the stock 5-position select: bound `moveq #4` and its icon table operand
    0x40046b08: "7004b0856500",
    # the render around H1: the second-pass test and the voice record pointer
    0x4000406a: "082f000400436608202b002460000090",
    0x40004108: "28798000",
    # stock's 4-entry TSTR string table (OFF AUTO NORM BEAT)
    0x400a7e2e: "400b4e78400b571e400b5728400b572d",
    # rp_sync: the bank blobs (bank b at 0x400e21e0 + b * 0x9b340, UI message 21); PART_B
    # moves at UI message 20, a step before the frame applies the new Part
    0x4006229a: "203c0009b3404c0208000680400e21e0",
    0x400621e2: "13c08000000313c0100b14cf",
}
# "Branches" the word-by-word scan finds that are operand words of a real instruction,
# each checked by objdump: source -> (the instruction's address, its bytes).
FALSE_BRANCHES = {
    0x4003670e: (0x4003670a, "4eb9400a6994"),   # jsr 0x400a6994's low address word
}
SELECT5 = 0x40046ab4         # stock's 5-position select: must still be unreferenced in stock


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], cwd=ROOT, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"{cmd[0]} failed:\n{r.stdout}{r.stderr}")
    return r


def link_unit(src, work, cpu, at, tag, asdefs=(), incdir=None):
    """Assemble + link the unit at `at`. asdefs: (name, value) for `as --defsym` (the
    assembly switch); incdir: an `as -I` directory. -> (bytes, {symbol: address})."""
    work.mkdir(parents=True, exist_ok=True)
    o, e, b = (work / f"vem_{tag}.{x}" for x in ("o", "elf", "bin"))
    run("m68k-elf-as", f"-mcpu={cpu}", *[f"--defsym={n}={v}" for n, v in asdefs],
        *(["-I", incdir] if incdir else []), "-o", o, src)
    run("m68k-elf-ld", "-e", "vem_frame", f"-Ttext=0x{at:x}", "-o", e, o)
    run("m68k-elf-objcopy", "-O", "binary", e, b)
    syms = {}
    for line in run("m68k-elf-nm", e).stdout.splitlines():
        f = line.split()
        if len(f) != 3:
            sys.exit(f"unresolved symbol in {e.name}: {line}")
        syms[f[2]] = int(f[0], 16)
    return b.read_bytes(), syms


def pc_targets(img, a):
    """PC-relative targets of an instruction that might start at image offset a."""
    op = int.from_bytes(img[a:a + 2], "big")
    pc = BASE + a + 2
    out = []
    if 0x6000 <= op <= 0x6FFF:                                   # Bcc / BRA / BSR
        d8 = op & 0xFF
        if d8 == 0:
            d = int.from_bytes(img[a + 2:a + 4], "big", signed=True)
        elif d8 == 0xFF:
            d = int.from_bytes(img[a + 2:a + 6], "big", signed=True)
        else:
            d = d8 - 0x100 if d8 & 0x80 else d8
        out.append(pc + d)
    elif op in (0x4EBA, 0x4EFA, 0x487A) or (op & 0xF1FF) == 0x41FA:   # jsr/jmp/pea/lea (d16,pc)
        out.append(pc + int.from_bytes(img[a + 2:a + 4], "big", signed=True))
    return out


def branch_targets(img):
    t = {}
    for o in range(0, len(img) - 6, 2):
        for x in pc_targets(img, o):
            t.setdefault(x, []).append(BASE + o)
    return t


def build_unit(src, work, asdefs=()):
    """The unit at CAVE, checked: 5407 == 54455 bytes, vem_end, inside the classic cave,
    no scratch-block reference. -> (blob, syms, end)."""
    blob, syms = link_unit(src, work, "5407", CAVE, "5407", asdefs)
    blob2, syms2 = link_unit(src, work, "54455", CAVE, "54455", asdefs)
    if blob != blob2 or syms != syms2:
        sys.exit("the unit links to different bytes for -mcpu=5407 and 54455 -- refusing")
    end = CAVE + len(blob)
    if syms["vem_end"] != end:
        sys.exit(f"vem_end 0x{syms['vem_end']:08x} != the blob's end 0x{end:08x}")
    if not (0x400d6500 <= CAVE and end <= CAVE_END):
        sys.exit(f"cave 0x{CAVE:08x}..0x{end:08x} outside the classic cave 0x400d6500..0x{CAVE_END:08x}")
    for i in range(0, len(blob) - 3):
        v = int.from_bytes(blob[i:i + 4], "big")
        if SCRATCH[0] <= v < SCRATCH[1]:
            sys.exit(f"the unit references 0x{v:08x} (the unreliable scratch block) at +0x{i:x}")
    print(f"  {len(blob)} B @ 0x{CAVE:08x}..0x{end:08x}  ({CAVE_END - end} B of the classic cave left); "
          f"5407 == 54455 bytes")
    return blob, syms, end


def splice(img, blob, syms, detours, pokes, context, returns):
    """Assert every context span, detour site and poke against stock (img must be stock),
    then write the unit, the detours and the pokes, and check each body's jump back.
    Returns the set of image offsets written."""
    o = lambda a: a - BASE
    end = CAVE + len(blob)
    if any(img[o(CAVE):o(end)]):
        sys.exit(f"cave 0x{CAVE:08x}..0x{end:08x} is not zero in stock")
    targets = branch_targets(img)
    for at, hexb in context.items():
        want = bytes.fromhex(hexb)
        if bytes(img[o(at):o(at) + len(want)]) != want:
            sys.exit(f"context 0x{at:08x}: {bytes(img[o(at):o(at)+len(want)]).hex()} is not stock {hexb}")
    for site, (hexb, sym, kind) in detours.items():
        want = bytes.fromhex(hexb)
        if bytes(img[o(site):o(site) + len(want)]) != want:
            sys.exit(f"detour 0x{site:08x}: {bytes(img[o(site):o(site)+len(want)]).hex()} is not stock {hexb}")
        inside = []
        for t in targets:
            if site < t < site + len(want):
                for src in targets[t]:
                    fp = FALSE_BRANCHES.get(src)
                    if fp and bytes(img[o(fp[0]):o(fp[0]) + len(fp[1]) // 2]).hex() == fp[1] \
                            and fp[0] < src < fp[0] + len(fp[1]) // 2:
                        continue
                    inside.append(t)
        if inside:
            sys.exit(f"REFUSING detour at 0x{site:08x}: {[hex(x) for x in targets[inside[0]]]} branch "
                     f"to 0x{inside[0]:08x}, inside the {len(want)} displaced bytes")
        if sym not in syms:
            sys.exit(f"detour 0x{site:08x}: no symbol {sym}")
    for at, (old, new, what) in pokes.items():
        cur = int.from_bytes(img[o(at):o(at) + 4], "big")
        if cur != old:
            sys.exit(f"poke 0x{at:08x} ({what}): 0x{cur:08x} is not stock 0x{old:08x}")
    # the 5-position select must still be unreferenced in stock (we point TSTR at it)
    for i in range(0, len(img) - 3):
        if int.from_bytes(img[i:i + 4], "big") == SELECT5:
            sys.exit(f"0x{SELECT5:08x} is referenced in stock at 0x{BASE + i:08x}")
    if SELECT5 in targets:
        sys.exit(f"0x{SELECT5:08x} is a PC-relative target in stock")

    written = set(range(o(CAVE), o(end)))
    img[o(CAVE):o(end)] = blob
    for site, (hexb, sym, kind) in detours.items():
        n = len(bytes.fromhex(hexb))
        br = (b"\x4e\xb9" if kind == "jsr" else b"\x4e\xf9") + syms[sym].to_bytes(4, "big")
        img[o(site):o(site) + n] = br + b"\x4e\x71" * ((n - 6) // 2)
        written.update(range(o(site), o(site) + n))
    for at, (old, new, what) in pokes.items():
        v = syms[new] if isinstance(new, str) else new
        img[o(at):o(at) + 4] = v.to_bytes(4, "big")
        written.update(range(o(at), o(at) + 4))
    # every body jumps back right behind the bytes its site displaced
    for sym, back in returns.items():
        a = syms[sym]
        # lea -N(sp),sp (4) ; movem.l regs,(sp) (4) ; jmp abs.l (6)
        if img[o(a) + 8:o(a) + 10] != b"\x4e\xf9" or \
                int.from_bytes(img[o(a) + 10:o(a) + 14], "big") != back:
            sys.exit(f"{sym} does not jump back to 0x{back:08x}")
    print(f"  {len(detours)} detours, {len(pokes)} descriptor pokes")
    for site, (hexb, sym, kind) in detours.items():
        print(f"    0x{site:08x} {kind} {sym} 0x{syms[sym]:08x}  ({len(hexb) // 2} B displaced)")
    for at, (old, new, what) in pokes.items():
        v = syms[new] if isinstance(new, str) else new
        print(f"    0x{at:08x} 0x{old:08x} -> 0x{v:08x}  {what}")
    return written


def check_manifest_reference(manifest, blob):
    """The octabam module's `reference` must be this unit (refused otherwise)."""
    man = manifest.read_text()
    m = re.search(r'reference=\(0x([0-9a-f]+),\s*"([0-9a-f]{64})"\)', man)
    sha = hashlib.sha256(blob).hexdigest()
    rel = manifest.relative_to(ROOT)
    if not m or (int(m.group(1), 16), m.group(2)) != (CAVE, sha):
        sys.exit(f"{rel}: reference is {m.groups() if m else 'missing'}, the unit is 0x{CAVE:08x} "
                 f"{sha} -- update it")
    print(f"  = {rel} reference")


def wrap(out, elek, out_syx, out_bin, verstr):
    """EFT wrap (.syx), make_bin (CF .bin), round-trip re-parse; prints the four sha256."""
    if not EFT.exists() or not STOCK_SYX.exists():
        print("\n  (EFT tool or stock syx missing -- skipping the .syx/.bin wrap)")
        return
    if len(verstr) > 10:
        sys.exit(f'version string "{verstr}" does not fit the 10-char field')
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(elek))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(out), "-V", verstr,
                        "-o", str(out_syx)], capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode != 0 or "too long" in r.stdout:
        sys.exit(f"EFT wrap failed:\n{r.stdout}\n{r.stderr}")
    run("python3", "tools/make_bin.py", elek, "-o", out_bin)
    chk = subprocess.run([str(EFT), str(out_syx)], capture_output=True, text=True, cwd=ROOT)
    if chk.returncode != 0:
        sys.exit("round-trip: the .syx container does not re-parse")
    print("  round-trip: container re-parses OK")
    for f in (out, out_syx, out_bin, elek):
        print(f"  {f.relative_to(ROOT)}  sha256 {hashlib.sha256(f.read_bytes()).hexdigest()}")
    print(f"  OS VERSION reads {verstr}")
