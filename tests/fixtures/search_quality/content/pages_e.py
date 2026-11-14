# -*- coding: utf-8 -*-
"""Topic pages, part B (including superseded and draft pages)."""
from .dsl import C, page

page("wiki/topics/preisanpassung-april-2026.md", "Preisanpassung zum 1. April 2026",
     "Anhebung des Arbeitspreises in der Grundversorgung zum 1. April 2026 mit Begründung und Auswirkung.",
     cluster="preise", gt="pf", stale_after="2027-03-31",
     body=[
"## Was sich ändert",
C("In der Grundversorgung (LindenStrom Basis) steigt der Arbeitspreis zum 1. April 2026 von 37,10 ct/kWh auf 38,72 ct/kWh brutto, also um 1,62 ct/kWh.", "S9@page=3", label="pa2026", replaces="pa2025"),
C("Der Grundpreis bleibt unverändert.", "S9@page=3"),
C("Grund der Anpassung sind das gestiegene Netzentgelt mit einem Arbeitspreis von 9,84 statt 9,12 ct/kWh und höhere Umlagen.", "S9@page=3"),
"## Kommunikation",
C("Die Kundenanschreiben zur Preisanpassung wurden am 14. Februar 2026 versandt.", "S9@page=3"),
C("Für einen Haushalt mit 2.500 kWh Jahresverbrauch bedeutet die Anpassung Mehrkosten von rund 40 EUR im Jahr.", "S9@page=3"),
C("Kunden im Tarif Fix12 sind während der laufenden Preisgarantie nicht betroffen.", "S9@page=3"),
"## Hinweise für das Gespräch",
"Die Mitteilung ging rechtzeitig vor der Sechs-Wochen-Frist der Grundversorgung hinaus. Betroffene Kunden können ohne Frist zum 1. April kündigen, siehe [[wiki/concepts/sonderkuendigungsrecht]], oder in einen Sondervertrag wechseln. Die allgemeinen Regeln stehen unter [[wiki/concepts/preisanpassung]]; der vorherige Stand ist unter [[wiki/topics/preisanpassung-januar-2025]] archiviert.",
     ])

page("wiki/topics/preisanpassung-januar-2025.md", "Preisanpassung zum 1. Januar 2025",
     "Abgelöste Preisstellung: Senkung des Arbeitspreises in der Grundversorgung zum 1. Januar 2025.",
     status="superseded", cluster="preise", gt="p",
     body=[
"## Status",
"Diese Seite ist abgelöst. Sie dokumentiert die Preisstellung, die bis zum 31. März 2026 galt, und wird für Rückfragen zu alten Rechnungen aufbewahrt. Der aktuelle Stand steht unter [[wiki/topics/preisanpassung-april-2026]].",
C("Zum 1. Januar 2025 wurde der Arbeitspreis in der Grundversorgung von 39,95 ct/kWh auf 37,10 ct/kWh gesenkt.", "S9@page=3", status="superseded", label="pa2025"),
C("Ursache der Senkung waren gesunkene Beschaffungskosten am Terminmarkt.", "S9@page=3", status="superseded"),
C("Diese Preisstellung galt bis zum 31. März 2026.", "S9@page=3"),
"## Einordnung",
"Die Senkung um 2,85 ct/kWh war die erste Preissenkung in der Grundversorgung seit mehreren Jahren. Sie wurde damals ebenfalls sechs Wochen vorher angekündigt. Kunden, die sich heute über den höheren Preis wundern, vergleichen oft mit diesem Stand; im Gespräch hilft der Hinweis, dass die Beschaffung weiterhin günstiger ist als 2024, die Netzkosten aber gestiegen sind. Die Regeln für Änderungen erklärt [[wiki/concepts/preisanpassung]].",
     ])

page("wiki/topics/beschwerdemanagement.md", "Beschwerdemanagement",
     "Umgang mit Kundenbeschwerden von der Annahme bis zur Schlichtung.",
     cluster="organisation", gt="f",
     body=[
"## Kern",
"Eine Beschwerde ist jede Äußerung von Unzufriedenheit, auf die der Kunde erkennbar eine Antwort oder Abhilfe erwartet. Sie wird unabhängig vom Eingangskanal erfasst und einem Vorgang zum Vertrag zugeordnet.",
C("Beschwerden von Verbrauchern beantwortet der Lieferant innerhalb von vier Wochen ab Zugang.", "S1@page=4"),
C("Hilft der Lieferant der Beschwerde nicht ab, kann der Verbraucher die Schlichtungsstelle Energie anrufen; das Verfahren ist für Verbraucher kostenlos.", "S1@page=4"),
C("Einwände gegen eine Rechnung können innerhalb von drei Jahren erhoben werden.", "S5@page=3"),
C("Beanstandungen zu Zählerständen gehen an die Lindenau Netz GmbH als Netzbetreiber.", "S4@page=3"),
"## Arbeitsweise",
"Jede Beschwerde erhält am Tag des Eingangs eine Eingangsbestätigung. Kann der Fall nicht sofort gelöst werden, bekommt der Kunde einen Zwischenbescheid mit dem voraussichtlichen Termin. Die Antwort nennt immer die Entscheidung, die Begründung und den Hinweis auf die [[wiki/entities/schlichtungsstelle-energie]]. Häufige Anlässe sind geschätzte Zählerstände, die Höhe des Abschlags und verspätete Abrechnungen.",
     ])

page("wiki/topics/rollout-intelligenter-messsysteme.md", "Rollout intelligenter Messsysteme",
     "Entwurf: Ausbaustand und gesetzlicher Fahrplan für intelligente Messsysteme im Netzgebiet Lindenau.",
     status="draft", concepts=["messstellenbetrieb"], cluster="netz-messung", gt="zf",
     body=[
"## Hinweis",
"Diese Seite ist ein Entwurf. Die Zahlen stammen aus dem Leitfaden des Messwesens und wurden noch nicht mit dem Netzbetreiber abgestimmt.",
"## Gesetzlicher Fahrplan",
C("Der gesetzliche Fahrplan verlangt, dass 20 Prozent der Pflichteinbaufälle bis zum 31. Dezember 2025, 50 Prozent bis zum 31. Dezember 2028 und 95 Prozent bis zum 31. Dezember 2030 ausgestattet sind.", "S7@page=1"),
"## Stand in Lindenau",
C("Zum 30. September 2026 waren im Netzgebiet Lindenau 11.400 intelligente Messsysteme verbaut; das entspricht 48 Prozent der 23.800 Pflichteinbaufälle.", "S7@page=3"),
C("Die übrigen Haushalte erhalten bis 2032 schrittweise eine moderne Messeinrichtung.", "S7@page=3"),
"## Offene Punkte",
"Unklar ist noch, wie viele Kunden den Einbau auf eigenen Wunsch beantragen werden und ob die Monteurkapazität dafür reicht. Ebenfalls offen ist, wann der Tarif [[wiki/entities/tarif-lindenstrom-flex|LindenStrom Flex]] aktiv beworben wird, da er ein [[wiki/concepts/intelligentes-messsystem]] voraussetzt.",
     ])

page("wiki/topics/vertrieb-an-der-haustuer.md", "Vertrieb an der Haustür",
     "Entwurf: geplante Regeln für ein Pilotprojekt zum Haustürvertrieb im Jahr 2027.",
     status="draft", cluster="vertrag", gt="v",
     body=[
"## Hinweis",
"Diese Seite ist ein Entwurf. Die Regeln sind noch nicht von der Geschäftsführung freigegeben und dürfen Kunden gegenüber nicht als geltend dargestellt werden.",
C("Die Stadtwerke Lindenau Vertrieb GmbH setzt seit 2024 keine externen Haustürvertriebe ein.", "S8@page=3"),
C("Für das Jahr 2027 ist ein Pilotprojekt mit eigenen Mitarbeitern geplant.", "S8@page=3"),
"## Geplante Regeln",
C("Besuche sollen nur montags bis samstags zwischen 9 und 19 Uhr stattfinden.", "S8@page=3"),
C("Die Mitarbeiter weisen sich mit Dienstausweis und Lichtbild aus.", "S8@page=3"),
C("Jeder Abschluss wird innerhalb von 48 Stunden durch einen Bestätigungsanruf überprüft.", "S8@page=3"),
C("Bei Personen, die erkennbar die Tragweite nicht erfassen, wird kein Vertrag aufgenommen.", "S8@page=3"),
"## Rechtlicher Rahmen",
"An der Haustür geschlossene Verträge gelten als außerhalb von Geschäftsräumen geschlossen. Der Kunde hat deshalb ein [[wiki/concepts/widerrufsrecht]] von 14 Tagen.",
     ])

page("wiki/topics/kuendigungsfristen-alte-rechtslage.md", "Kündigungsfristen nach alter Rechtslage",
     "Abgelöst: Verlängerung um zwölf Monate und dreimonatige Kündigungsfrist bei Verträgen vor März 2022.",
     status="superseded", cluster="vertrag", gt="vkf",
     body=[
"## Status",
"Diese Seite ist abgelöst und beschreibt Bedingungen, die heute für keinen Vertrag mehr gelten. Sie wird aufbewahrt, weil Kunden mit langjährigen Verträgen sich noch auf die alten Fristen berufen. Aktuell gilt [[wiki/concepts/kuendigungsfrist]].",
C("Verträge, die vor dem 1. März 2022 geschlossen wurden, verlängerten sich stillschweigend um jeweils zwölf Monate.", "S1@page=4", status="superseded"),
C("Die Kündigungsfrist dieser Altverträge betrug drei Monate zum Ende der Laufzeit.", "S1@page=4", status="superseded"),
C("Die Altverträge wurden zum 1. Juli 2023 auf die heutigen Bedingungen umgestellt.", "S1@page=4"),
"## Was das heute bedeutet",
"Ein Kunde, der 2020 abgeschlossen hat, kann seit der Umstellung mit einer Frist von einem Monat kündigen; die alte Bindung von einem weiteren Jahr besteht nicht mehr. Schreibt ein Kunde, er habe die Dreimonatsfrist verpasst, ist das kein Hindernis. Die heutige Verlängerung auf unbestimmte Zeit erklärt [[wiki/concepts/vertragslaufzeit]].",
     ])
