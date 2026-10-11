#!/usr/bin/env python3
"""Decide whether an incoming note modifies an existing page or becomes a new one.

One typed choice question contrasts the incoming candidate with the best
matching maintained page. The conservative rule follows the decision-layer
literature: when confidence is below tau_cons, a new note is created, because
a spurious duplicate does less harm than a wrong modification. The decision
is a proposal: the rewrite itself only happens through the validated
page-batch workflow with preview and confirmation. This helper never writes
into the wiki.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import decision_provider
import navigation
from frontmatter_contract import FrontmatterError, parse_document
from wiki_lock import require_lock


OPTION_MODIFY = "modify"
OPTION_NEW_NOTE = "new_note"

CONSOLIDATION_QUESTION = {
    "de": (
        "Die kommende Notiz und die bestehende Seite:\n{state}\n"
        "Ändert die kommende Notiz die bestehende Seite (gleiches Thema, neue oder aktualisierte "
        "Informationen) — „modify“ —, oder ist sie eine eigene Seite (verwandtes, aber "
        "eigenständiges Thema) — „new_note“?"
    ),
    "en": (
        "The incoming note and the existing page:\n{state}\n"
        "Does the incoming note modify the existing page (same subject, new or updated "
        "information) — “modify” —, or is it a distinct page (related but separate subject) — "
        "“new_note”?"
    ),
}


def note_block(document, path_label: str) -> str:
    parts = [
        f"{path_label} — Titel: {document.data.get('title', '')}",
        f"Beschreibung: {document.data.get('description', '')}",
        document.body,
    ]
    return "\n".join(part for part in parts if str(part).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--note-file", required=True, help="Candidate note Markdown outside the wiki")
    parser.add_argument("--page", required=True, help="Existing wiki page, for example wiki/concepts/example")
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
    page_relative = str(args.page)
    if page_relative.startswith("/") or ".." in Path(page_relative).parts:
        raise SystemExit("--page must be a wiki-relative path")
    page_path = target / page_relative
    if not page_path.is_file():
        raise SystemExit(f"the existing page is not a file: {page_relative}")

    try:
        candidate = parse_document(note_path.read_text(encoding="utf-8"), "candidate-note", require_frontmatter=True)
        page = parse_document(page_path.read_text(encoding="utf-8"), page_relative, require_frontmatter=True)
    except FrontmatterError as exc:
        raise SystemExit(f"one of the notes is outside the strict frontmatter subset: {exc}") from exc

    language = navigation.wiki_language(target).split("-", 1)[0].casefold()
    state = "\n\n".join(
        (
            note_block(candidate, "Kommende Notiz"),
            note_block(page, f"Bestehende Seite ({page_relative})"),
        )
    )

    loaded = decision_provider.load_config(target)
    base = {
        "page": page_relative,
        "fallback": "agent_decision",
        "instruction": (
            "The decision layer is not available; take the consolidation decision as part of the "
            "normal curation review."
        ),
    }
    if loaded["state"] != "active":
        print(json.dumps({"state": loaded["state"], "reason": loaded["reason"], **base}, ensure_ascii=False, indent=2))
        return 0

    config = loaded["config"]
    question = CONSOLIDATION_QUESTION.get(language, CONSOLIDATION_QUESTION["en"]).format(
        state=decision_provider.clamp_state(state, int(config["state_chars"]))
    )
    try:
        request = decision_provider.build_request(
            config,
            state,
            [decision_provider.question_choice("consolidate", question, [OPTION_MODIFY, OPTION_NEW_NOTE])],
        )
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

    probabilities = answers["consolidate"]["probabilities"]
    p_modify = float(probabilities.get(OPTION_MODIFY, 0.0))
    p_new = float(probabilities.get(OPTION_NEW_NOTE, 1.0 - p_modify))
    confidence = decision_provider.confidence_choice(probabilities)

    if confidence < float(config["tau_cons"]):
        decision = OPTION_NEW_NOTE
        rule = f"confidence {confidence:.4f} is below tau_cons {config['tau_cons']}; a new note does less harm than a wrong modification"
    else:
        decision = OPTION_MODIFY if p_modify > 0.5 else OPTION_NEW_NOTE
        rule = "highest-probability option above the confidence threshold"

    output = {
        "state": "decided",
        "decision": decision,
        "rule": rule,
        "probabilities": {OPTION_MODIFY: round(p_modify, 4), OPTION_NEW_NOTE: round(p_new, 4)},
        "confidence": round(confidence, 4),
        "model": str(config["model"]),
        "transport": transport,
        "page": page_relative,
    }
    if decision == OPTION_MODIFY:
        output["instruction"] = (
            f"Rewrite {page_relative} from the full incoming source through the validated page-batch "
            "workflow (preview, confirmation, snapshot), and return an updated one-line description "
            "for the index. Keep protected human:keep blocks untouched."
        )
    else:
        output["instruction"] = (
            "Create the candidate as a new page through the normal curation workflow; it does not "
            "replace the existing page."
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
