"""Unit tests for `app.services.search_hybrid` 순수 함수.

- reciprocal_rank_fusion (RRF): 순수 랭크 결합 알고리즘
- DB 의존 함수(hybrid_*_search, *_vector_ids 등) 는 integration 영역으로 skip
"""

from __future__ import annotations

import pytest

from app.services.search_hybrid import RRF_K, reciprocal_rank_fusion


class TestRRFBasics:
    def test_empty_lists_returns_empty(self):
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[]]) == []
        assert reciprocal_rank_fusion([[], []]) == []

    def test_single_list_preserves_order(self):
        assert reciprocal_rank_fusion([[1, 2, 3]]) == [1, 2, 3]

    def test_identical_lists_preserves_order(self):
        out = reciprocal_rank_fusion([[1, 2, 3], [1, 2, 3]])
        assert out == [1, 2, 3]

    def test_default_k_is_60(self):
        assert RRF_K == 60


class TestRRFCombination:
    def test_boosts_items_in_multiple_lists(self):
        # id=2 는 두 리스트 모두에 있음 → 점수 더 높음.
        out = reciprocal_rank_fusion([[1, 2, 3], [5, 2, 7]])
        # 2 가 가장 앞에 와야 함.
        assert out[0] == 2

    def test_disjoint_lists_merge_preserving_rank_sum(self):
        # [1,2] 와 [3,4] 는 겹치지 않음. 1,3 이 1등이므로 동점, 2,4 가 2등.
        # 하지만 dict 의 순서는 삽입 순이라 동점 시 두 순위가 한 묶음.
        out = reciprocal_rank_fusion([[1, 2], [3, 4]])
        assert set(out) == {1, 2, 3, 4}
        # top 2 는 첫 번째 랭크의 1, 3 (각 1/(60+1))
        assert out[0] in (1, 3)
        assert out[1] in (1, 3)

    def test_k_parameter_changes_scores_not_order_if_shared(self):
        # k 가 달라져도 같은 구성이면 결과 id 순서는 동일 (dense 대칭 케이스).
        out1 = reciprocal_rank_fusion([[1, 2, 3]], k=10)
        out2 = reciprocal_rank_fusion([[1, 2, 3]], k=100)
        assert out1 == out2 == [1, 2, 3]

    def test_higher_rank_outweighs_lower(self):
        # 1 은 list A 의 1등, list B 의 100등. 총 점수는 1등 보너스가 주도.
        a = [1] + list(range(100, 200))  # 1 은 A 의 1등
        b = list(range(200, 299)) + [1]  # 1 은 B 의 100등
        out = reciprocal_rank_fusion([a, b])
        assert out[0] == 1

    def test_duplicate_within_single_list(self):
        """같은 id 가 한 리스트에 두 번 나오면 점수가 합산된다."""
        out = reciprocal_rank_fusion([[1, 1, 2]])
        assert out[0] == 1  # 두 번 합산되어 1등
        assert 2 in out


class TestRRFRobustness:
    def test_large_lists_merges_all(self):
        a = list(range(1000))
        b = list(range(500, 1500))
        out = reciprocal_rank_fusion([a, b])
        # 두 리스트의 모든 고유 id 가 결과에 포함되어야 함.
        assert len(out) == 1500
        assert set(out) == set(a) | set(b)

    def test_three_or_more_lists(self):
        out = reciprocal_rank_fusion([[1, 2], [1, 3], [1, 4]])
        # 1 은 세 리스트 모두 1등 → 압도적으로 top.
        assert out[0] == 1

    def test_single_item_lists(self):
        out = reciprocal_rank_fusion([[1], [2], [3]])
        # 모두 각자 1등 → 점수 동일 (1/(60+1)) → 삽입 순 (Python dict 보장).
        assert set(out) == {1, 2, 3}

    @pytest.mark.parametrize(
        "ranks,expected_top",
        [
            ([[10, 20, 30]], 10),
            # 30,10 동점(1/61+1/63) > 20(2*1/62). 삽입 순으로 30 이 먼저.
            ([[30, 20, 10], [10, 20, 30]], 30),
            ([[5]], 5),
        ],
    )
    def test_parametrized_tops(self, ranks, expected_top):
        out = reciprocal_rank_fusion(ranks)
        assert out[0] == expected_top
