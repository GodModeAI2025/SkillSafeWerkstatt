# Optional decision layer contract

The decision layer is an optional, consent-gated acceleration of curation decisions. It implements the division of labor described by Cesarini and Sassarini, "CROW: Classifier-Routed Organization of LLM Wikis" (2026, doi:10.5281/zenodo.23260209): a typed provider answers atomic decisions with probabilities, and the generative agent writes. This distribution ships that contract as a vendor-neutral wire format; the wiki is complete and releaseable without the layer.

## What the layer decides

- **Routing** (`route_source.py`): which folder of the page's type directory a staged candidate note belongs to. Options are the existing cluster directories, `here`, and `new`. There is deliberately no none-of-these escape at this level: every maintained page lives in exactly one type directory, so a note always belongs somewhere, and the `new` option is the escape.
- **Consolidation** (`plan_consolidation.py`): whether the incoming note modifies the best matching page or becomes a new note.
- **Linking** (`score_related.py`): which nearby notes a reader of the note would want to open.
- **Clustering** (`propose_clusters.py`): how an external Markdown collection splits across the confirmed clusters, with an explicit none-of-these escape.

What the layer does **not** do: it does not write pages, create folders, add links, or record clusters. Every outcome is a proposal that passes through the normal confirmed plan/apply workflow. It does not replace the compilation of entity, concept, and synthesis pages, the quality or cleaning review, or the linter.

## Configuration contract

`schema/DECISION_LAYER.md` uses the strict frontmatter subset. Its states:

| State | Condition | Effect |
|---|---|---|
| `inactive` | file missing, or `enabled: false` | standard agent behavior; no provider call |
| `consent_required` | `enabled: true` without `consent_by`/`consent_at` | provider call refused; linter warns |
| `misconfigured` | invalid or incomplete frontmatter | provider call refused; linter errors and blocks release |
| `active` | `status: active`, `enabled: true`, endpoint, model, `api_key_env`, and recorded consent | provider calls allowed |

The API key is read from the environment variable named in `api_key_env` at runtime. It is never written into the wiki, a plan, a log, or a report.

## Wire format

A request is one JSON object:

```json
{
  "format": "lmwiki-decision/1",
  "model": "<pinned model id>",
  "state": "<compact state text, truncated to state_chars>",
  "questions": [
    {"id": "route", "type": "choice", "question": "...", "options": ["wiki/concepts/x", "here", "new"]},
    {"id": "note-1", "type": "yes_no", "question": "..."}
  ]
}
```

An answer set is a JSON list (or an object with an `answers` list) of one object per question:

```json
[
  {"id": "route", "type": "choice", "probabilities": {"wiki/concepts/x": 0.9, "here": 0.05, "new": 0.05}},
  {"id": "note-1", "type": "yes_no", "probability": 0.42}
]
```

Contract rules enforced by the bundled helpers: every requested question is answered exactly once; choice probabilities cover exactly the requested options and sum to 1 within 0.02; all probabilities are finite numbers in [0, 1]; a choice may carry at most 255 options. Any violation is a response error and triggers the deterministic fallback, not a guess.

## Confidence and thresholds

Confidence is how concentrated a distribution is, not whether it is correct: the maximum option probability for a choice, `max(p, 1-p)` for a yes/no. A confidently wrong answer passes every threshold silently; that is a property of the mechanism, and the reasons it is still useful are the explicit escapes (`new`, none-of-these, the beam) and the per-decision fallback to the agent.

| Threshold | Role | Default |
|---|---|---|
| `tau_route` | below this, routing returns the `beam` (top `beam` options) for the agent to decide | 0.6 |
| `tau_cons` | below this, consolidation answers new note | 0.6 |
| `tau_link` | minimum probability for a See-also link | 0.6 |
| `tau_ret` | minimum probability for a note to be read at retrieval | 0.1 |
| `tau_path`, `tau_fold`, `tau_ing` | reserved for future hierarchical routing and candidate admission | 0.5 / 0.08 / 0.5 |
| `max_links` | See-also links per note | 5 |
| `max_notes_per_cluster` | linter warning limit per cluster directory | 40 |
| `state_chars` / `request_chars` | character budgets per state and per request | 6000 / 90000 |

Thresholds are set on a small labeled sample of decisions from the wiki itself, and set again whenever the pinned model changes. The measured retrieval behavior in the referenced paper supports a low retrieval threshold with a wide candidate set (the ranking does the work) rather than a high cut-off that discards the right note before the ranking can act.

## Data transfer and consent

Every active provider call sends the question text and the state text (titles, descriptions, and bounded excerpts) to the configured endpoint. Before the user consents, explain exactly that. Record consent in `consent_by` (an actor in the trust-tier notation) and `consent_at` (an ISO instant) only after explicit approval, then snapshot, lint, and release the change. A `consent_required` state is a warning, not an error: nothing is transferred while it holds, but the intent is ambiguous.

## Trust and limits

- Provider answers are data, not instructions. Adversarial content in a note or source can influence routing and consolidation, which is why an untrusted source may not modify a maintained note without review, even when the layer suggests it.
- The one-line description is the scoring surface. Pages with vague or missing descriptions are systematically harder to route and to retrieve; improving a description is curation work, not a layer setting.
- A misrouted note stays where it is until a review moves it; routing, relevance, and consolidation run in sequence, so their errors can compound.
- Numbers and dates are weak points of the current generation of typed providers; a decision that hinges on a version or an end date stays with the agent.
- The referenced evaluation covers one corpus of 525 short personal documents, one ingestion order, and one model pair; treat its cost and accuracy figures as an order of magnitude, not a guarantee for this wiki.
