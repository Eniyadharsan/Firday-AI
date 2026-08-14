"""Shared pytest / Hypothesis configuration for the test suite.

Registers Hypothesis profiles so property-based tests can trade breadth of
generated examples for speed. The ``fast`` profile keeps example counts low
for quick local/CI runs; ``thorough`` restores a higher count for deeper
verification.

Selection order:
    1. The ``HYPOTHESIS_PROFILE`` environment variable, when set.
    2. Otherwise the ``fast`` profile (few examples, no deadline) by default.

Note: a per-test ``@settings(max_examples=...)`` decorator overrides the active
profile's ``max_examples``. Tests in this suite that hardcode a value have been
set to a low count so the whole suite runs quickly.
"""

from __future__ import annotations

import os

from hypothesis import settings, HealthCheck

# Few examples for fast feedback; deadline disabled to avoid flaky timing
# failures on shared/CI machines.
settings.register_profile(
    "fast",
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# A deeper profile available on demand via HYPOTHESIS_PROFILE=thorough.
settings.register_profile(
    "thorough",
    max_examples=100,
    deadline=None,
)

settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "fast"))
