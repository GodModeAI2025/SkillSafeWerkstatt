# -*- coding: utf-8 -*-
"""Confirmed schema additions, identity input and authoring guards for the fixture."""

IDENTITY = {
    "identity": {
        "purpose": "Vertrags- und Tarifwissen der Stadtwerke Lindenau für Kundenservice und Vertrieb bereitstellen.",
        "knowledge_types": ["concept", "entity", "topic", "comparison"],
        "audience": "Mitarbeitende im Kundenservice, Vertrieb und Forderungsmanagement.",
        "answer_language": "de",
        "form_of_address": "Sie",
        "tone": "sachlich",
        "detail": "medium",
        "answer_structure": "Antwort, dann Belege.",
        "citation_display": "claim_id, Titel, Quelle",
        "uncertainty_style": "Unsicherheit ausdrücklich benennen.",
        "history_presentation": "Abgelöstes als Historie kennzeichnen.",
        "boundaries": "Nur belegtes Wissen aus diesem Wiki.",
        "taboos": "Keine erfundenen Quellen, keine Rechtsberatung.",
    },
    "content_policy": {
        "update_model": "current-state",
        "supersession_policy": "Neuere belegte Aussage ersetzt ältere nur ausdrücklich.",
        "removal_policy": "preview-confirm-never-automatic",
        "conflict_policy": "preserve-and-disclose",
    },
}

CLUSTERS_MD = """
## vertrag
- Label: Vertrag und Kündigung
- Color: #000099
- Status: active
- Purpose: Zustandekommen, Laufzeit, Beendigung und Wechsel von Lieferverträgen

## preise
- Label: Preise und Tarife
- Color: #FE8F11
- Status: active
- Purpose: Tarife, Preisbestandteile, Preisänderungen und Boni

## abrechnung
- Label: Abrechnung und Zahlung
- Color: #1195EB
- Status: active
- Purpose: Abschläge, Zählerstände, Rechnungen, Mahnwesen

## netz-messung
- Label: Netz und Messwesen
- Color: #84C041
- Status: active
- Purpose: Netzentgelte, Messstellenbetrieb, Zähler und Marktkennungen

## organisation
- Label: Akteure und Abläufe
- Color: #FFC83A
- Status: active
- Purpose: Unternehmen, Stellen und übergreifende Abläufe
"""

# Eight active concepts. Deliberately NOT controlled: Kündigung, Preisanpassung,
# Zählerstand, Umzug, Zahlungsverzug, intelligentes Messsystem, Bonus, Beschwerde,
# Ökostrom, Jahresverbrauchsabrechnung, Ratenzahlung and all their everyday synonyms.
CONCEPTS_MD = """
## netzentgelt
- Preferred: Netzentgelt
- Status: active
- Definition: Entgelt des Netzbetreibers für die Nutzung des Stromnetzes
- Aliases: Netznutzungsentgelt | Netzgebühr | grid fee

## grundversorgung
- Preferred: Grundversorgung
- Status: active
- Definition: Gesetzliche Belieferung von Haushaltskunden durch den Grundversorger
- Aliases: Basisversorgung | Grundtarif

## abschlag
- Preferred: Abschlagszahlung
- Status: active
- Definition: Regelmäßige Zahlung auf den voraussichtlichen Jahresverbrauch vor der Abrechnung
- Aliases: Abschlag | Teilbetrag

## lieferantenwechsel
- Preferred: Lieferantenwechsel
- Status: active
- Definition: Wechsel des Stromlieferanten an einer Marktlokation
- Aliases: Anbieterwechsel | Versorgerwechsel | supplier switch

## messstellenbetrieb
- Preferred: Messstellenbetrieb
- Status: active
- Definition: Einbau, Betrieb und Wartung von Messeinrichtungen
- Aliases: Zählerbetrieb | MSB
- Related: netzentgelt

## bonitaetspruefung
- Preferred: Bonitätsprüfung
- Status: active
- Definition: Prüfung der Zahlungsfähigkeit eines Antragstellers vor Vertragsbestätigung
- Aliases: Kreditwürdigkeitsprüfung | Schufa-Abfrage

## widerrufsrecht
- Preferred: Widerrufsrecht
- Status: active
- Definition: Recht des Verbrauchers, einen Vertrag binnen 14 Tagen zu widerrufen
- Aliases: Widerruf | Rücktrittsrecht

## versorgungsunterbrechung
- Preferred: Versorgungsunterbrechung
- Status: active
- Definition: Unterbrechung der Stromlieferung wegen Zahlungsverzugs
- Aliases: Stromsperre | Sperrung
- Related: abschlag
"""

QUESTIONS_MD = """
## Offene Punkte nach der Erstbefüllung

- Wird der Sofortbonus zurückgefordert, wenn der Kunde den Vertrag widerruft oder vor Ablauf von zwölf Monaten kündigt? Die Stromlieferbedingungen regeln das nicht ausdrücklich.
- Gilt die Bagatellgrenze von 100,00 EUR für die Versorgungsunterbrechung auch im Sondervertrag? Belegt ist sie nur für die Grundversorgung.
- Das Notfallhandbuch und der Leitfaden zu Solarstrom in Mehrfamilienhäusern sind registriert, aber noch nicht in Seiten überführt.
"""

# Authoring guard, checked by build_fixture.py against the curated pages only.
# These words must not occur on any wiki page so that the ground-truth premises
# hold: (a) everyday synonyms that are NOT in CONCEPTS.md, (b) topics that exist
# only in sources/, (c) CONCEPTS.md aliases that are deliberately kept off the pages.
ABSENT_TERMS = {
    # (a) uncontrolled synonyms
    "Preiserhöhung", "Tariferhöhung", "Smart Meter", "Smart-Meter", "Wohnungswechsel",
    "Grünstrom", "Reklamation", "Prämie", "Zahlungsrückstand", "Zählerwert", "Jahresrechnung",
    # (b) source-only topics
    "Inkasso", "Verjährung", "Insolvenz", "Stromausfall", "Störungshotline", "Mieterstrom",
    "Eichfrist", "Überspannung", "Gebäudeversorgung", "Vorrangregister", "Notstrom",
    # (c) controlled aliases kept off the pages
    "Netznutzungsentgelt", "Netzgebühr", "Anbieterwechsel", "Versorgerwechsel", "Stromsperre",
    "Sperrung", "Schufa-Abfrage", "Kreditwürdigkeitsprüfung", "Zählerbetrieb", "Basisversorgung",
    "Rücktrittsrecht", "Teilbetrag",
}
