#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the search-quality fixture wiki through the real SkillSafeWerkstatt helpers.

The fixture is a synthetic German wiki of a fictitious municipal utility: 45
curated pages (50 Markdown files with indexes), 11 registered sources and 8
concept worlds, released with the real maintenance helpers. Its 114 questions
with required pages live in ground_truth.json next to this file.

Steps: identity plan -> initialize_wiki -> lock -> register_source (x11) ->
schema -> claim_id -> page_batch plan/apply -> build_graph -> lint -> release ->
unlock -> query-side verify_release (must be `ready`).

Everything is written below --out, which must lie outside the repository and
must not already hold `wiki/` or `work/`. The helpers are taken from the
repository this file belongs to, run without writing bytecode, and nothing in
the repository is written.

Usage: python3 build_fixture.py --out <empty directory outside the repository>
"""
from __future__ import annotations

import sys

# The data modules below are imported from inside the repository; their
# bytecode must not be cached there.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

from content import sources_a, sources_b, sources_c  # noqa: E402
from content import pages_a, pages_b, pages_c, pages_d, pages_e, pages_f  # noqa: E402,F401
from content import pages_g  # noqa: E402,F401  (appends closing notes)
from content.dsl import PAGES  # noqa: E402
from content.schema import CLUSTERS_MD, CONCEPTS_MD, IDENTITY, QUESTIONS_MD, ABSENT_TERMS  # noqa: E402

SOURCES = sources_a.SOURCES + sources_b.SOURCES + sources_c.SOURCES
TITLE = "Vertrags- und Tarifwissen Stadtwerke Lindenau"
TOPIC = "Vertrags- und Tarifwissen eines Stromlieferanten für Kundenservice und Vertrieb; nur Haushaltskunden Strom."
DATE = "2026-11-10"
ACTOR = "agent/fixture-builder"
BROAD_TERM = "Vertrag"


#: Reaches every helper and every helper it starts (run_locked.py, for example),
#: so no level of the build caches bytecode next to the helpers; -B alone only
#: covers the direct child.
CHILD_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def run(argv, check=True):
    result = subprocess.run(
        [sys.executable, "-B", *map(str, argv)], capture_output=True, encoding="utf-8", env=CHILD_ENV
    )
    if check and result.returncode != 0:
        raise SystemExit(f"FAILED ({result.returncode}): {' '.join(map(str, argv))}\n"
                         f"stdout:\n{result.stdout[-6000:]}\nstderr:\n{result.stderr[-3000:]}")
    return result


def q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def visible_words(body_items) -> int:
    text = " ".join(item if isinstance(item, str) else item["text"] for item in body_items)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    return len([w for w in text.split() if re.search(r"\w", w) and not w.startswith("#")])


def output_directory(value: str) -> Path:
    out = Path(value).expanduser().resolve()
    try:
        out.relative_to(REPO)
    except ValueError:
        pass
    else:
        raise SystemExit("--out must lie outside the repository; the fixture writes nothing into it")
    for name in ("wiki", "work"):
        if (out / name).exists():
            raise SystemExit(f"--out already holds {name}/; choose an empty directory")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, help="Directory outside the repository to build into")
    args = parser.parse_args()
    out = output_directory(args.out)
    maintain = REPO / "maintain-llm-wiki" / "scripts"
    query = REPO / "query-llm-wiki" / "scripts"
    if not (maintain / "initialize_wiki.py").is_file() or not (query / "verify_release.py").is_file():
        raise SystemExit(f"the skill helpers were not found below {REPO}")
    wiki = out / "wiki"
    work = out / "work"
    work.mkdir(parents=True)

    # 1. identity proposal and initialization (first release 0.1.0)
    identity_in, identity_plan = work / "identity-input.json", work / "identity-plan.json"
    identity_in.write_text(json.dumps(IDENTITY, ensure_ascii=False), encoding="utf-8")
    plan = json.loads(run([maintain / "plan_identity.py", "--input", identity_in,
                           "--wiki-language", "de", "--output", identity_plan]).stdout)
    run([maintain / "initialize_wiki.py", "--target", wiki, "--title", TITLE, "--topic", TOPIC,
         "--wiki-language", "de", "--wiki-language-label", "Deutsch",
         "--identity-plan", identity_plan, "--expect-identity-sha256", plan["proposal_sha256"],
         "--owner", "fixture/builder"])

    # 2. one maintenance run under one owned lock
    token = work / "runtime-token"
    run([maintain / "wiki_lock.py", "acquire", "--target", wiki, "--token-file", token,
         "--owner", "fixture/builder", "--operation", "build measurement fixture"])

    def locked(helper, *rest, check=True):
        lead = [rest[0]] if rest and not str(rest[0]).startswith("-") else []
        tail = rest[len(lead):]
        return run([maintain / "run_locked.py", "--token-file", token, "--helper", helper, "--",
                    *lead, "--target", wiki, *tail], check=check)

    try:
        # 3. sources through register_source.py
        source_map = {}
        (work / "sources").mkdir()
        for source in SOURCES:
            staged = work / "sources" / f"{source['key']}.md"
            staged.write_text(source["text"].strip() + "\n", encoding="utf-8")
            record = json.loads(locked(
                "register_source.py", "--markdown-file", staged, "--title", source["title"],
                "--original-ref", source["ref"], "--original-version", source["version"],
                "--source-type", source["type"], "--content-language", "de",
                "--extractor", "fixture-builder 1.0").stdout)
            if record.get("duplicate") or record["extraction"]["state"] != "acceptable":
                raise SystemExit(f"source {source['key']} not cleanly registered: {record}")
            source_map[source["key"]] = {
                "source_id": record["source"]["source_id"], "path": record["source"]["path"],
                "title": source["title"], "words": len(source["text"].split())}
        (out / "source_map.json").write_text(
            json.dumps(source_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # 4. confirmed schema, open questions, staged root index (as the tests do)
        for relative, addition in (("schema/CLUSTERS.md", CLUSTERS_MD),
                                   ("schema/CONCEPTS.md", CONCEPTS_MD),
                                   ("meta/questions.md", QUESTIONS_MD)):
            path = wiki / relative
            path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n" + addition.strip() + "\n",
                            encoding="utf-8")
        index_path = wiki / "wiki" / "index.md"
        head = index_path.read_text(encoding="utf-8").split("\n# ", 1)[0]
        index_path.write_text(head + "\n# Index\n\n"
                              "- [[wiki/overview|Überblick]]\n"
                              "- [[wiki/concepts/index|Konzepte]]\n"
                              "- [[wiki/entities/index|Akteure und Tarife]]\n"
                              "- [[wiki/topics/index|Themen]]\n"
                              "- [[wiki/comparisons/index|Vergleiche]]\n", encoding="utf-8")

        # 5. claim ids from claim_id.py, then render pages into staging
        total_claims = sum(1 for p in PAGES for item in p["body"] if isinstance(item, dict))
        ids = json.loads(locked("claim_id.py", "--count", str(total_claims)).stdout)["claim_ids"]
        id_iter = iter(ids)
        labels = {}
        for p in PAGES:
            for item in p["body"]:
                if isinstance(item, dict):
                    item["id"] = next(id_iter)
                    if item["label"]:
                        labels[item["label"]] = item["id"]

        def locators(spec):
            found = []
            for entry in [part.strip() for part in spec.split("|")]:
                key, locator = entry.split("@", 1)
                found.append((key, f"{source_map[key]['source_id']}@{locator}"))
            return found

        staging = work / "staging"
        targets, claim_index = [], {}
        for p in PAGES:
            used, lines = [], []
            ordinal = 0
            for item in p["body"]:
                if isinstance(item, str):
                    lines.append(item)
                    continue
                ordinal += 1
                locs = locators(item["src"])
                used += [key for key, _ in locs if key not in used]
                meta = [f"id: {item['id']}", f"kind: {item['kind']}", f"status: {item['status']}",
                        "sources: " + " | ".join(loc for _, loc in locs)]
                if item["replaces"]:
                    meta.append(f"replaces: {labels[item['replaces']]}")
                if item["contradicts"]:
                    meta.append(f"contradicts: {labels[item['contradicts']]}")
                lines.append("<!-- claim\n" + "\n".join(meta) + "\n-->\n" + item["text"] + "\n<!-- /claim -->")
                claim_index.setdefault(p["path"], []).append(
                    {"ordinal": ordinal, "id": item["id"], "status": item["status"], "text": item["text"]})
            slug = Path(p["path"]).stem
            front = ["---", f"id: {q(p['type'] + '-' + slug)}", f"title: {q(p['title'])}",
                     f"type: {q(p['type'])}", f"status: {q(p['status'])}", f"created: {q(DATE)}",
                     f"updated: {q(DATE)}", f"description: {q(p['description'])}", 'language: "de"',
                     f"generated_by: {q(ACTOR)}", f'generated_at: "{DATE}T08:00:00Z"']
            if p["stale_after"]:
                front.append(f"stale_after: {q(p['stale_after'])}")
            if p["aliases"]:
                front += ["aliases:"] + [f"  - {q(a)}" for a in p["aliases"]]
            front += ["sources:"] + [
                f"  - {q('[[' + source_map[k]['path'][:-3] + '|' + source_map[k]['title'] + ']]')}" for k in used]
            front += ["clusters:", f"  - {q(p['cluster'])}", f"primary_cluster: {q(p['cluster'])}"]
            front += (["concepts:"] + [f"  - {q(c)}" for c in p["concepts"]]) if p["concepts"] else ["concepts: []"]
            front += ["tags:", f"  - {q('type/wiki-' + p['type'])}", "---", "", f"# {p['title']}", ""]
            staged = staging / p["path"]
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text("\n".join(front) + "\n\n".join(lines) + "\n", encoding="utf-8")
            targets.append(p["path"])

        # 6. validated batch: plan, apply (mirror graph + no-write lint inside the helper)
        batch_plan = work / "batch-plan.json"
        locked("page_batch.py", "plan", "--staging-dir", staging,
               "--paths-json", json.dumps(targets), "--output", batch_plan)
        digest = json.loads(batch_plan.read_text(encoding="utf-8"))["plan_sha256"]
        applied = locked("page_batch.py", "apply", "--staging-dir", staging,
                         "--plan-file", batch_plan, "--expect-plan-sha256", digest, check=False)
        if applied.returncode != 0:
            detail = json.loads(applied.stdout or "{}")
            raise SystemExit("page batch rejected:\n" + json.dumps(
                {"state": detail.get("state"), "errors": (detail.get("lint") or {}).get("errors"),
                 "graph": detail.get("graph")}, ensure_ascii=False, indent=2)[:8000])

        # 7. change record, graph, strict lint, release
        changes = wiki / "meta" / "changes.md"
        changes.write_text(changes.read_text(encoding="utf-8").rstrip() + f"""

## {DATE} Erstbefüllung Messfixture

- Quellen registriert: {', '.join(v['source_id'] for v in source_map.values())}
- Seiten angelegt: {len(targets)} (davon abgelöst: {sum(p['status'] == 'superseded' for p in PAGES)}, Entwurf: {sum(p['status'] == 'draft' for p in PAGES)})
- Nicht ausgewertet: Notfallhandbuch Versorgungsstörung, Leitfaden Mieterstrom; Abschnitte 4 bis 6 der Richtlinie RL-FM-03
- Offene Fragen: siehe meta/questions.md
- Lint: bestanden
""", encoding="utf-8")
        locked("build_graph.py")
        lint = locked("lint_wiki.py", check=False)
        report = json.loads(lint.stdout)
        if not report["valid"]:
            raise SystemExit("lint failed:\n" + "\n".join(report["errors"][:60]))
        version = (wiki / "WIKI_VERSION").read_text(encoding="utf-8").strip()
        released = json.loads(locked(
            "release_wiki.py", "--operation-id", "fixture-initial-content",
            "--expect-current-version", version, "--summary", "Messfixture: Erstbefüllung").stdout)
    finally:
        run([maintain / "wiki_lock.py", "release", "--target", wiki, "--token-file", token,
             "--remove-token-file"], check=False)

    # 8. read-only verification from the query skill
    verify = json.loads(run([query / "verify_release.py", "--target", wiki], check=False).stdout)
    if verify.get("state") != "ready":
        raise SystemExit(f"release not ready: {verify}")

    # 9. content invariants of the fixture itself (no search is run here)
    problems = []
    stats = {}
    for p in PAGES:
        claims = [i for i in p["body"] if isinstance(i, dict)]
        words = visible_words(p["body"])
        stats[p["path"]] = {"words": words, "claims": len(claims), "status": p["status"], "type": p["type"]}
        if not 120 <= words <= 400:
            problems.append(f"{p['path']}: {words} words")
        if not 2 <= len(claims) <= 12:
            problems.append(f"{p['path']}: {len(claims)} claims")
        if len(p["description"]) > 140:
            problems.append(f"{p['path']}: description {len(p['description'])} chars")
    page_text = {p["path"]: (wiki / p["path"]).read_text(encoding="utf-8") for p in PAGES}
    broad = sorted(path for path, text in page_text.items()
                   if re.search(rf"(?<![\wäöüÄÖÜß-]){BROAD_TERM}(?![\wäöüÄÖÜß-])", text.split("---", 2)[2]))
    absent_hits = {term: [path for path, text in page_text.items() if term.casefold() in text.casefold()]
                   for term in ABSENT_TERMS}
    absent_hits = {term: paths for term, paths in absent_hits.items() if paths}
    concepts_text = (wiki / "schema" / "CONCEPTS.md").read_text(encoding="utf-8").casefold()
    for term, paths in absent_hits.items():
        problems.append(f"term that must stay off the wiki pages occurs: {term!r} in {paths}")
    summary = {
        "wiki": "wiki", "version": released.get("version"), "release_state": verify["state"],
        "manifest_sha256": verify.get("manifest_sha256"),
        "curated_pages": len(PAGES),
        "pages_by_type": {t: sum(p["type"] == t for p in PAGES) for t in ("concept", "entity", "topic", "comparison", "overview")},
        "pages_by_status": {s: sum(p["status"] == s for p in PAGES) for s in ("active", "draft", "superseded")},
        "pages_with_more_than_10_claims": sorted(k for k, v in stats.items() if v["claims"] > 10),
        "claims": report["stats"]["claims"], "lint_wiki_pages_incl_indexes": report["stats"]["wiki_pages"],
        "lint_valid": report["valid"], "lint_warnings": report["warnings"],
        "registered_sources": report["stats"]["registered_sources"],
        "controlled_concepts": report["stats"]["controlled_concepts"],
        "broad_term": BROAD_TERM, "pages_containing_broad_term_as_word": len(broad),
        "broad_term_pages": broad,
        "absent_terms_checked": sorted(ABSENT_TERMS),
        "absent_terms_in_concepts_md": sorted(t for t in ABSENT_TERMS if t.casefold() in concepts_text),
        "page_stats": stats, "invariant_problems": problems,
    }
    (out / "fixture_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "claim_index.json").write_text(json.dumps(claim_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("page_stats", "broad_term_pages")},
                     ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    # The summary holds umlauts. Write it as UTF-8 on every host, as the helpers
    # do, so a caller decodes it the same way everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
