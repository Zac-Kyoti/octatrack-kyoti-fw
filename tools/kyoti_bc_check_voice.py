#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
BLACKPYRAMIDS_303's own emulator check (tools/ot303/verify_ot303.py) on KYOTI V1.8BC (build_kyoti.py --clyps-bp),
without editing it: the same jobs and the same verdicts, pointed at the combined image.

  * the image, and the voice's runtime as linked there (out/KYOTI_WIP/KYOTI_V1.8BC/bp_runtime/, written by
    build_kyoti.py): verify's symbols (render counters, event log, descriptor) come from that ELF;
  * the DSP code's org there (bp_runtime/dsp_layout.json): hwprobe_image.build is asked at that org, so
    the pcwatch at hq_start and every DSP address verify reads are the combined image's;
  * the DRAM audit: the runtime is a unit of KYOTI's one DRAM payload (tools/dram/), not behind its own
    loader, so the audit watches KYOTI's loader (octabam_bootstrap once, never `fatal`) and the unit's own
    range, and compares its code + constants with the linked runtime after boot, project load and play.

Expected difference, by design: verify's last line compares PLATE REV (id 0x14) against stock; V1.8BC gives
PLATE up (its dispatch is the passthrough stub, as SPRING's), so that line reads DIFFERS and the run ends
FAILED on it alone. Every other line is verify's own verdict.

    python3 tools/kyoti_bc_check_voice.py        (needs out/ot303/ot_emu_8d0ad6f4, as verify does)
"""
import json, os, pathlib, re, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "out/KYOTI_WIP/KYOTI_V1.8BC"
os.environ["OT303_IMAGE"] = str((OUT / "mainos_kyoti_v1.8bc.bin").relative_to(ROOT / "out"))
sys.path.insert(0, str(ROOT / "tools/ot303"))
import verify_ot303 as v                    # noqa: E402

v.ELF = str(OUT / "bp_runtime/ot303_runtime.elf")
v.RUNTIME = str(OUT / "bp_runtime/ot303_runtime.bin")
LAY = json.loads((OUT / "bp_runtime/dsp_layout.json").read_text())
MAP = json.loads((OUT / "kyoti_v1.8bc_map.json").read_text())
_build = v.hwprobe_image.build


def build_at(tag, host=False, org=None):
    return _build(tag, host, org=LAY[f"bp_dsp_org_{tag}"] if org is None else org)


v.hwprobe_image.build = build_at


def dram_audit():
    """verify's dram job for a unit of KYOTI's DRAM payload: (p, loader hits, writer PCs, the unit after the
    run, the linked runtime, its base)"""
    lo = int(MAP["pieces"]["bp_runtime"]["at"], 16)
    blob = open(v.RUNTIME, "rb").read()
    sym = {}
    for line in subprocess.run(["m68k-elf-nm", str(OUT / "_dram/loader.elf")], capture_output=True, text=True,
                               check=True).stdout.splitlines():
        f = line.split()
        if len(f) == 3:
            sym[f[2]] = int(f[0], 16)
    with tempfile.TemporaryDirectory() as td:
        p = v.emu(v.IMAGE, ["--sequencer", "--internal-clock", "--frames", str(v.FRAMES), "--watch-pc",
                            f'{sym["octabam_bootstrap"]:#x},{sym["fatal"]:#x}', "--watch-mem", f"{lo:#x},{len(blob):#x}",
                            "--mem-dump", f"{lo:#x},{len(blob)}={td}/unit.bin"], td)
        got = open(f"{td}/unit.bin", "rb").read() if os.path.exists(f"{td}/unit.bin") else b""
    hits = re.findall(r"\] at (0x[0-9a-f]+) ", p.stdout)
    pcs = [int(x, 16) for x in re.findall(r"<- .* at pc (0x[0-9a-f]+)", p.stdout)]
    print(f"kyoti dram: unit bp_runtime 0x{lo:08x}+{len(blob)}; loader entry/fatal hits {hits}")
    return p, hits, pcs, got, blob, lo


v.dram_audit = dram_audit

if __name__ == "__main__":
    print(f"image {v.IMAGE}\nruntime {v.ELF}\nDSP orgs {LAY}")
    sys.exit(v.main())
