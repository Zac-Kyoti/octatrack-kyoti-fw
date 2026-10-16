| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| VARISPEED (octabam) -- the VARISPEED_EMUS source with its assembly switch at 0: VARI and
| QUAN, nothing emulated. remix.inc is that source's text (../varispeed-emus/varispeed_emus.s),
| written beside this unit by the build (manifest.py: Linked.include), so the two modules
| assemble ONE source. tools/build_varispeed.py checks this form gives its unit's bytes.
        .equ    VEM_EMUS, 0
        .include "remix.inc"
