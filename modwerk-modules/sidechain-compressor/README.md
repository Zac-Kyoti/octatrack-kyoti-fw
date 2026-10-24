# Sidechain Compressor (Modwerk)

Stock COMPRESSOR with a side-chain KEY from any track. Page 2: RMS, MON, KEY, KGN, KBAS (the key's high-pass, in Hz) and KWID (its low-pass, in octaves above KBAS).

- `patch_sc_dsp3.asm`, `patch_sidechain.s`, `ui_switch.s`, `sc_tables.py`, `sc_keyfilt.py`: the final SIDECHAIN_COMPRESSOR sources, unchanged.
- `manifest.py`: the Modwerk form of `octabam-modules/sidechain-compressor/manifest.py`, with its sources beside it in this folder.

Version 0.2.0 for Modwerk, replacing 0.1.2 (KFLT gave way to KBAS and KWID; a COMPRESSOR saved with 0.1.x keeps its KEY, and its other page-2 values land on different knobs). Not submitted yet: Modwerk's beta USB base builds Sidechain Compressor into its resident DSP engine (`resident_dsp.py`, `stock_hook_controllers.py`), so this version needs that base updated as well.

Checked 23 October 2026: Modwerk's toolchain image builds this module alone natively (both ColdFire units match the author's builds byte for byte; 677 DSP words placed on both cores, four hooks). Not yet built into Modwerk's USB base or flashed in this form.
