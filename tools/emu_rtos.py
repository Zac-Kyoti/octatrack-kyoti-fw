#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Thin wrapper around **octabam's full-firmware emulator** (route A):
`refs/octabam/tools/emu_rtos.py`.  It runs the OS's *own* scheduler — the handoff
trap, PIT0 ticking, all eleven tasks waking each other through the kernel, a real
CompactFlash mount, a real LOAD PROJECT, and the sequencer stepping a saved bank.

Use it for **"what runs when the user does X"** — the dynamic-analysis tool
`NOTES.md` L413 asked for.  First target: locate the LIVE-REC `[NO]`+knob
p-lock-erase handler (Session 13 Phase 1) by watching the sequenced-data RAM
region while driving a `[NO]` press + an encoder delta.

We do **not** vendor octabam's ~3700 lines (`emu_rtos.py` + `emu_bringup.py` +
`emu_card.py`).  Licence posture: `refs/` is a disposable cache this project
redistributes nothing from — same call as `build_sidechain2.py` loading
`dsp_modmap.py` from there.  This wrapper:

  * checks `refs/octabam/` is populated  (else: run `python3 tools/refs/sync.py`)
  * passes `--image <our out/raw/section_3_MAIN_OS.bin>` (identical SHA
    `164f3122…`, verified Session 17) so nothing is copied into `refs/octabam/`
  * defaults `--project` to the factory **OT DEMO** export if it's on this Mac
  * runs octabam's script from the `refs/octabam/` cwd (its relative imports +
    `REPO` detection need that), forwarding every other argument

    python3 tools/emu_rtos.py --ms 800 --until-gate               # smoke test (M6a gate)
    python3 tools/emu_rtos.py --load-project --watch-mem 0x…      # M6b + watch a RAM span
    python3 tools/emu_rtos.py --sequencer --via-key --frames 400  # M6c: run the sequencer
    python3 tools/emu_rtos.py --help                             # every octabam flag

Needs `unicorn>=2.1` (plain m68k — the CFV4E ops decode fine on 2.1.4; no special
build).  octabam pins its own OS build; we override it with `--image`, so a
`refs/` re-sync picks up octabam's fixes automatically.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
OCTA_RTOS = OCTABAM / "tools" / "emu" / "emu_rtos.py"
OUR_IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"

# a real hardware export to put on the emulated card; the factory demo is reproducible
DEMO_PROJECT = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"


def main(argv):
    if not OCTA_RTOS.exists():
        sys.exit(
            f"missing {OCTA_RTOS.relative_to(ROOT)}\n"
            f"  -> populate the refs cache:  python3 tools/refs/sync.py"
        )
    if not OUR_IMAGE.exists():
        sys.exit(f"missing {OUR_IMAGE.relative_to(ROOT)}  -> ./fetch-os.sh && ./analyze.sh")

    # octabam's emu_rtos now refuses route A on stock Unicorn 2.1.4 (its ColdFire EMAC
    # halves every fractional product -- RTOS_FORK.md §10.16).  build_unicorn.sh parks a
    # patched libunicorn where emu_bringup auto-detects it.
    emac_lib = OCTABAM / ".venv" / "lib" / "unicorn-emac"
    if not emac_lib.is_dir():
        sys.exit(
            f"missing the EMAC-patched Unicorn ({emac_lib.relative_to(ROOT)})\n"
            f"  -> build it once (needs cmake):\n"
            f"     ( cd {OCTABAM.relative_to(ROOT)} && PY=$(command -v python3) bash scripts/build_unicorn.sh )"
        )

    passthru = list(argv)
    if not any(a == "--image" or a.startswith("--image=") for a in passthru):
        passthru = ["--image", str(OUR_IMAGE)] + passthru
    if (not any(a == "--project" or a.startswith("--project=") for a in passthru)
            and DEMO_PROJECT.is_dir()):
        passthru = ["--project", str(DEMO_PROJECT)] + passthru

    os.chdir(OCTABAM)                       # octabam's script resolves REPO from its own path,
    sys.path.insert(0, str(OCTABAM / "tools"))   # and imports emu_bringup / emu_card as siblings
    import toolpath  # noqa: E402  -- adds tools/build,harness,emu,hw,verify to sys.path
    sys.argv = [str(OCTA_RTOS)] + passthru
    print(f"[emu_rtos wrapper] octabam @ {OCTABAM.relative_to(ROOT)}  ·  image = our {OUR_IMAGE.name}")
    print(f"[emu_rtos wrapper] argv: {' '.join(passthru)}\n")
    code = compile(OCTA_RTOS.read_text(), str(OCTA_RTOS), "exec")
    g = {"__name__": "__main__", "__file__": str(OCTA_RTOS)}
    try:
        exec(code, g)
    except SystemExit as e:
        return e.code or 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
