#!/bin/sh
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
# OT-303 Phase 1: render the time-domain matrix into out/ot303/renders (parallel).
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
B="$ROOT/out/ot303/voice_study"; R="$ROOT/out/ot303/renders"; mkdir -p "$R"
{
for sc in sweep hot squelch square; do
  echo "$sc o303 4 ell 0 0 $R/$sc.o303-4-ell.f32"
  echo "$sc o303 4 fir 0 0 $R/$sc.o303-4-fir.f32"
  echo "$sc ref 8 fir 0 0 $R/$sc.ref-8.f32"
  for n in 2 3 4; do echo "$sc zdf $n fir 0 0 $R/$sc.zdf-$n.f32"; done
  for d in 0.5 1 2; do
    echo "$sc refnl 8 fir $d 0 $R/$sc.refnl-8-d$d.f32"
    for n in 2 3 4; do for h in 0 1; do
      echo "$sc zdfnl $n fir $d $h $R/$sc.zdfnl-$n-d$d-h$h.f32"
    done; done
  done
done
} | xargs -P 8 -L 1 "$B" render
