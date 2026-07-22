"""Ranking for type-to-filter.

Plain fuzzy ratio is the wrong tool for a launcher: it rewards overall string
similarity, whereas what a user means by typing ``rfr`` is "the item whose words
start with r, f, r". So this scorer layers the strategies people actually expect,
strongest first, and only falls back to rapidfuzz for typo tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rapidfuzz import fuzz

from .model import Tab, Template

#: Below this, a candidate is not shown at all. Tuned so that a two-character
#: query does not drag in half the library through coincidental body matches.
MIN_SCORE = 45.0


@dataclass
class Hit:
    tab: Tab
    template: Template
    score: float


def _is_subsequence(query: str, text: str) -> bool:
    """Whether ``query`` appears in ``text`` in order, gaps allowed (fzf-style)."""
    it = iter(text)
    return all(char in it for char in query)


def _acronym(text: str) -> str:
    return "".join(word[0] for word in text.replace("-", " ").replace("_", " ").split() if word)


def score_template(query: str, template: Template, tab: Tab, bonus: float = 0.0) -> float:
    """Rank one template against ``query``. Higher is better; 0 means no match.

    ``bonus`` is an optional frecency nudge (see :mod:`pcc.usage`), added only to
    genuine matches and capped by the caller so it can break ties without ever
    overturning a title-prefix match. A non-match stays 0 regardless of bonus:
    familiarity must not drag an unrelated template into the results.
    """
    base = _base_score(query, template, tab)
    return base + bonus if base > 0 else 0.0


def _base_score(query: str, template: Template, tab: Tab) -> float:
    title = template.title.lower()
    body = template.body.lower()
    tab_name = tab.name.lower()

    # 1. Prefix of the title -- the strongest possible signal.
    if title.startswith(query):
        return 100.0

    # 2. Substring, penalised by how deep into the title it sits.
    index = title.find(query)
    if index >= 0:
        return 92.0 - min(index, 20) * 0.4

    # 3. Word-initial acronym: "rfr" -> "Refactor For Readability".
    acronym = _acronym(title)
    if acronym.startswith(query):
        return 88.0
    if query in acronym:
        return 80.0

    # 4. In-order subsequence of the title.
    if _is_subsequence(query, title):
        return 74.0

    # 5. Typo tolerance. Scaled down so a fuzzy title match never outranks an
    #    exact structural one above.
    ratio = fuzz.WRatio(query, title)
    if ratio >= 78:
        return ratio * 0.72

    # 6. Weaker signals: the tab name, then the body text.
    if query in tab_name:
        return 58.0
    if any(query in tag.lower() for tag in template.tags):
        return 56.0
    if query in body:
        return 50.0

    return 0.0


def search(
    query: str,
    tabs: list[Tab],
    limit: int = 60,
    bonus: "Callable[[str], float] | None" = None,
) -> list[Hit]:
    """Rank every template in every tab against ``query``.

    Results are stable: equal scores keep library order, so the grid does not
    reshuffle unpredictably as the query grows. ``bonus`` optionally maps a
    template id to a frecency nudge; it is applied only to matches and only
    after the structural score clears :data:`MIN_SCORE`.
    """
    query = query.strip().lower()
    if not query:
        return []

    hits: list[tuple[float, int, Hit]] = []
    for order, (tab, template) in enumerate(
        (tab, template) for tab in tabs for template in tab.templates
    ):
        base = score_template(query, template, tab)
        if base < MIN_SCORE:
            continue
        score = base + (bonus(template.id) if bonus is not None else 0.0)
        hits.append((score, order, Hit(tab, template, score)))

    hits.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in hits[:limit]]
