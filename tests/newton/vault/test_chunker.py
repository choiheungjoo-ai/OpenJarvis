"""Tests for newton.vault.chunker."""

from __future__ import annotations

from newton.vault.chunker import Chunk, chunk_text, estimate_tokens


def test_empty_body():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_no_heading_single_chunk():
    chunks = chunk_text("Just a paragraph with no headings at all.")
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].heading is None


def test_split_by_h2():
    body = "# Title\n\nIntro text.\n\n## Section A\n\nAlpha.\n\n## Section B\n\nBeta."
    chunks = chunk_text(body)
    # preamble (# Title + Intro) + Section A + Section B = 3
    assert len(chunks) == 3
    headings = [c.heading for c in chunks]
    assert headings[0] is None  # preamble before first ## heading
    assert "Section A" in headings[1]
    assert "Section B" in headings[2]


def test_indices_sequential():
    body = "## A\n\na\n\n## B\n\nb\n\n## C\n\nc"
    chunks = chunk_text(body)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_large_section_subsplit_with_overlap():
    # Build a section well over the token budget from many sentences.
    sentences = " ".join(f"Sentence number {i} has some words." for i in range(300))
    body = f"## Big\n\n{sentences}"
    chunks = chunk_text(body, max_tokens=100, overlap_tokens=20)
    assert len(chunks) > 1
    # All sub-chunks keep the section heading.
    assert all("Big" in c.heading for c in chunks)
    # Overlap: consecutive chunks share some trailing/leading text.
    # (At least one adjacent pair shares a sentence fragment.)
    shared = any(
        chunks[i].text.split()[-3:]
        and any(w in chunks[i + 1].text for w in chunks[i].text.split()[-3:])
        for i in range(len(chunks) - 1)
    )
    assert shared


def test_estimate_tokens_english_and_cjk():
    assert estimate_tokens("hello world") == 2
    # Korean: words + per-CJK-char weighting makes it larger than word count.
    ko = estimate_tokens("안녕하세요 세계")
    assert ko > 2


def test_small_section_not_split():
    body = "## Small\n\nOne short sentence here."
    chunks = chunk_text(body, max_tokens=800)
    assert len(chunks) == 1


def test_chunk_dataclass_fields():
    c = Chunk(index=0, text="x", heading="## H")
    assert c.index == 0
    assert c.text == "x"
    assert c.heading == "## H"
