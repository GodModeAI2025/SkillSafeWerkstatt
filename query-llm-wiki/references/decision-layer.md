# Decision layer, reader's side

The wiki may carry an optional, consent-gated decision layer. From the reading side it is one extra helper and a disclosure rule. Nothing about the layer changes the integrity boundary: you still answer only from a verified release, and the layer never writes.

## The helper

`score_notes.py` re-ranks the BM25 candidate notes of a question through the consent-gated provider. Its states:

| State | Meaning | What you do |
|---|---|---|
| `scored` | the provider ranked the candidates above `tau_ret` | read the returned notes (top `k`) as your selection |
| `inactive` | no configured layer | use the returned `fallback` notes (BM25 order) |
| `consent_required` | layer enabled without recorded consent | same; name the state if asked |
| `provider_unavailable` | no API key, unreachable endpoint, or transport error | same |
| `provider_invalid_response` | the provider answer violated the wire contract | same |
| `no_candidates_above_threshold` | no note cleared the retrieval threshold | same; the BM25 order is returned as `fallback` notes |

In every non-`scored` state the `notes` field already carries the deterministic BM25 selection capped at `--limit`, so the retrieval workflow continues unchanged.

## Disclosure

When the layer was active and produced the selection, name it in the answer, for example `Notizauswahl: Entscheidungsschicht (Modell <model>)`. When it fell back, you do not need to advertise the failure, but you must not present the BM25 result as a classifier decision.

## Boundaries

- The layer is a maintenance concern. From the reading side you never configure, enable, or consent to it.
- An active layer means note content is transferred to the configured external endpoint under consent recorded by a maintainer. You did not decide that in this run, and you must not imply that you did.
- The provider's probabilities are a selection signal, not evidence. A claim is still evidenced only by its `source_id@locator` chain, and a note selected by the layer is no more or less true than one selected by BM25.
- The helper writes nothing. If the manifest verification fails before or after a scoring run, treat the wiki state exactly as the verification reports it.
