"""Small invariants for bounded SEC filing viewer navigation."""

from unified_api.routers.edgar import _page_for_chunk


def test_chunk_page_is_one_based_and_respects_page_boundaries():
    assert _page_for_chunk(0, 20) == 1
    assert _page_for_chunk(19, 20) == 1
    assert _page_for_chunk(20, 20) == 2
    assert _page_for_chunk(101, 20) == 6
