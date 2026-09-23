"""Library health checks: the only feature that makes a prompt library shrink.

Prompt collections rot silently -- they only ever grow, and nobody schedules a
cleanup. Surfacing the dead weight (never-used, duplicated, broken, empty) turns
"organise your library someday" into a concrete, finishable list. Loss aversion,
used honestly: "you have 14 templates you have never used" prunes what a tidy
"Manage" button never would.

Pure: a function of the library (and, optionally, usage), returning findings.
The UI just renders them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .model import INCLUDE_PREFIX, PLACEHOLDER_RE, Library

#: Ordering/severity: lower sorts first in the health view.
SEVERITY = {"broken-include": 0, "empty": 1, "duplicate-title": 2, "untitled": 3, "unused": 4}


@dataclass(frozen=True)
class Finding:
    kind: str
    message: str
    template_id: str
    tab_name: str

    @property
    def severity(self) -> int:
        return SEVERITY.get(self.kind, 99)


def _include_refs(body: str) -> list[str]:
    refs = []
    for match in PLACEHOLDER_RE.finditer(body):
        name = match.group(1).strip()
        if name.startswith(INCLUDE_PREFIX):
            ref = name[len(INCLUDE_PREFIX):].strip()
            if ref:
                refs.append(ref)
    return refs


def lint(library: Library, frecency: Callable[[str], float] | None = None) -> list[Finding]:
    """Return health findings, most severe first.

    ``frecency`` (from :class:`pcc.usage.UsageStore`) enables the "never used"
    check; without it that check is skipped, so a fresh install is not scolded
    for templates it has not had a chance to use yet.
    """
    findings: list[Finding] = []

    # Duplicate titles, compared case-insensitively across the whole library.
    seen: dict[str, int] = {}
    for _tab, template in library.iter_all():
        seen[template.title.strip().lower()] = seen.get(template.title.strip().lower(), 0) + 1

    # Valid include targets: any template id or title.
    valid_refs = set()
    for _tab, template in library.iter_all():
        valid_refs.add(template.id)
        valid_refs.add(template.title.strip().lower())

    for tab, template in library.iter_all():
        title = template.title.strip()

        if not template.body.strip():
            findings.append(Finding("empty", "empty body", template.id, tab.name))

        if title.lower() == "untitled" or not title:
            findings.append(Finding("untitled", "no title", template.id, tab.name))

        if seen.get(title.lower(), 0) > 1:
            findings.append(
                Finding("duplicate-title", f"duplicate title “{title}”", template.id, tab.name)
            )

        for ref in _include_refs(template.body):
            if ref not in valid_refs and ref.lower() not in valid_refs:
                findings.append(
                    Finding("broken-include", f"include “{ref}” not found", template.id, tab.name)
                )

        if frecency is not None and frecency(template.id) <= 0.0:
            findings.append(Finding("unused", "never used", template.id, tab.name))

    findings.sort(key=lambda f: (f.severity, f.tab_name))
    return findings


def summary(findings: list[Finding]) -> str:
    """One-line rollup for a toast, e.g. ``2 broken · 3 unused``."""
    if not findings:
        return "library looks healthy"
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.kind] = counts.get(finding.kind, 0) + 1
    order = sorted(counts, key=lambda k: SEVERITY.get(k, 99))
    return " · ".join(f"{counts[k]} {k.replace('-', ' ')}" for k in order)
