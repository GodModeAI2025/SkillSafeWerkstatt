#!/usr/bin/env python3
"""Quantities in another notation (Stufe 6): units, symbols and number words.

A number and the unit or word after it give one quantity token in a canonical
unit ("2,5 MWh" and "2500 kWh" give "=2500kwh"). Ranking and scan both read
it; the ranking only where it bridges a notation the query words cannot reach.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "query-llm-wiki" / "scripts"))

import search_core  # noqa: E402
from harness import PageTree, page  # noqa: E402


def quantities(text: str) -> list[str]:
    repaired = search_core.wordforms.repair_text(text)
    spelled = search_core.number_spelling(search_core.normalized(repaired))
    return [token for _, token in search_core.text_quantities(repaired, spelled)]


PAGES = {
    "wiki/schwelle.md": page("Gewerbetarif", "Ab einem Jahresverbrauch von 2,5 MWh gilt der Gewerbetarif."),
    "wiki/bonus.md": page("Wechselbonus", "Der Wechselbonus beträgt 50 € und wird verrechnet."),
    "wiki/arbeitspreis.md": page("Arbeitspreis Basis", "Der Arbeitspreis beträgt 0,3172 EUR/kWh brutto."),
    "wiki/widerruf.md": page("Widerrufsfrist", "Die Widerrufsfrist beträgt 14 Tage ab Vertragsschluss."),
    "wiki/erklaerung.md": page("Widerruf erklären", "Der Widerruf ist binnen 14 Tagen in Textform zu erklären."),
    "wiki/garantie.md": page("Preisgarantie", "Die Preisgarantie gilt zwölf Monate ab Lieferbeginn."),
    "wiki/anschluss.md": page("Anschlussleistung", "Die Anschlussleistung beträgt 2.500 kW im Vorjahr."),
    "wiki/zahlung.md": page("Ratenplan", "Der Kundenservice bietet zwölf Monatsraten für eine Nachzahlung an."),
    "wiki/preisaenderung.md": page("Preisänderung", "Veränderung des Arbeitspreises zum Vorjahr: minus 5 %."),
    "wiki/paragraf.md": page("Paragrafen", "Nach § 3 EnWG gelten drei Absätze."),
}

#: Pages whose numbers are no quantity of the probes below: a scale word
#: without a number, a label, a sign, a calendar week. From the precision
#: review of Stufe 6. Since Stufe 7 a scale word after a number multiplies:
#: budget.md ("100 Tausend Euro pro Jahr") reads as "=100000eur", an amount
#: no probe below asks for.
TRAPS = {
    "wiki/wallbox.md": page("Wallbox", "Die Wallbox wird mit einem Typ 2 Stecker geliefert und lädt mit bis zu 11 kW."),
    "wiki/baukosten.md": page(
        "Baukostenzuschuss Gewerbe", "Für Gewerbeanschlüsse fällt ein Baukostenzuschuss von mehreren hundert Euro an."
    ),
    "wiki/foerderung.md": page(
        "Förderprogramm Wärmepumpe", "Die Förderung für eine Wärmepumpe beträgt einige tausend Euro je Anlage."
    ),
    "wiki/budget.md": page("Förderbudget", "Das Förderbudget der Stadtwerke beträgt 100 Tausend Euro pro Jahr."),
    "wiki/montage.md": page("Montagetermine", "Die Montage der Wärmepumpe erfolgt frühestens in der 12 KW."),
    "wiki/heizstrom.md": page("Heizstrom", "Für Heizstrom gilt nachts der Stufe 2 Tarif mit reduziertem Arbeitspreis."),
    "wiki/preisaenderung.md": page("Preisänderung", "Veränderung des Arbeitspreises gegenüber dem Vorjahr: −5 %."),
    "wiki/euro6.md": page("Umweltprämie", "Für Euro 6 Fahrzeuge zahlen die Stadtwerke keine Umweltprämie."),
}


class QuantityTokens(unittest.TestCase):
    def test_units_of_one_dimension_meet_in_one_token(self) -> None:
        self.assertEqual(quantities("2,5 MWh"), ["=2500kwh"])
        self.assertEqual(quantities("2.500 kWh"), ["=2500kwh"])
        self.assertEqual(quantities("2500kWh"), ["=2500kwh"])
        self.assertEqual(quantities("0,8 kW"), quantities("800 W"))
        self.assertEqual(quantities("9,84 ct/kWh"), quantities("0,0984 EUR/kWh"))
        self.assertEqual(quantities("75,00 EUR"), quantities("75 €"))
        self.assertEqual(quantities("75 Euro"), ["=75eur"])
        self.assertEqual(quantities("19 %"), quantities("19 Prozent"))
        self.assertEqual(quantities("2,5 Megawattstunden"), ["=2500kwh"])
        self.assertEqual(quantities("1,5 Terawattstunden"), quantities("1500 GWh"))
        self.assertEqual(quantities("1,5 Terawattstunden"), ["=1500000000kwh"])

    def test_every_converted_symbol_has_its_written_word(self) -> None:
        """Each unit symbol the texts list converts like its written-out word, singular and plural."""
        units = search_core.QUANTITY_UNITS
        for symbol, words in (
            ("wh", ("wattstunde", "wattstunden")), ("kwh", ("kilowattstunde", "kilowattstunden")),
            ("mwh", ("megawattstunde", "megawattstunden")), ("gwh", ("gigawattstunde", "gigawattstunden")),
            ("twh", ("terawattstunde", "terawattstunden")), ("w", ("watt",)), ("kw", ("kilowatt",)),
            ("mw", ("megawatt",)), ("gw", ("gigawatt",)), ("ct", ("cent",)), ("eur", ("euro",)), ("€", ("euro",)),
            ("%", ("prozent",)), ("m3", ("kubikmeter", "kubikmetern")), ("l", ("liter", "litern")),
            ("ml", ("milliliter",)), ("kg", ("kilogramm",)), ("t", ("tonne", "tonnen")),
            ("m", ("meter", "metern")), ("km", ("kilometer", "kilometern")), ("cm", ("zentimeter",)), ("mm", ("millimeter",)),
            ("m2", ("quadratmeter", "quadratmetern")), ("km2", ("quadratkilometer",)), ("ha", ("hektar",)),
        ):
            for word in words:
                with self.subTest(symbol=symbol, word=word):
                    self.assertEqual(units[word], units[symbol])

    def test_whole_euro_and_prefixed_money_notations(self) -> None:
        """"75,- €" and "EUR 25,00" are money amounts like "75 €" (recall review of Stufe 6)."""
        for text, expected in (
            ("75,- €", "=75eur"), ("75,– €", "=75eur"), ("75,-- €", "=75eur"), ("75,- EUR", "=75eur"),
            ("€ 75", "=75eur"), ("EUR 25,00", "=25eur"), ("€ 1.500,00 je Anlage", "=1500eur"), ("EUR 9,84 netto", "=9.84eur"),
            ("€ 1,5 Mio. einmalig", "=1500000eur"), ("EUR 2 Tausend", "=2000eur"),
        ):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), [expected])
        # A sign before the amount or "Euro" before a number (Euro 6) give none.
        for text in ("minus € 5", "Euro 6 Fahrzeuge", "EUR/kWh 0,30", "75,- Tage"):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), [])

    def test_number_words_meet_digits_before_the_same_word(self) -> None:
        self.assertEqual(quantities("drei Monate"), quantities("3 Monaten"))
        self.assertEqual(quantities("zwölf Monate"), ["=12monat"])
        self.assertEqual(quantities("vierzehn Tage"), quantities("14 Tage"))
        # A number no number word names gains nothing from a plain word after it.
        self.assertEqual(quantities("2026 netto"), [])
        self.assertEqual(quantities("24 Monate"), [])
        # Articles are no number words.
        self.assertEqual(quantities("einen Monat"), [])

    def test_a_count_meets_its_dative_and_a_list_marker(self) -> None:
        # The closed count-word list keys every case form by one unit, and a
        # hyphen that starts a line is a list marker, no sign.
        for text in ("- 14 Tage", "binnen 14 Tagen", "vierzehn Tage"):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), ["=14tag"])

    def test_dimensions_stay_apart(self) -> None:
        self.assertNotEqual(quantities("2.500 kW"), quantities("2.500 kWh"))
        self.assertNotEqual(quantities("20 Prozentpunkte"), quantities("20 Prozent"))
        # kWp is no plain kW: it stays a counted word, never converted.
        self.assertNotEqual(quantities("10 kWp"), quantities("10 kW"))

    def test_identifiers_dates_and_citations_give_none(self) -> None:
        for text in (
            "31.12.2025", "1. Januar 2026", "OBIS 1.8.1", "0800 5546330", "0800 554 63 30", "Version 2.5 MWh",
            "§ 3 EnWG", "§ 41 Abs. 5 EnWG", "Art. 6 DSGVO", "Nr. 2 Satz 3 BGB", "Typ-2 Stecker", "12:30 Uhr",
            "24/7 Hotline", "4-Personen-Haushalt", "vier-Personen-Haushalt", "800W", "Bitte geben Sie Acht",
        ):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), [])

    def test_scales_signs_ranges_and_labels_give_none(self) -> None:
        """A number that is only part of the quantity, or no count at all, gives no token.

        A scale word without a number ("mehrere hundert Euro"), a glued unit
        compound ("20 %-Punkte"), a fraction, a sign or a range would lose a
        factor, the sign or the range; a number before a word outside the
        closed count-word list is a label.
        """
        for text in (
            "mehrere hundert Euro", "einige tausend Kilowattstunden", "20 %-Punkte", "50 €-Cent", "½ Jahr",
            "−15 %", "+5 %", "Veränderung - 5 %", "minus 20 Grad", "zwei Komma fünf Prozent", "1 - 3 Monate",
            "1-3 Monate", "1–3 Monate", "1 – 3 Monate", "1 — 3 Monate", "10–20 %", "1 bis 3 Monate", "2 bis 4 Wochen",
            "drei bis vier Wochen", "sechs bis zwölf Monate", "zwischen 10 und 20 Prozent", "zwischen 2 und 3 Monaten",
            "Typ 2 Stecker", "Kapitel 4 Abrechnung", "Stufe 2 Tarif", "Modul 2 reduziert", "## 3 Ablauf",
            "@page=1",
        ):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), [])

    def test_only_the_second_number_of_a_range_gives_none(self) -> None:
        """The upper bound of a range is skipped; a lower bound with its own unit, a dash
        between words, and "und" outside "zwischen ... und" leave a quantity."""
        self.assertEqual(quantities("von 10 € bis 20 €"), ["=10eur"])
        self.assertEqual(quantities("zwischen 10 € und 20 €"), ["=10eur"])
        self.assertEqual(quantities("Die Frist – wie üblich – drei Monate"), ["=3monat"])
        self.assertEqual(quantities("Ausbau bis 2028 und 95 Prozent Ökostrom"), ["=95prozent"])
        self.assertEqual(quantities("Hotline bis 14 Uhr, Rückruf binnen 14 Tagen"), ["=14tag"])

    def test_citations_places_identifiers_and_a_line_break(self) -> None:
        """A number after a citation, a place in a document or an identifier names no count; a line break
        joins a unit word only in running text (Stage 7)."""
        for text in (
            "§ 3 Tage", "Abs. 2 Jahre", "Nr. 12 Monate", "page=3 Tage", "auf Seite 12 Monate", "vgl. S. 12 Monate",
            "siehe Abschnitt 3 Tage", "Kapitel 4 Wochen", "Tabelle 2 Stunden", "Anhang 3 Monate", "Rn. 12 Monate", "Abb. 3 Tage",
            # The longest place word still fits the window of 12 characters before the number.
            "Randnummer 12 Monate",
        ):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), [])
        # "Anlage" (also a plant) and "Teil" ("zum Teil") are no place.
        self.assertEqual(quantities("die PV-Anlage 20 Jahre betreiben"), ["=20jahr"])
        self.assertEqual(quantities("zum Teil 14 Tage"), ["=14tag"])
        # "Seiten" is no place ("für beide Seiten 3 Monate", review of Stufe 7).
        self.assertEqual(quantities("Die Kündigungsfrist beträgt für beide Seiten 3 Monate"), ["=3monat"])
        # A label line ("Frist: 14", "Stand 2024") or a unit word alone on its line joins nothing.
        for text in (
            "Frist: 14\nTage", "Stand 2024\nEuro und Cent im Überblick", "Version 12\nMonate Laufzeit", "Hotline 12\nMonate",
            # Review of Stufe 7: the unit word alone on its line, and 18 characters before the number (LINE_JOIN_MIN 20).
            "Für alle Verträge im Tarif Basis beträgt die Frist 14\nTage\nab Vertragsschluss.",
            "Der Bonus beträgt 75\nEuro und wird verrechnet.",
        ):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), [])
        self.assertEqual(quantities("Für alle Verträge im Tarif Basis beträgt die Frist 14\nTage ab Vertragsschluss."), ["=14tag"])
        # 33 characters before the number are running text.
        self.assertEqual(quantities("Im Tarif Basis beträgt die Frist 14\nTage ab Vertragsschluss."), ["=14tag"])

    def test_case_tells_units_apart(self) -> None:
        """"KW" is a calendar week, "mW" a milliwatt; "kW", "MW" and "KWh" keep their reading (Stage 7)."""
        for text in ("in der 12 KW", "Liefertermin: 38 KW 2026", "zwölf KW", "12KW"):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), [])
        self.assertEqual(quantities("500 mW"), quantities("0,5 W"))
        self.assertEqual(quantities("500 mW"), ["=0.0005kw"])
        self.assertEqual(quantities("500 MW"), ["=500000kw"])
        self.assertEqual(quantities("12 kW"), ["=12kw"])
        self.assertEqual(quantities("2.500 KWh"), ["=2500kwh"])
        self.assertEqual(quantities("11 kw"), ["=11kw"])
        # A calendar week in the same text keeps "KWh" a kilowatt hour (review of Stufe 7).
        self.assertEqual(quantities("Montage in der 12 KW, Verbrauch 2.500 KWh"), ["=2500kwh"])

    def test_scale_words_multiply(self) -> None:
        """A scale word between number and unit is part of the amount (Stage 7)."""
        for texts, expected in (
            (("1,5 Mio. €", "€ 1,5 Mio.", "1.500.000 €", "1,5 Millionen Euro", "1500 Tsd. €", "1.500 T€", "1500 TEUR"), "=1500000eur"),
            (("2 Tsd. kWh", "2 Tausend Kilowattstunden", "2.000 kWh"), "=2000kwh"),
            (("zwei Millionen Euro", "2 Mio. EUR"), "=2000000eur"),
            (("eine Million Euro",), "=1000000eur"),
            (("75 Tausend Euro",), "=75000eur"), (("zehn Tausend Euro",), "=10000eur"), (("drei Hundert Watt",), "=0.3kw"),
        ):
            for text in texts:
                with self.subTest(text=text):
                    self.assertEqual(quantities(text), [expected])
        # A scale word before a count word names no count either (review of Stufe 7).
        for text in (
            "zwei Millionen Kunden", "2 Mio. Kunden", "rund 1,5 Mio. Haushalte", "Millionen Euro", "1.5 million EUR",
            "zwei Tausend Tage", "2 Mio. Monate", "2 Tausend Personen",
        ):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), [])

    def test_volume_mass_length_area_and_temperature(self) -> None:
        """A closed list of further units, each within its dimension (Stage 7)."""
        for texts, expected in (
            (("100 m³", "100 m3", "100 Kubikmeter", "100.000 Liter", "100.000 l"), "=100m3"),
            (("3,5 t", "3.500 kg", "3,5 Tonnen"), "=3500kg"),
            (("2 km", "2.000 m", "2000 Meter"), "=2000m"),
            (("20 m²", "20 qm", "20 Quadratmeter"), "=20m2"),
            (("1 ha", "10.000 m²"), "=10000m2"),
            (("20 °C", "20 Grad Celsius", "20 ℃", "20°C"), "=20celsius"),
            (("2,10 €/m³", "2,10 € je Kubikmeter"), "=2.1eur"),
        ):
            for text in texts:
                with self.subTest(text=text):
                    self.assertEqual(quantities(text), [expected])
        # A screw size, a tesla, a limited partnership, a speed, a glued letter, an angle, a sign, a
        # scaled euro, a citation and "5 G" are none of them.
        for text, expected in (
            ("2 M3 Schrauben", []), ("2 M3-Schrauben", []), ("BMW M3", []), ("3 T Feldstärke", []), ("2 KG Gesellschafter", []),
            ("3 m/s", []), ("50 km/h", []), ("6 l/100 km", []), ("3 hl Bier", []), ("1l Wasser", []), ("Neigung 20 Grad", []), ("minus 5 °C", []), ("-5 °C", []), ("LTE und 5 G", []),
            ("Abs. 1 l DSGVO", []), ("500 T€", ["=500000eur"]),
            # Review of Stufe 7: a calendar week or a tonne in the same text keeps a "T€" amount.
            ("Liefertermin 12 KW; Budget 500 T€", ["=500000eur"]), ("Der LKW wiegt 3,5 t. Budget: 500 T€.", ["=3500kg", "=500000eur"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(quantities(text), expected)

    def test_disclosed_residuals(self) -> None:
        """Readings the texts disclose as residuals of Stufe 7: a hit through them is checked in the text."""
        # Of a unit counted per another only the first is read: "0,10 € pro Tag" meets "10 Cent".
        self.assertEqual(quantities("0,10 € pro Tag"), ["=0.1eur"])
        self.assertEqual(quantities("0,10 € pro Tag"), quantities("10 Cent"))
        # "KW" is read by its case as a calendar week, so an upper-case power gives no quantity.
        self.assertEqual(quantities("11 KW Ladeleistung"), [])


class QuantitySearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tree = PageTree(PAGES)
        cls.root = cls._tree.__enter__()
        cls.loaded = search_core.load(cls.root, include_sources=True, exhaustive=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tree.__exit__(None, None, None)

    def search(self, query: str, *also: str) -> dict:
        return search_core.search_loaded(self.loaded, query, also=list(also), limit=12, exhaustive=True)

    def hit_pages(self, report: dict) -> list[str]:
        return [entry["path"] for entry in report["exhaustive_hits"]]

    def quantity_rules_on(self, report: dict, path: str) -> list[dict]:
        return [
            rule
            for result in report["results"]
            if result["path"] == path
            for rule in result["match_rules"]
            if rule["rule"] == "quantity"
        ]

    def test_the_ranking_reaches_another_unit(self) -> None:
        report = self.search("2.500 kWh Jahresverbrauch")
        self.assertEqual(report["results"][0]["path"], "wiki/schwelle.md")
        rules = {(rule["term"], rule["token"], rule["rule"]) for rule in report["results"][0]["match_rules"]}
        self.assertIn(("kwh", "=2500kwh", "quantity"), rules)

    def test_the_scan_reaches_units_symbols_and_number_words(self) -> None:
        for query, page_path in (
            ("Gewerbetarif ab 2500 kWh", "wiki/schwelle.md"),
            ("50 Euro Wechselbonus", "wiki/bonus.md"),
            ("Arbeitspreis 31,72 ct/kWh", "wiki/arbeitspreis.md"),
            ("Widerrufsfrist vierzehn Tage", "wiki/widerruf.md"),
            ("Preisgarantie 12 Monate", "wiki/garantie.md"),
        ):
            with self.subTest(query=query):
                report = self.search(query)
                self.assertIn(page_path, self.hit_pages(report))
                self.assertEqual(report["absence_check"]["absent_terms"], [])

    def test_a_number_word_reaches_the_dative_as_a_heuristic(self) -> None:
        report = self.search("Widerruf vierzehn Tage")
        [hit] = [hit for entry in report["exhaustive_hits"] if entry["path"] == "wiki/erklaerung.md" for hit in entry["hits"]]
        self.assertEqual(hit["strength"], "heuristic")
        self.assertIn({"term": "vierzehn", "token": "=14tag", "rule": "quantity", "in": "text"}, hit["matched"])
        self.assertNotIn("vierzehn", report["absence_check"]["absent_terms"])

    def test_a_query_written_like_the_page_gets_no_quantity_member(self) -> None:
        # The only page that holds "=12monat" writes "zwölf Monate" as the query does: no bridge is needed.
        self.assertEqual(quantities("Preisgarantie zwölf Monate"), ["=12monat"])
        report = self.search("Preisgarantie zwölf Monate")
        self.assertEqual(report["results"][0]["path"], "wiki/garantie.md")
        for result in report["results"]:
            self.assertNotIn("quantity", {rule["rule"] for rule in result["match_rules"]})

    def test_claims_and_snippet_read_the_quantity(self) -> None:
        """The claim and the line that give the amount only in another unit are the ones shown."""

        def claim(identifier: str, text: str) -> str:
            return f"<!-- claim\nid: {identifier}\nkind: fact\nstatus: active\nsources: src-1@page=1\n-->\n{text}\n<!-- /claim -->"

        body = "\n\n".join((
            "Der Jahresverbrauch wird einmal im Jahr vom Messstellenbetreiber abgelesen und gemeldet.",
            "Ab 2,5 MWh Jahresverbrauch gilt der Gewerbetarif.",
            claim("clm-00000000000000a1", "Der Jahresverbrauch steht auf der Rechnung."),
            claim("clm-00000000000000a2", "Die Schwelle liegt bei 2,5 MWh."),
        ))
        pages = {
            "wiki/topics/tarif.md": page("Tarifschwelle", body, heading=True),
            "wiki/topics/sonst.md": page("Sonstiges", "Nichts dazu.", heading=True),
        }
        with PageTree(pages) as root:
            report = search_core.search(root, "Jahresverbrauch 2500 kWh", limit=12)
        top = report["results"][0]
        self.assertEqual(top["path"], "wiki/topics/tarif.md")
        self.assertIn("clm-00000000000000a2", [item["id"] for item in top["claims"]])
        self.assertEqual(top["snippet"], "Ab 2,5 MWh Jahresverbrauch gilt der Gewerbetarif.")

    def test_no_wrong_equivalence(self) -> None:
        """Every other word of the query is on the page; only a wrong equivalence would make it a hit.

        kW is no kWh; "zwölf Monatsraten" is no count of months; "minus 5 %"
        is no "5 Prozent".
        """
        for query, page_path in (
            ("Anschlussleistung 2500 kWh", "wiki/anschluss.md"),
            ("Kundenservice zwölf Monate Nachzahlung", "wiki/zahlung.md"),
            ("Veränderung Arbeitspreis Vorjahr 5 Prozent", "wiki/preisaenderung.md"),
        ):
            with self.subTest(query=query):
                report = self.search(query)
                self.assertNotIn(page_path, self.hit_pages(report))
                self.assertEqual(self.quantity_rules_on(report, page_path), [])
                # The page is ranked through the words it holds.
                self.assertIn(page_path, [result["path"] for result in report["results"]])


class QuantityBridge(unittest.TestCase):
    """When the ranking takes a quantity token as a member, and what the scan adds without it."""

    def quantity_members(self, pages: dict, query: str) -> dict[str, list[tuple[str, str]]]:
        with PageTree(pages) as root:
            report = search_core.search(root, query, limit=12)
        return {
            result["path"]: sorted((rule["term"], rule["token"]) for rule in result["match_rules"] if rule["rule"] == "quantity")
            for result in report["results"]
        }

    def test_only_a_word_that_reaches_no_page_with_the_amount_bridges(self) -> None:
        """"14" bridges to "vierzehn Tage"; "Tage" already reaches that page and takes no quantity."""
        found = self.quantity_members({
            "wiki/topics/a.md": page("Frist A", "Die Frist beträgt 14 Tage.", heading=True),
            "wiki/topics/b.md": page("Frist B", "Die Frist beträgt vierzehn Tage.", heading=True),
        }, "Frist 14 Tage")
        self.assertEqual(found, {"wiki/topics/a.md": [("14", "=14tag")], "wiki/topics/b.md": [("14", "=14tag")]})

    def test_a_navigation_page_never_opens_the_bridge(self) -> None:
        found = self.quantity_members({
            "wiki/index.md": page("Index", "Alles zur Frist von vierzehn Tagen.", "index"),
            "wiki/topics/a.md": page("Frist A", "Die Frist beträgt 14 Tage.", heading=True),
            "wiki/topics/c.md": page("Frist C", "Die Frist ist anders geregelt.", heading=True),
        }, "Frist 14 Tage")
        self.assertIn("wiki/topics/a.md", found)
        self.assertEqual({path: members for path, members in found.items() if members}, {})

    def test_the_scan_adds_a_quantity_the_ranking_did_not_take(self) -> None:
        """The only page with "=14tag" also holds "14" ("bis 14 Uhr"), so the ranking takes no
        quantity member; the scan still finds "vierzehn Tage" through the query word's token."""
        pages = {
            "wiki/topics/widerruf.md": page(
                "Widerruf", "Die Widerrufsfrist beträgt vierzehn Tage.\n\n## Kontakt\n\nDie Hotline ist bis 14 Uhr erreichbar.",
                heading=True,
            ),
            "wiki/topics/sonst.md": page("Sonstiges", "Hier steht nichts zur Sache.", heading=True),
        }
        with PageTree(pages) as root:
            report = search_core.search(
                root, "Widerrufsfrist 14 Tage", also=["Widerruf binnen 14 Tagen", "Rücktritt Frist zwei Wochen"],
                limit=12, exhaustive=True,
            )
        ranked = [rule for result in report["results"] for rule in result["match_rules"] if rule["rule"] == "quantity"]
        self.assertEqual(ranked, [])
        matched = [
            entry for page_ in report["exhaustive_hits"] if page_["path"] == "wiki/topics/widerruf.md"
            for hit in page_["hits"] for entry in hit.get("matched") or []
        ]
        self.assertIn({"term": "14", "token": "=14tag", "rule": "quantity", "in": "text"}, matched)


class QuantityNegatives(unittest.TestCase):
    """Absence-style negatives with quantities in every formulation: no page answers them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tree = PageTree(TRAPS)
        cls.root = cls._tree.__enter__()
        cls.loaded = search_core.load(cls.root, include_sources=True, exhaustive=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tree.__exit__(None, None, None)

    def search(self, query: str, *also: str) -> dict:
        return search_core.search_loaded(self.loaded, query, also=list(also), limit=12, exhaustive=True)

    def test_negatives_stay_complete_without_a_quantity_hit(self) -> None:
        for name, trap, query, also in (
            (
                "n1", "wiki/wallbox.md", "Wallbox zwei Ladepunkte",
                ("Wallbox mit zwei Steckern", "Doppel-Wallbox zwei Stecker", "Wallbox 2 Ladepunkte gleichzeitig"),
            ),
            (
                "n4", "wiki/baukosten.md", "Baukostenzuschuss 100 Euro",
                ("BKZ Gewerbe 100 €", "Baukostenzuschuss Gewerbeanschluss 100 EUR", "Zuschuss Netzanschluss 100 Euro"),
            ),
            (
                "n5", "wiki/foerderung.md", "Förderung Wärmepumpe 1000 Euro",
                ("Wärmepumpe Zuschuss 1.000 €", "Förderung 1000 EUR Wärmepumpe", "Wärmepumpenförderung 1000 Euro"),
            ),
        ):
            with self.subTest(probe=name, trap=trap):
                report = self.search(query, *also)
                check = report["absence_check"]
                self.assertTrue(check["complete"], check["reasons"])
                self.assertEqual(check["counts"]["hits_word_form"], 0)
                for result in report["results"]:
                    self.assertNotIn("quantity", {rule["rule"] for rule in result["match_rules"]}, result["path"])
                for entry in report["exhaustive_hits"]:
                    for hit in entry["hits"]:
                        rules = {item["rule"] for item in hit.get("matched", ())}
                        self.assertNotIn("quantity", rules, entry["path"])

    def test_a_calendar_week_is_no_power(self) -> None:
        # "12 KW" names a calendar week: "12000 Watt" reaches the page through no quantity (Stage 7).
        report = self.search("Wärmepumpe 12000 Watt")
        hits = [hit for entry in report["exhaustive_hits"] if entry["path"] == "wiki/montage.md" for hit in entry["hits"]]
        self.assertEqual([item for hit in hits for item in hit.get("matched") or () if item["rule"] == "quantity"], [])
        self.assertEqual(report["absence_check"]["counts"]["hits_word_form"], 0)


if __name__ == "__main__":
    unittest.main()
