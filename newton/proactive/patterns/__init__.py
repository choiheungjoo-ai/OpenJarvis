"""Pattern recognition — block 4 step 4.3.

Three pattern types live here, two implemented:

    * **time**     — weekly / daily routines, e.g. "session at Tue 9 a.m."
    * **sequence** — "X often follows Y", e.g. vault_search → vault_write
    * **context**  — deferred; see :mod:`context` for the design gap.

The learner detects each kind from existing tables (``sessions``,
``tool_approvals``, …), then scores it with a three-factor confidence
model and upserts a row into ``user_patterns``. Step 4.4's
anticipation engine reads those rows; step 4.6 will subtract a
rejection penalty from the score without restructuring the math.
"""

from newton.proactive.patterns.confidence import (
    ConfidenceBreakdown,
    score,
)
from newton.proactive.patterns.learner import LearnReport, PatternLearner

__all__ = [
    "ConfidenceBreakdown",
    "LearnReport",
    "PatternLearner",
    "score",
]
