#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
BLACKPYRAMIDS_303: a TB-303 voice as a track machine (shown as BLKPYRAMD), adapted from Open303's algorithm for the
DSP56300 and recalibrated on the TB-303's own circuit (2026-10-21). The voice's constants and tables come from
tools/ot303/body/gen_body.py (tools/ot303/cf/body_tables.h, body_dsp.json); what is Open303's and what is new:
reference/BLACKPYRAMIDS_303.md. The design, the voicing decisions and the resources: reference/BLACKPYRAMIDS_303.md; the
development record (MT1-MT17, the listening rounds, the hardware diagnostics):
reference/handoffs/OT303_SCOPE.md.

The machine is the sixth row of a track's machine chooser and of SRC SETUP, on any track, one per DSP
core (T1-4, T5-8). The track is stored as FLEX plus a signature in unused NEIGHBOR page bytes, so a
stock OS loads the project as a FLEX track (FLEX's own values are kept in NEIGHBOR's unused bytes and
put back when the track leaves the machine; the machine's own knobs are kept there while the track
is another machine, MT35). Its FLEX renderer sends the DSP a control record (the
signature, the note, the knobs compiled into the engine's words, a chunk of the voice's tables)
instead of sample data; the voice runs at the per-track source seam, upstream of stock AMP, FX1 and
FX2. Registration follows octabam's ANALOG BD (repeat98, MIT).

Stock 1.40C plus exactly this:
  * DSP, both payloads: tools/ot303/host.asm + the engine over SPRING REV's P words (DARK REV's
    helper moved to the module's end, callers retargeted), SPRING's X records, the source seam
    (A P:$39c / B P:$1a2) -> jsr the host; SPRING's dispatch -> the passthrough stub.
  * ColdFire: SPRING REV out of the FX choosers; tools/ot303/cf/{machine.s,control.c} as a DRAM runtime
    (the arena's bottom 16 pages; base literal at 24 sites + 4 geometry words; the boot site's jsr ->
    the appended loader); 45 detours (ANALOG BD's seams, the glyph, the step handler's entry and its
    note write, the machine window's focus, the SETUP preview's value read, three SLIC reads; since
    2026-11-17 TRACK PASTE's wrapper and the UI loop's tail: one BLKPYRAMD per DSP core on every path,
    control.c), 7 pokes and the FLEX renderer slot, each asserted against stock.

Usage:   python3 tools/build_blackpyramids_303.py      (WIP: KYOTI_ALLOW_WIP=1)
Outputs: out/mainos_blackpyramids_303.bin, out/OCTATRACK_OS1.40C_BLACKPYRAMIDS_303.syx,
         out/OCTATRACK_BLACKPYRAMIDS_303.bin (CF card: PROJECT > OS UPGRADE)
"""
import json, os, pathlib, subprocess, sys
from kyoti_status import gate, seal

gate(__file__)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "ot303"))
import dsp_patch
import dram
import hwprobe_image
import kyoti_place                   # combined-image placement (build_kyoti.py); no-op standalone

# KYOTI V1.8BC (tools/build_kyoti.py --clyps-bp) places this machine beside SIDECHAIN_COMPRESSOR; every
# value below is the standalone one when KYOTI_PLACE is unset, and the image is then byte-identical.
#   bp_dsp_org_A/B   the DSP code's first P word, inside SPRING REV's module (default: SPRING's init);
#                    DARK REV's helper still goes to the module's last 35 words
#   bp_donor_ids     the effects given up (default SPRING REV, 0x15; the combined image adds PLATE REV, 0x14)
#   bp_runtime       the runtime's link address (default: this build's own reserve, dram.RESERVE)
#   bp_runtime_dram  True: the runtime is one unit of the combined image's DRAM payload (tools/dram/, linked
#                    at bp_runtime, carried by that image's loader): no reserve, boot poke or loader here
DSP_ORGS = {t: kyoti_place.at(f"bp_dsp_org_{t}", None) for t in ("A", "B")}
DONOR_IDS = list(kyoti_place.at("bp_donor_ids", [0x15]))
RT_AT = kyoti_place.at("bp_runtime", dram.RESERVE)
RT_IN_KYOTI = bool(kyoti_place.at("bp_runtime_dram", False))
#   bp_mm_keymask    MUTE_MODES' KEYMASK byte in the combined image: the renderer then drops a silenced track's
#                    notes as MUTE_MODES drops its trigs (control.c KYOTI_MM_GATE); unset = none of it is compiled
MM_KEYMASK = kyoti_place.at("bp_mm_keymask", None)
# PLATE REV (id 0x14): its dispatch entries per payload (X:$215 / X:$235, read off our image) and its
# descriptor pointer as the FX tables store it (E 0x400d5594 + 0x38)
PLATE = dict(fx_id=0x14, p=0x400d5594 + 0x38, A=(0x01000, 0x01055), B=(0x00dc0, 0x00e15))

BASE = 0x40000400
ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SECT = ROOT / "out/raw/section_3_MAIN_OS.bin"
STOCK_SYX = ROOT / "downloads/extracted/OCTATRACK_OS1.40C.syx"
EFT = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"
CF = ROOT / "tools/ot303/cf"
WORK = ROOT / "out/ot303/cf"
OUT = ROOT / "out/mainos_blackpyramids_303.bin"
ELEK = ROOT / "out/elek_blackpyramids_303.bin"
OUT_SYX = ROOT / "out/OCTATRACK_OS1.40C_BLACKPYRAMIDS_303.syx"
OUT_BIN = ROOT / "out/OCTATRACK_BLACKPYRAMIDS_303.bin"
VERSTR = "140C_BP303"      # the field takes 10 characters

# MT4: no ROM cave. The ColdFire code is a DRAM runtime (tools/ot303/dram.py): linked at its arena
# reserve, appended after the OS image behind tools/ot303/cf/loader.S, copied in at boot.
LIBGCC = None
CFLAGS = ["-mcpu=5407", "-msoft-float", "-O2", "-ffreestanding", "-fno-builtin", "-fno-common", "-fno-jump-tables",
          "-fno-asynchronous-unwind-tables", "-fno-ident", "-fomit-frame-pointer", "-fno-zero-initialized-in-bss",
          "-Wall", "-Wextra", "-Werror"]
H = bytes.fromhex
# ANALOG BD's seams (octabam modules/analog-bassdrum/manifest.py), each re-read against our image:
# (site, stock bytes, symbol, kind, bytes written)
DETOURS = (
    (0x400334D8, H("2f02222f0008"), "ot_machine_name", "jmp", 6),          # chooser row 5's name
    (0x4003C928, H("4bf9400a78c8"), "ot_src_names", "lea", 6),             # SRC SETUP's six names
    (0x4003D718, H("41f9400a78c8"), "ot_name_a", "jmp", 6),                # main page name lookup
    (0x4004C36A, H("41f9400a78c8"), "ot_name_b", "jmp", 6),                # the second one
    (0x4003C980, H("71104fef0018"), "ot_setup_row", "jmp", 6),             # SRC SETUP row highlight
    (0x400786C8, H("7110b480662e"), "ot_chooser_row", "jmp", 6),           # chooser row highlight
    (0x400585DC, H("161079034879400bb704"), "ot_setup_open", "jmp", 10),   # SRC SETUP opens on row 5
    (0x4005221E, H("4ebaff1c4eb94007e940"), "ot_tick_hook", "jmp", 10),    # publish the page
    (0x40078886, H("71102f004879460e7386"), "ot_chooser_open", "jmp", 10),  # chooser opens on row 5
    (0x40031E74, H("710541f9400d5f386050"), "ot_resolve_pb", "jmp", 10),   # the track's page
    (0x4007981C, H("77101084d081"), "ot_main_commit", "jmp", 6),           # chooser commit
    (0x4005A616, H("2239460d5c30"), "ot_src_commit", "jmp", 6),            # SRC SETUP commit
    (0x4005A850, H("2239460d5c30"), "ot_src_commit2", "jmp", 6),           # its second path
    (0x4003A52E, H("2002e788d4829082"), "ot_setup_edit6", "jmp", 8),       # SETUP edits row 5 as FLEX
    (0x4003CD98, H("2e06e78fdc869e86"), "ot_setup_draw6", "jmp", 8),       # SETUP draws it so
    (0x40002318, H("4fefffa048d77cfc"), "ot_validate", "jmp", 8),          # the Part validator
    (0x4003D552, H("4eb940031d18"), "ot_slot_rec", "jsr", 6),             # MT2: the label builder's sample
    (0x4004C1C0, H("4eb940031d18"), "ot_slot_rec_ui", "jsr", 6),          # MT2: the track box's sample name
    (0x4004012C, H("486a00012f034879400bf10a2f36cce8"), "ot_glyph", "jmp", 16),  # MT3: side glyph 3
    (0x4009D1E8, H("4fefff9848d77cfc"), "ot_step_hook", "jmp", 8),         # MT5: the step handler's entry
    (0x400788C4, H("71907401b480"), "ot_chooser_level", "jmp", 6),         # MT6: double-tap opens the machine list
    (0x4009D422, H("41f946c7a810741d21827c00"), "ot_note_hook", "jmp", 12),  # MT6: a note the step handler schedules
    (0x4003CE02, H("207946c82456d1ced1c3d1c7d1fc0008ef5a1c10"), "ot_setup_value_hook", "jmp", 20),  # MT7: SETUP preview values
    (0x4003B33C, H("d3fc0008ef5b1011"), "ot_slic_a", "jmp", 8),           # MT8: LEN's label reads the machine's SLIC
    (0x40044DBE, H("d1fc0008ef5b4a10"), "ot_slic_b", "jmp", 8),           # MT8: a slice check reads it
    (0x4004FEE2, H("d1fc0008ef5b1c10"), "ot_slic_c", "jmp", 8),           # MT8: another slice check
    (0x4003BFF0, H("711041f9400d5f38605a"), "ot_pmtr_pb", "jmp", 10),     # MT13: the LFO PMTR names
    (0x40005030, H("4fefffe848d7047c"), "ot_live_req_hook", "jmp", 8),    # MT18: live notes: the voice request
    (0x4000E746, H("721d2b812c00"), "ot_live_midi_hook", "jmp", 6),       # MT18: a MIDI chromatic note
    (0x4004FC84, H("2002eb8841f946c7dfda320a11810800"), "ot_live_chrom_hook", "jmp", 16),  # MT18: a chromatic key
    (0x4000B4F6, H("183980001828" "1f440076"), "ot_live_rel_hook", "jmp", 10),  # MT18: a live release
    (0x4009D4A8, H("743d21827c00"), "ot_oneshot_hook", "jmp", 6),         # MT18: a one-shot trig
    (0x4004FD0C, H("2f3946c7e9562f002f0a42a72f024eb940042158"), "ot_rec_chrom_hook", "jmp", 20),  # MT19: a chromatic key recorded
    (0x40062604, H("712a0002204041f00c004868fe9c"), "ot_rec_midi_hook", "jmp", 14),  # MT19: a MIDI note recorded
    (0x400047F0, H("2f02222f0014"), "ot_idle_hook", "jmp", 6),             # MT22: an idle track feeds the DSP's tables
    (0x40044006, H("2039460d16f0"), "ot_led_hook", "jmp", 6),              # MT23: SLOTS / SLICES LEDs dark
    (0x4004F8DC, H("4feffff448d7001c"), "ot_slices_hook", "jmp", 8),      # MT23: SLICES keys inert
    (0x4004FA54, H("2f032f02242f000c"), "ot_slots_hook", "jmp", 8),       # MT23: SLOTS keys inert
    (0x40045918, H("7401b5b9460d16fc"), "ot_oct_hook", "jmp", 8),         # MT23: CHROMATIC octaves 0..3
    (0x40050254, H("2039460d16fc"), "ot_chrom_key_hook", "jmp", 6),       # MT23: other tracks keep 0 / 1
    (0x4004FBA8, H("7218b28a650001ba6d0001b6"), "ot_chrom_limit_hook", "jmp", 12),  # MT23: idx up to 52
    (0x40044968, H("7201b2b9460d16fc6616"), "ot_chrom_img_hook", "jmp", 10),  # MT23: the full keyboard image
    (0x4004FDE4, H("4ab9460d16fc660001aa"), "ot_page_key_hook", "jmp", 10),  # the PAGE key: a 17th note on every octave
    (0x40050CE2, H("72ffb280660000a6"), "ot_plock_hook", "jmp", 8),     # MT31: held trigs' PTCH locks
    # one BLKPYRAMD per DSP core on every path (2026-11-17): TRACK PASTE refused, the UI task's net
    (0x4002B988, H("7004b0b9460d0ffa"), "ot_paste_hook", "jmp", 8),      # the TRACK PASTE wrapper's entry
    (0x40062D1C, H("4ab946c7c72c"), "bp_uitail", "jsr", 6),             # the UI loop's tail (V1.8BC: Clyps' site, SUPERSEDE)
    # SRC page copy / paste keeps the machine (2026-11-18, B3): VARISPEED owns the paste itself (0x40027e4c)
    (0x40026314, H("4fefffe848d70c3c"), "ot_pgcopy_hook", "jmp", 8),     # the page copy (clipboard or undo buffer)
    (0x40028FC4, H("2f2f00102f2f0010"), "ot_pgpaste_hook", "jmp", 8),    # the page paste from the clipboard
    (0x40028F94, H("4879460bf218"), "ot_pgundo_hook", "jsr", 6),         # the page UNDO's buffer push
)
POKES = (
    (0x40079248, H("48780005"), H("48780006"), "machine chooser has six rows, OT-303 the last"),
    (0x400585FA, H("48780005"), H("48780006"), "SRC SETUP selector has six rows"),
    (0x400585FE, H("48780005"), H("48780006"), "MT6: SRC SETUP shows all six rows"),
    (0x4003C950, H("7204"), H("7205"), "SRC SETUP name lookup admits row 5"),
    (0x40078678, H("7004"), H("7005"), "machine chooser draws row 5"),
    (0x400786CE, H("7004"), H("7005"), "machine chooser highlights row 5"),
    (0x40079904, H("7604"), H("7605"), "machine chooser persists row 5"),
)
FLEX_SLOT, FLEX_RENDER = 0x400D6438, 0x40004008     # the source-supplier table's FLEX entry


def run(*cmd):
    r = subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{cmd[0]} failed:\n{r.stdout}{r.stderr}")
    return r


def build_cf():
    """-> (blob, {symbol: address}, sizes): the runtime linked at the reserve, .text .rodata .data back
    to back, no .bss (the loader copies the image; nothing zeroes a .bss); libgcc for the ColdFire"""
    WORK.mkdir(parents=True, exist_ok=True)
    libgcc = run("m68k-elf-gcc", "-mcpu=5407", "-print-libgcc-file-name").stdout.strip()
    assert "m5407" in libgcc, f"not the ColdFire multilib: {libgcc}"
    import hwprobe_image
    hwprobe_image.write_ytab(WORK / "ytab.c")
    objs = []
    for src in (CF / "control.c", CF / "record.c", CF / "params.c", WORK / "ytab.c"):
        objs.append(str(WORK / (src.stem + ".o")))
        mm = [] if MM_KEYMASK is None else ["-DKYOTI_MM_GATE=1", f"-DKYOTI_MM_KEYMASK=0x{MM_KEYMASK:x}u"]
        run("m68k-elf-gcc", *CFLAGS, *mm, f"-I{CF}", "-c", str(src), "-o", objs[-1])
    run("m68k-elf-as", "-mcpu=5407", "-o", str(WORK / "machine.o"), str(CF / "machine.s"))
    (WORK / "runtime.ld").write_text(f"""SECTIONS {{
  . = 0x{RT_AT:x};
  .text : {{ *(.text) *(.text.*) }}
  .rodata : {{ *(.rodata) *(.rodata.*) }}
  .data : ALIGN(4) {{ *(.data) *(.data.*) }}
  .bss : {{ *(.bss) *(COMMON) }}
  /DISCARD/ : {{ *(.comment) *(.note*) }}
}}
""")
    elf = WORK / "ot303_runtime.elf"
    run("m68k-elf-ld", "-T", str(WORK / "runtime.ld"), "-o", str(elf), str(WORK / "machine.o"), *objs, libgcc)
    sizes = {}
    for line in run("m68k-elf-objdump", "-h", str(elf)).stdout.splitlines():
        f = line.split()
        if len(f) >= 4 and f[1].startswith("."):
            sizes[f[1]] = (int(f[2], 16), int(f[3], 16))
    if sizes.get(".bss", (0, 0))[0]:
        sys.exit(f"the runtime has .bss ({sizes['.bss'][0]} B): the loader would not zero it")
    run("m68k-elf-objcopy", "-O", "binary", "-j", ".text", "-j", ".rodata", "-j", ".data", str(elf), str(WORK / "ot303_runtime.bin"))
    blob = (WORK / "ot303_runtime.bin").read_bytes()
    syms = {}
    for line in run("m68k-elf-nm", str(elf)).stdout.splitlines():
        f = line.split()
        if len(f) == 3 and f[1] in "TtDdRr":
            syms[f[2]] = int(f[0], 16)
    und = [l for l in run("m68k-elf-nm", "-u", str(elf)).stdout.splitlines() if l.strip()]
    if und:
        sys.exit(f"undefined symbols in the runtime: {und}")
    return blob, syms, sizes


def build_loader(blob):
    """-> the appended bytes: the loader at dram.IMAGE_END, the runtime behind it"""
    o, e = WORK / "loader.o", WORK / "loader.elf"
    run("m68k-elf-as", "-mcpu=5407", f"-I{WORK}", f"--defsym=DST=0x{dram.RESERVE | dram.UNCACHED:x}",
        f"--defsym=LEN={len(blob)}", f"--defsym=HASH=0x{dram.x33(blob):x}", "-o", str(o), str(CF / "loader.S"))
    run("m68k-elf-ld", f"-Ttext=0x{dram.IMAGE_END:x}", "-e", "ot_loader", "-o", str(e), str(o))
    run("m68k-elf-objcopy", "-O", "binary", "-j", ".text", str(e), str(WORK / "loader.bin"))
    app = (WORK / "loader.bin").read_bytes()
    assert app.endswith(blob), "the loader's tail is not the runtime"
    return app


def give_up_plate(img, mm):
    """PLATE REV out as SPRING REV is (dsp_patch.patch_dsp / remove_spring): its DSP dispatch -> the
    passthrough stub on both payloads, its rows off both FX choosers, id2e -> the NONE page, so a project
    naming it loads NONE. The combined image puts SIDECHAIN_COMPRESSOR's DSP section over its P words."""
    print("\n=== PLATE REV given up as well (combined image) ===")
    for tag, d in dsp_patch.DSP.items():
        xt = dsp_patch.x_off(mm, img, d["va"], d["ln"], 0x215)
        si, sp = xt + PLATE["fx_id"] * 3, xt + (0x20 + PLATE["fx_id"]) * 3
        assert (dsp_patch.rd3(img, si), dsp_patch.rd3(img, sp)) == PLATE[tag], f"payload {tag}: PLATE dispatch"
        img[si:si + 3] = dsp_patch.w3(d["stub_init"])
        img[sp:sp + 3] = dsp_patch.w3(d["stub_proc"])
        print(f"  payload {tag}: X:$215[$14] -> passthrough stub")

    def u32(a):
        return int.from_bytes(img[a - BASE:a - BASE + 4], "big")

    def wr32(a, v):
        img[a - BASE:a - BASE + 4] = v.to_bytes(4, "big")
    for bus in dsp_patch.FX_BUSES:
        entries = []
        while (v := u32(bus["lst"] + 4 * len(entries))):
            entries.append(v)
            assert len(entries) < 0x20
        if PLATE["p"] in entries:
            pos = entries.index(PLATE["p"])
            del entries[pos]
            for i, v in enumerate(entries):
                wr32(bus["lst"] + 4 * i, v)
            wr32(bus["lst"] + 4 * len(entries), 0)
            wr32(bus["id2pos"] + PLATE["fx_id"] * 4, 0)
            for idv in range(0x20):
                p = u32(bus["id2pos"] + idv * 4)
                if idv != PLATE["fx_id"] and p > pos:
                    wr32(bus["id2pos"] + idv * 4, p - 1)
            print(f"  {bus['tag']}: dropped row {pos}; {len(entries)} entries")
        else:
            print(f"  {bus['tag']}: PLATE not offered on this bus")
        assert u32(bus["id2e"] + PLATE["fx_id"] * 4) in (PLATE["p"], dsp_patch.NONE_P)
        wr32(bus["id2e"] + PLATE["fx_id"] * 4, dsp_patch.NONE_P)


def main():
    if not STOCK_SECT.exists():
        sys.exit(f"missing {STOCK_SECT}")
    img = bytearray(STOCK_SECT.read_bytes())
    stock = bytes(img)
    mm = dsp_patch.modmap()

    def o(a):
        return a - BASE

    def u32(a):
        return int.from_bytes(img[o(a):o(a) + 4], "big")

    bs = dsp_patch.patch_dsp(img, mm, host=True, orgs={t: v for t, v in DSP_ORGS.items() if v is not None})
    print()
    assert 0x15 in DONOR_IDS and set(DONOR_IDS) <= {0x14, 0x15}, f"donors {DONOR_IDS}: SPRING, or SPRING + PLATE"
    dsp_patch.remove_spring(img)
    if 0x14 in DONOR_IDS:
        give_up_plate(img, mm)
    if kyoti_place.active():                       # the composer reads the DSP layout back
        (ROOT / "out/bp_dsp_layout.json").write_text(json.dumps(
            {t: dict(org=b["org"], words=len(b["words"]),
                     helper=dsp_patch.DSP[t]["spring_init"] + hwprobe_image.SPRING_N - hwprobe_image.DARK_N)
             for t, b in zip(dsp_patch.DSP, bs)}))

    print("\n=== ColdFire: the OT-303 runtime (registration + renderer) in DRAM ===")
    blob, syms, sizes = build_cf()
    end = RT_AT + len(blob)
    if RT_IN_KYOTI:
        print(f"  runtime {len(blob)} B linked at 0x{RT_AT:08x}..0x{end:08x}: a unit of the combined image's DRAM "
              f"payload; " + ", ".join(f"{k} {v[0]} B" for k, v in sizes.items() if v[0]))
    else:
        assert RT_AT == dram.RESERVE, "the runtime's own reserve starts at dram.RESERVE"
        assert end <= dram.RESERVE_END, f"the runtime ends at 0x{end:08x}, past its reserve's end 0x{dram.RESERVE_END:08x}"
        print(f"  runtime {len(blob)} B at 0x{dram.RESERVE:08x}..0x{end:08x} (reserve {dram.RESERVE_PAGES} pages, "
              f"{dram.RESERVE_END - end} B left); " + ", ".join(f"{k} {v[0]} B" for k, v in sizes.items() if v[0]))
    written = []
    for site, expect, sym, kind, n in DETOURS:
        assert stock[o(site):o(site) + len(expect)] == expect, f"detour 0x{site:08x}: not the stock bytes"
        assert len(expect) >= n
        tgt = syms[sym]
        if kind == "lea":                              # the six-byte `lea abs.l,An` keeps its opcode
            new = expect[:2] + tgt.to_bytes(4, "big")
        else:                                          # jmp, or jsr (the stub returns)
            new = bytes.fromhex("4ef9" if kind == "jmp" else "4eb9") + tgt.to_bytes(4, "big") + bytes.fromhex("4e71") * ((n - 6) // 2)
        assert len(new) == n
        img[o(site):o(site) + n] = new
        written.append((site, site + n, sym))
        print(f"    0x{site:08x} {kind} -> {sym} 0x{tgt:08x} ({n} B)")
    for site, expect, new, note in POKES:
        assert stock[o(site):o(site) + len(expect)] == expect, f"poke 0x{site:08x}: not the stock bytes"
        img[o(site):o(site) + len(new)] = new
        written.append((site, site + len(new), note))
        print(f"    0x{site:08x} {expect.hex()} -> {new.hex()}  {note}")
    assert u32(FLEX_SLOT) == FLEX_RENDER, "the FLEX renderer slot is not stock"
    img[o(FLEX_SLOT):o(FLEX_SLOT) + 4] = syms["ot_render"].to_bytes(4, "big")
    written.append((FLEX_SLOT, FLEX_SLOT + 4, "FLEX renderer"))
    print(f"    0x{FLEX_SLOT:08x} FLEX renderer 0x{FLEX_RENDER:08x} -> ot_render 0x{syms['ot_render']:08x}")

    print("\n=== the DRAM runtime: arena reserve, boot site, loader appended ===")
    for site, expect, new, note in ([] if RT_IN_KYOTI else dram.arena_pokes() + [dram.boot_poke()]):
        assert stock[o(site):o(site) + 4] == expect, f"0x{site:08x} ({note}): not the stock bytes {stock[o(site):o(site) + 4].hex()}"
        img[o(site):o(site) + 4] = new
        written.append((site, site + 4, note))
    if RT_IN_KYOTI:
        print("  none here: the combined image's loader (tools/dram/) carries the runtime")
    else:
        print(f"  arena base 0x{dram.BASE:08x} -> 0x{dram.RESERVE_END:08x} at {len(dram.BASE_SITES) + len(dram.DERIVED_SITES)} sites; "
              f"page count {dram.PAGES} -> {(dram.END - dram.RESERVE_END) // dram.PAGE - 1}; boot site 0x{dram.BOOT_SITE:08x} -> 0x{dram.IMAGE_END:08x}")
    written.sort()
    for (a0, a1, n0), (b0, b1, n1) in zip(written, written[1:]):
        assert a1 <= b0, f"{n0} and {n1} overlap"
    assert len(img) == dram.IMAGE_END - BASE, "the OS image does not end where the loader goes"
    if not RT_IN_KYOTI:
        app = build_loader(blob)
        img += app
        print(f"  loader + runtime {len(app)} B appended at 0x{dram.IMAGE_END:08x} (runtime hash 0x{dram.x33(blob):08x})")

    OUT.write_bytes(bytes(img))
    seal(__file__, OUT)
    changed = sum(1 for a, b in zip(stock, img) if a != b)
    print(f"\n  {OUT.name}: {changed} bytes changed vs stock")

    if not EFT.exists() or not STOCK_SYX.exists():
        print("  (EFT / stock syx missing -- skipping wrap)")
        return
    print("\n=== wrap ===")
    env = dict(os.environ, EFT_EMIT_CONTAINER=str(ELEK))
    r = subprocess.run([str(EFT), "-i", str(STOCK_SYX), "-c", "3", str(OUT), "-V", VERSTR,
                        "-o", str(OUT_SYX)], capture_output=True, text=True, env=env, cwd=ROOT)
    print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                             if any(k in l for k in ("version", "emitted", "wrote", "checksum", "round-trip"))))
    if r.returncode or "too long" in r.stdout:
        sys.exit(f"wrap failed:\n{r.stdout}\n{r.stderr}")
    subprocess.run(["python3", "tools/make_bin.py", str(ELEK), "-o", str(OUT_BIN)], check=True, cwd=ROOT)
    print(f"\n  {OUT_SYX.name}  +  {OUT_BIN.name}")


if __name__ == "__main__":
    main()
