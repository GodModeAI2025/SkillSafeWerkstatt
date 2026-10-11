#!/usr/bin/env python3
"""Route one candidate note into the wiki's folder tree via the decision layer.

The page type fixes the type directory deterministically. The typed provider
then chooses between the confirmed cluster directories of that type directory,
the type directory itself ("here"), or a new cluster directory ("new"). A
confidence below tau_route returns the beam of most probable options instead,
and the agent takes the routing decision as it does without the decision
layer. This helper only decides and reports; it never writes into the wiki.
A "new" decision always hands back to the confirmed cluster-proposal workflow
and never creates a directory by itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import decision_provider
import lint_wiki
import navigation
from frontmatter_contract import FrontmatterError, parse_document
from wiki_lock import require_lock


TYPE_DIRECTORIES = {
    "concept": "wiki/concepts",
    "entity": "wiki/entities",
    "topic": "wiki/topics",
    "comparison": "wiki/comparisons",
}
OPTION_HERE = "here"
OPTION_NEW = "new"

ROUTE_QUESTION = {
    "de": (
        "Verfügbare Ordner:\n{options}\n"
        "In welchen Ordner gehört die kommende Notiz? Wähle genau einen der Ordner-Pfade, "
        "„here“ für den aktuellen Ordner selbst, oder „new“, wenn die Notiz in einen neuen "
        "Cluster-Ordner gehört, der hier noch nicht existiert."
    ),
    "en": (
        "Available folders:\n{options}\n"
        "Which folder does the incoming note belong to? Choose exactly one folder path, "
        "“here” for the current folder itself, or “new” if the note belongs in a new "
        "cluster folder that does not exist here yet."
    ),
}


def candidate_directory_for_type(type_directory: Path) -> list[Path]:
    if not type_directory.is_dir():
        return []
    return sorted(
        path for path in type_directory.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


def cluster_descriptions(target: Path) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for cluster_id, definition in lint_wiki.load_clusters(
        target / "schema/CLUSTERS.md", [], []
    ).items():
        if definition.get("status") != "active":
            continue
        directory = str(definition.get("directory") or "")
        if not directory:
            continue
        label = str(definition.get("label") or "")
        purpose = str(definition.get("purpose") or "")
        text = " — ".join(part for part in (label, purpose) if part)
        if text:
            descriptions[directory] = text
    return descriptions


def note_entries(directory: Path, target: Path, cap: int = 24) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == navigation.INDEX_NAME:
            continue
        try:
            document = parse_document(path.read_text(encoding="utf-8"), path.name, require_frontmatter=True)
        except FrontmatterError:
            entries.append({"path": path.relative_to(target).as_posix(), "title": path.stem, "description": ""})
            continue
        entries.append(
            {
                "path": path.relative_to(target).as_posix(),
                "title": str(document.data.get("title") or path.stem),
                "description": str(document.data.get("description") or ""),
            }
        )
        if len(entries) >= cap:
            break
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument(
        "--note-file",
        required=True,
        help="Candidate note Markdown in a temporary workspace outside the wiki",
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    note_path = Path(args.note_file).expanduser().resolve()
    if not note_path.is_file():
        raise SystemExit(f"note-file is not a readable file: {args.note_file}")
    try:
        note_path.relative_to(target)
        raise SystemExit("note-file must live outside the wiki; candidates belong to the temporary workspace")
    except ValueError:
        pass

    try:
        document = parse_document(note_path.read_text(encoding="utf-8"), "candidate-note", require_frontmatter=True)
    except FrontmatterError as exc:
        raise SystemExit(f"the candidate note is outside the strict frontmatter subset: {exc}") from exc
    data = document.data
    page_type = str(data.get("type") or "")
    if page_type not in TYPE_DIRECTORIES:
        raise SystemExit(f"the candidate note has no routable type {page_type!r}; expected one of {sorted(TYPE_DIRECTORIES)}")
    type_directory = TYPE_DIRECTORIES[page_type]
    type_root = target / type_directory
    if not type_root.is_dir():
        raise SystemExit(f"type directory is missing: {type_directory}")

    language = navigation.wiki_language(target).split("-", 1)[0].casefold()
    descriptions = cluster_descriptions(target)
    subfolders = candidate_directory_for_type(type_root)
    options = [str(subfolder.relative_to(target).as_posix()) for subfolder in subfolders]
    options.append(OPTION_HERE)
    options.append(OPTION_NEW)
    option_lines = [
        f"- {option} — {descriptions.get(option, 'unbestätigter Ordner ohne Beschreibung')}"
        for option in options
        if option != OPTION_HERE
    ]
    option_lines.append(f"- {OPTION_HERE} — {type_directory} selbst (ohne Cluster-Unterverzeichnis)")
    question = ROUTE_QUESTION.get(language, ROUTE_QUESTION["en"]).format(options="\n".join(option_lines))

    state = "\n".join(
        part
        for part in (
            f"Titel: {data.get('title', '')}",
            f"Beschreibung: {data.get('description', '')}",
            document.body,
        )
        if str(part).strip()
    )

    loaded = decision_provider.load_config(target)
    base = {
        "state_directory": type_directory,
        "options": options,
        "fallback": "agent_decision",
        "notes": note_entries(type_root, target),
    }
    if loaded["state"] != "active":
        print(json.dumps({"state": loaded["state"], "reason": loaded["reason"], **base}, ensure_ascii=False, indent=2))
        return 0

    config = loaded["config"]
    try:
        request = decision_provider.build_request(config, state, [decision_provider.question_choice("route", question, options)])
    except decision_provider.DecisionError as exc:
        print(json.dumps({"state": "misconfigured", "reason": str(exc), **base}, ensure_ascii=False, indent=2))
        return 0

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

    try:
        response, transport = decision_provider.send_request(
            str(config["endpoint"]),
            api_key,
            request,
            timeout_seconds=int(config["timeout_seconds"]),
            attempts=int(config["attempts"]),
        )
        answers = decision_provider.validate_response(request, response)
    except decision_provider.DecisionError as exc:
        print(json.dumps({"state": "provider_unavailable", "reason": str(exc), **base}, ensure_ascii=False, indent=2))
        return 0

    probabilities = answers["route"]["probabilities"]
    ranked = sorted(probabilities.items(), key=lambda item: (-float(item[1]), item[0]))
    top_option, top_probability = ranked[0]
    confidence = decision_provider.confidence_choice(probabilities)

    if confidence < float(config["tau_route"]):
        beam = ranked[: int(config["beam"])]
        print(
            json.dumps(
                {
                    "state": "low_confidence",
                    "reason": f"routing confidence {confidence:.4f} is below tau_route {config['tau_route']}",
                    "beam": [{"option": option, "probability": round(float(probability), 4)} for option, probability in beam],
                    "model": str(config["model"]),
                    "transport": transport,
                    **base,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if top_option == OPTION_HERE:
        selected_folder = type_directory
    elif top_option == OPTION_NEW:
        print(
            json.dumps(
                {
                    "state": "new_cluster_requested",
                    "reason": (
                        "The provider routed the note to a new cluster folder. No folder is created here: "
                        "propose the cluster (name, scope, color) to the user and record the confirmed "
                        "result in schema/CLUSTERS.md before filing the note."
                    ),
                    "state_directory": type_directory,
                    "probability": round(float(top_probability), 4),
                    "confidence": round(confidence, 4),
                    "model": str(config["model"]),
                    "transport": transport,
                    "candidate": {
                        "title": str(data.get("title") or ""),
                        "description": str(data.get("description") or ""),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    else:
        selected_folder = top_option

    folder_root = target / selected_folder
    if not folder_root.is_dir():
        print(
            json.dumps(
                {
                    "state": "provider_invalid_response",
                    "reason": f"the provider selected a folder that does not exist: {selected_folder}",
                    **base,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(
        json.dumps(
            {
                "state": "routed",
                "folder": selected_folder,
                "probability": round(float(top_probability), 4),
                "confidence": round(confidence, 4),
                "model": str(config["model"]),
                "transport": transport,
                "candidate_notes": note_entries(folder_root, target),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
