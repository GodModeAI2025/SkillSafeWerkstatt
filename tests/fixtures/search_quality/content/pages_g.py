# -*- coding: utf-8 -*-
"""Closing practice notes appended to pages that were too thin (prose only, no new claims)."""
from .dsl import PAGES

EXTRA = {
"wiki/overview.md":
    "## Arbeitsweise\n\nJede Seite trennt belegte Aussagen von Einordnung und Beratungshinweisen. Abgelöste Seiten bleiben als Historie erhalten und sind entsprechend gekennzeichnet; Entwürfe dürfen Kunden gegenüber nicht als geltende Regel verwendet werden. Offene Punkte stehen in der Fragenliste der Redaktion.",
"wiki/entities/tarif-lindenstrom-basis.md":
    "## Typische Fragen\n\nViele Kunden wissen nicht, dass sie in Basis sind, weil sie nie etwas unterschrieben haben. Der Vertrag ist trotzdem wirksam, sobald Strom entnommen wird. Ein Wechsel in einen anderen Tarif der Stadtwerke ist jederzeit zum nächsten Monatsersten möglich.",
"wiki/concepts/messstellenbetrieb.md":
    "## Abrechnung des Entgelts\n\nDas Entgelt für den Messstellenbetrieb ist bei den meisten Haushalten im Grundpreis des Stromtarifs enthalten und wird vom Lieferanten an den Messstellenbetreiber weitergereicht. Hat der Kunde einen wettbewerblichen Messstellenbetreiber beauftragt, erhält er von diesem eine eigene Rechnung.",
"wiki/topics/vertrieb-an-der-haustuer.md":
    "Solange das Pilotprojekt nicht freigegeben ist, gilt: Wer an der Tür im Namen der Stadtwerke Verträge anbietet, handelt nicht in unserem Auftrag. Kunden, die davon berichten, bitten wir um Datum und Uhrzeit des Besuchs.",
"wiki/entities/schlichtungsstelle-energie.md":
    "Geht ein Schlichtungsantrag ein, fordert die Stelle das Unternehmen zur Stellungnahme auf. Zuständig für die Antwort ist die Rechtsabteilung, nicht der Kundenservice.",
"wiki/entities/tarif-lindenstrom-fix12.md":
    "Für Kunden mit Wärmepumpe oder Elektroauto lohnt zusätzlich der Blick auf die reduzierten Netzentgelte für steuerbare Geräte.",
"wiki/concepts/vertragslaufzeit.md":
    "Eine Erstlaufzeit von mehr als zwölf Monaten bieten die Stadtwerke Haushaltskunden derzeit in keinem Tarif mehr an.",
"wiki/entities/tarif-lindenstrom-flex.md":
    "Die Stundenpreise des Folgetages sind ab dem frühen Nachmittag im Kundenportal einsehbar.",
"wiki/entities/tarif-lindenstrom-klassik.md":
    "In alten Rechnungen und Schreiben taucht der Tarifname noch bis Ende 2026 auf.",
}

for entry in PAGES:
    if entry["path"] in EXTRA:
        entry["body"].append(EXTRA.pop(entry["path"]))
assert not EXTRA, EXTRA
