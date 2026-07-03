"""Section-aware text chunking for rulebook RAG.

Pure functions — heavily unit-tested. Targets ~800 "tokens" (approximated as
chars/4) with overlap, cutting cleanly at section headings.
"""

from dataclasses import dataclass

TARGET_CHARS = 3200  # ~800 tokens
MIN_CHARS = 400
OVERLAP_CHARS = 480  # ~15%


@dataclass
class PageText:
    page: int  # 1-based
    text: str
    headings: list[str]  # headings that appear on this page, in order


@dataclass
class ChunkOut:
    text: str
    section_path: str
    page_start: int
    page_end: int


def chunk_pages(pages: list[PageText]) -> list[ChunkOut]:
    """Walk pages paragraph by paragraph, cutting chunks near TARGET_CHARS and
    labeling each chunk with the section heading it started under. Heading
    boundaries cut cleanly (no overlap carry); size-based cuts carry a small
    overlap tail for context continuity."""
    chunks: list[ChunkOut] = []
    buffer: list[str] = []
    buffer_len = 0
    section = ""  # heading currently in effect
    chunk_section = ""  # heading attributed to the chunk being built
    page_start = pages[0].page if pages else 1
    current_page = page_start

    def flush(end_page: int, carry_overlap: bool = True) -> None:
        nonlocal buffer, buffer_len, page_start
        text = "\n\n".join(buffer).strip()
        if len(text) >= 40:  # skip page-number crumbs
            chunks.append(
                ChunkOut(
                    text=text,
                    section_path=chunk_section,
                    page_start=page_start,
                    page_end=end_page,
                )
            )
        if carry_overlap and buffer:
            tail = buffer[-1][-OVERLAP_CHARS:]
            buffer = [tail] if len(tail) > 80 else []
        else:
            buffer = []
        buffer_len = sum(len(b) for b in buffer)
        page_start = end_page

    for page in pages:
        current_page = page.page
        headings = set(page.headings)
        for para in (p.strip() for p in page.text.split("\n\n")):
            if not para:
                continue
            if para in headings:
                if buffer_len >= MIN_CHARS:
                    flush(current_page, carry_overlap=False)
                section = para
                if not buffer:
                    chunk_section = section
                continue
            if not buffer:
                chunk_section = section
                page_start = current_page
            buffer.append(para)
            buffer_len += len(para)
            if buffer_len >= TARGET_CHARS:
                flush(current_page)

    if buffer_len:
        flush(current_page)
    return chunks
