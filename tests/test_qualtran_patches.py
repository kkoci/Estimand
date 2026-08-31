"""Tests for guppy_estimand._qualtran_patches -- local corrections for
confirmed, filed-upstream bugs in Qualtran. See CLAUDE.md / VERIFICATION.md.
"""

import math

from qualtran.surface_code import CompactDataBlock

from guppy_estimand._qualtran_patches import CorrectedCompactDataBlock


def test_corrected_compact_data_block_matches_the_cited_paper():
    """Litinski (arXiv:1808.02892, page 7, Fig. 9): a compact block storing
    n data qubits uses 1.5n + 3 tiles -- confirmed in the figure caption,
    body text, and summary paragraph (see VERIFICATION.md Sec. 8)."""
    block = CorrectedCompactDataBlock(data_d=17)
    for n in (1, 2, 3, 10, 100):
        assert block.n_tiles(n) == math.ceil(1.5 * n) + 3


def test_upstream_qualtran_still_has_the_1943_bug():
    """Guard for quantumlib/Qualtran#1943.

    This asserts Qualtran's OWN (unpatched) CompactDataBlock still computes
    the known-buggy value (missing the paper's "+3" tiles). If Qualtran
    fixes #1943 upstream, this assertion will start failing -- n_tiles(2)
    would become 6 (the paper-correct value) instead of 3.

    That failure is the signal to: (1) check Qualtran's CHANGELOG / release
    notes to confirm a real code fix landed (not just a version bump or a
    "won't fix" close), and (2) if confirmed, remove
    guppy_estimand._qualtran_patches.CorrectedCompactDataBlock and switch
    estimate._make_beverland_model back to calling
    PhysicalCostModel.make_beverland_et_al() directly for data_block_name
    == "compact". Do NOT just delete this test when it starts failing --
    that would silently duplicate the fix.
    """
    block = CompactDataBlock(data_d=17)
    n = 2
    assert block.n_tiles(n) == math.ceil(1.5 * n)  # == 3, the known-buggy value
    assert block.n_tiles(n) != math.ceil(1.5 * n) + 3  # != 6, the paper-correct value
