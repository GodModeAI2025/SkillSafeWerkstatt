# -*- coding: utf-8 -*-
"""Faithful source extractions, part C (S9-S11). S10 and S11 are source-only knowledge."""

SOURCES = []

SOURCES.append(dict(
    key="S9",
    title="Protokoll Tarifrunde Produktportfolio 2026",
    ref="intern/produktmanagement/protokoll-tarifrunde-2026.docx",
    type="docx",
    version="beschlossen am 18.11.2025, ergänzt am 10.02.2026",
    text="""<!-- page: 1 -->

## 1 Produktportfolio ab 1. Januar 2026

**LindenStrom Fix12.** Festpreistarif für Haushaltskunden. Grundpreis 11,90 EUR pro Monat, Arbeitspreis 31,48 ct/kWh, jeweils brutto. Erstlaufzeit zwölf Monate, eingeschränkte Preisgarantie für zwölf Monate.

**LindenStrom Öko.** Strom zu 100 Prozent aus Wasserkraft; die Herkunftsnachweise stammen aus Norwegen und Österreich. Grundpreis 12,90 EUR pro Monat, Arbeitspreis 32,60 ct/kWh brutto. Je verbrauchter Kilowattstunde fließen 0,5 Cent in den Ausbaufonds „Sonne für Lindenau“, aus dem Photovoltaikanlagen auf städtischen Schulen finanziert werden. Laufzeit und Preisgarantie wie Fix12.

**LindenStrom Flex.** Dynamischer Tarif nach § 41a EnWG. Der Arbeitspreis entspricht dem stündlichen Day-Ahead-Preis der Strombörse EPEX Spot zuzüglich eines festen Aufschlags von 16,90 ct/kWh für Netzentgelte, Abgaben, Umlagen und Vertrieb. Grundpreis 14,50 EUR pro Monat. Voraussetzung ist ein intelligentes Messsystem. Der Tarif ist monatlich kündbar und wird monatlich abgerechnet. Eine Preisgarantie und einen Neukundenbonus gibt es im Tarif Flex nicht.

<!-- page: 2 -->

## 2 Weitere Tarife

**LindenWärme WP.** Tarif für Wärmepumpen. Arbeitspreis 24,95 ct/kWh, Grundpreis 9,50 EUR pro Monat, brutto. Voraussetzung sind ein separater Zähler für die Wärmepumpe und die Wahl von Modul 2 nach § 14a EnWG.

**LindenStrom Basis.** Grundversorgungstarif. Grundpreis 13,20 EUR pro Monat, Arbeitspreis ab 1. April 2026 38,72 ct/kWh brutto.

## 3 Einstellung von LindenStrom Klassik

Der Tarif LindenStrom Klassik wird zum 31. Dezember 2025 eingestellt. Er hatte eine Erstlaufzeit von 24 Monaten, einen Grundpreis von 10,50 EUR pro Monat und einen Arbeitspreis von 34,90 ct/kWh. Die rund 4.300 Bestandskunden werden zum 1. Januar 2026 in den Tarif LindenStrom Fix12 überführt. Sie erhalten dazu ein Schreiben mit Hinweis auf ihr Sonderkündigungsrecht. Neuabschlüsse im Tarif Klassik sind seit dem 1. Oktober 2025 nicht mehr möglich.

<!-- page: 3 -->

## 4 Preisanpassung zum 1. April 2026

In der Grundversorgung (LindenStrom Basis) steigt der Arbeitspreis zum 1. April 2026 von 37,10 ct/kWh auf 38,72 ct/kWh brutto, also um 1,62 ct/kWh. Der Grundpreis bleibt unverändert. Grund sind das gestiegene Netzentgelt (Arbeitspreis 9,84 statt 9,12 ct/kWh) und höhere Umlagen. Die Kundenanschreiben wurden am 14. Februar 2026 versandt. Für einen Haushalt mit 2.500 kWh Jahresverbrauch bedeutet die Anpassung Mehrkosten von rund 40 EUR im Jahr.

Kunden im Tarif Fix12 sind während der laufenden Preisgarantie nicht betroffen.

## 5 Rückblick: Preisanpassung zum 1. Januar 2025

Zum 1. Januar 2025 wurde der Arbeitspreis in der Grundversorgung von 39,95 ct/kWh auf 37,10 ct/kWh gesenkt. Ursache waren gesunkene Beschaffungskosten am Terminmarkt. Diese Preisstellung galt bis zum 31. März 2026.

## 6 Beschluss zum Neukundenbonus

Der Neukundenbonus von 75,00 EUR und der Sofortbonus von 40,00 EUR gelten unverändert für Fix12 und Öko. Bei Vertragsabschluss über Vergleichsportale wird kein Sofortbonus gewährt.
""",
))

SOURCES.append(dict(
    key="S10",
    title="Notfallhandbuch Versorgungsstörung und Krisenkommunikation",
    ref="intern/netzbetrieb/notfallhandbuch-versorgungsstoerung.pdf",
    type="pdf",
    version="Ausgabe 5, 2026",
    text="""<!-- page: 1 -->

## 1 Störungsannahme

Die Störungshotline der Lindenau Netz GmbH ist rund um die Uhr unter 0800 5546112 erreichbar. Der Kundenservice des Vertriebs nimmt keine Störungsmeldungen an, sondern verbindet zur Netzleitstelle. Ziel ist, dass der Entstördienst innerhalb von 90 Minuten nach Eingang der Meldung vor Ort ist.

Ein Stromausfall, der nur eine einzelne Wohnung betrifft, liegt meist an der Kundenanlage. Dann ist ein Elektroinstallateur zu beauftragen; die Kosten trägt der Anschlussnutzer.

## 2 Kennzahlen

Die durchschnittliche Unterbrechungsdauer je Letztverbraucher (SAIDI) lag im Netzgebiet Lindenau im Jahr 2025 bei 9,8 Minuten. Der Bundesdurchschnitt lag im selben Jahr bei rund 12 Minuten.

<!-- page: 2 -->

## 3 Geplante Abschaltungen

Geplante Versorgungsunterbrechungen wegen Bauarbeiten werden den betroffenen Anschlussnutzern mindestens drei Werktage vorher durch Aushang oder Einwurf angekündigt. Abschaltungen sollen werktags zwischen 8 und 15 Uhr liegen und vier Stunden nicht überschreiten.

## 4 Vorrangkunden

Anschlussnutzer, die auf lebenserhaltende elektrische Geräte angewiesen sind, etwa Heimbeatmung oder Heimdialyse, können sich in das Vorrangregister eintragen lassen. Sie werden vor geplanten Abschaltungen telefonisch informiert. Eine unterbrechungsfreie Versorgung kann das Register nicht garantieren; Betroffenen wird ein Akku-Puffer oder ein Notstromgerät empfohlen. Krankenhäuser und Pflegeheime sind gesetzlich zu einer eigenen Notstromversorgung verpflichtet.

## 5 Haftung

Für Schäden durch eine Versorgungsstörung haftet der Netzbetreiber, nicht der Lieferant. Bei leicht fahrlässig verursachten Sachschäden ist die Haftung auf 5.000 EUR je Anschlussnutzer begrenzt (§ 18 NAV). Schäden an Geräten durch Überspannung sind der Lindenau Netz GmbH innerhalb von 14 Tagen schriftlich zu melden.

<!-- page: 3 -->

## 6 Krisenstab und großflächiger Ausfall

Ab einem Ausfall von mehr als 2.000 Anschlüssen oder einer erwarteten Dauer von mehr als drei Stunden beruft der Leiter Netzbetrieb den Krisenstab ein. Die Pressestelle veröffentlicht innerhalb von 30 Minuten eine erste Meldung auf der Internetseite und über den SMS-Warndienst.

Bei einer Unterfrequenz im Verbundnetz greift der automatische Lastabwurf in fünf Stufen ab 49,0 Hertz. Die Reihenfolge der abzuwerfenden Netzbereiche wird jährlich neu festgelegt, damit nicht immer dieselben Stadtteile betroffen sind.

## 7 Notstrom

Die Lindenau Netz GmbH hält vier mobile Notstromaggregate mit je 250 kVA vor. Sie werden vorrangig für Wasserwerke, die Feuerwehrleitstelle und Notunterkünfte eingesetzt. Privathaushalte haben keinen Anspruch auf ein Aggregat.
""",
))

SOURCES.append(dict(
    key="S11",
    title="Leitfaden Mieterstrom und gemeinschaftliche Gebäudeversorgung",
    ref="intern/produktmanagement/leitfaden-mieterstrom-ggv.pdf",
    type="pdf",
    version="Entwurf 0.9",
    text="""<!-- page: 1 -->

## 1 Mieterstrom

Mieterstrom ist Strom aus einer Solaranlage auf einem Wohngebäude, der ohne Nutzung des öffentlichen Netzes an Bewohner dieses Gebäudes oder des Quartiers geliefert wird. Der Anlagenbetreiber erhält dafür den Mieterstromzuschlag nach § 21 Abs. 3 EEG. Für Anlagen bis 10 kW beträgt er 2,56 ct/kWh, bis 40 kW 2,38 ct/kWh und bis 1.000 kW 1,60 ct/kWh.

Der Mieterstromvertrag muss die vollständige Versorgung des Mieters sicherstellen, also auch in Zeiten ohne Sonnenschein. Der Preis darf 90 Prozent des im Netzgebiet geltenden Grundversorgungstarifs nicht übersteigen (§ 42a Abs. 4 EnWG).

## 2 Vertragliche Besonderheiten

Der Mieterstromvertrag darf nicht Bestandteil des Mietvertrags sein (Kopplungsverbot). Die Erstlaufzeit darf höchstens zwei Jahre betragen. Der Vertrag endet automatisch mit der Rückgabe der Wohnung, ohne dass es einer Kündigung bedarf. Der Mieter bleibt frei, einen anderen Lieferanten zu wählen.

<!-- page: 2 -->

## 3 Gemeinschaftliche Gebäudeversorgung

Seit dem Solarpaket I gibt es als Alternative die gemeinschaftliche Gebäudeversorgung (§ 42b EnWG). Dabei wird der Solarstrom nach einem vereinbarten Schlüssel auf die teilnehmenden Bewohner aufgeteilt. Der Betreiber ist nicht zur Vollversorgung verpflichtet; jeder Teilnehmer behält für den Reststrom seinen eigenen Liefervertrag. Ein Mieterstromzuschlag wird in diesem Modell nicht gezahlt.

Voraussetzung ist eine viertelstündliche Messung aller teilnehmenden Zähler. Die Aufteilung kann statisch (feste Prozentsätze) oder dynamisch (nach tatsächlichem Verbrauch in der Viertelstunde) erfolgen.

## 4 Messkonzepte

Beim physischen Summenzählermodell misst ein Zweirichtungszähler am Netzanschlusspunkt den Bezug und die Einspeisung des gesamten Gebäudes. Beim virtuellen Summenzähler werden die Werte der einzelnen intelligenten Messsysteme rechnerisch zusammengeführt; ein Umbau der Zählerschränke entfällt.

<!-- page: 3 -->

## 5 Angebot der Stadtwerke Lindenau

Die Stadtwerke Lindenau Vertrieb GmbH bietet Mieterstrom unter dem Namen „LindenDach“ für Gebäude ab zwölf Wohneinheiten an. Die Solaranlage wird von den Stadtwerken finanziert und betrieben; der Gebäudeeigentümer erhält eine Dachpacht von 3,00 EUR je Quadratmeter Modulfläche pro Jahr. Erfahrungsgemäß nehmen 60 bis 70 Prozent der Mietparteien teil.

Für kleinere Gebäude wird die gemeinschaftliche Gebäudeversorgung als Dienstleistungspaket „LindenDach Teilen“ angeboten. Die Abrechnungsdienstleistung kostet 4,90 EUR pro Teilnehmer und Monat.

Dieser Leitfaden ist ein Entwurf; die Wiki-Redaktion hat ihn noch nicht ausgewertet.
""",
))
