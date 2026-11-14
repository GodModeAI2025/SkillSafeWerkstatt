# -*- coding: utf-8 -*-
"""Faithful source extractions, part A (S1-S4). Fictional supplier, realistic rules."""

SOURCES = []

SOURCES.append(dict(
    key="S1",
    title="Allgemeine Stromlieferbedingungen Sondervertrag 2026",
    ref="intern/vertrieb/agb-strom-sondervertrag-2026.pdf",
    type="pdf",
    version="Stand 01.01.2026",
    text="""<!-- page: 1 -->

## § 1 Vertragsschluss und Lieferbeginn

Der Stromliefervertrag kommt zustande, sobald die Stadtwerke Lindenau Vertrieb GmbH (nachfolgend „Lieferant“) dem Kunden die Vertragsbestätigung in Textform übermittelt, spätestens jedoch mit Aufnahme der Belieferung. Der Lieferant behält sich vor, vor der Vertragsbestätigung eine Bonitätsprüfung durchzuführen.

Die Belieferung beginnt frühestens nach Ablauf der Widerrufsfrist, es sei denn, der Kunde verlangt ausdrücklich einen früheren Lieferbeginn.

## § 2 Vertragslaufzeit und Kündigung

Die Erstlaufzeit beträgt im Tarif LindenStrom Fix12 zwölf Monate, im Tarif LindenStrom Flex einen Monat. Wird der Vertrag nicht zum Ende der Erstlaufzeit gekündigt, verlängert er sich auf unbestimmte Zeit. Die Kündigungsfrist beträgt einen Monat zum Ende der Erstlaufzeit; nach der Verlängerung kann der Vertrag jederzeit mit einer Frist von einem Monat gekündigt werden.

Die Kündigung bedarf der Textform. Der Lieferant bestätigt dem Kunden die Kündigung innerhalb einer Woche nach Zugang unter Angabe des Vertragsendes (§ 41b Abs. 1 EnWG).

<!-- page: 2 -->

## § 3 Preise, Preisgarantie und Preisanpassung

Der Strompreis setzt sich aus einem verbrauchsunabhängigen Grundpreis in Euro je Monat und einem Arbeitspreis in Cent je Kilowattstunde zusammen.

Im Tarif LindenStrom Fix12 gilt für die ersten zwölf Monate eine eingeschränkte Preisgarantie. Sie umfasst die Kosten für Energiebeschaffung, Vertrieb und Netzentgelte. Von der Preisgarantie ausgenommen sind die Stromsteuer, die Umsatzsteuer sowie neu eingeführte staatliche Umlagen.

Preisanpassungen teilt der Lieferant Haushaltskunden spätestens einen Monat vor dem geplanten Wirksamwerden in Textform mit. Im Fall einer Preisanpassung kann der Kunde den Vertrag ohne Einhaltung einer Frist zum Zeitpunkt des Wirksamwerdens der Änderung kündigen (§ 41 Abs. 5 EnWG). Auf dieses Sonderkündigungsrecht wird in der Mitteilung hingewiesen.

Änderungen der Umsatzsteuer werden ohne Ankündigung und ohne Sonderkündigungsrecht an den Kunden weitergegeben.

<!-- page: 3 -->

## § 4 Abschlagszahlungen und Abrechnung

Der Kunde leistet elf monatliche Abschlagszahlungen je Abrechnungsjahr. Die Abschläge sind nach Wahl des Kunden zum 1. oder zum 15. eines Monats fällig.

Die Jahresverbrauchsabrechnung erhält der Kunde spätestens sechs Wochen nach Ende des Abrechnungszeitraums. Ein Guthaben wird binnen zwei Wochen nach Rechnungsstellung ausgezahlt oder mit dem nächsten Abschlag verrechnet. Auf Wunsch des Kunden rechnet der Lieferant monatlich, vierteljährlich oder halbjährlich ab (§ 40b EnWG).

## § 5 Zahlungsverzug

Bei Zahlungsverzug berechnet der Lieferant ab der zweiten Mahnung eine Mahnpauschale von 2,50 EUR je Mahnschreiben. Verzugszinsen fallen in Höhe von fünf Prozentpunkten über dem Basiszinssatz an. Für eine vom Kunden zu vertretende Rücklastschrift werden 4,00 EUR zuzüglich der Bankgebühr berechnet.

<!-- page: 4 -->

## § 6 Umzug

Der Kunde ist verpflichtet, dem Lieferanten einen Umzug mit einer Frist von sechs Wochen unter Angabe der neuen Anschrift und des Auszugsdatums anzuzeigen. Der Vertrag wird an der neuen Entnahmestelle zu unveränderten Bedingungen fortgesetzt, sofern diese im Netzgebiet Lindenau liegt. Kann der Lieferant die neue Entnahmestelle nicht beliefern, darf der Kunde den Vertrag mit einer Frist von sechs Wochen außerordentlich kündigen (§ 41b Abs. 5 EnWG).

## § 7 Bonus

Neukunden erhalten einen Neukundenbonus von 75,00 EUR nach zwölf Monaten ununterbrochener Belieferung; er wird mit der ersten Jahresverbrauchsabrechnung verrechnet. Der Sofortbonus von 40,00 EUR wird innerhalb von 60 Tagen nach Lieferbeginn überwiesen. Neukunde ist, wer in den letzten sechs Monaten vor Vertragsschluss nicht vom Lieferanten mit Strom beliefert wurde.

## § 8 Beschwerden und Schlichtung

Beschwerden von Verbrauchern beantwortet der Lieferant innerhalb von vier Wochen ab Zugang. Hilft der Lieferant der Beschwerde nicht ab, kann der Verbraucher die Schlichtungsstelle Energie e. V., Friedrichstraße 133, 10117 Berlin, anrufen. Das Schlichtungsverfahren ist für Verbraucher kostenlos.

## § 9 Übergangsregelung für Altverträge

Für Verträge, die vor dem 1. März 2022 geschlossen wurden, galten bis zu ihrer Umstellung die früheren Bedingungen: Der Vertrag verlängerte sich stillschweigend um jeweils zwölf Monate, und die Kündigungsfrist betrug drei Monate zum Ende der Laufzeit. Diese Altverträge wurden zum 1. Juli 2023 auf die Bedingungen nach § 2 umgestellt.
""",
))

SOURCES.append(dict(
    key="S2",
    title="Erläuterung Grundversorgung nach StromGVV",
    ref="intern/recht/erlaeuterung-stromgvv-grundversorgung.pdf",
    type="pdf",
    version="Fassung März 2026",
    text="""<!-- page: 1 -->

## 1 Anspruch auf Grundversorgung

Jeder Haushaltskunde hat Anspruch auf Grundversorgung mit Strom in Niederspannung (§ 36 Abs. 1 EnWG). Grundversorger ist das Energieversorgungsunternehmen, das im jeweiligen Netzgebiet die meisten Haushaltskunden beliefert. Der Netzbetreiber stellt den Grundversorger alle drei Jahre zum 1. Juli fest. Im Netzgebiet Lindenau ist die Stadtwerke Lindenau Vertrieb GmbH Grundversorger; der Grundversorgungstarif heißt LindenStrom Basis.

Der Grundversorgungsvertrag kommt auch ohne ausdrückliche Erklärung zustande, wenn ein Kunde Strom aus dem Netz der allgemeinen Versorgung entnimmt (§ 2 Abs. 2 StromGVV). Eine Mindestlaufzeit gibt es nicht. Der Kunde kann den Grundversorgungsvertrag mit einer Frist von zwei Wochen kündigen (§ 20 Abs. 1 StromGVV).

Der Grundversorger darf die Belieferung nur ablehnen, wenn sie ihm aus wirtschaftlichen Gründen nicht zumutbar ist (§ 36 Abs. 1 Satz 4 EnWG).

<!-- page: 2 -->

## 2 Ersatzversorgung

Entnimmt ein Letztverbraucher Strom, ohne dass die Entnahme einem Liefervertrag zugeordnet werden kann, gilt der Strom als vom Grundversorger geliefert (Ersatzversorgung, § 38 EnWG). Die Ersatzversorgung endet, sobald ein Liefervertrag besteht, spätestens aber drei Monate nach ihrem Beginn. Für Haushaltskunden werden seit der EnWG-Novelle 2022 gesonderte Ersatzversorgungspreise ausgewiesen; sie dürfen zum 1. und zum 15. eines Kalendermonats angepasst werden.

## 3 Preisänderungen in der Grundversorgung

Änderungen der Allgemeinen Preise werden öffentlich bekannt gegeben und dem Kunden zusätzlich brieflich mitgeteilt, und zwar mindestens sechs Wochen vor dem Wirksamwerden (§ 5 Abs. 2 StromGVV). Der Kunde kann den Vertrag in diesem Fall ohne Einhaltung einer Frist zum Wirksamwerden der Änderung kündigen (§ 5 Abs. 3 StromGVV).

<!-- page: 3 -->

## 4 Unterbrechung der Versorgung

Der Grundversorger darf die Versorgung wegen Zahlungsverzugs erst unterbrechen lassen, wenn der Kunde mit mindestens dem Doppelten des monatlichen Abschlags, mindestens jedoch mit 100,00 EUR, in Verzug ist (§ 19 Abs. 2 StromGVV). Die Unterbrechung ist vier Wochen vorher anzudrohen. Der konkrete Beginn der Unterbrechung ist dem Kunden acht Werktage im Voraus anzukündigen.

Mit der Androhung bietet der Grundversorger eine Abwendungsvereinbarung an. Sie enthält eine zinsfreie Ratenzahlung über die Rückstände sowie die Weiterversorgung auf Vorauszahlungsbasis. Die Unterbrechung unterbleibt, wenn ihre Folgen außer Verhältnis zur Schwere der Zuwiderhandlung stehen, insbesondere bei Gefahr für Leib oder Leben.

Die Versorgung ist unverzüglich wiederherzustellen, sobald die Gründe für die Unterbrechung entfallen sind und der Kunde die Kosten ersetzt hat. Nach dem Preisblatt des Netzbetreibers kostet die Unterbrechung 58,00 EUR und die Wiederherstellung des Anschlusses 72,00 EUR.

## 5 Vorauszahlung und Sicherheitsleistung

Der Grundversorger kann eine Vorauszahlung verlangen, wenn nach den Umständen des Einzelfalls Grund zu der Annahme besteht, dass der Kunde seinen Zahlungsverpflichtungen nicht oder nicht rechtzeitig nachkommt (§ 14 StromGVV). Ist der Kunde zur Vorauszahlung nicht bereit oder nicht in der Lage, kann eine Sicherheitsleistung verlangt werden (§ 15 StromGVV). Barsicherheiten werden zum jeweiligen Basiszinssatz verzinst.
""",
))

SOURCES.append(dict(
    key="S3",
    title="Preisblatt Netzentgelte Strom 2026 Lindenau Netz",
    ref="https://example.org/lindenau-netz/preisblatt-netzentgelte-strom-2026.pdf",
    type="pdf",
    version="gültig ab 01.01.2026",
    text="""<!-- page: 1 -->

## 1 Netzentgelte für die Entnahme

Die Lindenau Netz GmbH veröffentlicht die Netzentgelte vorläufig zum 15. Oktober des Vorjahres und endgültig zum 1. Januar (§ 20 Abs. 1 EnWG). Alle Preise auf dieser Seite sind Nettopreise.

| Kundengruppe | Grundpreis | Leistungspreis | Arbeitspreis |
|---|---|---|---|
| Niederspannung ohne Leistungsmessung (Standardlastprofil) | 62,00 EUR/Jahr | – | 9,84 ct/kWh |
| Niederspannung mit Leistungsmessung, unter 2.500 Benutzungsstunden | – | 28,40 EUR/kW | 6,12 ct/kWh |
| Niederspannung mit Leistungsmessung, ab 2.500 Benutzungsstunden | – | 142,60 EUR/kW | 1,55 ct/kWh |

Im Jahr 2025 betrug der Arbeitspreis für Kunden ohne Leistungsmessung 9,12 ct/kWh. Die Netzentgelte machen rund 28 Prozent des Strompreises eines Haushaltskunden aus.

<!-- page: 2 -->

## 2 Abgaben und Umlagen 2026

| Bestandteil | Höhe |
|---|---|
| Konzessionsabgabe Tarifkunden | 1,59 ct/kWh |
| Konzessionsabgabe Sondervertragskunden | 0,11 ct/kWh |
| KWKG-Umlage | 0,446 ct/kWh |
| Offshore-Netzumlage | 0,941 ct/kWh |
| Aufschlag für besondere Netznutzung | 1,559 ct/kWh |
| Stromsteuer | 2,05 ct/kWh |

Die Konzessionsabgabe richtet sich nach der Einwohnerzahl der Gemeinde; Lindenau hat rund 85.000 Einwohner.

## 3 Reduzierte Netzentgelte nach § 14a EnWG

Für steuerbare Verbrauchseinrichtungen wählt der Betreiber eines der folgenden Module:

- Modul 1: pauschale Reduzierung des Netzentgelts um 168,00 EUR brutto pro Jahr.
- Modul 2: Reduzierung des Arbeitspreises um 60 Prozent auf 3,94 ct/kWh; setzt einen separaten Zähler für die steuerbare Verbrauchseinrichtung voraus.
- Modul 3: zeitvariables Netzentgelt, nur in Kombination mit Modul 1 und mit intelligentem Messsystem. Hochtarif 14,20 ct/kWh von 17 bis 20 Uhr, Standardtarif 9,84 ct/kWh, Niedertarif 3,10 ct/kWh von 0 bis 5 Uhr.

<!-- page: 3 -->

## 4 Entgelte für den Messstellenbetrieb

Die Lindenau Netz GmbH ist grundzuständiger Messstellenbetreiber. Die folgenden Entgelte sind Bruttopreise pro Jahr und entsprechen den gesetzlichen Preisobergrenzen.

| Ausstattung | Entgelt |
|---|---|
| Konventioneller Ferraris-Zähler | 13,60 EUR |
| Moderne Messeinrichtung | 25,00 EUR |
| Intelligentes Messsystem, Jahresverbrauch über 6.000 bis 10.000 kWh | 40,00 EUR |
| Intelligentes Messsystem, Jahresverbrauch über 10.000 bis 20.000 kWh | 50,00 EUR |
| Intelligentes Messsystem bei steuerbarer Verbrauchseinrichtung | 50,00 EUR |

Für den vorzeitigen Einbau eines intelligenten Messsystems auf Kundenwunsch wird einmalig ein Entgelt von 100,00 EUR erhoben.

## 5 Sonstige Leistungen

| Leistung | Entgelt netto |
|---|---|
| Unterbrechung der Anschlussnutzung | 58,00 EUR |
| Wiederherstellung der Anschlussnutzung | 72,00 EUR |
| Zusätzliche Ablesung auf Kundenwunsch | 19,50 EUR |
""",
))

SOURCES.append(dict(
    key="S4",
    title="Arbeitsanweisung Lieferantenwechsel AA-LW-07",
    ref="intern/marktkommunikation/aa-lw-07-lieferantenwechsel.docx",
    type="docx",
    version="Revision 7, Juli 2025",
    text="""<!-- page: 1 -->

## 1 Grundsätze

Der Lieferantenwechsel ist für den Kunden unentgeltlich. Das Verfahren darf drei Wochen, gerechnet ab dem Zugang der Anmeldung beim Netzbetreiber, nicht überschreiten (§ 20a Abs. 2 EnWG). Seit dem 6. Juni 2025 wird der technische Wechselvorgang werktags innerhalb von 24 Stunden abgewickelt (Verfahren LFW24).

Jede Entnahmestelle wird über die Marktlokations-Identifikationsnummer (MaLo-ID) identifiziert. Die MaLo-ID besteht aus elf Ziffern. Kennt der Kunde seine MaLo-ID nicht, ermitteln wir sie über die Zählernummer und die Anschrift der Entnahmestelle. Die MaLo-ID steht auf jeder Stromrechnung.

## 2 Abgrenzung Marktlokation und Messlokation

Die Marktlokation ist der Ort, an dem Energie verbraucht oder erzeugt wird; an ihr hängen Bilanzierung und Belieferung. Die Messlokation ist der Ort der Messung; ihre Kennung (MeLo-ID) hat 33 Zeichen und beginnt mit dem Länderkennzeichen DE. Beispiel aus der Schulungsumgebung: MaLo-ID 50412897364.

<!-- page: 2 -->

## 3 Ablauf

1. Der Kunde erteilt uns mit dem Auftrag eine Vollmacht zur Kündigung des bisherigen Liefervertrags.
2. Wir kündigen beim bisherigen Lieferanten und melden die Netznutzung beim Netzbetreiber an.
3. Der Netzbetreiber bestätigt die Anmeldung oder lehnt sie mit einem Antwortcode ab.
4. Der Kunde erhält die Vertragsbestätigung mit dem verbindlichen Lieferbeginn.
5. Der bisherige Lieferant erstellt die Schlussrechnung spätestens sechs Wochen nach Lieferende (§ 40c Abs. 2 EnWG).

Den Zählerstand zum Wechseltermin meldet der Kunde im Zeitraum von fünf Werktagen vor bis fünf Werktagen nach dem Lieferbeginn. Liegt kein Zählerstand vor, schätzt der Netzbetreiber den Stand rechnerisch.

## 4 Fehlerfälle

- Ablehnung wegen Vertragsbindung: Der bisherige Vertrag läuft noch; der Wechsel wird zum nächstmöglichen Termin erneut angemeldet.
- Kunde nicht identifizierbar: Name, Anschrift oder Zählernummer weichen von den Stammdaten des Netzbetreibers ab.
- Doppelanmeldung: Zwei Lieferanten melden dieselbe Marktlokation zum selben Termin an; es gilt die zuerst eingegangene Anmeldung.

Scheitert ein Wechsel, bleibt der Kunde nicht ohne Strom. Die Marktlokation wird dem Grundversorger zugeordnet, der im Rahmen der Ersatzversorgung liefert.

<!-- page: 3 -->

## 5 Ein- und Auszug

Seit Einführung von LFW24 können Ein- und Auszüge nicht mehr rückwirkend gemeldet werden. Die Anmeldung muss spätestens am Tag vor dem Einzug beim Netzbetreiber eingehen. Meldet sich ein einziehender Kunde verspätet, wird er für die Zwischenzeit vom Grundversorger beliefert.

Beim Auszug meldet der Kunde den Zählerstand vom Tag der Wohnungsübergabe. Das Übergabeprotokoll des Vermieters wird als Nachweis anerkannt.

## 6 Zuständigkeiten

Fragen zum Wechselstatus beantwortet das Team Marktkommunikation (Postfach wechsel@stadtwerke-lindenau.example). Reklamationen zu Zählerständen gehen an die Lindenau Netz GmbH als Netzbetreiber.
""",
))
