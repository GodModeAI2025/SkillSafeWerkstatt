#!/usr/bin/env python3
"""Build an offline interactive graph from Markdown files and wikilinks."""

from __future__ import annotations

import argparse
import html
import json
import os
import posixpath
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Optional
from urllib.parse import quote
from uuid import uuid4

from design_contract import CLUSTER_COLORS
from frontmatter_contract import FrontmatterError, parse_document
from wiki_lock import require_lock


WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
CLUSTER_HEADING = re.compile(r"^##\s+([a-z0-9]+(?:-[a-z0-9]+)*)\s*$")
CLUSTER_FIELD = re.compile(r"^-\s+([A-Za-z]+):\s*(.*)$")
CLAIM_BLOCK = re.compile(
    r"<!--\s*claim\s*\n(?P<meta>.*?)-->\s*(?P<text>.*?)\s*<!--\s*/claim\s*-->",
    re.DOTALL | re.IGNORECASE,
)
PAGE_MARKER = re.compile(r"^<!--\s*(page|slide)\s*:\s*([^>]+?)\s*-->$", re.IGNORECASE)
CLAIM_SENTINEL = re.compile(r"^@@LMWIKI_CLAIM_(\d+)@@$")
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_CLUSTER_COLORS = CLUSTER_COLORS


def frontmatter(text: str, source: str) -> dict[str, Any]:
    try:
        return parse_document(text, source).data
    except FrontmatterError as exc:
        raise SystemExit(str(exc)) from exc


def link_target(raw: str) -> str:
    value = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return value.removesuffix(".md").lstrip("./")


def graph_safe_target(raw: str) -> str:
    value = raw.split("|", 1)[0].split("#", 1)[0].strip()
    if value.lower().startswith("file:") or value.startswith(("~/", "~\\")):
        return "<non-portable-local-reference>"
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        return "<non-portable-local-reference>"
    return link_target(raw)


def quoted_route(route: PurePosixPath) -> str:
    return "/".join(quote(part, safe="") for part in route.parts)


def raw_file_href(relative: Path) -> str:
    route = PurePosixPath(posixpath.relpath(relative.as_posix(), start="graph"))
    return quoted_route(route)


def reader_output(relative: Path) -> Path:
    return Path("graph/pages") / relative.with_suffix(".html")


def reader_href(relative: Path) -> str:
    return quoted_route(PurePosixPath("pages") / PurePosixPath(relative.with_suffix(".html").as_posix()))


def strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return text
    return "\n".join(lines[end + 1 :]).lstrip()


def inline_markup(text: str, current_output: Path, page_outputs: dict[str, Path]) -> str:
    def plain(value: str) -> str:
        escaped = html.escape(value)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)

        def external_link(match: re.Match[str]) -> str:
            label, url = match.group(1), html.unescape(match.group(2))
            if not url.startswith(("https://", "http://", "mailto:")):
                return match.group(0)
            return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{label}</a>'

        return re.sub(r"\[([^\]]+)\]\((https?://[^)]+|mailto:[^)]+)\)", external_link, escaped)

    rendered: list[str] = []
    cursor = 0
    for match in WIKILINK.finditer(text):
        rendered.append(plain(text[cursor : match.start()]))
        raw = match.group(1)
        destination = link_target(raw)
        label = raw.split("|", 1)[1].strip() if "|" in raw else destination.rsplit("/", 1)[-1].replace("-", " ")
        output = page_outputs.get(destination)
        if output:
            relative = PurePosixPath(
                posixpath.relpath(output.as_posix(), start=current_output.parent.as_posix())
            )
            rendered.append(f'<a href="{quoted_route(relative)}">{html.escape(label)}</a>')
        else:
            rendered.append(f'<span class="unresolved" title="Nicht aufgelöster Wikilink">{html.escape(label)}</span>')
        cursor = match.end()
    rendered.append(plain(text[cursor:]))
    return "".join(rendered)


def locator_anchor(locator: str) -> str:
    match = re.search(r"(?:^|[.\s_-])(?:S|p|page|slide)[.\s:_-]*(\d+)", locator, re.IGNORECASE)
    return f"page-{match.group(1)}" if match else ""


def source_reader(source_id: str, page_outputs: dict[str, Path]) -> Optional[Path]:
    prefix = f"sources/{source_id}-"
    for node_id, output in page_outputs.items():
        if node_id.startswith(prefix) or node_id == f"sources/{source_id}":
            return output
    return None


def render_claim(
    match: re.Match[str],
    current_output: Path,
    page_outputs: dict[str, Path],
    source_mode: bool,
) -> str:
    metadata: dict[str, str] = {}
    for raw_line in match.group("meta").splitlines():
        if ":" in raw_line:
            key, value = raw_line.split(":", 1)
            metadata[key.strip().casefold()] = value.strip()
    claim_id = metadata.get("id", "claim")
    kind = metadata.get("kind", "")
    status = metadata.get("status", "")
    source_links: list[str] = []
    for entry in (item.strip() for item in metadata.get("sources", "").split("|")):
        if not entry or "@" not in entry:
            continue
        source_id, locator = entry.split("@", 1)
        output = source_reader(source_id, page_outputs)
        label = html.escape(f"{source_id}@{locator}")
        if output is None:
            source_links.append(f'<span class="unresolved">{label}</span>')
            continue
        relative = PurePosixPath(posixpath.relpath(output.as_posix(), start=current_output.parent.as_posix()))
        anchor = locator_anchor(locator)
        href = quoted_route(relative) + (f"#{quote(anchor, safe='')}" if anchor else "")
        source_links.append(f'<a href="{href}">{label}</a>')
    evidence = " · ".join(source_links) if source_links else "Kein verknüpfter Locator"
    body = render_markdown(match.group("text"), current_output, page_outputs, source_mode=source_mode)
    return (
        '<aside class="claim" aria-label="Belegter Claim">'
        f'<div class="claim-meta"><code>{html.escape(claim_id)}</code>'
        f'<span>{html.escape(kind)}</span><span>{html.escape(status)}</span></div>'
        f'<div class="claim-body">{body}</div>'
        f'<div class="claim-sources">Beleg: {evidence}</div></aside>'
    )


def render_markdown(
    text: str,
    current_output: Path,
    page_outputs: dict[str, Path],
    *,
    source_mode: bool = False,
) -> str:
    """Render a safe, dependency-free HTML reading view for common wiki Markdown."""
    body = strip_frontmatter(text)
    claim_html: list[str] = []

    def claim_placeholder(match: re.Match[str]) -> str:
        index = len(claim_html)
        claim_html.append(render_claim(match, current_output, page_outputs, source_mode))
        return f"\n@@LMWIKI_CLAIM_{index}@@\n"

    body = CLAIM_BLOCK.sub(claim_placeholder, body)
    lines = body.splitlines()
    rendered: list[str] = []
    index = 0

    def is_table_divider(line: str) -> bool:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)

    def table_cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        claim_marker = CLAIM_SENTINEL.fullmatch(stripped)
        if claim_marker:
            rendered.append(claim_html[int(claim_marker.group(1))])
            index += 1
            continue
        page_marker = PAGE_MARKER.fullmatch(stripped)
        if page_marker:
            kind = "Seite" if page_marker.group(1).casefold() == "page" else "Folie"
            value = page_marker.group(2).strip()
            anchor = locator_anchor(f"page {value}") or f"page-{re.sub(r'[^A-Za-z0-9_-]+', '-', value).strip('-')}"
            rendered.append(
                f'<div class="page-marker" id="{html.escape(anchor, quote=True)}" '
                f'role="separator" aria-label="{html.escape(kind + " " + value, quote=True)}">'
                f'<span>{html.escape(kind)} {html.escape(value)}</span></div>'
            )
            index += 1
            continue
        if stripped.startswith("```"):
            language = stripped[3:].strip()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            index += 1
            class_name = f' class="language-{html.escape(language, quote=True)}"' if language else ""
            rendered.append(f"<pre><code{class_name}>{html.escape(chr(10).join(code))}</code></pre>")
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            if source_mode and re.fullmatch(r"#+(?:\s+#+)*", heading.group(2).strip()):
                rendered.append(f'<pre class="source-fragment">{html.escape(stripped)}</pre>')
                index += 1
                continue
            level = len(heading.group(1))
            rendered.append(f"<h{level}>{inline_markup(heading.group(2), current_output, page_outputs)}</h{level}>")
            index += 1
            continue
        if index + 1 < len(lines) and "|" in line and is_table_divider(lines[index + 1]):
            headers = table_cells(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(table_cells(lines[index]))
                index += 1
            rendered.append("<div class=\"table-scroll\"><table><thead><tr>" + "".join(
                f"<th>{inline_markup(cell, current_output, page_outputs)}</th>" for cell in headers
            ) + "</tr></thead><tbody>" + "".join(
                "<tr>" + "".join(f"<td>{inline_markup(cell, current_output, page_outputs)}</td>" for cell in row) + "</tr>"
                for row in rows
            ) + "</tbody></table></div>")
            continue
        if source_mode and line.count("|") >= 2:
            fragments: list[str] = []
            while index < len(lines) and lines[index].count("|") >= 2 and lines[index].strip():
                fragments.append(lines[index])
                index += 1
            rendered.append(f'<pre class="source-fragment">{html.escape(chr(10).join(fragments))}</pre>')
            continue
        unordered = re.match(r"^\s*[-*+]\s+(.+)$", line)
        if unordered:
            items: list[str] = []
            while index < len(lines):
                match = re.match(r"^\s*[-*+]\s+(.+)$", lines[index])
                if not match:
                    break
                items.append(f"<li>{inline_markup(match.group(1), current_output, page_outputs)}</li>")
                index += 1
            rendered.append("<ul>" + "".join(items) + "</ul>")
            continue
        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if ordered:
            items = []
            while index < len(lines):
                match = re.match(r"^\s*\d+[.)]\s+(.+)$", lines[index])
                if not match:
                    break
                items.append(f"<li>{inline_markup(match.group(1), current_output, page_outputs)}</li>")
                index += 1
            rendered.append("<ol>" + "".join(items) + "</ol>")
            continue
        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().lstrip(">").strip())
                index += 1
            rendered.append(f"<blockquote>{inline_markup(' '.join(quote_lines), current_output, page_outputs)}</blockquote>")
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            rendered.append("<hr>")
            index += 1
            continue
        paragraph = [stripped]
        index += 1
        while index < len(lines) and lines[index].strip():
            candidate = lines[index].strip()
            if re.match(r"^(#{1,6})\s+", candidate) or candidate.startswith(("```", ">")):
                break
            if re.match(r"^\s*([-*+]\s+|\d+[.)]\s+)", lines[index]):
                break
            if index + 1 < len(lines) and "|" in lines[index] and is_table_divider(lines[index + 1]):
                break
            paragraph.append(candidate)
            index += 1
        separator = "<br>" if source_mode else " "
        rendered.append(
            f"<p>{separator.join(inline_markup(item, current_output, page_outputs) for item in paragraph)}</p>"
        )
    return "\n".join(rendered)


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_cluster_definitions(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    definitions: dict[str, dict[str, str]] = {}
    current: Optional[dict[str, str]] = None
    fenced = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = CLUSTER_HEADING.match(line)
        if heading:
            cluster_id = heading.group(1)
            current = {"id": cluster_id, "label": cluster_id.replace("-", " ").title()}
            definitions[cluster_id] = current
            continue
        field = CLUSTER_FIELD.match(line)
        if field and current is not None:
            current[field.group(1).casefold()] = field.group(2).strip()
    for index, cluster in enumerate(definitions.values()):
        color = cluster.get("color", "")
        if not HEX_COLOR.fullmatch(color):
            cluster["color"] = DEFAULT_CLUSTER_COLORS[index % len(DEFAULT_CLUSTER_COLORS)]
    return definitions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--no-tags", action="store_true", help="Do not render tags as graph nodes")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    template = Path(__file__).resolve().parent.parent / "assets/graph-template.html"
    page_template = Path(__file__).resolve().parent.parent / "assets/page-template.html"
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    if not template.is_file():
        raise SystemExit("Bundled graph template not found")
    if not page_template.is_file():
        raise SystemExit("Bundled page template not found")

    markdown_files = sorted(
        path
        for path in target.rglob("*.md")
        if not path.relative_to(target).as_posix().startswith("meta/history/")
    )

    known = {path.relative_to(target).with_suffix("").as_posix(): path for path in markdown_files}
    page_outputs = {
        node_id: reader_output(path.relative_to(target))
        for node_id, path in known.items()
    }
    cluster_definitions = parse_cluster_definitions(target / "schema/CLUSTERS.md")
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    seen_links: set[tuple[str, str, str]] = set()
    used_tags: set[str] = set()

    for node_id, path in known.items():
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(target).as_posix()
        data = frontmatter(text, relative)
        heading = H1.search(text)
        title = str(data.get("title") or (heading.group(1).strip() if heading else path.stem))
        page_type = str(data.get("type") or ("source" if node_id.startswith("sources/") else "root"))
        if node_id.startswith("sources/"):
            group = "source"
        elif node_id.startswith("schema/"):
            group = "schema"
        elif node_id.startswith("meta/"):
            group = "meta"
        elif node_id.startswith("captures/"):
            group = "capture"
        elif node_id.startswith("input/work/"):
            group = "input-work"
        elif node_id.startswith("input/ventures/"):
            group = "input-ventures"
        elif node_id.startswith("input/personal/"):
            group = "input-personal"
        elif node_id.startswith("input/"):
            group = "input"
        elif node_id.startswith("output/"):
            group = "output"
        else:
            group = page_type
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(tag) for tag in tags]
        clusters = data.get("clusters", [])
        if not isinstance(clusters, list):
            clusters = []
        clusters = [str(cluster) for cluster in clusters]
        primary_cluster = str(data.get("primary_cluster") or "")
        used_tags.update(tags)
        nodes.append(
            {
                "id": node_id,
                "title": title,
                "group": group,
                "description": str(data.get("description") or data.get("extraction_notes") or ""),
                "status": str(data.get("status") or ""),
                "tags": tags,
                "clusters": clusters,
                "primaryCluster": primary_cluster,
                "href": reader_href(path.relative_to(target)),
                "rawHref": raw_file_href(path.relative_to(target)),
                "path": path.relative_to(target).as_posix(),
                "kind": "file",
            }
        )
        for raw in WIKILINK.findall(text):
            destination = link_target(raw)
            if destination in known:
                edge = (node_id, destination, "wikilink")
                if edge not in seen_links:
                    links.append({"source": node_id, "target": destination, "kind": "wikilink"})
                    seen_links.add(edge)
            elif not node_id.startswith("sources/"):
                unresolved.append({"source": node_id, "target": graph_safe_target(raw)})

    referenced_clusters = {
        cluster_id
        for node in nodes
        if node["kind"] == "file"
        for cluster_id in node.get("clusters", [])
    }
    for index, cluster_id in enumerate(sorted(set(cluster_definitions) | referenced_clusters)):
        definition = cluster_definitions.get(cluster_id, {})
        cluster_node_id = f"cluster:{cluster_id}"
        nodes.append(
            {
                "id": cluster_node_id,
                "title": definition.get("label", cluster_id.replace("-", " ").title()),
                "group": "cluster",
                "description": definition.get("purpose", "Referenced cluster without a confirmed definition"),
                "status": definition.get("status", "unknown"),
                "tags": [],
                "clusters": [],
                "primaryCluster": "",
                "href": reader_href(Path("schema/CLUSTERS.md")) if cluster_definitions else "",
                "rawHref": raw_file_href(Path("schema/CLUSTERS.md")) if cluster_definitions else "",
                "path": "schema/CLUSTERS.md" if cluster_definitions else "",
                "kind": "cluster",
                "color": definition.get("color", DEFAULT_CLUSTER_COLORS[index % len(DEFAULT_CLUSTER_COLORS)]),
                "directory": definition.get("directory", ""),
            }
        )
    for node in list(nodes):
        if node["kind"] != "file":
            continue
        for cluster_id in node.get("clusters", []):
            edge = (node["id"], f"cluster:{cluster_id}", "cluster")
            if edge not in seen_links:
                links.append({"source": node["id"], "target": f"cluster:{cluster_id}", "kind": "cluster"})
                seen_links.add(edge)

    if not args.no_tags:
        for tag in sorted(used_tags):
            tag_id = f"tag:{tag}"
            nodes.append(
                {
                    "id": tag_id,
                    "title": f"#{tag}",
                    "group": "tag",
                    "description": "Structural or conceptual tag",
                    "status": "",
                    "tags": [],
                    "clusters": [],
                    "primaryCluster": "",
                    "href": "",
                    "rawHref": "",
                    "path": "",
                    "kind": "tag",
                }
            )
        for node in list(nodes):
            if node["kind"] != "file":
                continue
            for tag in node["tags"]:
                edge = (node["id"], f"tag:{tag}", "tag")
                if edge not in seen_links:
                    links.append({"source": node["id"], "target": f"tag:{tag}", "kind": "tag"})
                    seen_links.add(edge)

    graph = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "title": H1.search((target / "WIKI.md").read_text(encoding="utf-8")).group(1),
        "nodes": nodes,
        "links": links,
        "clusters": list(cluster_definitions.values()),
        "unresolved": unresolved,
    }
    output_dir = target / "graph"
    output_dir.mkdir(parents=True, exist_ok=True)
    page_template_text = page_template.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="lmwiki-graph-", dir=str(target.parent)) as temporary:
        staged_graph = Path(temporary) / "graph"
        for node_id, source_path in known.items():
            source_relative = source_path.relative_to(target)
            output_relative = page_outputs[node_id]
            output_path = staged_graph / output_relative.relative_to("graph")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            graph_route = PurePosixPath(
                posixpath.relpath("graph/index.html", start=output_relative.parent.as_posix())
            )
            raw_route = PurePosixPath(
                posixpath.relpath(source_relative.as_posix(), start=output_relative.parent.as_posix())
            )
            source_text = source_path.read_text(encoding="utf-8")
            node = next(item for item in nodes if item.get("kind") == "file" and item.get("id") == node_id)
            source_mode = node_id.startswith("sources/")
            notice = (
                '<div class="source-notice" role="note">Quellenextrakt: Die Markdown-Rohdatei bleibt '
                'maßgeblich; Tabellen und Layout können vom Original abweichen.</div>'
                if source_mode else ""
            )
            page_html = (
                page_template_text.replace("__PAGE_TITLE__", html.escape(str(node["title"])))
                .replace("__SOURCE_PATH__", html.escape(source_relative.as_posix()))
                .replace("__GRAPH_HREF__", quoted_route(graph_route))
                .replace("__RAW_HREF__", quoted_route(raw_route))
                .replace("__ARTICLE_CLASS__", "source-view" if source_mode else "wiki-view")
                .replace("__VIEW_NOTICE__", notice)
                .replace(
                    "__ARTICLE_HTML__",
                    render_markdown(source_text, output_relative, page_outputs, source_mode=source_mode),
                )
            )
            output_path.write_text(page_html, encoding="utf-8")
        json_text = json.dumps(graph, ensure_ascii=False, indent=2)
        (staged_graph / "graph.json").write_text(json_text + "\n", encoding="utf-8")
        embedded = json_text.replace("<", "\\u003c")
        graph_html = template.read_text(encoding="utf-8").replace("__GRAPH_DATA__", embedded)
        (staged_graph / "index.html").write_text(graph_html, encoding="utf-8")

        expected_pages = {
            path.relative_to(staged_graph / "pages").as_posix()
            for path in (staged_graph / "pages").rglob("*.html")
        }
        for staged_page in sorted((staged_graph / "pages").rglob("*.html")):
            relative = staged_page.relative_to(staged_graph)
            atomic_write(output_dir / relative, staged_page.read_bytes())
        atomic_write(output_dir / "graph.json", (staged_graph / "graph.json").read_bytes())
        atomic_write(output_dir / "index.html", (staged_graph / "index.html").read_bytes())
        pages_dir = output_dir / "pages"
        if pages_dir.is_dir():
            for stale_page in pages_dir.rglob("*.html"):
                if stale_page.relative_to(pages_dir).as_posix() not in expected_pages:
                    stale_page.unlink()

    print(
        json.dumps(
            {
                "output": "graph/index.html",
                "files": len(markdown_files),
                "nodes": len(nodes),
                "links": len(links),
                "clusters": len(cluster_definitions),
                "reader_pages": len(page_outputs),
                "unresolved": unresolved,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
