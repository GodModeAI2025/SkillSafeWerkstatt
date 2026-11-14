# -*- coding: utf-8 -*-
"""Tiny authoring helpers for the fixture pages. No wiki logic lives here."""

PAGES = []


def C(text, src, kind="fact", status="active", label=None, replaces=None, contradicts=None):
    """One claim block. `src` is 'S1@page=2' or several joined with ' | '."""
    return {"text": text, "src": src, "kind": kind, "status": status,
            "label": label, "replaces": replaces, "contradicts": contradicts}


def page(path, title, description, body, type=None, status="active", aliases=None,
         concepts=None, cluster="vertrag", gt=(), stale_after=None):
    """Register one curated page. `gt` holds authoring-time topic tags used only
    for the broad ground-truth queries (v=Vertrag, k=Kuendigung, f=Fristen,
    p=Preise, z=Zaehler); it is never written into the wiki."""
    folder = path.split("/")[1] if path.count("/") > 1 else "overview"
    kind = type or {"concepts": "concept", "entities": "entity", "topics": "topic",
                    "comparisons": "comparison"}[folder]
    PAGES.append(dict(path=path, title=title, description=description, body=body,
                      type=kind, status=status, aliases=aliases or [],
                      concepts=concepts or [], cluster=cluster, gt=tuple(gt),
                      stale_after=stale_after))
