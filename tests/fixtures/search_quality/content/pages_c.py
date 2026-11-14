# -*- coding: utf-8 -*-
"""Entity pages: companies, bodies, tariffs."""
from .dsl import C, page

page("wiki/entities/stadtwerke-lindenau-vertrieb.md", "Stadtwerke Lindenau Vertrieb GmbH",
     "Stromlieferant und Grundversorger im Netzgebiet Lindenau; Vertragspartner der Kunden.",
     aliases=["SLV", "Stadtwerke Lindenau"], cluster="organisation", gt="v",
     body=[
"## Rolle",
"Die Stadtwerke Lindenau Vertrieb GmbH ist der Lieferant, mit dem Kunden ihren Stromliefervertrag schließen. Sie kauft Energie ein, rechnet ab und betreut die Kunden. Das Netz und die Zähler gehören nicht zu ihren Aufgaben; dafür ist die [[wiki/entities/lindenau-netz|Lindenau Netz GmbH]] zuständig.",
C("Die Stadtwerke Lindenau Vertrieb GmbH ist im Netzgebiet Lindenau Grundversorger.", "S2@page=1"),
C("Der Stromliefervertrag kommt zustande, sobald die Stadtwerke Lindenau Vertrieb GmbH dem Kunden die Vertragsbestätigung in Textform übermittelt, spätestens mit Aufnahme der Belieferung.", "S1@page=1"),
C("Der Kundenservice ist telefonisch unter 0800 5546330 erreichbar.", "S5@page=2"),
C("Beschwerden von Verbrauchern beantwortet das Unternehmen innerhalb von vier Wochen ab Zugang.", "S1@page=4"),
C("Fragen zum Wechselstatus beantwortet das Team Marktkommunikation.", "S4@page=3"),
"## Tarife",
"Aktuell angeboten werden [[wiki/entities/tarif-lindenstrom-fix12|LindenStrom Fix12]], [[wiki/entities/tarif-lindenstrom-oeko|LindenStrom Öko]], [[wiki/entities/tarif-lindenstrom-flex|LindenStrom Flex]], [[wiki/entities/tarif-lindenwaerme-wp|LindenWärme WP]] und in der Grundversorgung [[wiki/entities/tarif-lindenstrom-basis|LindenStrom Basis]]. Nicht mehr angeboten wird [[wiki/entities/tarif-lindenstrom-klassik|LindenStrom Klassik]].",
     ])

page("wiki/entities/lindenau-netz.md", "Lindenau Netz GmbH",
     "Verteilnetzbetreiber und grundzuständiger Messstellenbetreiber im Netzgebiet Lindenau.",
     cluster="organisation", gt="z",
     body=[
"## Rolle",
"Die Lindenau Netz GmbH betreibt das Stromverteilnetz in Lindenau. Sie ist rechtlich vom Vertrieb getrennt und behandelt alle Lieferanten gleich. Kunden haben mit ihr meist nur beim Zähler, beim Hausanschluss oder bei einer Unterbrechung zu tun.",
C("Die Lindenau Netz GmbH veröffentlicht die Netzentgelte vorläufig zum 15. Oktober des Vorjahres und endgültig zum 1. Januar.", "S3@page=1"),
C("Die Lindenau Netz GmbH ist grundzuständiger Messstellenbetreiber im Netzgebiet.", "S3@page=3 | S7@page=3"),
C("Der Netzbetreiber stellt alle drei Jahre zum 1. Juli fest, wer Grundversorger ist.", "S2@page=1"),
C("Liegt zum Wechseltermin kein Zählerstand vor, schätzt der Netzbetreiber den Stand rechnerisch.", "S4@page=2"),
C("Beanstandungen zu Zählerständen sind an die Lindenau Netz GmbH als Netzbetreiber zu richten.", "S4@page=3"),
"## Abgrenzung",
"Preisfragen zum Stromtarif, zum Abschlag oder zur Rechnung beantwortet nicht der Netzbetreiber, sondern der Lieferant. Die Entgelte des Netzbetreibers stehen unter [[wiki/concepts/netzentgelt]] und [[wiki/concepts/messstellenbetrieb]]. Die Rollenverteilung fasst [[wiki/comparisons/netzbetreiber-lieferant-messstellenbetreiber]] zusammen.",
     ])

page("wiki/entities/schlichtungsstelle-energie.md", "Schlichtungsstelle Energie",
     "Unabhängige Stelle zur außergerichtlichen Beilegung von Streit zwischen Verbrauchern und Energieunternehmen.",
     cluster="organisation", gt="f",
     body=[
"## Rolle",
"Die Schlichtungsstelle Energie e. V. vermittelt, wenn sich ein Verbraucher und sein Energieunternehmen nicht einigen. Sie ersetzt kein Gericht, ihre Empfehlungen werden in der Praxis aber meist befolgt.",
C("Hilft der Lieferant einer Beschwerde nicht ab, kann der Verbraucher die Schlichtungsstelle Energie e. V. anrufen.", "S1@page=4"),
C("Die Anschrift lautet Friedrichstraße 133, 10117 Berlin.", "S1@page=4"),
C("Das Schlichtungsverfahren ist für Verbraucher kostenlos.", "S1@page=4"),
C("Der Hinweis auf die Schlichtungsstelle Energie gehört zu den Pflichtangaben jeder Rechnung nach § 40 EnWG.", "S5@page=3"),
"## Hinweise für den Kundenservice",
"Ein Schlichtungsantrag setzt voraus, dass der Kunde sich zuerst beim Unternehmen beschwert hat und die Antwortfrist abgelaufen ist oder die Antwort ihn nicht zufriedenstellt. Unternehmer und Gewerbekunden können die Stelle nicht anrufen. Den internen Ablauf bis dahin beschreibt [[wiki/topics/beschwerdemanagement]].",
     ])

page("wiki/entities/tarif-lindenstrom-fix12.md", "LindenStrom Fix12",
     "Festpreistarif für Haushaltskunden mit zwölf Monaten Erstlaufzeit und eingeschränkter Preisgarantie.",
     cluster="preise", gt="pvk",
     body=[
"## Steckbrief",
C("LindenStrom Fix12 kostet 11,90 EUR Grundpreis pro Monat und 31,48 ct/kWh Arbeitspreis, jeweils brutto.", "S9@page=1"),
C("Die Erstlaufzeit beträgt zwölf Monate; für diese Zeit gilt eine eingeschränkte Preisgarantie.", "S9@page=1 | S1@page=2"),
C("Nach der Erstlaufzeit verlängert sich der Vertrag auf unbestimmte Zeit und ist mit einer Frist von einem Monat kündbar.", "S1@page=1"),
C("Neukunden erhalten in Fix12 den Neukundenbonus von 75,00 EUR und den Sofortbonus von 40,00 EUR.", "S9@page=3"),
C("Die rund 4.300 Bestandskunden des Tarifs LindenStrom Klassik wurden zum 1. Januar 2026 in Fix12 überführt.", "S9@page=2"),
"## Einordnung",
"Fix12 ist das Standardprodukt für Haushalte, die planbare Kosten wünschen. Wer flexibel auf Börsenpreise reagieren kann, ist mit [[wiki/entities/tarif-lindenstrom-flex|LindenStrom Flex]] unter Umständen günstiger unterwegs; den Unterschied erklärt [[wiki/comparisons/festpreistarif-und-dynamischer-tarif]]. Was die Garantie abdeckt, steht unter [[wiki/concepts/preisgarantie]], die Bonusregeln unter [[wiki/topics/neukundenbonus]].",
     ])

page("wiki/entities/tarif-lindenstrom-oeko.md", "LindenStrom Öko",
     "Ökostromtarif aus Wasserkraft mit Förderbeitrag für Solaranlagen auf Lindenauer Schulen.",
     aliases=["Ökostromtarif"], cluster="preise", gt="p",
     body=[
"## Steckbrief",
C("LindenStrom Öko liefert Strom zu 100 Prozent aus Wasserkraft; die Herkunftsnachweise stammen aus Norwegen und Österreich.", "S9@page=1"),
C("Der Tarif kostet 12,90 EUR Grundpreis pro Monat und 32,60 ct/kWh Arbeitspreis brutto.", "S9@page=1"),
C("Je verbrauchter Kilowattstunde fließen 0,5 Cent in den Ausbaufonds „Sonne für Lindenau“, aus dem Photovoltaikanlagen auf städtischen Schulen finanziert werden.", "S9@page=1"),
C("Laufzeit und Preisgarantie entsprechen dem Tarif Fix12.", "S9@page=1"),
"## Einordnung",
"Der Tarif richtet sich an Haushalte, denen die Herkunft ihres Stroms wichtig ist und die dafür einen kleinen Aufpreis akzeptieren. Gegenüber [[wiki/entities/tarif-lindenstrom-fix12|Fix12]] ist die Kilowattstunde 1,12 Cent teurer und der Grundpreis einen Euro höher. Im Beratungsgespräch sollte erklärt werden, dass physikalisch derselbe Strom aus der Steckdose kommt; der Unterschied liegt in der Beschaffung und im Förderbeitrag. Bonus und Vertragsbedingungen sind identisch, siehe [[wiki/topics/neukundenbonus]].",
     ])

page("wiki/entities/tarif-lindenstrom-flex.md", "LindenStrom Flex",
     "Dynamischer Stromtarif nach § 41a EnWG mit stündlichem Börsenpreis.",
     aliases=["dynamischer Tarif"], cluster="preise", gt="pvkz",
     body=[
"## Steckbrief",
C("LindenStrom Flex ist ein dynamischer Tarif nach § 41a EnWG.", "S9@page=1"),
C("Der Arbeitspreis entspricht dem stündlichen Day-Ahead-Preis der Strombörse EPEX Spot zuzüglich eines festen Aufschlags von 16,90 ct/kWh für Netzentgelte, Abgaben, Umlagen und Vertrieb.", "S9@page=1"),
C("Der Grundpreis beträgt 14,50 EUR pro Monat.", "S9@page=1"),
C("Voraussetzung für den Tarif ist ein intelligentes Messsystem.", "S9@page=1"),
C("Der Tarif ist monatlich kündbar und wird monatlich abgerechnet.", "S9@page=1"),
C("Eine Preisgarantie und einen Neukundenbonus gibt es im Tarif Flex nicht.", "S9@page=1"),
"## Einordnung",
"Flex lohnt sich für Haushalte, die große Verbräuche in günstige Stunden verschieben können, zum Beispiel das Laden eines Elektroautos in der Nacht. Das Preisrisiko trägt der Kunde: In teuren Stunden kann die Kilowattstunde deutlich mehr kosten als im Festpreis. Ohne [[wiki/concepts/intelligentes-messsystem]] kann der Vertrag nicht starten. Den Vergleich zieht [[wiki/comparisons/festpreistarif-und-dynamischer-tarif]].",
     ])

page("wiki/entities/tarif-lindenstrom-klassik.md", "LindenStrom Klassik",
     "Eingestellter Tarif mit 24 Monaten Erstlaufzeit; Bestandskunden wurden 2026 in Fix12 überführt.",
     status="superseded", cluster="preise", gt="pvk",
     body=[
"## Status",
"Diese Seite beschreibt einen Tarif, der nicht mehr angeboten wird. Sie bleibt als Historie erhalten, weil Bestandskunden und alte Rechnungen weiterhin darauf Bezug nehmen. Nachfolger ist [[wiki/entities/tarif-lindenstrom-fix12|LindenStrom Fix12]].",
C("Der Tarif LindenStrom Klassik wurde zum 31. Dezember 2025 eingestellt.", "S9@page=2"),
C("Neuabschlüsse im Tarif Klassik waren seit dem 1. Oktober 2025 nicht mehr möglich.", "S9@page=2"),
"## Frühere Konditionen",
C("LindenStrom Klassik hatte eine Erstlaufzeit von 24 Monaten.", "S9@page=2", status="superseded"),
C("Der Grundpreis betrug 10,50 EUR pro Monat und der Arbeitspreis 34,90 ct/kWh.", "S9@page=2", status="superseded"),
"## Überführung",
C("Die rund 4.300 Bestandskunden wurden zum 1. Januar 2026 in den Tarif LindenStrom Fix12 überführt.", "S9@page=2"),
C("Die betroffenen Kunden erhielten ein Schreiben mit Hinweis auf ihr Sonderkündigungsrecht.", "S9@page=2"),
"Fragt ein Kunde nach seinem alten Vertrag, gelten für ihn heute die Bedingungen von Fix12, einschließlich der kürzeren [[wiki/concepts/kuendigungsfrist]].",
     ])

page("wiki/entities/tarif-lindenwaerme-wp.md", "LindenWärme WP",
     "Tarif für Wärmepumpen mit separatem Zähler und reduziertem Netzentgelt.",
     cluster="preise", gt="pz",
     body=[
"## Steckbrief",
C("LindenWärme WP ist der Tarif für Wärmepumpen; er kostet 24,95 ct/kWh Arbeitspreis und 9,50 EUR Grundpreis pro Monat, brutto.", "S9@page=2"),
C("Voraussetzung sind ein separater Zähler für die Wärmepumpe und die Wahl von Modul 2 nach § 14a EnWG.", "S9@page=2"),
C("Modul 2 reduziert den Arbeitspreis des Netzentgelts um 60 Prozent auf 3,94 ct/kWh.", "S3@page=2"),
"## Einordnung",
"Der niedrige Arbeitspreis entsteht fast vollständig durch das reduzierte Netzentgelt, das der Netzbetreiber für steuerbare Geräte gewährt. Der Tarif gilt deshalb nur für den Strom, der über den eigenen Zähler der Wärmepumpe läuft; der übrige Haushalt braucht weiterhin einen normalen Vertrag, etwa [[wiki/entities/tarif-lindenstrom-fix12|Fix12]]. Hat das Haus nur einen gemeinsamen Zähler, kommt der Tarif nicht in Frage. Dann bleibt die pauschale Entlastung nach Modul 1, die unabhängig vom Liefertarif gezahlt wird. Die technischen und rechtlichen Hintergründe stehen unter [[wiki/concepts/steuerbare-verbrauchseinrichtung]].",
     ])

page("wiki/entities/tarif-lindenstrom-basis.md", "LindenStrom Basis",
     "Tarif der Grundversorgung im Netzgebiet Lindenau mit den aktuell geltenden Preisen.",
     concepts=["grundversorgung"], cluster="preise", gt="pvk",
     body=[
"## Steckbrief",
C("LindenStrom Basis ist der Tarif der Grundversorgung im Netzgebiet Lindenau.", "S2@page=1 | S9@page=2"),
C("Der Grundpreis beträgt 13,20 EUR pro Monat.", "S9@page=2"),
C("Der Arbeitspreis beträgt seit dem 1. April 2026 38,72 ct/kWh brutto.", "S9@page=2", label="basis2026", replaces="basis2025"),
C("Vom 1. Januar 2025 bis zum 31. März 2026 betrug der Arbeitspreis 37,10 ct/kWh.", "S9@page=3", status="superseded", label="basis2025"),
C("Der Vertrag hat keine Mindestlaufzeit und kann mit einer Frist von zwei Wochen gekündigt werden.", "S2@page=1"),
"## Einordnung",
"Basis ist der teuerste Haushaltstarif der Stadtwerke, dafür ohne jede Bindung. Kunden landen hier oft unbemerkt, etwa nach einem Einzug ohne Anmeldung. Im Gespräch lohnt der Hinweis auf [[wiki/entities/tarif-lindenstrom-fix12|Fix12]]; die Unterschiede zeigt [[wiki/comparisons/grundversorgung-und-sondervertrag]]. Die letzte Preisrunde ist unter [[wiki/topics/preisanpassung-april-2026]] beschrieben.",
     ])
