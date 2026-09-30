#!/usr/bin/env python3
"""
Regenerate a sysex/patches/<name>-<ver>.json from a freshly built out/mainos.bin.

The JSON is the input to apply_patch.py (the reproducible "fast path"): it carries
the stock/target hashes and a list of byte hunks (contiguous runs that differ
between the stock MAIN OS and the patched one). This script derives all of that by
diffing:

    stock  = <section 3 decompressed from the stock .syx>
    built  = out/mainos_midi_plays_free_fix.bin   (tools/build_midi_plays_free_fix.py output)

then repacks with elektron-firmware-tool so it can record result_syx_sha256.

    python3 sysex/gen_patch_json.py \
        -i downloads/extracted/OCTATRACK_OS1.40C.syx \
        --built out/mainos_midi_plays_free_fix.bin --trigscale-only \
        --version r1 -o sysex/patches/playsfreefix-r1.json

Hunk grouping: bytes are contiguous if <= GAP unchanged bytes lie between them
(GAP=0 -> exact runs). A small gap keeps the hunk count sane when a detour leaves
one or two stale bytes between edits; those unchanged bytes are written verbatim
in both `orig` and `new`, so the result is still an exact image.
"""
import argparse, hashlib, json, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOAD_BASE = 0x40000400
GAP = 3

TOOL = ROOT / "vendor/elektron-firmware-tool/elektron-firmware-tool"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def decompress_section(tool, syx, n):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([str(tool), "-i", str(syx), "-d", str(n), "-o", td], check=True,
                       capture_output=True)
        c = list(Path(td).glob(f"section_{n}_*.bin"))
        assert len(c) == 1, c
        return c[0].read_bytes()


def hunks(stock, built, gap=GAP):
    assert len(stock) == len(built)
    diff = [i for i in range(len(stock)) if stock[i] != built[i]]
    if not diff:
        return []
    groups, cur = [], [diff[0], diff[0]]
    for i in diff[1:]:
        if i - cur[1] - 1 <= gap:
            cur[1] = i
        else:
            groups.append(tuple(cur)); cur = [i, i]
    groups.append(tuple(cur))
    out = []
    for lo, hi in groups:
        out.append({
            "addr": f"0x{LOAD_BASE + lo:08x}",
            "offset": lo,
            "len": hi - lo + 1,
            "orig": bytes(stock[lo:hi + 1]).hex(),
            "new": bytes(built[lo:hi + 1]).hex(),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True, help="stock .syx")
    ap.add_argument("--built", default=str(ROOT / "out/mainos.bin"))
    ap.add_argument("--section", type=int, default=3)
    ap.add_argument("--version", required=True, help="patch rev, e.g. r13")
    ap.add_argument("--display-version", default="keep",
                    help='ELEK version string to set; "" or "keep" -> leave the stock field untouched')
    ap.add_argument("--name", default="playsfreefix", help="patch name")
    ap.add_argument("--trigscale-only", action="store_true",
                    help="only the MIDI manual-trig fix is applied (stock + fix)")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--tool", default=str(TOOL))
    a = ap.parse_args()

    syx = Path(a.input)
    stock = decompress_section(a.tool, syx, a.section)
    built = Path(a.built).read_bytes()
    if len(stock) != len(built):
        sys.exit(f"length mismatch: stock {len(stock)} vs built {len(built)}")

    hk = hunks(stock, built)
    total_new = sum(len(bytes.fromhex(h["new"])) for h in hk)
    total_changed = sum(1 for x, y in zip(stock, built) if x != y)

    keep_version = a.display_version in ("", "keep")
    disp = None if keep_version else a.display_version

    # repack to record the resulting .syx hash (matches apply_patch.py's step 4)
    with tempfile.TemporaryDirectory() as td:
        outp = Path(td) / "r.syx"
        cmd = [a.tool, "-i", str(syx), "-c", str(a.section), a.built]
        if disp:
            cmd += ["-V", disp]
        cmd += ["-o", str(outp)]
        subprocess.run(cmd, check=True, capture_output=True)
        result_sha = sha(outp.read_bytes())

    trigscale_change = {
        "id": "midi-trig-scale-fix", "source": "octabam-modules/batch-bugfixes/patch_trigscale.s",
        "desc": "Fix: a Plays-Free MIDI track with trig quant Direct and pattern scale "
                "Per Track no longer stalls after step 1 when manually triggered. "
                "FUN_4009b5c8 was seeding the per-track scale index with the audio "
                "stride for MIDI tracks. Always on (bug fix, no PERSONALIZE gate)."}
    full_changes = [trigscale_change]

    doc = {
        "name": a.name,
        "version": a.version,
        "target": {
            "device": "Elektron Octatrack (one 1.40C image for MKI and MKII)",
            "os": "1.40C",
            "stock_syx_sha256": sha(syx.read_bytes()),
            "section": a.section,
            "section_name": "MAIN_OS",
            "section_len": len(stock),
            "section_sha256_before": sha(stock),
            "section_sha256_after": sha(built),
            "load_base": f"0x{LOAD_BASE:08x}",
        },
        "display_version": disp,
        "result_syx_sha256": result_sha,
        "changes": [trigscale_change] if a.trigscale_only else full_changes,
        "hunks": hk,
    }
    if a.trigscale_only and len(hk) != 2:
        sys.exit(f"--trigscale-only expects exactly 2 hunks, got {len(hk)} "
                 f"(is --built the stock+fix image from tools/build_midi_plays_free_fix.py?)")
    Path(a.output).write_text(json.dumps(doc, indent=1) + "\n")
    print(f"wrote {a.output}")
    print(f"  {len(hk)} hunks, {total_new} bytes in hunks, {total_changed} bytes changed vs stock")
    print(f"  section_sha256_after = {doc['target']['section_sha256_after']}")
    print(f"  result_syx_sha256    = {result_sha}")


if __name__ == "__main__":
    main()
