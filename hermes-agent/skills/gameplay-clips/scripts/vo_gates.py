"""VO timing gates shared by gen_vo_natural.py and gen_vo_custom.py (stdlib only)."""


def gap_need(vo_end):
    """Gaps >0.25 s a take needs: 4 per 20 s, i.e. one per 5 s of speech, at least 1.

    A fixed 4 (the 20 s rule) cannot pass on a 10 s clip of 4 phrases (3 gaps at most):
    nikos-bath-toy 2026-11-18 lost 21 min asking Fix about that false WARN twice."""
    return max(1, round(vo_end / 5.0))
