#!/bin/sh
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# Fetch Open303 at its pinned commit into out/ot303/refs and build the voice-study harness.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/out/ot303"
REF="$OUT/refs/Open303"
PIN=313bf0d9ade7c1dcb6b3a74f5ea1780a29d70074
mkdir -p "$OUT/refs"
[ -d "$REF/.git" ] || git clone -q https://github.com/RobinSchmidt/Open303 "$REF"
git -C "$REF" fetch -q origin 2>/dev/null || true
git -C "$REF" checkout -q "$PIN"
SRC="$REF/Source/DSPCode"
clang++ -O2 -std=c++17 -w -I"$SRC" "$ROOT/tools/ot303/voice_study.cpp" \
    $(ls "$SRC"/*.cpp) -o "$OUT/voice_study"
echo "built $OUT/voice_study (Open303 @ $PIN)"
