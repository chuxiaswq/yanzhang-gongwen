"""Transparent baseline citation renderers for imported records."""

# ruff: noqa: RUF001 -- Chinese citations and messages use full-width punctuation.

from __future__ import annotations

import re
from collections.abc import Sequence

from yanzhang_academic.models import Author, BibliographicRecord, CitationStyle


def format_bibliography(records: Sequence[BibliographicRecord], style: CitationStyle) -> list[str]:
    """Format a bibliography in input order using one baseline style."""

    _assert_unique_records(records)
    return [format_reference(record, style, index=index) for index, record in enumerate(records, 1)]


def format_reference(
    record: BibliographicRecord,
    style: CitationStyle,
    *,
    index: int = 1,
) -> str:
    """Format one already-imported record; no metadata is synthesized."""

    if index < 1:
        raise ValueError("index 必须大于等于 1")
    if style == "gb-t-7714":
        return _format_gb(record, index=index)
    if style == "apa":
        return _format_apa(record)
    if style == "mla":
        return _format_mla(record)
    if style == "chicago":
        return _format_chicago(record)
    raise ValueError(f"未知引文格式：{style}")


def format_in_text_citation(
    record: BibliographicRecord,
    style: CitationStyle,
    *,
    index: int = 1,
    locator: str = "",
) -> str:
    """Render a compact in-text citation linked to one imported record."""

    if index < 1:
        raise ValueError("index 必须大于等于 1")
    if style == "gb-t-7714":
        return f"[{index}]"
    author = _short_author(record, english=style in {"apa", "mla", "chicago"})
    year = str(record.issued_year or "n.d.")
    suffix = f", {locator}" if locator else ""
    if style == "apa":
        return f"({author}, {year}{suffix})"
    if style == "mla":
        locator_part = f" {locator}" if locator else ""
        return f"({author}{locator_part})"
    if style == "chicago":
        return f"({author} {year}{suffix})"
    raise ValueError(f"未知引文格式：{style}")


def _format_gb(record: BibliographicRecord, *, index: int) -> str:
    authors = _gb_authors(record.authors)
    marker = {
        "article-journal": "J",
        "book": "M",
        "chapter": "M",
        "paper-conference": "C",
        "report": "R",
        "thesis": "D",
        "webpage": "EB/OL",
        "preprint": "J/OL",
        "document": "Z",
    }[record.type]
    prefix = f"[{index}] "
    author_part = f"{authors}. " if authors else ""
    title = f"{record.title}[{marker}]"
    year = str(record.issued_year) if record.issued_year is not None else "日期不详"
    if record.type == "article-journal":
        source = record.container_title
        volume_issue = _volume_issue(record)
        details = ", ".join(part for part in (year, volume_issue) if part)
        if record.pages:
            details = f"{details}: {record.pages}" if details else record.pages
        body = f"{author_part}{title}. {source}"
        if details:
            body += f", {details}"
    elif record.type in {"book", "chapter"}:
        publication = ": ".join(part for part in (record.publisher_place, record.publisher) if part)
        if publication:
            body = f"{author_part}{title}. {publication}, {year}"
        else:
            body = f"{author_part}{title}. {year}"
        if record.pages:
            body += f": {record.pages}"
    else:
        source = record.container_title or record.publisher
        if source:
            body = f"{author_part}{title}. {source}, {year}"
        else:
            body = f"{author_part}{title}. {year}"
    if record.doi:
        body += f". DOI:{record.doi}"
    elif record.url:
        body += f". {record.url}"
    return _finish(prefix + body)


def _format_apa(record: BibliographicRecord) -> str:
    authors = _apa_authors(record.authors)
    year = str(record.issued_year) if record.issued_year is not None else "n.d."
    prefix = f"{authors} ({year}). " if authors else f"({year}). "
    body = prefix + f"{record.title}."
    if record.container_title:
        body += f" {record.container_title}"
        if record.volume:
            body += f", {record.volume}"
        if record.issue:
            body += f"({record.issue})"
        if record.pages:
            body += f", {record.pages}"
        body += "."
    elif record.publisher:
        body += f" {record.publisher}."
    link = _persistent_link(record)
    if link:
        body += f" {link}"
    return _finish(body)


def _format_mla(record: BibliographicRecord) -> str:
    authors = _mla_authors(record.authors)
    body = f'{authors}. "{record.title}."' if authors else f'"{record.title}."'
    if record.container_title:
        body += f" {record.container_title},"
    if record.volume:
        body += f" vol. {record.volume},"
    if record.issue:
        body += f" no. {record.issue},"
    if record.issued_year is not None:
        body += f" {record.issued_year},"
    if record.pages:
        body += f" pp. {record.pages},"
    if record.publisher and not record.container_title:
        body += f" {record.publisher},"
    link = _persistent_link(record)
    if link:
        body += f" {link}."
    return _finish(body.rstrip(","))


def _format_chicago(record: BibliographicRecord) -> str:
    authors = _chicago_authors(record.authors)
    body = f'{authors}. "{record.title}."' if authors else f'"{record.title}."'
    if record.container_title:
        body += f" {record.container_title}"
        if record.volume:
            body += f" {record.volume}"
        if record.issue:
            body += f", no. {record.issue}"
        if record.issued_year is not None:
            body += f" ({record.issued_year})"
        if record.pages:
            body += f": {record.pages}"
        body += "."
    else:
        publication = ": ".join(part for part in (record.publisher_place, record.publisher) if part)
        if publication:
            body += f" {publication}"
        if record.issued_year is not None:
            body += f", {record.issued_year}"
        body += "."
    link = _persistent_link(record)
    if link:
        body += f" {link}."
    return _finish(body)


def _gb_authors(authors: Sequence[Author]) -> str:
    names = [author.display_name(family_first=True) for author in authors[:3]]
    if len(authors) > 3:
        names.append("等")
    return ", ".join(names)


def _apa_authors(authors: Sequence[Author]) -> str:
    names = [_apa_name(author) for author in authors[:20]]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + ", & " + names[-1]


def _apa_name(author: Author) -> str:
    if author.literal:
        return author.literal
    initials = " ".join(f"{part[0].upper()}." for part in re.findall(r"[A-Za-z]+", author.given))
    return ", ".join(part for part in (author.family, initials) if part)


def _mla_authors(authors: Sequence[Author]) -> str:
    if not authors:
        return ""
    first = authors[0]
    if first.literal:
        result = first.literal
    else:
        result = ", ".join(part for part in (first.family, first.given) if part)
    return f"{result}, et al" if len(authors) > 1 else result


def _chicago_authors(authors: Sequence[Author]) -> str:
    if not authors:
        return ""
    names = []
    for index, author in enumerate(authors[:3]):
        names.append(author.display_name(family_first=index == 0))
    result = ", ".join(names)
    return f"{result}, et al" if len(authors) > 3 else result


def _short_author(record: BibliographicRecord, *, english: bool) -> str:
    if not record.authors:
        return "Anonymous" if english else "佚名"
    first = record.authors[0]
    name = first.family or first.literal or first.given
    if len(record.authors) > 2:
        return f"{name} et al." if english else f"{name}等"
    if len(record.authors) == 2:
        second = record.authors[1]
        second_name = second.family or second.literal or second.given
        return f"{name} & {second_name}" if english else f"{name}、{second_name}"
    return name


def _persistent_link(record: BibliographicRecord) -> str:
    if record.doi:
        return f"https://doi.org/{record.doi}"
    return record.url or ""


def _volume_issue(record: BibliographicRecord) -> str:
    if record.volume and record.issue:
        return f"{record.volume}({record.issue})"
    return record.volume or (f"({record.issue})" if record.issue else "")


def _finish(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    cleaned = re.sub(r"\s+([,.:;])", r"\1", cleaned)
    return cleaned if cleaned.endswith((".", "。")) else f"{cleaned}."


def _assert_unique_records(records: Sequence[BibliographicRecord]) -> None:
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            raise ValueError(f"文献记录 ID 重复：{record.id}")
        seen.add(record.id)


__all__ = ["format_bibliography", "format_in_text_citation", "format_reference"]
