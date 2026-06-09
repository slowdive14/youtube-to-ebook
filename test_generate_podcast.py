"""
Tests for podcast episode grouping (free-plan-safe audio generation).

NotebookLM's free plan allows only 3 Audio Overviews per day. To avoid
mixing episodes while respecting that cap, articles are split into at most
N ordered groups (one podcast each). Pure grouping logic is tested here;
the live NotebookLM calls are not.
"""

import pytest

from generate_podcast import group_articles


def _arts(n):
    return [{"title": f"A{i}", "channel": "C", "article": f"body {i}"} for i in range(n)]


class TestGroupArticles:
    def test_fewer_than_cap_one_each(self):
        groups = group_articles(_arts(3), max_slots=3)
        assert [len(g) for g in groups] == [1, 1, 1]

    def test_two_articles_two_groups(self):
        groups = group_articles(_arts(2), max_slots=3)
        assert [len(g) for g in groups] == [1, 1]

    def test_single_article(self):
        groups = group_articles(_arts(1), max_slots=3)
        assert [len(g) for g in groups] == [1]

    def test_five_articles_into_three_slots(self):
        groups = group_articles(_arts(5), max_slots=3)
        # even-ish, larger groups first: 2,2,1
        assert [len(g) for g in groups] == [2, 2, 1]

    def test_nine_articles_into_three_slots(self):
        groups = group_articles(_arts(9), max_slots=3)
        assert [len(g) for g in groups] == [3, 3, 3]

    def test_never_exceeds_max_slots(self):
        for n in range(1, 20):
            groups = group_articles(_arts(n), max_slots=3)
            assert len(groups) <= 3

    def test_preserves_order_and_count(self):
        arts = _arts(7)
        groups = group_articles(arts, max_slots=3)
        flat = [a for g in groups for a in g]
        assert flat == arts  # same objects, same order

    def test_empty(self):
        assert group_articles([], max_slots=3) == []

    def test_max_slots_one_bundles_all(self):
        groups = group_articles(_arts(5), max_slots=1)
        assert len(groups) == 1
        assert len(groups[0]) == 5

    def test_larger_groups_come_first(self):
        # remainder is distributed to the earliest groups
        groups = group_articles(_arts(4), max_slots=3)
        assert [len(g) for g in groups] == [2, 1, 1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
