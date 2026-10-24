# Quant Live Rec (Modwerk)

Hold [REC] and tap [PLAY] to see QUANTIZE LIVE REC; tap [PLAY] again while the toast is up to switch it.

- `patch_qlrec.s`: the author's source. It is the final QUANTIZE_LIVE_REC_TOGGLE except that the flip writes the battery copy before the setting word. In the other order the two stores and the `jsr` after them repeat 12 bytes of stock's PERSONALIZE setter (0x40068ccf), which Modwerk's USB package scan refuses. The behaviour is the same.
- `manifest.py`: the Modwerk form (one floating linked unit of 196 bytes, two `jmp` detours, the retired 0x400522ca site kept as a guard).

Version 0.1.1 on Modwerk (repeat98/modwerk#846). Hardware: the author's MKI, a card image of this module alone (OS VERSION MW_QLR011), 23 October 2026: the gesture, the PERSONALIZE redraw and a power cycle.
