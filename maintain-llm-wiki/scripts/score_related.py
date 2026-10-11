#!/usr/bin/env python3
"""Score which nearby notes deserve a See-also link to a given note.

One typed yes/no question per candidate asks whether a reader of the note
would want to open the candidate. Candidates above tau_link are returned as a
bidirectional link plan, capped at max_links. The plan is a proposal: links
are written only through the validated page-batch workflow. This helper never
writes into the wiki.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import decision_provider
import navigation
from frontmatter_contract import FrontmatterError, ParsedDocument, parse_document
from wiki_lock import require_lock


LINK_QUESTION = {
    "de": (
        "Wurde die Notiz „{note_title}“ ({note_description}) gerade gelesen. Würde ein Leser "
        "dieser Notiz die Notiz „{candidate_title}“ ({candidate_description}) ebenfalls öffnen "
        "wollen?"
    ),
    "en": (
        "The reader has just read the note “{note_title}” ({note_description}). Would they also "
        "want to open the note “{candidate_title}” ({candidate_description})?"
    ),
}


def parse_note(path: Path, label: str, target: Path) -> ParsedDocument:
    try:
        return parse_document(path.read_text(encoding="utf-8"), label, require_frontmatter=True)
    except FrontmatterError as exc:
        raise SystemExit(f"{label} is outside the strict frontmatter subset: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--note", required=True, help="The note to link, wiki-relative, for example wiki/topics/example")
    parser.add_argument("--candidates", required=True, help="Comma-separated wiki-relative candidate paths (2..24)")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    note_relative = str(args.note)
    note_path = target / note_relative
    if not note_path.is_file():
        raise SystemExit(f"the note is not a file: {note_relative}")
    candidates_raw = [item.strip() for item in str(args.candidates).split(",") if item.strip()]
    if not 2 <= len(candidates_raw) <= 24:
        raise SystemExit("candidates must hold between 2 and 24 wiki-relative paths")
    if note_relative in candidates_raw:
        raise SystemExit("the note must not be one of its own link candidates")

    note = parse_note(note_path, note_relative, target)
    candidate_notes = []
    for relative in candidates_raw:
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise SystemExit(f"candidate is not a wiki-relative path: {relative}")
        candidate_path = target / relative
        if not candidate_path.is_file():
            raise SystemExit(f"the candidate is not a file: {relative}")
        candidate_notes.append((relative, parse_note(candidate_path, relative, target)))

    language = navigation.wiki_language(target).split("-", 1)[0].casefold()
    template = LINK_QUESTION.get(language, LINK_QUESTION["en"])
    note_title = str(note.data.get("title") or note_path.stem)
    note_description = str(note.data.get("description") or "")
    state = "\n".join(
        part
        for part in (
            f"Titel: {note_title}",
            f"Beschreibung: {note_description}",
            note.body,
        )
        if str(part).strip()
    )

    loaded = decision_provider.load_config(target)
    base = {
        "note": note_relative,
        "candidates": [relative for relative, _ in candidate_notes],
        "fallback": "agent_decision",
        "links": [],
    }
    if loaded["state"] != "active":
        print(json.dumps({"state": loaded["state"], "reason": loaded["reason"], **base}, ensure_ascii=False, indent=2))
        return 0

    config = loaded["config"]
    questions = [
        decision_provider.question_yes_no(
            f"link-{index}",
            template.format(
                note_title=note_title,
                note_description=note_description or "ohne Beschreibung",
                candidate_title=str(document.data.get("title") or Path(relative).stem),
                candidate_description=str(document.data.get("description") or "ohne Beschreibung"),
            ),
        )
        for index, (relative, document) in enumerate(candidate_notes, start=1)
    ]
    try:
        request = decision_provider.build_request(config, state, questions)
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

    threshold = float(config["tau_link"])
    scored: list[dict[str, Any]] = []
    for index, (relative, _) in enumerate(candidate_notes, start=1):
        probability = float(answers[f"link-{index}"]["probability"])
        if probability > threshold:
            scored.append({"target": relative, "probability": round(probability, 4)})
    scored.sort(key=lambda item: (-float(item["probability"]), str(item["target"])))
    links = scored[: int(config["max_links"])]
    link_entries: list[dict[str, Any]] = []
    for link in links:
        link_entries.append({"from": str(link["target"]), "to": note_relative, "probability": link["probability"]})
        link_entries.append({"from": note_relative, "to": str(link["target"]), "probability": link["probability"]})

    print(
        json.dumps(
            {
                "state": "scored",
                "note": note_relative,
                "threshold": threshold,
                "above_threshold": len(scored),
                "links": link_entries,
                "model": str(config["model"]),
                "transport": transport,
                "instruction": (
                    "Write the proposed See-also links through the validated page-batch workflow "
                    "(preview, confirmation, snapshot). They are a proposal, never applied automatically."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
