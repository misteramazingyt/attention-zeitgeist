"""Tests for composite score normalization."""

from __future__ import annotations

from attention_ledger.transforms.score_attention import percentile_scores


def test_empty_and_single():
    assert percentile_scores([]) == []
    assert percentile_scores([42.0]) == [0.0]


def test_monotonic_ordering():
    scores = percentile_scores([1.0, 10.0, 100.0, 1000.0])
    assert scores[0] == 0.0
    assert scores[-1] == 1.0
    assert scores == sorted(scores)


def test_ties_share_min_rank():
    scores = percentile_scores([5.0, 5.0, 50.0])
    # The two tied smallest values share percentile 0.0; the largest is 1.0.
    assert scores[0] == scores[1] == 0.0
    assert scores[2] == 1.0


def test_bounds():
    scores = percentile_scores([0.0, 3.0, 7.0, 9.0, 11.0])
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_log_transform_compresses_outlier():
    # A massive outlier should not dominate because of the log1p transform:
    # its percentile is still bounded at 1.0 like any top value.
    scores = percentile_scores([1.0, 2.0, 3.0, 1_000_000.0])
    assert scores[-1] == 1.0
    assert scores[0] == 0.0
