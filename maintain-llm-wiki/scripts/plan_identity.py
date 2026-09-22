#!/usr/bin/env python3
"""Build a hash-bound SOUL and content-policy proposal without touching a wiki."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from identity_contract import IdentityError, build_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Temporary JSON containing identity and content_policy")
    parser.add_argument(
        "--wiki-language",
        required=True,
        help=(
            "BCP-47-style code of the maintained wiki language, for example de or en-GB; "
            "headings and explanatory prose of both files are rendered in it"
        ),
    )
    parser.add_argument("--output", help="Temporary path for the immutable proposal")
    args = parser.parse_args()
    try:
        raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "wiki_language" in raw and raw["wiki_language"] != args.wiki_language:
            raise IdentityError(
                "wiki_language in the input differs from --wiki-language; pass the wiki language once"
            )
        if isinstance(raw, dict):
            raw = {**raw, "wiki_language": args.wiki_language}
        plan = build_plan(raw)
    except (OSError, json.JSONDecodeError, IdentityError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
