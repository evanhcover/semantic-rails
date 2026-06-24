"""A4: ``metric_by_dimension_rollup`` pattern.

The pattern names the common "measure / metric (by dimension) (top N)"
intent shape. It must:

1. Fire from ``plan`` on representative simple intents.
2. Decline intents that should fire a more specific earlier pattern
   (thresholds, period shifts, X-vs-Y).
"""

from __future__ import annotations

import pytest

from semantic_rails.planner import compose

_FIRES_FROM_PROPOSE = [
    ("top stores by revenue", "measure.jaffle.revenue_usd"),
    ("monthly revenue by store", "measure.jaffle.revenue_usd"),
    ("orders by store", "measure.jaffle.order_count"),
]


@pytest.mark.parametrize("intent,expected_target", _FIRES_FROM_PROPOSE)
def test_metric_by_dimension_fires_from_plan(
    runtime_factory, intent: str, expected_target: str
) -> None:
    runtime = runtime_factory("jaffle_shop")
    try:
        result = compose(runtime, intent)
    finally:
        runtime.close()
    assert result.pattern == "metric_by_dimension_rollup", (
        f"plan did not fire metric_by_dimension_rollup for {intent!r}; "
        f"got pattern={result.pattern!r}"
    )
    target = result.draft.interpreted_intent.get("target")
    assert target == expected_target, (
        f"resolved wrong target for {intent!r}: got {target!r}, expected {expected_target!r}"
    )


@pytest.mark.parametrize(
    "intent,expected_winner",
    [
        ("top 3 stores by revenue with at least 4 customers", "qualified_metric_rollup"),
        ("revenue YoY", "inline_period_shift"),
        ("food vs drink revenue", "inline_comparison"),
        ("signup to send adoption", "filtered_adoption_funnel"),
    ],
)
def test_specific_patterns_win_over_catch_all(
    runtime_factory, intent: str, expected_winner: str
) -> None:
    """The catch-all returns ``score=0.5`` so any more
    specific pattern (score=1.0) wins via score-based selection.
    """

    runtime = runtime_factory("jaffle_shop")
    try:
        result = compose(runtime, intent)
    finally:
        runtime.close()
    assert result.pattern == expected_winner, (
        f"{intent!r}: expected specific pattern {expected_winner!r} to win on score, "
        f"got pattern={result.pattern!r}"
    )
