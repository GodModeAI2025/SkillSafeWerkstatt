#!/usr/bin/env python3
"""Assign a collection of Markdown files to confirmed clusters, zero-shot.

This is the clustering view of the decision layer: each file outside the wiki
is routed against the active clusters of schema/CLUSTERS.md plus an explicit
"none_of_these" escape. Nothing is written into the wiki. Files routed to
"none_of_these" and uncertain files are returned as raw material for the
confirmed cluster-proposal workflow, where the agent names and describes the
proposed clusters and the user confirms, merges, splits, or rejects them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import decision_provider
import lint_wiki
import navigation
from frontmatter_contract import FrontmatterError
from wiki_lock import require_lock


OPTION_NONE = "none_of_these"
EXCERPT_LIMIT = 1500

CLUSTER_QUESTION = {
    "de": (
        "Bestätigte Cluster:\n{clusters}\n"
        "Zu welchem Cluster gehört das folgende Dokument? Wähle genau eine Cluster-ID oder "
        "„none_of_these“, wenn es zu keinem der bestätigten Cluster passt."
    ),
    "en": (
        "Confirmed clusters:\n{clusters}\n"
        "Which cluster does the following document belong to? Choose exactly one cluster id or "
        "“none_of_these” if it fits none of the confirmed clusters."
    ),
}


def excerpt(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    title = path.stem
    lines = text.splitlines()
    body_lines: list[str] = []
    in_frontmatter = False
    seen_frontmatter = False
    for line in lines:
        if line.strip() == "---":
            if not seen_frontmatter and not body_lines:
                in_frontmatter = not in_frontmatter
                seen_frontmatter = True
                continue
            elif in_frontmatter:
                in_frontmatter = False
                continue
        if in_frontmatter:
            continue
        stripped = line.strip()
        if not body_lines and stripped.startswith("# "):
            title = stripped[2:].strip()
            continue
        if not stripped or stripped.startswith("#"):
            continue
        body_lines.append(stripped)
        if len(" ".join(body_lines)) >= EXCERPT_LIMIT:
            break
    excerpt_text = " ".join(" ".join(body_lines).split())[:EXCERPT_LIMIT]
    return title, excerpt_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--directory", required=True, help="Directory of Markdown files, outside the wiki")
    parser.add_argument("--max-files", type=int, default=500, help="Maximum number of files to assign")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        raise SystemExit(f"directory is not a readable directory: {args.directory}")
    try:
        directory.relative_to(target)
        raise SystemExit("directory must live outside the wiki; adoption works on external collections")
    except ValueError:
        pass
    if args.max_files < 1 or args.max_files > 5000:
        raise SystemExit("max-files must be between 1 and 5000")

    files = sorted(path for path in directory.glob("*.md") if path.is_file())[: args.max_files]
    if not files:
        raise SystemExit(f"no Markdown files found in {args.directory}")

    cluster_errors: list[str] = []
    cluster_warnings: list[str] = []
    definitions = lint_wiki.load_clusters(target / "schema/CLUSTERS.md", cluster_errors, cluster_warnings)
    active = {
        cluster_id: definition
        for cluster_id, definition in definitions.items()
        if definition.get("status") == "active"
    }
    if not active:
        raise SystemExit("no active clusters in schema/CLUSTERS.md; confirm a cluster set first")

    language = navigation.wiki_language(target).split("-", 1)[0].casefold()
    options = sorted(active) + [OPTION_NONE]
    cluster_lines = [
        f"- {cluster_id} — {definition.get('label', '')}: {definition.get('purpose', '')}"
        for cluster_id, definition in sorted(active.items())
    ]
    cluster_lines.append(f"- {OPTION_NONE} — passt zu keinem der bestätigten Cluster")
    question = CLUSTER_QUESTION.get(language, CLUSTER_QUESTION["en"]).format(clusters="\n".join(cluster_lines))

    loaded = decision_provider.load_config(target)
    base = {
        "files": [path.name for path in files],
        "clusters": sorted(active),
        "fallback": "agent_proposal",
    }
    if loaded["state"] != "active":
        print(json.dumps({"state": loaded["state"], "reason": loaded["reason"], **base}, ensure_ascii=False, indent=2))
        return 0

    config = loaded["config"]
    api_key = decision_provider.api_key_for(config)
    if api_key is None:
        print(
            json.dumps(
                {
                    "state": "provider_unavailable",
                    "reason": f"The environment variable {config['api_key_env']} is not set; no provider call was made.",
                    **base,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    assignments: list[dict[str, Any]] = []
    transport_totals = {"requests": 0, "errors": 0, "latency_ms": 0}
    aborted: str = ""
    for path in files:
        title, excerpt_text = excerpt(path)
        state = f"Titel: {title}\n{excerpt_text}"
        try:
            request = decision_provider.build_request(
                config, state, [decision_provider.question_choice("assign", question, options)]
            )
            response, transport = decision_provider.send_request(
                str(config["endpoint"]),
                api_key,
                request,
                timeout_seconds=int(config["timeout_seconds"]),
                attempts=int(config["attempts"]),
            )
            answers = decision_provider.validate_response(request, response)
        except decision_provider.DecisionError as exc:
            transport_totals["errors"] += 1
            aborted = str(exc)
            assignments.append({"file": path.name, "cluster": "failed", "reason": str(exc)})
            continue
        transport_totals["requests"] += 1
        transport_totals["latency_ms"] += int(transport.get("latency_ms", 0))
        probabilities = answers["assign"]["probabilities"]
        ranked = sorted(probabilities.items(), key=lambda item: (-float(item[1]), item[0]))
        top_option, top_probability = ranked[0]
        confidence = decision_provider.confidence_choice(probabilities)
        if confidence < float(config["tau_route"]):
            cluster = "uncertain"
        elif top_option == OPTION_NONE:
            cluster = "new"
        else:
            cluster = top_option
        assignments.append(
            {
                "file": path.name,
                "cluster": cluster,
                "probability": round(float(top_probability), 4),
                "confidence": round(confidence, 4),
            }
        )

    if transport_totals["requests"] == 0:
        print(
            json.dumps(
                {
                    "state": "provider_unavailable",
                    "reason": f"No file could be assigned: {aborted}",
                    "assignments": assignments,
                    **base,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    new_candidates: list[dict[str, Any]] = []
    for item in assignments:
        if item["cluster"] != "new":
            continue
        path = directory / str(item["file"])
        title, excerpt_text = excerpt(path)
        new_candidates.append({"file": str(item["file"]), "title": title, "excerpt": excerpt_text})

    print(
        json.dumps(
            {
                "state": "proposed",
                "model": str(config["model"]),
                "threshold": float(config["tau_route"]),
                "assigned": sum(1 for item in assignments if item["cluster"] not in ("new", "uncertain", "failed")),
                "new_candidates": new_candidates,
                "uncertain": [str(item["file"]) for item in assignments if item["cluster"] == "uncertain"],
                "assignments": assignments,
                "transport": transport_totals,
                "instruction": (
                    "Group the new_candidates into provisional clusters with names, descriptions, "
                    "and palette colors, and present them to the user with the existing cluster "
                    "options (confirm, rename, merge, split, reject). Nothing is recorded before "
                    "confirmation; uncertain and failed files stay with the agent's own review."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
