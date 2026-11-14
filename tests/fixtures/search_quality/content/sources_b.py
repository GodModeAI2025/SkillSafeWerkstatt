# -*- coding: utf-8 -*-
"""Faithful source extractions, part B (S5-S8)."""

SOURCES = []

SOURCES.append(dict(
    key="S5",
    title="Handbuch Kundenservice Kapitel 4 Abrechnung",
    ref="intern/kundenservice/handbuch-kapitel-4-abrechnung.pdf",
    type="pdf",
    version="Ausgabe 2026-02",
    text="""<!-- page: 1 -->

## 4.1 Berechnung des Abschlags

Der monatliche Abschlag ergibt sich aus der Jahresverbrauchsprognose multipliziert mit dem Arbeitspreis, zuzüglich des Grundpreises für zwölf Monate, geteilt durch elf. Der zwölfte Monat bleibt abschlagsfrei, weil in ihm die Jahresverbrauchsabrechnung erstellt wird.

Bei Neukunden ohne bekannten Vorjahresverbrauch richtet sich die Prognose nach der Haushaltsgröße:

| Personen im Haushalt | Prognose pro Jahr |
|---|---|
| 1 | 1.500 kWh |
| 2 | 2.500 kWh |
| 3 | 3.500 kWh |
| 4 | 4.250 kWh |

Kunden können ihren Abschlag im Kundenportal MeinLindenau jederzeit selbst um bis zu 20 Prozent erhöhen oder senken. Für eine größere Senkung verlangen wir einen aktuellen Zählerstand. Nach einer Preisänderung passt das Abrechnungssystem den Abschlag automatisch an und informiert den Kunden schriftlich.

<!-- page: 2 -->

## 4.2 Zählerstände

Die Zähler werden einmal jährlich im Auftrag des Messstellenbetreibers abgelesen. Kunden können den Zählerstand auch selbst ablesen und über das Kundenportal, per Foto in der App oder telefonisch unter 0800 5546330 melden.

Jeder gemeldete Stand durchläuft eine Plausibilitätsprüfung. Weicht der Verbrauch um mehr als 30 Prozent vom Erwartungswert ab, fragen wir beim Kunden nach und bitten um ein Foto des Zählers. Liegt zum Abrechnungsstichtag kein Zählerstand vor, wird der Verbrauch auf Grundlage des Vorjahresverbrauchs rechnerisch geschätzt; die Schätzung ist auf der Rechnung als solche gekennzeichnet. Ein geschätzter Stand kann bis zur nächsten Jahresverbrauchsabrechnung durch einen abgelesenen Stand korrigiert werden.

Bei Zweitarifzählern sind beide Zählwerke zu melden: Hochtarif mit der OBIS-Kennzahl 1.8.1 und Niedertarif mit der OBIS-Kennzahl 1.8.2. Bei Einspeisung zeigt die Kennzahl 2.8.0 die ins Netz gelieferte Energie.

<!-- page: 3 -->

## 4.3 Jahresverbrauchsabrechnung

Der Abrechnungszeitraum umfasst höchstens zwölf Monate. Die Rechnung muss dem Kunden spätestens sechs Wochen nach Ende des Abrechnungszeitraums zugehen. Pflichtangaben nach § 40 EnWG sind unter anderem der Verbrauch im Abrechnungszeitraum, der Vergleich mit dem Vorjahresverbrauch, der Vergleich mit Vergleichskundengruppen, die Stromkennzeichnung, die MaLo-ID sowie der Hinweis auf die Schlichtungsstelle Energie.

Eine Nachzahlung ist 14 Tage nach Zugang der Rechnung fällig. Einwände gegen die Rechnung können innerhalb von drei Jahren erhoben werden. Sie berechtigen nur dann zum Zahlungsaufschub, wenn die ernsthafte Möglichkeit eines offensichtlichen Fehlers besteht.

<!-- page: 4 -->

## 4.4 Ratenzahlung und Stundung

Bei einer Nachzahlung von mehr als 100,00 EUR bieten wir auf Wunsch einen Ratenplan mit bis zu sechs zinsfreien Monatsraten an. Eine Verlängerung auf bis zu zwölf Raten bedarf der Zustimmung der Teamleitung. Eine Stundung ist für höchstens 30 Tage möglich. Während eines laufenden Ratenplans müssen die regulären Abschläge pünktlich weitergezahlt werden; andernfalls wird der gesamte Restbetrag sofort fällig.

## 4.5 Mahnlauf

Sieben Tage nach Fälligkeit versenden wir eine kostenfreie Zahlungserinnerung. Die erste Mahnung folgt 14 Tage später. Weitere 14 Tage später ergeht die zweite Mahnung; sie enthält in der Grundversorgung die Androhung der Versorgungsunterbrechung. Kunden mit erteiltem SEPA-Lastschriftmandat durchlaufen den Mahnlauf nur nach einer Rücklastschrift.
""",
))

SOURCES.append(dict(
    key="S6",
    title="Richtlinie Bonitätsprüfung und Forderungsmanagement RL-FM-03",
    ref="intern/forderungsmanagement/rl-fm-03-bonitaet.pdf",
    type="pdf",
    version="Version 3.2",
    text="""<!-- page: 1 -->

## 1 Anwendungsbereich

Vor der Bestätigung jedes neuen Sondervertrags wird die Zahlungsfähigkeit des Antragstellers geprüft. Rechtsgrundlage ist das berechtigte Interesse nach Art. 6 Abs. 1 Buchstabe f DSGVO. Abgefragt werden die SCHUFA Holding AG und die Creditreform Boniversum GmbH.

Die Auskunfteien liefern eine Scoreklasse von A (sehr geringes Ausfallrisiko) bis M (sehr hohes Ausfallrisiko). Es gilt folgende Entscheidungsmatrix:

| Scoreklasse | Entscheidung |
|---|---|
| A bis G | Annahme ohne Auflagen |
| H bis K | Annahme nur mit SEPA-Lastschriftmandat oder Vorauszahlung |
| L und M | Ablehnung des Sondervertrags, Hinweis auf die Grundversorgung |

In der Grundversorgung findet keine Ablehnung wegen schlechter Bonität statt, weil dort Kontrahierungszwang besteht.

<!-- page: 2 -->

## 2 Ablehnung und Widerspruch

Wird ein Antrag abgelehnt, erhält der Antragsteller eine Mitteilung, die die verwendete Auskunftei nennt. Eine Entscheidung darf nicht ausschließlich automatisiert ergehen, ohne dass der Betroffene eine Überprüfung durch einen Menschen verlangen kann (Art. 22 DSGVO). Der Antragsteller kann der Ablehnung innerhalb von 14 Tagen widersprechen. Das Forderungsmanagement prüft den Fall dann manuell und entscheidet innerhalb von fünf Werktagen.

Das Ergebnis der Prüfung wird zwölf Monate gespeichert und danach gelöscht.

## 3 Bestandskunden

Bei einem Tarifwechsel von Bestandskunden wird die Bonität nur dann erneut geprüft, wenn offene Forderungen von mehr als 50,00 EUR bestehen.

<!-- page: 3 -->

## 4 Inkasso und Forderungsverkauf

Nach der dritten erfolglosen Mahnung wird die Forderung an die Nordwest Inkasso GmbH zum Einzug übergeben. Ein Verkauf der Forderung ist frühestens 180 Tage nach Fälligkeit zulässig und bedarf der Freigabe durch die kaufmännische Leitung. Forderungen unter 25,00 EUR werden nicht an das Inkassobüro übergeben, sondern ausgebucht.

## 5 Verjährung

Forderungen aus Stromlieferungen verjähren in drei Jahren. Die Frist beginnt mit dem Schluss des Jahres, in dem die Forderung entstanden ist (§§ 195, 199 BGB). Ein gerichtlicher Mahnbescheid hemmt die Verjährung.

## 6 Insolvenz des Kunden

Wird über das Vermögen eines Kunden das Verbraucherinsolvenzverfahren eröffnet, melden wir alle bis zum Eröffnungstag entstandenen Forderungen zur Insolvenztabelle an. Für die Belieferung ab dem Eröffnungstag wird ein neues Vertragskonto angelegt. Eine Aufrechnung von Guthaben aus der Zeit nach der Eröffnung mit Altforderungen ist unzulässig.
""",
))

SOURCES.append(dict(
    key="S7",
    title="Rollout-Leitfaden intelligente Messsysteme LF-MSB-2026",
    ref="intern/messwesen/lf-msb-2026-rollout-leitfaden.pdf",
    type="pdf",
    version="Stand Oktober 2026",
    text="""<!-- page: 1 -->

## 1 Begriffe

Eine moderne Messeinrichtung ist ein digitaler Stromzähler ohne Kommunikationseinheit. Sie zeigt den aktuellen Zählerstand sowie tages-, wochen-, monats- und jahresbezogene Verbrauchswerte der letzten 24 Monate an. Ein intelligentes Messsystem besteht aus einer modernen Messeinrichtung und einem Smart-Meter-Gateway, das die Messwerte verschlüsselt überträgt.

## 2 Pflichteinbaufälle

Ein intelligentes Messsystem ist verpflichtend einzubauen bei

- Letztverbrauchern mit einem Jahresverbrauch von mehr als 6.000 kWh,
- Erzeugungsanlagen mit mehr als 7 kW installierter Leistung,
- steuerbaren Verbrauchseinrichtungen nach § 14a EnWG.

Der gesetzliche Fahrplan verlangt, dass 20 Prozent der Pflichteinbaufälle bis zum 31. Dezember 2025, 50 Prozent bis zum 31. Dezember 2028 und 95 Prozent bis zum 31. Dezember 2030 ausgestattet sind.

<!-- page: 2 -->

## 3 Rechte und Pflichten des Anschlussnutzers

Der Messstellenbetreiber kündigt den Einbau mindestens drei Monate im Voraus an und nennt den konkreten Termin spätestens zwei Wochen vorher. Der Anschlussnutzer muss den Einbau dulden; ein Widerspruchsrecht gegen das Gerät besteht nicht. Er kann jedoch anstelle des grundzuständigen Messstellenbetreibers einen wettbewerblichen Messstellenbetreiber beauftragen (§ 5 MsbG).

Seit 2025 kann jeder Anschlussnutzer den Einbau eines intelligenten Messsystems verlangen. Der grundzuständige Messstellenbetreiber muss dem Wunsch innerhalb von vier Monaten ab Beauftragung nachkommen.

## 4 Datenübermittlung

Das intelligente Messsystem übermittelt Viertelstundenwerte einmal täglich an den Messstellenbetreiber. Diese Werte sind Voraussetzung für die Abrechnung dynamischer Stromtarife und zeitvariabler Netzentgelte. Fällt das Gateway aus, bildet der Messstellenbetreiber Ersatzwerte.

<!-- page: 3 -->

## 5 Stand im Netzgebiet Lindenau

Grundzuständiger Messstellenbetreiber ist die Lindenau Netz GmbH. Zum 30. September 2026 waren 11.400 intelligente Messsysteme verbaut; das entspricht 48 Prozent der 23.800 Pflichteinbaufälle. Die übrigen Haushalte erhalten bis 2032 schrittweise eine moderne Messeinrichtung.

## 6 Eichfristen und Gerätetausch

Elektronische Zähler haben eine Eichfrist von acht Jahren, Ferraris-Zähler von sechzehn Jahren. Nach Ablauf der Eichfrist wird der Zähler getauscht oder die Frist im Stichprobenverfahren verlängert. Der Zählertausch dauert in der Regel 20 Minuten; die Stromversorgung ist in dieser Zeit unterbrochen. Den Ausbaustand des alten Zählers dokumentiert der Monteur mit einem Foto.
""",
))

SOURCES.append(dict(
    key="S8",
    title="Rechtsleitfaden Vertrieb Widerruf und Fernabsatz RL-V-11",
    ref="intern/recht/rl-v-11-widerruf-fernabsatz.pdf",
    type="pdf",
    version="Version 2026.1",
    text="""<!-- page: 1 -->

## 1 Wann besteht ein Widerrufsrecht

Verbraucher können Stromlieferverträge widerrufen, die im Fernabsatz (Internet, Telefon, Brief) oder außerhalb von Geschäftsräumen (zum Beispiel an der Haustür) geschlossen wurden (§§ 312g, 355 BGB). Die Widerrufsfrist beträgt 14 Tage. Sie beginnt bei Stromlieferverträgen mit dem Vertragsschluss, nicht mit der ersten Lieferung. Der Widerruf muss nicht begründet werden.

Der Kunde erhält mit der Vertragsbestätigung die Widerrufsbelehrung und das Muster-Widerrufsformular. Fehlt die Belehrung oder ist sie fehlerhaft, erlischt das Widerrufsrecht erst zwölf Monate und 14 Tage nach Vertragsschluss.

Kein Widerrufsrecht besteht bei Verträgen, die im Kundenzentrum geschlossen werden, und bei Verträgen mit Unternehmern.

<!-- page: 2 -->

## 2 Form und Folgen des Widerrufs

Der Widerruf erfolgt durch eindeutige Erklärung gegenüber dem Lieferanten. Er ist auch telefonisch möglich; aus Beweisgründen empfehlen wir die Textform. Zur Wahrung der Frist genügt die rechtzeitige Absendung.

Hat der Kunde ausdrücklich verlangt, dass die Lieferung vor Ablauf der Widerrufsfrist beginnt, schuldet er nach einem Widerruf Wertersatz für den bis dahin gelieferten Strom. Bereits geleistete Zahlungen sind innerhalb von 14 Tagen nach Zugang des Widerrufs zurückzuerstatten.

Nach dem Widerruf bleibt der Kunde bei seinem bisherigen Lieferanten, wenn dessen Vertrag noch nicht beendet wurde. Andernfalls wird er vom Grundversorger beliefert.

## 3 Telefonisch geschlossene Verträge

Stromlieferverträge mit Haushaltskunden außerhalb der Grundversorgung bedürfen der Textform (§ 41 Abs. 1 Satz 1 EnWG). Ein allein am Telefon abgegebenes Einverständnis genügt nicht; der Kunde muss das Angebot in Textform bestätigen. Werbeanrufe bei Verbrauchern sind nur mit vorheriger ausdrücklicher Einwilligung zulässig (§ 7 Abs. 2 UWG).

<!-- page: 3 -->

## 4 Vertrieb an der Haustür

Die Stadtwerke Lindenau Vertrieb GmbH setzt seit 2024 keine externen Haustürvertriebe ein. Für das Jahr 2027 ist ein Pilotprojekt mit eigenen Mitarbeitern geplant. Dafür gelten vorläufig folgende Regeln:

- Besuche nur montags bis samstags zwischen 9 und 19 Uhr.
- Die Mitarbeiter weisen sich mit Dienstausweis und Lichtbild aus.
- Jeder Abschluss wird innerhalb von 48 Stunden durch einen Bestätigungsanruf überprüft.
- Bei Personen, die erkennbar die Tragweite des Vertrags nicht erfassen, wird kein Vertrag aufgenommen.

Diese Regeln sind noch nicht von der Geschäftsführung freigegeben.
""",
))
