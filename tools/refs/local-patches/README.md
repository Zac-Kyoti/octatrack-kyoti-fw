# `tools/refs/local-patches/`

`refs/*` is **gitignored** — the clones under `refs/` are a disposable cache, so any edit
made inside one is outside version control and dies with the next sync, reset, or
re-clone. This directory is the durable home for those edits: it lives in **our** repo, so
a patch committed here survives all of that.

`tools/refs/sync.py` writes into this directory automatically (see `sync_one()`), in two
cases:

| file | what it captures |
|---|---|
| `<name>-local.patch` | **uncommitted** working-tree edits found in `refs/<name>` before it is reset |
| `<name>-local-commits.patch` | **committed** work in `refs/<name>` that is not reachable from the sync target |

Nothing here is re-applied automatically. `sync.py` prints the exact `git -C refs/<name>
apply …` command; re-applying is a deliberate act.

**Commit the patches you care about.** A patch sitting here untracked is no safer than the
clone it came from — `git clean -fdx` removes both.

## ⚠️ `octabam-emu-samplebank-map.patch` is REQUIRED, not optional

Without it the emulator **cannot boot this repo's firmware images at all**: the post-PR#360
(more-correct EMAC) boot branch reaches a stock ~10.8 MB zero-fill at `0x4f502c10`, which
no other mapping covers, and Unicorn aborts with `UC_ERR_WRITE_UNMAPPED` partway through
`gate_m6a()`. Project mount then DMAs card sectors into the same bank at `0x4ece3000`.
A/B tested upstream:

```
refs/octabam tools/emu/emu_rtos.py @ 111fd76 (the MANIFEST.lock pin)  -> BOOT FAILED
                                   + this patch                       -> BOOT OK
```

Verified 2026-09-25: it **applies cleanly to the pinned commit `111fd76`**, so
re-application is mechanical.

It currently also exists as commit `d5b84fb` on the local branch `emu/map-audio-sdram`
inside `refs/octabam`. **Do not rely on that branch.** `sync.py`'s `checkout --detach`
moves off it; before Session 92 that happened silently, because the old dirty-check saw
only uncommitted edits and a committed fix left a clean tree. The branch ref survives, so
nothing looks lost — the clone just quietly stops carrying the fix. That gap is now closed
(`sync.py` exports unreachable commits as `-local-commits.patch` and prints the re-apply
command), but the patch committed here is the thing that actually guarantees recovery.

`MANIFEST.lock` deliberately still pins `111fd76` rather than `d5b84fb`: `d5b84fb` exists
only in this local clone and is not on `origin`, so pinning it would break any fresh clone.
The pin stays upstream-resolvable and this patch goes on top.

One staleness note: the patch's own inline comment says "`tools/emu_reload.py` grows pages
the same way". That is no longer true — Session 92 retired our duplicate pager, because
octabam's own hook is registered first and takes every fault, making ours dead code (and
it had a real defect: it swallowed an overlapping-`mem_map` error and returned "handled"
anyway). The comment is left alone so the patch keeps applying byte-for-byte.
