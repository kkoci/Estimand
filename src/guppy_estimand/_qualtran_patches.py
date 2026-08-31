"""Local corrections for confirmed, filed-upstream bugs in Qualtran's
``PhysicalCostModel.make_beverland_et_al()`` composite preset.

See CLAUDE.md ("Update", 2026-09-01) and VERIFICATION.md for the full
derivation of each bug against its cited paper, and for the reasoning behind
why only one of the two known issues is patched here.

Every class in this module corrects exactly one filed, open upstream issue.
**Remove the override once its issue is closed with a landed code fix** --
check Qualtran's actual diff / CHANGELOG / release notes, not just that the
GitHub issue is closed (it could be closed as "won't fix", or fixed
differently than assumed here). ``tests/test_qualtran_patches.py`` has a
test per override that is designed to start failing the moment Qualtran's
own upstream output changes to match the paper -- that failure is the
signal to remove the corresponding override, not a bug to silently fix.
"""

from __future__ import annotations

import math

from qualtran.surface_code import CompactDataBlock as _QualtranCompactDataBlock


class CorrectedCompactDataBlock(_QualtranCompactDataBlock):
    """Fixes https://github.com/quantumlib/Qualtran/issues/1943.

    Qualtran's ``CompactDataBlock.n_tiles()`` computes ``ceil(1.5 * n)``, but
    the source it cites for this formula (Litinski, "A Game of Surface
    Codes", arXiv:1808.02892, page 7, Figure 9) states the compact block
    uses ``1.5n + 3`` tiles -- confirmed against the actual paper directly
    (the "+3" appears identically in the paper's Figure 9 caption, its body
    text introducing the design, and its Summary paragraph; cross-checked
    against the ar5iv LaTeX-derived HTML rendering to rule out a PDF
    text-extraction artifact). Qualtran's formula is simply missing the
    additive "+3" term -- this is a straightforward transcription bug, not
    an intentional simplification (the sibling
    ``n_steps_to_consume_a_magic_state = 9`` constant on the same class is
    transcribed correctly from the same figure). See VERIFICATION.md Sec. 8.

    REMOVE THIS OVERRIDE once quantumlib/Qualtran#1943 is closed *with a
    landed code fix* in the installed qualtran version.
    """

    def n_tiles(self, n_algo_qubits: int) -> int:
        return math.ceil(1.5 * n_algo_qubits) + 3
