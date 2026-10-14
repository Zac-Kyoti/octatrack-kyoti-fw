# REPITCH rewrite: overlap with Jannik's REPITCH (DIRTY: clean agents must not read this)

Written 2026-10-13 by the dirty side, after the clean scope (`REPITCH_REWRITE_SCOPE.md`) came
back. It compares the sites the clean agent derived from the stock image with the sites Jannik
Aßfalg's octabam REPITCH uses (`modules/repitch/`, and adapted into the shipped
REPITCH_REPEAT98_KYOTI). Its purpose is an honest answer to "how much of the *where* is forced",
for the user's reply to Jannik.

## ColdFire detours

| Jannik's site | his routine | clean scope | same address? | clean verdict |
|---|---|---|---|---|
| `0x4000406a` | `rate_gate` (gate, tempo source) | not used: the gate is computed inside H1 | no | — |
| `0x4000409e` | `pitch_gate` (PTCH → neutral) | not used. Found independently as alternative (b) and rejected: the rate-only increment is exact without it | no | — |
| `0x40004100` | `rate_hook` (scale the finished increment) | **H1, the whole per-frame core** | **yes** | window `0x40004084..0x40004107` FORCED. The exact site is CHOSEN, but in practice it is the only one-hook site: the EMAC result appears here, and `0x40004108` would need its own pass test |
| `0x40007d96` | `tstr_resolve` (4..6 → OFF) | not used: H1 writes lane `+28 := 0` every frame (stock re-copies the lane byte each frame). Found independently as alternative (b) | no | dry mechanism CHOSEN |
| `0x4006e71c` | `attr_label` | H2 | **yes** | FORCED: stock's `ERROR` branch for unknown TSMODE is the only place |
| `0x4006ee56` | `attr_up` | H3 at `0x4006ee48` | no (14 bytes earlier, the row's first instruction) | FORCED region, site chosen |
| `0x4006ef7c` | `attr_down` | H4 | **yes** | FORCED: the row's first instruction |

**Score: 3 of his 7 detour addresses recur.** All three are where stock itself decides (the
increment's final value, the ATTR label's fallback, the ATTR down row's entry). The other four
are avoided by a different mechanism (one hook doing gate + scale + dry) or a different
instruction.

## Data pokes and pointers

| what | Jannik | clean scope | note |
|---|---|---|---|
| TSTR count `0x400d30de` / `0x400d3270` | 4 → 5 | 4 → 7 (RPCH-only: 5) | FORCED: the descriptor format |
| TSTR formatter pointer (`0x400d310e` / `0x400d32a0`) | → his `tstr_fmt` | → a new formatter | FORCED: stock's is shared with PICKUP |
| TSTR widget → `0x40046ab4` | the unreferenced 5-position select | the same widget, made 7 (RPCH-only: unmodified) | CHOSEN. Independently re-found from stock and octabam's PARAM_PAGES widget census. The shipped module already used it (made 7) |
| PTCH widget pointer (`0x400d3116` / `0x400d32a8`) | → `ptch_widget` (blank knob) | → our `quant_widget` (retained, ours) | same slot, different purpose; QUAN was always ours |

## What to tell Jannik (suggested)

The firmware has one increment builder and one ATTR editor, so a rewrite touches the same
functions. The new core is one detour where his has three in the builder plus a resolver hook.
It shares the builder's final store site and two ATTR entry points with his, because those are
where stock decides. No code, structure or mechanism is his: it computes the increment from RATE
alone instead of neutralising PTCH, and it gets dry playback by clearing the lane's TSTR byte
instead of hooking the resolver.

## Clean-room record

The clean agent opened no blacklisted file. Disclosed: one stray `grep -l` printed file names
only (`tools/repitch_*`, builder, DSP asm, engine model, NOTES/README/CREDITS), and the
auto-memory index was in its context at start (no addresses of his in it). It read the module
README (allowed), which names the old hook kinds. Its design uses neither.

## Addendum 2026-10-14: the VARISPEED_EMUS revision (`REPITCH_REWRITE_SCOPE_EMUS.md`)

- **TSTR now matches his data changes exactly**: count 4 → 5, widget → the unmodified 5-position
  select `0x40046ab4`, and a new formatter. The descriptor format forces this: it is stock's
  only 5-position select. The labels differ (`VARI` vs `RPCH`).
- The new EMUS sites have no counterpart in his module: the TSNS widget pokes
  `0x400d3142`/`0x400d32d4` and the page-2 editor's step redirect at `0x4003a566`.
- The trig latch lives inside H1 and adds no site.
- Clean-room record: the agent opened no blacklisted file. It disclosed reading
  `reference/kb/memory-map.md` ~1100–1240 (one line on the old swap's base-word fix, a fact
  that is ours and also in the retained code), seeing file names only, and the memory index in
  its context.
