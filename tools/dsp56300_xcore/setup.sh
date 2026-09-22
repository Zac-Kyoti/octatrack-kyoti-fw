#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# Reproduces the dual-core DSP56300 emulator (Session 77, cross-core
# SIDECHAIN handoff) into vendor/dsp56300 -- gitignored like the rest of
# vendor/, so this is what makes the toolchain investment survive a fresh
# clone or a `git clean` of vendor/.
#
# What it does:
#   1. Applies vendor.patch to vendor/dsp56300 -- octabam's own
#      tools/patches/dsp56300.patch (refs/octabam/), reconciled against
#      OUR vendored commit (4fb5fea): source/dsp56kEmu/dsp.h and
#      jitops_alu.cpp needed manual fixes for upstream drift between the
#      two vendor commits, everything else applied clean. See NOTES.md
#      "Session 77" for exactly what changed and why (AGU underflow fix,
#      per-core host-stepping hooks on DSP, MPYRI opcode, dual-core Memory
#      redirect of the shared Y:0x30000-0x3FFFF window).
#   2. Drops octabam's dual-core dsp_host.cpp in as a NEW, separately-named
#      CMake target `dsp_host_xcore` under source/dsp_host_xcore/ -- NOT
#      overwriting vendor/dsp56300/source/dsp_host/, which is OUR OWN
#      single-core dsp_host that every existing tools/emu_*.py already
#      depends on. The two dsp_host.cpp files share a name upstream but are
#      NOT interchangeable; colliding them would silently break every
#      existing emu tool.
#   3. Reconfigures + rebuilds dsp56kEmu, dsp_host, dsp_asm and
#      dsp_host_xcore, and runs the existing emu_sc_dsp3.py regression
#      suite to confirm the vendor patch didn't regress anything already
#      shipped.
#
# Idempotent: safe to re-run (git apply --check first; skips if already
# applied). Requires vendor/dsp56300 already cloned + built once per
# BUILD_KYOTI.md's normal DSP56300 toolchain prerequisite.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENDOR="$ROOT/vendor/dsp56300"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$VENDOR/.git" ]; then
    echo "missing $VENDOR -- build the normal DSP56300 toolchain first (BUILD_KYOTI.md)" >&2
    exit 1
fi

cd "$VENDOR"
if grep -q "octabam" source/dsp56kEmu/agu.h 2>/dev/null; then
    echo "vendor.patch already applied, skipping"
elif git apply --check "$HERE/vendor.patch" 2>/dev/null; then
    echo "applying $HERE/vendor.patch ..."
    git apply "$HERE/vendor.patch"
else
    echo "vendor.patch does not apply cleanly -- upstream vendor/dsp56300 has moved" >&2
    echo "since this was last reconciled (4fb5fea). Manual reconciliation needed" >&2
    echo "the same way Session 77 did it -- see NOTES.md for the two files that" >&2
    echo "needed it last time (dsp.h, jitops_alu.cpp) and why." >&2
    exit 1
fi

mkdir -p source/dsp_host_xcore
cp "$HERE/dsp_host_xcore.cpp" source/dsp_host_xcore/
cp "$HERE/CMakeLists.txt" source/dsp_host_xcore/

cd build
cmake . > /tmp/dsp56300_xcore_configure.log 2>&1 || { cat /tmp/dsp56300_xcore_configure.log; exit 1; }
cmake --build . --target dsp56kEmu dsp_host dsp_asm dsp_host_xcore -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)" \
    > /tmp/dsp56300_xcore_build.log 2>&1 || { tail -80 /tmp/dsp56300_xcore_build.log; exit 1; }

echo "built: $VENDOR/build/source/dsp_host_xcore/dsp_host_xcore"
echo "regression-testing the existing single-core dsp_host against the patched library ..."
cd "$ROOT"
python3 tools/emu_sc_dsp3.py

echo "OK -- dual-core dsp_host_xcore is ready, single-core dsp_host unregressed."
