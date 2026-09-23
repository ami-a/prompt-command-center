"""Search ranking — the behaviour that makes type-to-filter feel right."""

from __future__ import annotations

from pcc.model import Tab, Template
from pcc.search import search


def _tabs() -> list[Tab]:
    return [
        Tab(name="Coding", id="t1", templates=[
            Template(title="Refactor for readability", body="Refactor this Python code", id="p1"),
            Template(title="Explain this code", body="Explain step by step", id="p2"),
            Template(title="Write tests", body="Write pytest tests for the code", id="p3"),
        ]),
        Tab(name="Writing", id="t2", templates=[
            Template(title="Summarise", body="Summarise the following", id="p4"),
            Template(title="Translate", body="Translate into Hebrew", id="p5", tags=["hebrew"]),
        ]),
    ]


def _ids(query: str) -> list[str]:
    return [hit.template.id for hit in search(query, _tabs())]


class TestFrecencyBonus:
    def test_bonus_breaks_ties_between_equal_matches(self):
        # "Explain this code" and (nothing else with a comparable structure);
        # use a query that matches two titles as a substring equally.
        # Equal-length prefixes so "review" sits at the same index in both -- a
        # genuine structural tie, which library order then breaks.
        tabs = [
            Tab(name="T", id="t1", templates=[
                Template(title="xxx review", body="", id="a"),
                Template(title="yyy review", body="", id="b"),
            ]),
        ]
        neutral = [h.template.id for h in search("review", tabs)]
        boost_b = lambda i: 5.0 if i == "b" else 0.0  # noqa: E731
        boosted = [h.template.id for h in search("review", tabs, bonus=boost_b)]
        assert neutral == ["a", "b"]      # library order on a tie
        assert boosted[0] == "b"          # frecency lifts b above the tie

    def test_bonus_never_overturns_a_prefix_match(self):
        # A huge bonus on a mere substring must still lose to a title prefix.
        tabs = [
            Tab(name="T", id="t1", templates=[
                Template(title="review something", body="", id="prefix"),
                Template(title="a review", body="", id="substr"),
            ]),
        ]
        hits = search("review", tabs, bonus=lambda i: 6.0 if i == "substr" else 0.0)
        assert hits[0].template.id == "prefix"

    def test_bonus_cannot_drag_in_a_nonmatch(self):
        tabs = _tabs()
        ids = [h.template.id for h in search("zzzz", tabs, bonus=lambda i: 6.0)]
        assert ids == []


def test_empty_query_returns_nothing():
    assert search("", _tabs()) == []
    assert search("   ", _tabs()) == []


def test_title_prefix_ranks_first():
    assert _ids("refactor")[0] == "p1"


def test_search_spans_all_tabs():
    # "Summarise" lives in a different tab than the one a user might be on.
    assert "p4" in _ids("summ")


def test_acronym_matches_word_initials():
    # "rfr" -> Refactor For Readability, the classic launcher shorthand.
    assert _ids("rfr")[0] == "p1"


def test_subsequence_matches_with_gaps():
    assert "p3" in _ids("wtst")


def test_case_is_ignored():
    assert _ids("REFACTOR")[0] == "p1"


def test_body_text_is_searchable_but_ranks_below_titles():
    hits = search("pytest", _tabs())
    assert [h.template.id for h in hits] == ["p3"]


def test_title_match_outranks_body_match():
    hits = search("explain", _tabs())
    assert hits[0].template.id == "p2"


def test_tags_are_searchable():
    assert "p5" in _ids("hebrew")


def test_tab_name_is_searchable():
    assert {"p4", "p5"} <= set(_ids("writing"))


def test_nonsense_query_returns_nothing():
    assert _ids("qqqzzzxxx") == []


def test_typo_still_matches():
    assert "p1" in _ids("refactr")


def test_results_are_ordered_by_descending_score():
    scores = [hit.score for hit in search("e", _tabs())]
    assert scores == sorted(scores, reverse=True)


def test_ties_keep_library_order():
    # Stability matters: the grid must not reshuffle arbitrarily as you type.
    tabs = [Tab(name="T", id="t1", templates=[
        Template(title="Same", body="", id="a"),
        Template(title="Same", body="", id="b"),
        Template(title="Same", body="", id="c"),
    ])]
    assert [h.template.id for h in search("same", tabs)] == ["a", "b", "c"]


def test_limit_is_respected():
    tabs = [Tab(name="T", id="t1", templates=[
        Template(title=f"Item {i}", body="", id=str(i)) for i in range(100)
    ])]
    assert len(search("item", tabs, limit=10)) == 10
