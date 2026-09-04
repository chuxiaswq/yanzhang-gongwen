"""Offline bibliography import and export for common research formats."""

# ruff: noqa: RUF001 -- Chinese keyword delimiters use full-width punctuation.

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import cast

from yanzhang_academic.models import Author, BibliographicRecord, RecordType


class BibliographyParseError(ValueError):
    """Raised when a bibliography payload is structurally invalid."""


_BIBTEX_TYPE_MAP: dict[str, RecordType] = {
    "article": "article-journal",
    "book": "book",
    "inbook": "chapter",
    "incollection": "chapter",
    "inproceedings": "paper-conference",
    "conference": "paper-conference",
    "mastersthesis": "thesis",
    "phdthesis": "thesis",
    "techreport": "report",
    "misc": "document",
    "online": "webpage",
    "unpublished": "preprint",
}

_CSL_TYPE_MAP: dict[str, RecordType] = {
    "article-journal": "article-journal",
    "article": "article-journal",
    "book": "book",
    "chapter": "chapter",
    "paper-conference": "paper-conference",
    "report": "report",
    "thesis": "thesis",
    "webpage": "webpage",
    "post-weblog": "webpage",
    "manuscript": "preprint",
    "document": "document",
}

_RECORD_TO_BIBTEX: dict[RecordType, str] = {
    "article-journal": "article",
    "book": "book",
    "chapter": "incollection",
    "paper-conference": "inproceedings",
    "report": "techreport",
    "thesis": "phdthesis",
    "webpage": "online",
    "preprint": "unpublished",
    "document": "misc",
}

_RECORD_TO_RIS: dict[RecordType, str] = {
    "article-journal": "JOUR",
    "book": "BOOK",
    "chapter": "CHAP",
    "paper-conference": "CPAPER",
    "report": "RPRT",
    "thesis": "THES",
    "webpage": "ELEC",
    "preprint": "UNPB",
    "document": "GEN",
}


def _source_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_bibtex_value(value: str) -> str:
    result = value.strip()
    while len(result) >= 2 and (
        (result.startswith("{") and result.endswith("}"))
        or (result.startswith('"') and result.endswith('"'))
    ):
        result = result[1:-1].strip()
    replacements = {
        r"\&": "&",
        r"\_": "_",
        r"\%": "%",
        r"\#": "#",
        r"\{": "{",
        r"\}": "}",
        "~": " ",
    }
    for source, target in replacements.items():
        result = result.replace(source, target)
    return " ".join(result.split())


def _split_top_level(value: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    braces = 0
    quoted = False
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"' and braces == 0:
            quoted = not quoted
        elif not quoted:
            if character == "{":
                braces += 1
            elif character == "}":
                braces = max(0, braces - 1)
            elif character == delimiter and braces == 0:
                parts.append(value[start:index])
                start = index + 1
    parts.append(value[start:])
    return parts


def _find_bibtex_entries(payload: str) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    position = 0
    while True:
        marker = payload.find("@", position)
        if marker < 0:
            break
        header = re.match(r"@([A-Za-z]+)\s*([\{(])", payload[marker:])
        if header is None:
            position = marker + 1
            continue
        entry_type = header.group(1).lower()
        opening = header.group(2)
        closing = "}" if opening == "{" else ")"
        body_start = marker + header.end()
        depth = 1
        quoted = False
        escaped = False
        cursor = body_start
        while cursor < len(payload) and depth:
            character = payload[cursor]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = not quoted
            elif not quoted:
                if character == opening:
                    depth += 1
                elif character == closing:
                    depth -= 1
            cursor += 1
        if depth:
            raise BibliographyParseError("BibTeX 条目缺少闭合符号")
        body = payload[body_start : cursor - 1].strip()
        split = _split_top_level(body, ",")
        if not split or not split[0].strip():
            raise BibliographyParseError("BibTeX 条目缺少引用键")
        entries.append((entry_type, split[0].strip(), ",".join(split[1:])))
        position = cursor
    if not entries and payload.strip():
        raise BibliographyParseError("未发现有效的 BibTeX 条目")
    return entries


def _parse_bibtex_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for item in _split_top_level(body, ","):
        if not item.strip():
            continue
        key, separator, value = item.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise BibliographyParseError("BibTeX 字段格式无效")
        fields[key.strip().lower()] = _clean_bibtex_value(value)
    return fields


def _parse_person(value: str, *, sequence: str = "additional") -> Author:
    cleaned = _clean_bibtex_value(value)
    sequence_value = "first" if sequence == "first" else "additional"
    if "," in cleaned:
        family, given = (part.strip() for part in cleaned.split(",", 1))
        return Author(family=family, given=given, sequence=sequence_value)
    words = cleaned.split()
    if len(words) > 1 and all(ord(character) < 128 for character in cleaned):
        return Author(
            family=words[-1],
            given=" ".join(words[:-1]),
            sequence=sequence_value,
        )
    return Author(literal=cleaned, sequence=sequence_value)


def _parse_people(value: str) -> list[Author]:
    people = re.split(r"\s+and\s+", value, flags=re.I)
    return [
        _parse_person(person, sequence="first" if index == 0 else "additional")
        for index, person in enumerate(people)
        if person.strip()
    ]


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(?:1[0-9]{3}|2[0-9]{3})", value)
    return int(match.group(0)) if match else None


def parse_bibtex(payload: str) -> list[BibliographicRecord]:
    """Parse BibTeX without resolving macros or accessing the network."""

    records: list[BibliographicRecord] = []
    for entry_type, source_key, body in _find_bibtex_entries(payload):
        if entry_type in {"comment", "preamble", "string"}:
            continue
        fields = _parse_bibtex_fields(body)
        title = fields.get("title", "").strip()
        if not title:
            raise BibliographyParseError(f"BibTeX 条目 {source_key} 缺少题名")
        pages = fields.get("pages", "").replace("--", "-")
        record_text = f"@{entry_type}{{{source_key},{body}}}"
        records.append(
            BibliographicRecord(
                type=_BIBTEX_TYPE_MAP.get(entry_type, "document"),
                title=title,
                authors=_parse_people(fields.get("author", "")),
                editors=_parse_people(fields.get("editor", "")),
                issued_year=_parse_year(fields.get("year")),
                container_title=fields.get("journal", fields.get("booktitle", "")),
                publisher=fields.get("publisher", fields.get("institution", "")),
                publisher_place=fields.get("address", ""),
                volume=fields.get("volume", ""),
                issue=fields.get("number", ""),
                pages=pages,
                edition=fields.get("edition", ""),
                doi=fields.get("doi"),
                url=fields.get("url") or None,
                abstract=fields.get("abstract", ""),
                keywords=_split_keywords(fields.get("keywords", "")),
                language=fields.get("language", ""),
                import_source="bibtex",
                source_key=source_key,
                source_hash=_source_hash(record_text),
            )
        )
    return records


def _split_keywords(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;，；]", value) if part.strip()]


def _bibtex_escape(value: str) -> str:
    return value.replace("\\", r"\textbackslash ").replace("{", r"\{").replace("}", r"\}")


def _bibtex_people(authors: Sequence[Author]) -> str:
    names: list[str] = []
    for author in authors:
        if author.literal:
            names.append(author.literal)
        elif author.family and author.given:
            names.append(f"{author.family}, {author.given}")
        else:
            names.append(author.family or author.given)
    return " and ".join(names)


def export_bibtex(records: Sequence[BibliographicRecord]) -> str:
    """Export imported records as deterministic UTF-8 BibTeX."""

    blocks: list[str] = []
    used_keys: set[str] = set()
    for index, record in enumerate(records, start=1):
        key = _safe_bibtex_key(record.source_key or _default_citation_key(record, index))
        base_key = key
        duplicate = 2
        while key in used_keys:
            key = f"{base_key}{duplicate}"
            duplicate += 1
        used_keys.add(key)
        fields: list[tuple[str, str]] = [("title", record.title)]
        if record.authors:
            fields.append(("author", _bibtex_people(record.authors)))
        if record.editors:
            fields.append(("editor", _bibtex_people(record.editors)))
        if record.issued_year is not None:
            fields.append(("year", str(record.issued_year)))
        container_field = "journal" if record.type == "article-journal" else "booktitle"
        if record.container_title:
            fields.append((container_field, record.container_title))
        for field_name, value in (
            ("publisher", record.publisher),
            ("address", record.publisher_place),
            ("volume", record.volume),
            ("number", record.issue),
            ("pages", record.pages.replace("-", "--")),
            ("edition", record.edition),
            ("doi", record.doi or ""),
            ("url", record.url or ""),
            ("abstract", record.abstract),
            ("keywords", ", ".join(record.keywords)),
            ("language", record.language),
        ):
            if value:
                fields.append((field_name, value))
        lines = [f"@{_RECORD_TO_BIBTEX[record.type]}{{{key},"]
        lines.extend(f"  {name} = {{{_bibtex_escape(value)}}}," for name, value in fields)
        lines[-1] = lines[-1].rstrip(",")
        lines.append("}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _safe_bibtex_key(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_:+.-]", "", value)
    return cleaned or "reference"


def _default_citation_key(record: BibliographicRecord, index: int) -> str:
    family = record.authors[0].family if record.authors and record.authors[0].family else "ref"
    return f"{family}{record.issued_year or 'nd'}_{index}"


def parse_ris(payload: str) -> list[BibliographicRecord]:
    """Parse RIS records and preserve repeated authors and keywords."""

    raw_records: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line.strip():
            continue
        match = re.match(r"^([A-Z0-9]{2})\s*-\s?(.*)$", line)
        if match is None:
            if current:
                tag, value = current[-1]
                current[-1] = (tag, f"{value} {line.strip()}")
                continue
            raise BibliographyParseError(f"RIS 第 {line_number} 行格式无效")
        tag, value = match.groups()
        if tag == "TY" and current:
            raise BibliographyParseError("RIS 记录缺少 ER 结束标记")
        current.append((tag, value.strip()))
        if tag == "ER":
            raw_records.append(current)
            current = []
    if current:
        raise BibliographyParseError("RIS 记录缺少 ER 结束标记")
    if not raw_records and payload.strip():
        raise BibliographyParseError("未发现有效的 RIS 记录")

    records: list[BibliographicRecord] = []
    for pairs in raw_records:
        fields: dict[str, list[str]] = {}
        for tag, value in pairs:
            fields.setdefault(tag, []).append(value)
        title = _first(fields, "TI", "T1", "CT")
        if not title:
            raise BibliographyParseError("RIS 记录缺少题名")
        type_code = _first(fields, "TY").upper()
        ris_map: dict[str, RecordType] = {
            "JOUR": "article-journal",
            "JFULL": "article-journal",
            "BOOK": "book",
            "CHAP": "chapter",
            "CPAPER": "paper-conference",
            "CONF": "paper-conference",
            "RPRT": "report",
            "THES": "thesis",
            "ELEC": "webpage",
            "UNPB": "preprint",
        }
        authors = fields.get("AU", []) + fields.get("A1", [])
        editors = fields.get("ED", []) + fields.get("A2", [])
        start_page = _first(fields, "SP")
        end_page = _first(fields, "EP")
        pages = f"{start_page}-{end_page}" if start_page and end_page else start_page
        source_text = "\n".join(f"{tag}  - {value}" for tag, value in pairs)
        records.append(
            BibliographicRecord(
                type=ris_map.get(type_code, "document"),
                title=title,
                authors=[
                    _parse_person(person, sequence="first" if index == 0 else "additional")
                    for index, person in enumerate(authors)
                    if person
                ],
                editors=[_parse_person(person) for person in editors if person],
                issued_year=_parse_year(_first(fields, "PY", "Y1", "DA")),
                container_title=_first(fields, "JO", "JF", "T2", "JA"),
                publisher=_first(fields, "PB"),
                publisher_place=_first(fields, "CY"),
                volume=_first(fields, "VL"),
                issue=_first(fields, "IS"),
                pages=pages,
                doi=_first(fields, "DO") or None,
                url=_first(fields, "UR", "L1") or None,
                abstract=_first(fields, "AB", "N2"),
                keywords=list(dict.fromkeys(fields.get("KW", []))),
                language=_first(fields, "LA"),
                import_source="ris",
                source_key=_first(fields, "ID"),
                source_hash=_source_hash(source_text),
            )
        )
    return records


def _first(fields: Mapping[str, Sequence[str]], *keys: str) -> str:
    for key in keys:
        values = fields.get(key)
        if values:
            return values[0].strip()
    return ""


def export_ris(records: Sequence[BibliographicRecord]) -> str:
    """Export records as deterministic RIS."""

    lines: list[str] = []
    for record in records:
        lines.append(f"TY  - {_RECORD_TO_RIS[record.type]}")
        if record.source_key:
            lines.append(f"ID  - {record.source_key}")
        lines.append(f"TI  - {record.title}")
        lines.extend(f"AU  - {author.display_name(family_first=True)}" for author in record.authors)
        lines.extend(f"ED  - {editor.display_name(family_first=True)}" for editor in record.editors)
        if record.issued_year is not None:
            lines.append(f"PY  - {record.issued_year}")
        for tag, value in (
            ("JO", record.container_title),
            ("PB", record.publisher),
            ("CY", record.publisher_place),
            ("VL", record.volume),
            ("IS", record.issue),
        ):
            if value:
                lines.append(f"{tag}  - {value}")
        if record.pages:
            start, separator, end = record.pages.partition("-")
            lines.append(f"SP  - {start}")
            if separator and end:
                lines.append(f"EP  - {end}")
        for tag, value in (
            ("DO", record.doi or ""),
            ("UR", record.url or ""),
            ("AB", record.abstract),
            ("LA", record.language),
        ):
            if value:
                lines.append(f"{tag}  - {value}")
        lines.extend(f"KW  - {keyword}" for keyword in record.keywords)
        lines.extend(("ER  -", ""))
    return "\n".join(lines)


def parse_csl_json(
    payload: str | bytes | Mapping[str, object] | Sequence[Mapping[str, object]],
) -> list[BibliographicRecord]:
    """Parse a CSL-JSON object or array into imported records."""

    if isinstance(payload, bytes):
        text = payload.decode("utf-8-sig")
        raw = _load_json(text)
        raw_text = text
    elif isinstance(payload, str):
        raw = _load_json(payload)
        raw_text = payload
    elif isinstance(payload, Mapping):
        raw = payload
        raw_text = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
    else:
        raw = list(payload)
        raw_text = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(raw, Mapping):
        items: list[Mapping[str, object]] = [cast(Mapping[str, object], raw)]
    elif isinstance(raw, list) and all(isinstance(item, Mapping) for item in raw):
        items = [cast(Mapping[str, object], item) for item in raw]
    else:
        raise BibliographyParseError("CSL-JSON 顶层必须是对象或对象数组")

    records: list[BibliographicRecord] = []
    for index, item in enumerate(items):
        title = _as_text(item.get("title"))
        if not title:
            raise BibliographyParseError(f"CSL-JSON 第 {index + 1} 条记录缺少题名")
        year, month, day = _csl_date(item.get("issued"))
        item_text = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        raw_type = _as_text(item.get("type"))
        source_key = _as_text(item.get("id"))
        records.append(
            BibliographicRecord(
                type=_CSL_TYPE_MAP.get(raw_type, "document"),
                title=title,
                authors=_csl_people(item.get("author")),
                editors=_csl_people(item.get("editor")),
                issued_year=year,
                issued_month=month,
                issued_day=day,
                container_title=_as_text(item.get("container-title")),
                publisher=_as_text(item.get("publisher")),
                publisher_place=_as_text(item.get("publisher-place")),
                volume=_as_text(item.get("volume")),
                issue=_as_text(item.get("issue")),
                pages=_as_text(item.get("page")),
                edition=_as_text(item.get("edition")),
                doi=_as_text(item.get("DOI")) or None,
                url=_as_text(item.get("URL")) or None,
                abstract=_as_text(item.get("abstract")),
                keywords=_csl_keywords(item.get("keyword")),
                language=_as_text(item.get("language")),
                import_source="csl-json",
                source_key=source_key,
                source_hash=_source_hash(item_text if item_text else raw_text),
            )
        )
    return records


def _load_json(payload: str) -> object:
    try:
        return cast(object, json.loads(payload))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BibliographyParseError("CSL-JSON 内容格式无效") from exc


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "; ".join(_as_text(item) for item in value if _as_text(item))
    return ""


def _csl_people(value: object) -> list[Author]:
    if not isinstance(value, list):
        return []
    authors: list[Author] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        literal = _as_text(item.get("literal"))
        family = _as_text(item.get("family"))
        given = _as_text(item.get("given"))
        if literal or family or given:
            authors.append(
                Author(
                    literal=literal,
                    family=family,
                    given=given,
                    sequence="first" if index == 0 else "additional",
                )
            )
    return authors


def _csl_date(value: object) -> tuple[int | None, int | None, int | None]:
    if not isinstance(value, Mapping):
        return None, None, None
    raw_parts = value.get("date-parts")
    if not isinstance(raw_parts, list) or not raw_parts or not isinstance(raw_parts[0], list):
        return None, None, None
    parts = raw_parts[0]
    values: list[int | None] = []
    for index in range(3):
        item = parts[index] if index < len(parts) else None
        values.append(item if isinstance(item, int) and not isinstance(item, bool) else None)
    return values[0], values[1], values[2]


def _csl_keywords(value: object) -> list[str]:
    if isinstance(value, str):
        return _split_keywords(value)
    if isinstance(value, list):
        return [_as_text(item) for item in value if _as_text(item)]
    return []


def _csl_person(author: Author) -> dict[str, str]:
    if author.literal:
        return {"literal": author.literal}
    result: dict[str, str] = {}
    if author.family:
        result["family"] = author.family
    if author.given:
        result["given"] = author.given
    return result


def export_csl_json(records: Sequence[BibliographicRecord], *, indent: int = 2) -> str:
    """Export records as CSL-JSON while retaining stable local identifiers."""

    items: list[dict[str, object]] = []
    for record in records:
        item: dict[str, object] = {
            "id": record.source_key or record.id,
            "type": record.type,
            "title": record.title,
        }
        if record.authors:
            item["author"] = [_csl_person(author) for author in record.authors]
        if record.editors:
            item["editor"] = [_csl_person(editor) for editor in record.editors]
        date_parts = [
            part
            for part in (record.issued_year, record.issued_month, record.issued_day)
            if part is not None
        ]
        if date_parts:
            item["issued"] = {"date-parts": [date_parts]}
        for key, value in (
            ("container-title", record.container_title),
            ("publisher", record.publisher),
            ("publisher-place", record.publisher_place),
            ("volume", record.volume),
            ("issue", record.issue),
            ("page", record.pages),
            ("edition", record.edition),
            ("DOI", record.doi or ""),
            ("URL", record.url or ""),
            ("abstract", record.abstract),
            ("language", record.language),
        ):
            if value:
                item[key] = value
        if record.keywords:
            item["keyword"] = ", ".join(record.keywords)
        items.append(item)
    return json.dumps(items, ensure_ascii=False, indent=indent, sort_keys=True) + "\n"


__all__ = [
    "BibliographyParseError",
    "export_bibtex",
    "export_csl_json",
    "export_ris",
    "parse_bibtex",
    "parse_csl_json",
    "parse_ris",
]
