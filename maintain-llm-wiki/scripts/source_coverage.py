#!/usr/bin/env python3
"""Where claim locators point inside registered sources, and which evidence no claim points to.

A maintenance-only library for lint_wiki.py, build_graph.py and
validate_extraction.py. It only reads: it takes the extraction text lint has
already parsed and the claim locators, and returns plain data. It has no
command line, writes nothing and takes no lock. The search core and the
exported knowledge skills never import it.

A unit of a source is what a canonical locator can name: a page or slide when
the extraction has `<!-- page: N -->` / `<!-- slide: N -->` markers on a line
of their own, otherwise a section (one per heading block), otherwise the whole
document. Text before the first marker or heading, segments without text and
the two headings register_source.py puts in front of an extraction belong to no
unit. Neither does the own text of a heading whose section spans every other
section (an extraction's title above its chapters): only `section=` of that
heading or `document` could name it, and both are broad citations, so it could
never count as cited.

Canonical locators are `page=N`, `page=A-B`, `slide=N`, `slide=A-B`,
`section=...`, `heading=...`, `sheet=...`, `timestamp=...` and `document`.
Every other spelling (`S. 12`, `paragraph=4`) stays allowed but is unchecked:
counted, never warned. A locator that resolves to every unit of a source with
at least two units credits nothing and counts as a broad citation. Coverage
counts only citations of active and disputed claims; resolution is checked for
every claim.

The marker syntax and the fence rule are the scan's (`search_core.PAGE_MARKER`,
`search_core.FENCE`: a line starting with three backticks or three tildes after
at most three spaces opens or closes a fence, and a marker or heading inside
one counts for nothing), so the search's exhaustive scan, lint, the reading
views and the preflight read the same comment. They differ in one deliberate
point: the scan also follows a marker that stands inside a line (it moves the
locator for the text after it, so an exhaustive hit names the page it was
printed on), while lint, coverage and the reading views only count a marker on
a line of its own (`PAGE_MARKER` here).
The preflight warns about inline markers, so such an extraction is registered
as `partial` and its `page=` citations do not resolve until it is repaired.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple, Optional

import search_core

#: The scan's marker comment anywhere in a line; the preflight uses it to find inline markers.
ANY_MARKER = search_core.PAGE_MARKER
#: A page or slide marker on a line of its own (after stripping): kind and value.
PAGE_MARKER = re.compile(rf"^(?:{search_core.PAGE_MARKER.pattern})$", re.IGNORECASE)
#: The scan's fence line, matched on the unstripped line: three backticks or tildes after at most three spaces.
FENCE = search_core.FENCE
#: An ATX heading: its level and its text without closing hashes.
HEADING = re.compile(r"^(#{1,6})(?:\s+(.*?))?(?:\s+#+)?\s*$")
KEYED = re.compile(r"^([A-Za-z]+)\s*=\s*(.*)$")
NUMBER = re.compile(r"^\d+$")
NUMBER_RANGE = re.compile(r"^(\d+)\s*[-–—]\s*(\d+)$")
NUMBER_LIST = re.compile(r"^\d+\s*[,;]\s*\d+")
NUMBER_THEN_TEXT = re.compile(r"^(\d+)\b\s*\S")
#: A leading enumeration of a folded heading: "§ 3 ", "4.1 ", "iv. ", "b) ".
ENUMERATION = re.compile(r"^(?:§+ )?(?:\d+(?:\.\d+)*[a-z]?\.?|[ivxlcdm]+\.|[a-z]\))\s+")
#: A time stamp in extraction text, never part of a longer one.
STAMP = re.compile(r"(?<![\d:])(\d{1,2}(?::\d{2}){1,2}(?:[.,]\d{1,3})?)(?![\d:])")
STAMP_VALUE = re.compile(r"^\d{1,2}(?::\d{2}){1,2}(?:[.,]\d{1,3})?$")
WORD = re.compile(r"\w")
LOCATOR_FORMS = {
    "page": "page", "slide": "slide", "section": "section", "heading": "section",
    "sheet": "section", "timestamp": "timestamp",
}
WRAPPER_HEADING = "## Extracted content"
COVERAGE_FORMAT = "lmwiki-source-coverage/1"
ASSESSED_STATUSES = frozenset({"active", "partial"})
COUNTING_CLAIMS = frozenset({"active", "disputed"})
SOURCES_LISTED, UNITS_LISTED, UNCHECKED_LISTED, MARKS_LISTED = 50, 20, 20, 10


class Heading(NamedTuple):
    level: int
    text: str
    line: int
    folded: str
    bare: str


class Structure(NamedTuple):
    """What a locator can name in one extraction. It keeps no source text."""

    unit_kind: str          # page | slide | section | document | empty
    units: tuple            # unit labels in order of first appearance
    markers: tuple          # (kind, value) in order of first appearance
    headings: tuple         # Heading
    heading_units: tuple    # per heading: frozenset of the units its section (with subsections) spans
    stamps: tuple           # (unit, frozenset of time stamps); unit "" for text that belongs to no unit


class Locator(NamedTuple):
    form: str               # page | slide | section | timestamp | document | unchecked
    key: str
    value: str
    start: Optional[int]
    end: Optional[int]


class Resolution(NamedTuple):
    state: str              # resolved | unresolved | unchecked
    units: frozenset
    reason: str
    missing_markers: str


def fold(text: str) -> str:
    """A heading or section value as compared: no emphasis or code marks, casefolded, accents removed, `§ ` spaced."""
    plain = search_core.normalized(text.replace("*", "").replace("`", ""))
    plain = re.sub(r"§\s*", "§ ", plain)
    return " ".join(plain.split()).rstrip(":.").rstrip()


def bare(folded: str) -> str:
    return ENUMERATION.sub("", folded, count=1)


def source_structure(body: str, first_line: int = 1) -> Structure:
    """The units, markers, headings and time stamps of an extraction body (pure).

    `body` is the text after the frontmatter, `first_line` the file line number
    of its first line, so heading line numbers are file line numbers.
    """
    lines = list(enumerate(body.splitlines(), first_line))
    content = [index for index, (_, line) in enumerate(lines) if line.strip()]
    if (
        len(content) >= 2
        and lines[content[0]][1].strip().startswith("# ")
        and lines[content[1]][1].strip() == WRAPPER_HEADING
    ):
        lines = lines[content[1] + 1:]
    headings: list[Heading] = []
    markers: list[tuple[str, str]] = []
    segments: list[tuple[Optional[tuple[str, str]], Optional[int], frozenset]] = []
    marker: Optional[tuple[str, str]] = None
    heading: Optional[int] = None
    fenced = False
    has_text = False
    stamps: set[str] = set()
    # Time stamps of segments without text (a stamped heading directly above the next one).
    loose_stamps: set[str] = set()

    def flush() -> None:
        if has_text:
            segments.append((marker, heading, frozenset(stamps)))
        else:
            loose_stamps.update(stamps)

    for number, raw in lines:
        line = raw.strip()
        if FENCE.match(raw):
            fenced = not fenced
            has_text = True
            continue
        if not fenced:
            found = PAGE_MARKER.match(line) if line.startswith("<!--") else None
            if found:
                flush()
                marker = (found.group(1).casefold(), found.group(2).strip())
                if marker not in markers:
                    markers.append(marker)
                has_text, stamps = False, set()
                continue
            found = HEADING.match(line) if line.startswith("#") else None
            if found and WORD.search(found.group(2) or ""):
                flush()
                words = found.group(2).strip()
                folded = fold(words)
                headings.append(Heading(len(found.group(1)), words, number, folded, bare(folded)))
                heading = len(headings) - 1
                # A transcript may carry its time stamps in headings ("## 00:12:30 Preise").
                has_text, stamps = False, set(STAMP.findall(words)) if ":" in words else set()
                continue
        if WORD.search(line):
            has_text = True
            if ":" in line:
                stamps.update(STAMP.findall(line))
    flush()

    if markers:
        unit_kind = "page" if any(kind == "page" for kind, _ in markers) else "slide"
    elif headings:
        unit_kind = "section"
    elif segments:
        unit_kind = "document"
    else:
        unit_kind = "empty"
    counts: dict[str, int] = {}
    for item in headings:
        counts[item.text] = counts.get(item.text, 0) + 1

    def label(seg_marker: Optional[tuple[str, str]], seg_heading: Optional[int]) -> Optional[str]:
        if unit_kind in ("page", "slide"):
            return f"{seg_marker[0]}={seg_marker[1]}" if seg_marker else None
        if unit_kind == "section":
            if seg_heading is None:
                return None
            item = headings[seg_heading]
            return f"section={item.text}" + (f" (line {item.line})" if counts[item.text] > 1 else "")
        return "document"

    labelled = [(label(m, h), h, s) for m, h, s in segments]
    # The end (exclusive) of each heading's section with its subsections.
    ends: list[int] = []
    for index, item in enumerate(headings):
        end = index + 1
        while end < len(headings) and headings[end].level > item.level:
            end += 1
        ends.append(end)
    if unit_kind == "section":
        # The own text of a heading whose section spans every other section (an
        # extraction's title above its chapters) belongs to no unit, like text
        # before the first heading: only section= of that heading or document
        # could name it, and both are broad. Each heading has at most one segment
        # here, and only the first heading with text can span all others; a chain
        # of single chapters gives up one spanning level after the other.
        with_text = sorted({h for unit, h, _ in labelled if unit is not None})
        spanning = 0
        while len(with_text) - spanning >= 2 and ends[with_text[spanning]] > with_text[-1]:
            spanning += 1
        if spanning:
            titles = set(with_text[:spanning])
            labelled = [(None if h in titles else unit, h, s) for unit, h, s in labelled]
    units: list[str] = []
    for unit, _, _ in labelled:
        if unit is not None and unit not in units:
            units.append(unit)
    by_heading: dict[int, list[str]] = {}
    for unit, h, _ in labelled:
        if unit is not None and h is not None:
            by_heading.setdefault(h, []).append(unit)
    heading_units = [
        frozenset(unit for h in range(index, ends[index]) for unit in by_heading.get(h, ()))
        for index in range(len(headings))
    ]
    # A time stamp outside every unit still resolves a timestamp= locator, which then credits nothing.
    stamp_map: dict[str, frozenset] = {"": frozenset(loose_stamps)} if loose_stamps else {}
    for unit, _, found_stamps in labelled:
        if found_stamps:
            stamp_map[unit or ""] = stamp_map.get(unit or "", frozenset()) | found_stamps
    return Structure(unit_kind, tuple(units), tuple(markers), tuple(headings), tuple(heading_units),
                     tuple(sorted(stamp_map.items())))


def parse_locator(locator: str) -> Locator:
    """The canonical form of a claim locator, or form `unchecked` for any other spelling (pure)."""
    text = locator.strip()
    if text.casefold() == "document":
        return Locator("document", "document", "", None, None)
    keyed = KEYED.match(text)
    if not keyed or keyed.group(1).casefold() not in LOCATOR_FORMS:
        return Locator("unchecked", "", text, None, None)
    key = keyed.group(1).casefold()
    value = keyed.group(2).strip()
    form = LOCATOR_FORMS[key]
    start = end = None
    if form in ("page", "slide"):
        if NUMBER.match(value):
            start = end = int(value)
        else:
            span = NUMBER_RANGE.match(value)
            if span:
                start, end = int(span.group(1)), int(span.group(2))
    return Locator(form, key, value, start, end)


def compress(values: list[str]) -> list[str]:
    """Consecutive integer values as one `A-B` item, everything else as written, in order (pure)."""
    out: list[str] = []
    run: list[str] = []
    for value in values + [None]:
        if value is not None and value.isdecimal() and run and int(value) == int(run[-1]) + 1:
            run.append(value)
            continue
        if run:
            out.append(run[0] if len(run) == 1 else f"{run[0]}-{run[-1]}")
            run = []
        if value is None:
            break
        if value.isdecimal():
            run = [value]
        else:
            out.append(value)
    return out


def _listing(values: list[str]) -> str:
    items = compress(values)
    shown = ", ".join(items[:MARKS_LISTED])
    return shown + (f" and {len(items) - MARKS_LISTED} more" if len(items) > MARKS_LISTED else "")


def _resolve_marker(locator: Locator, structure: Structure) -> Resolution:
    nothing: frozenset = frozenset()
    kind = locator.form
    present = [value for marker_kind, value in structure.markers if marker_kind == kind]
    if not present:
        return Resolution("unresolved", nothing, f"the extraction has no {kind} markers", kind)
    numeric: dict[int, list[str]] = {}
    for value in present:
        # isdecimal, not isdigit: int() refuses superscript and circled digits such as "²".
        if value.isdecimal():
            numeric.setdefault(int(value), []).append(value)
    if locator.start is not None:
        if locator.start > locator.end:
            return Resolution(
                "unresolved", nothing,
                f"the range {locator.value} is reversed; write {kind}={locator.end}-{locator.start}", "",
            )
        if locator.start in numeric and locator.end in numeric:
            names = {
                f"{kind}={value}"
                for number, values in numeric.items() if locator.start <= number <= locator.end
                for value in values
            }
            return Resolution("resolved", frozenset(unit for unit in structure.units if unit in names), "", "")
    wanted = [value for value in present if value.casefold() == locator.value.casefold()]
    if wanted:
        names = {f"{kind}={value}" for value in wanted}
        return Resolution("resolved", frozenset(unit for unit in structure.units if unit in names), "", "")
    if locator.start is None:
        if NUMBER_LIST.match(locator.value):
            return Resolution("unresolved", nothing, f"write one entry per {kind}, or a range such as {kind}=3-5", "")
        lead = NUMBER_THEN_TEXT.match(locator.value)
        if lead:
            return Resolution(
                "unresolved", nothing,
                f"{locator.value!r} is not a {kind} marker value; write {kind}={lead.group(1)} and keep "
                "further detail in the claim text", "",
            )
    return Resolution("unresolved", nothing, f"the extraction marks {kind}s {_listing(present)}", "")


def _resolve_section(locator: Locator, structure: Structure) -> Resolution:
    nothing: frozenset = frozenset()
    target = fold(locator.value)
    if not target:
        return Resolution("unresolved", nothing, f"the locator names no {locator.key}", "")
    headings = structure.headings
    hits = [index for index, item in enumerate(headings) if item.folded == target]
    if not hits:
        hits = [index for index, item in enumerate(headings) if item.bare != item.folded and item.bare == target]
        if len(hits) > 1:
            return Resolution(
                "unresolved", nothing,
                f"{len(hits)} headings match {locator.value!r}; cite the full heading with its number", "",
            )
    if not hits:
        prefix = target + " "
        hits = [
            index for index, item in enumerate(headings)
            if item.folded.startswith(prefix) or (item.bare != item.folded and item.bare.startswith(prefix))
        ]
        if len(hits) > 1:
            return Resolution(
                "unresolved", nothing, f"{len(hits)} headings begin with {locator.value!r}; cite the full heading", "",
            )
    if not hits:
        return Resolution("unresolved", nothing, f"no heading of the extraction matches {locator.value!r}", "")
    covered: set[str] = set()
    for index in hits:
        covered |= structure.heading_units[index]
    return Resolution("resolved", frozenset(covered), "", "")


def resolve(locator: Locator, structure: Structure) -> Resolution:
    """Whether a parsed locator names a place in the extraction, and which units it covers (pure).

    An unresolved resolution carries the reason lint prints; `missing_markers`
    names the marker kind when the extraction has none of that kind at all.
    """
    nothing: frozenset = frozenset()
    if locator.form == "unchecked":
        return Resolution("unchecked", nothing, "", "")
    if locator.form == "document":
        return Resolution("resolved", frozenset(structure.units), "", "")
    if not locator.value:
        return Resolution("unresolved", nothing, f"the locator names no {locator.key}", "")
    if locator.form in ("page", "slide"):
        return _resolve_marker(locator, structure)
    if locator.form == "section":
        return _resolve_section(locator, structure)
    value = locator.value.strip("[]() ")
    if not STAMP_VALUE.match(value):
        return Resolution("unresolved", nothing, f"{locator.value!r} is not a time stamp such as 00:12:30 or 12:30", "")
    hits = [unit for unit, found in structure.stamps if value in found]
    if not hits:
        return Resolution("unresolved", nothing, f"the extraction does not contain the time stamp {value!r}", "")
    return Resolution("resolved", frozenset(unit for unit in hits if unit), "", "")


def _unit_labels(open_units: list[str], unit_kind: str) -> list[tuple[str, int]]:
    """Uncited unit labels in source order, consecutive integer pages or slides as one range, with their sizes."""
    if unit_kind not in ("page", "slide"):
        return [(unit, 1) for unit in open_units]
    out: list[tuple[str, int]] = []
    run: list[tuple[str, str]] = []

    def close() -> None:
        if run:
            kind = run[0][0]
            out.append((f"{kind}={run[0][1]}" if len(run) == 1 else f"{kind}={run[0][1]}-{run[-1][1]}", len(run)))

    for unit in open_units:
        kind, value = unit.split("=", 1)
        if run and kind == run[-1][0] and value.isdecimal() and int(value) == int(run[-1][1]) + 1:
            run.append((kind, value))
            continue
        close()
        run = [(kind, value)] if value.isdecimal() else []
        if not run:
            out.append((unit, 1))
    close()
    return out


def coverage_stats(sources: list[dict[str, Any]], citations: list[dict[str, Any]]) -> dict[str, Any]:
    """The `stats.source_coverage` block of the lint report (pure and deterministic).

    `sources` holds every registered source: source_id, path, title, status and
    its Structure, or None when its file is missing or did not parse.
    `citations` holds every claim entry without an entry-level error whose
    source parsed: page, claim_id, claim_status, source_id, entry, resolution.
    """
    structures = {item["source_id"]: item["structure"] for item in sources}
    counts = {"resolved": 0, "unresolved": 0, "unchecked": 0}
    unchecked: list[dict[str, str]] = []
    grouped: dict[tuple[str, str], set[str]] = {}
    per_source: dict[str, dict[str, Any]] = {}
    for citation in citations:
        resolution = citation["resolution"]
        counts[resolution.state] += 1
        if resolution.state == "unchecked":
            unchecked.append({"page": citation["page"], "claim_id": citation["claim_id"], "entry": citation["entry"]})
        if resolution.missing_markers:
            grouped.setdefault((citation["source_id"], resolution.missing_markers), set()).add(citation["claim_id"])
        if citation["claim_status"] not in COUNTING_CLAIMS:
            continue
        entry = per_source.setdefault(citation["source_id"], {"citations": 0, "broad": 0, "unchecked": 0, "units": set()})
        entry["citations"] += 1
        if resolution.state == "unchecked":
            entry["unchecked"] += 1
        if resolution.state != "resolved":
            continue
        structure = structures.get(citation["source_id"])
        all_units = set(structure.units) if structure else set()
        if len(all_units) >= 2 and set(resolution.units) == all_units:
            entry["broad"] += 1
        else:
            entry["units"] |= resolution.units
    assessed = [item for item in sources if item["structure"] is not None and item["status"] in ASSESSED_STATUSES]
    listed: list[dict[str, Any]] = []
    by_source: dict[str, list[int]] = {}
    units_total = units_cited = uncited = broad_total = 0
    empty: dict[str, Any] = {"citations": 0, "broad": 0, "unchecked": 0, "units": set()}
    for item in assessed:
        structure = item["structure"]
        cited = per_source.get(item["source_id"], empty)
        units = list(structure.units)
        open_units = [unit for unit in units if unit not in cited["units"]]
        cited_units = len(units) - len(open_units)
        units_total += len(units)
        units_cited += cited_units
        broad_total += cited["broad"]
        if cited["citations"]:
            by_source[item["source_id"]] = [len(units), cited_units, cited["citations"], cited["broad"], cited["unchecked"]]
        else:
            uncited += 1
        if not open_units and cited["citations"]:
            continue
        labels = _unit_labels(open_units, structure.unit_kind)
        shown = labels[:UNITS_LISTED]
        listed.append({
            "source_id": item["source_id"], "path": item["path"], "title": item["title"], "status": item["status"],
            "unit_kind": structure.unit_kind, "units": len(units), "cited_units": cited_units,
            "uncited_units": [label for label, _ in shown],
            "uncited_units_omitted": len(open_units) - sum(size for _, size in shown),
            "citations": cited["citations"], "broad_citations": cited["broad"], "unchecked_citations": cited["unchecked"],
        })
    listed.sort(key=lambda entry: (entry["citations"] > 0, entry["path"], entry["source_id"]))
    paths = {item["source_id"]: item["path"] for item in sources}
    unchecked.sort(key=lambda entry: (entry["page"], entry["claim_id"], entry["entry"]))
    return {
        "format": COVERAGE_FORMAT,
        "sources_assessed": len(assessed),
        "sources_not_assessed": len(sources) - len(assessed),
        "sources_uncited": uncited,
        "units_total": units_total,
        "units_cited": units_cited,
        "broad_citations": broad_total,
        "locators": counts,
        "by_source": dict(sorted(by_source.items())),
        "sources": listed[:SOURCES_LISTED],
        "sources_omitted": max(0, len(listed) - SOURCES_LISTED),
        "unchecked_examples": unchecked[:UNCHECKED_LISTED],
        "unresolved_without_markers": [
            {"source_id": source_id, "path": paths.get(source_id, ""), "kind": kind, "claim_ids": sorted(ids)}
            for (source_id, kind), ids in sorted(grouped.items(), key=lambda item: (paths.get(item[0][0], ""), item[0][1], item[0][0]))
        ],
    }
