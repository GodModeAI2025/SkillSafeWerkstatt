#!/usr/bin/env python3
"""Optional, consent-gated decision layer for SkillSafeWerkstatt.

Implements the split described by Cesarini and Sassarini ("CROW: Classifier-
Routed Organization of LLM Wikis", 2026, doi:10.5281/zenodo.23260209) as a
vendor-neutral contract: a typed decision provider answers atomic questions
(one choice among options, or one yes/no statement) with probabilities, and
the confidence of each answer gates an explicit fallback to the agent.

The module is deliberately conservative:

- The layer is inactive unless `schema/DECISION_LAYER.md` exists, is enabled,
  and records explicit user consent for the data transfer.
- No bundled helper starts a service. The one outbound transport call is a
  plain client request issued by the calling helper after all gates passed.
- Probabilities are trusted for ranking and thresholding only; confidence
  measures how concentrated an answer is, not whether it is correct.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from frontmatter_contract import FrontmatterError, parse_document


FORMAT = "lmwiki-decision/1"
CONFIG_PATH = "schema/DECISION_LAYER.md"
MAX_OPTIONS = 255
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

TAU_FIELDS = ("tau_route", "tau_path", "tau_ing", "tau_cons", "tau_link", "tau_fold", "tau_ret")
INTEGER_FIELDS = {
    "timeout_seconds": (1, 600),
    "attempts": (1, 10),
    "state_chars": (500, 1000000),
    "request_chars": (1000, 10000000),
    "beam": (1, 8),
    "k": (1, 50),
    "max_depth": (1, 8),
    "max_links": (1, 20),
    "max_notes_per_cluster": (1, 10000),
}


class DecisionError(ValueError):
    """Raised for provider transport or response contract violations."""


def clamp_state(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


def question_choice(qid: str, question: str, options: list[str]) -> dict[str, Any]:
    if not qid or not question.strip():
        raise DecisionError("a decision question needs an id and a question")
    options = [str(option) for option in options]
    if not 1 <= len(options) <= MAX_OPTIONS:
        raise DecisionError(f"a choice question needs 1..{MAX_OPTIONS} options")
    if len(set(options)) != len(options):
        raise DecisionError("choice options must be unique")
    return {"id": qid, "type": "choice", "question": " ".join(question.split()), "options": options}


def question_yes_no(qid: str, question: str) -> dict[str, Any]:
    if not qid or not question.strip():
        raise DecisionError("a decision question needs an id and a question")
    return {"id": qid, "type": "yes_no", "question": " ".join(question.split())}


def build_request(config: dict[str, Any], state_text: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    state = clamp_state(state_text, int(config["state_chars"]))
    if not state:
        raise DecisionError("the decision state must not be empty")
    if not questions:
        raise DecisionError("a decision request needs at least one question")
    total = len(state) + sum(len(q["question"]) + sum(len(o) for o in q.get("options", [])) for q in questions)
    if total > int(config["request_chars"]):
        raise DecisionError(
            f"the decision request holds {total} characters and exceeds the request budget of "
            f"{config['request_chars']}; split it into smaller batches"
        )
    return {
        "format": FORMAT,
        "model": str(config["model"]),
        "state": state,
        "questions": list(questions),
    }


def confidence_choice(probabilities: dict[str, float]) -> float:
    """How peaked a choice distribution is. It is not a correctness estimate."""
    return max(probabilities.values()) if probabilities else 0.0


def confidence_yes_no(probability: float) -> float:
    return max(probability, 1.0 - probability)


def geometric_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    if any(value <= 0 for value in values):
        return 0.0
    return math.exp(sum(math.log(value) for value in values) / len(values))


def validate_response(request: dict[str, Any], response: Any) -> dict[str, dict[str, Any]]:
    """Normalize one provider response against the request it answers.

    Accepts either a bare JSON list of answers or an envelope object whose
    "answers" list carries them. Raises DecisionError on any contract
    violation so the caller can fall back instead of guessing.
    """
    if isinstance(response, list):
        answers_raw = response
    elif isinstance(response, dict) and isinstance(response.get("answers"), list):
        answers_raw = response["answers"]
    else:
        raise DecisionError("provider response must be a list of answers or an object with an answers list")

    requested = {question["id"]: question for question in request.get("questions", [])}
    if not requested:
        raise DecisionError("the request carries no questions")

    normalized: dict[str, dict[str, Any]] = {}
    for entry in answers_raw:
        if not isinstance(entry, dict):
            raise DecisionError("every provider answer must be an object")
        qid = entry.get("id")
        if not isinstance(qid, str) or qid not in requested:
            raise DecisionError(f"provider answered an unknown question id: {qid!r}")
        if qid in normalized:
            raise DecisionError(f"provider answered question {qid} more than once")
        question = requested[qid]
        answer_type = entry.get("type")
        if answer_type == "choice":
            if question["type"] != "choice":
                raise DecisionError(f"question {qid} expects a yes_no answer, not a choice")
            probabilities = entry.get("probabilities")
            if not isinstance(probabilities, dict):
                raise DecisionError(f"choice answer for {qid} needs a probabilities object")
            if set(probabilities) != set(question["options"]):
                raise DecisionError(f"choice answer for {qid} must cover exactly the requested options")
            values: list[float] = []
            for option, value in probabilities.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise DecisionError(f"probability for option {option!r} is not a number")
                if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                    raise DecisionError(f"probability for option {option!r} is out of range")
                values.append(float(value))
            if abs(sum(values) - 1.0) > 0.02:
                raise DecisionError(f"choice probabilities for {qid} sum to {sum(values):.4f}, not 1")
            normalized[qid] = {"type": "choice", "probabilities": probabilities}
        elif answer_type == "yes_no":
            if question["type"] != "yes_no":
                raise DecisionError(f"question {qid} expects a choice answer, not a yes_no")
            probability = entry.get("probability")
            if not isinstance(probability, (int, float)) or isinstance(probability, bool):
                raise DecisionError(f"yes_no answer for {qid} needs a numeric probability")
            if not math.isfinite(float(probability)) or not 0.0 <= float(probability) <= 1.0:
                raise DecisionError(f"yes_no probability for {qid} is out of range")
            normalized[qid] = {"type": "yes_no", "probability": float(probability)}
        else:
            raise DecisionError(f"provider answer for {qid} has unsupported type {answer_type!r}")

    missing = sorted(set(requested) - set(normalized))
    if missing:
        raise DecisionError(f"provider did not answer: {missing}")
    return normalized


def send_request(
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int = 60,
    attempts: int = 3,
) -> tuple[Any, dict[str, Any]]:
    """Send one decision request to the configured endpoint (outbound client call).

    Returns the decoded JSON response plus a transport record (attempts, HTTP
    status, latency). The API key is attached as a bearer token and never
    appears in any error message.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    last_error = "no attempt was made"
    started = time.monotonic()
    used = 0
    for attempt in range(1, max(1, attempts) + 1):
        used = attempt
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            last_error = f"HTTP {status}"
            if status in RETRYABLE_STATUS and attempt < attempts:
                time.sleep(0.5 * attempt)
                continue
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            last_error = f"unreachable endpoint: {reason}"
            if attempt < attempts:
                time.sleep(0.5 * attempt)
                continue
            break
        else:
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise DecisionError(f"provider response is not valid JSON: {exc}") from exc
            return decoded, {
                "attempts": used,
                "status": status,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
    raise DecisionError(f"decision provider request failed after {used} attempt(s): {last_error}")


def _as_int(config: dict[str, Any], key: str) -> int:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DecisionError(f"{key} must be an integer")
    low, high = INTEGER_FIELDS[key]
    if not low <= value <= high:
        raise DecisionError(f"{key} must be between {low} and {high}")
    return value


def _as_tau(config: dict[str, Any], key: str) -> float:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionError(f"{key} must be a number between 0 and 1")
    if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
        raise DecisionError(f"{key} must be between 0 and 1")
    return float(value)


def load_config(target: Path) -> dict[str, Any]:
    """Load and validate the optional decision layer configuration.

    Returns {"state": ..., "reason": ..., "config": {...}} where state is one
    of "inactive", "consent_required", "misconfigured", "active". Only "active"
    authorizes a provider call; every other state means the caller falls back
    to its standard, deterministic behavior.
    """
    path = target / CONFIG_PATH
    if not path.is_file():
        return {"state": "inactive", "reason": f"{CONFIG_PATH} does not exist; the decision layer is not configured", "config": {}}
    try:
        document = parse_document(path.read_text(encoding="utf-8"), CONFIG_PATH, require_frontmatter=True)
    except FrontmatterError as exc:
        return {
            "state": "misconfigured",
            "reason": f"{CONFIG_PATH} is outside the strict frontmatter subset: {exc}",
            "config": {"exists": True},
        }
    raw = document.data
    config: dict[str, Any] = {"exists": True}
    try:
        schema_version = raw.get("schema_version")
        if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
            raise DecisionError("schema_version must be 1")
        config["schema_version"] = schema_version
        status = raw.get("status")
        if status not in ("draft", "active"):
            raise DecisionError("status must be draft or active")
        config["status"] = status
        if not isinstance(raw.get("enabled"), bool):
            raise DecisionError("enabled must be a boolean")
        config["enabled"] = bool(raw.get("enabled"))
        provider = raw.get("provider")
        if not isinstance(provider, str) or provider != "http":
            raise DecisionError("provider must be http")
        config["provider"] = provider
        endpoint = str(raw.get("endpoint") or "")
        if endpoint and not endpoint.startswith(("http://", "https://")):
            raise DecisionError("endpoint must be an http or https URL")
        config["endpoint"] = endpoint
        model = str(raw.get("model") or "")
        config["model"] = model
        api_key_env = str(raw.get("api_key_env") or "")
        if api_key_env and not ENV_NAME_RE.fullmatch(api_key_env):
            raise DecisionError("api_key_env must be a plain environment variable name")
        config["api_key_env"] = api_key_env
        config["consent_by"] = str(raw.get("consent_by") or "")
        config["consent_at"] = str(raw.get("consent_at") or "")
        for key in TAU_FIELDS:
            config[key] = _as_tau(raw, key)
        for key in INTEGER_FIELDS:
            config[key] = _as_int(raw, key)
    except DecisionError as exc:
        return {"state": "misconfigured", "reason": f"{CONFIG_PATH}: {exc}", "config": {"exists": True, **config}}

    if not config["enabled"]:
        return {"state": "inactive", "reason": f"{CONFIG_PATH} exists but enabled is false", "config": config}
    if config["status"] != "active":
        return {
            "state": "misconfigured",
            "reason": f"{CONFIG_PATH}: an enabled decision layer requires status active (currently draft)",
            "config": config,
        }
    if not config["consent_by"] or not config["consent_at"]:
        return {
            "state": "consent_required",
            "reason": (
                f"{CONFIG_PATH}: enabled is true, but no explicit consent is recorded. "
                "Confirming consent means accepting that note and question content is sent to the "
                "configured external endpoint. Record consent_by and consent_at after the user's explicit approval."
            ),
            "config": config,
        }
    if not config["endpoint"] or not config["model"] or not config["api_key_env"]:
        return {
            "state": "misconfigured",
            "reason": f"{CONFIG_PATH}: endpoint, model, and api_key_env are all required for an enabled decision layer",
            "config": config,
        }
    return {"state": "active", "reason": "", "config": config}


def api_key_for(config: dict[str, Any]) -> Optional[str]:
    name = str(config.get("api_key_env") or "")
    if not name:
        return None
    return os.environ.get(name) or None
