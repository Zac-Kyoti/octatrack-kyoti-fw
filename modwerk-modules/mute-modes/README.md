# Mute Modes (Modwerk)

PERSONALIZE > MUTE MODE: what a muted audio track does (OT, OTFX, OTFX-T, DT-T).

Mirrored from Modwerk `main` `c8fcb805` (version 0.2.1), unchanged. The two sources are the author's MUTE_MODES, with blocks Modwerk contributors added under `.ifdef MODWERK_EVENTS` for Modwerk's USB base: `ev_mute_keep`, `ev_voice_bind` and the battery restore. `runtime.json` declares the base events the module subscribes to and raises. `manifest.py` is the Modwerk form.

2026-10-27, for Modwerk 0.2.2: SHADOW (`pre`'s per-frame silenced set) moved from SRAM `0x80006c66`, inside the stock timestretch task's work area, into the unit after KEYMASK, as in the octabam form (pinned in octabam at `a1e0288`). The octabam-form references in `manifest.py` are updated to match (`ca7792be…`, `9be6df77…`).

2026-11-13, for Modwerk 0.2.3: `mm_trig_muted` answers the base's raised `ev_trig_muted` (Modwerk #777), for a machine that starts its own note from a trig before stock binds the voice (FM Synth). It is `fresh_bind`'s per-track test as one mask (16 instructions at most per ask; an earlier draft asked `mm_voice_bind` eight times, 305), and Modwerk's `loader_mute_keep_fixture` checks it against the resets `mm_voice_bind` drops in every frame; OT and OTFX answer 0. Built only under `MODWERK_EVENTS`: no KYOTI, standalone or octabam image changes.
