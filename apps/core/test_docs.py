"""Keep the ADRs honest: indexed, well-formed, and pointing at code that still exists."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "docs" / "adr"
ADRS = sorted(p for p in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md") if not p.name.startswith("0000"))
FILE_HINT = re.compile(r"\.(py|json|yml|yaml|tsx|ts|md)$")


def test_there_are_adrs():
    assert len(ADRS) >= 10


@pytest.mark.parametrize("adr", ADRS, ids=lambda p: p.name)
def test_adr_is_well_formed(adr):
    text = adr.read_text()
    number = adr.name[:4]
    assert text.startswith(f"# {number}. "), "title must start with its number"
    assert re.search(r"^- \*\*Status:\*\* (Proposed|Accepted|Superseded by)", text, re.M)
    assert re.search(r"^- \*\*Date:\*\* \d{4}-\d{2}-\d{2}$", text, re.M)
    for heading in ("Context", "Decision", "Alternatives considered", "Consequences", "Code"):
        assert f"\n## {heading}" in text, f"missing section: {heading}"


def test_numbers_are_unique_and_contiguous():
    numbers = [int(p.name[:4]) for p in ADRS]
    assert numbers == list(range(1, len(numbers) + 1))


def test_index_lists_every_adr_and_links_resolve():
    index = (ADR_DIR / "README.md").read_text()
    for adr in ADRS:
        assert f"]({adr.name})" in index, f"{adr.name} is missing from the index"
    for target in re.findall(r"\]\(([^)#]+\.md)\)", index):
        assert (ADR_DIR / target).exists(), f"broken link in index: {target}"


@pytest.mark.parametrize("adr", ADRS, ids=lambda p: p.name)
def test_code_paths_cited_by_adr_exist(adr):
    """If a file an ADR points at is renamed or deleted, the ADR needs a look."""
    section = adr.read_text().split("\n## Code", 1)[1]
    for token in re.findall(r"`([^`]+)`", section):
        if "/" in token or FILE_HINT.search(token):
            assert (ROOT / token).exists(), f"{adr.name} cites a missing path: {token}"


# --- the design doc ---

DESIGN = ROOT / "docs" / "design.md"
SECTIONS = (
    "Summary",
    "Goals and non-goals",
    "Requirements and how they are met",
    "Architecture",
    "Data model",
    "Key flows",
    "Security and privacy",
    "Reliability and failure modes",
    "Performance and capacity",
    "Testing",
    "Risks and open questions",
    "Status",
    "Questions for reviewers",
)


def test_design_doc_has_the_sections_a_review_needs():
    text = DESIGN.read_text()
    for name in SECTIONS:
        assert re.search(rf"^## \d+\. {re.escape(name)}$", text, re.M), f"missing section: {name}"
    assert text.count("```mermaid") >= 5  # architecture, data model, three flows


def test_design_doc_links_and_code_paths_resolve():
    text = DESIGN.read_text()
    for target in re.findall(r"\]\(([^)#]+\.md)\)", text):
        assert (DESIGN.parent / target).exists(), f"broken link: {target}"
    for token in re.findall(r"`([^`]+)`", text):
        if token.split("/")[0] in {"apps", "config", "frontend", "observability", "contracts"} and (
            "/" in token
        ):
            assert (ROOT / token.rstrip("/")).exists(), f"design.md cites a missing path: {token}"


def test_design_doc_links_every_adr():
    text = DESIGN.read_text()
    for adr in ADRS:
        assert f"adr/{adr.name}" in text, f"design.md never references {adr.name}"
