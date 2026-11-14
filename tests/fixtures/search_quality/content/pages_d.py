# -*- coding: utf-8 -*-
"""Topic pages, part A."""
from .dsl import C, page

page("wiki/topics/lieferantenwechsel.md", "Lieferantenwechsel",
     "Ablauf, Fristen und Fehlerfälle beim Wechsel des Stromlieferanten.",
     concepts=["lieferantenwechsel"], cluster="vertrag", gt="vkfz",
     body=[
"## Grundsätze",
C("Der Lieferantenwechsel ist für den Kunden unentgeltlich.", "S4@page=1"),
C("Das Verfahren darf drei Wochen ab Zugang der Anmeldung beim Netzbetreiber nicht überschreiten (§ 20a Abs. 2 EnWG).", "S4@page=1"),
C("Seit dem 6. Juni 2025 wird der technische Wechselvorgang werktags innerhalb von 24 Stunden abgewickelt (Verfahren LFW24).", "S4@page=1"),
"## Ablauf",
C("Der Kunde erteilt dem neuen Lieferanten mit dem Auftrag eine Vollmacht zur Kündigung des bisherigen Liefervertrags.", "S4@page=2"),
C("Der neue Lieferant kündigt beim bisherigen Lieferanten und meldet die Netznutzung beim Netzbetreiber an.", "S4@page=2"),
C("Der Netzbetreiber bestätigt die Anmeldung oder lehnt sie mit einem Antwortcode ab.", "S4@page=2"),
C("Der Kunde erhält die Vertragsbestätigung mit dem verbindlichen Lieferbeginn.", "S4@page=2"),
"## Fehlerfälle",
C("Bei einer Ablehnung wegen Vertragsbindung läuft der bisherige Vertrag noch; der Wechsel wird zum nächstmöglichen Termin erneut angemeldet.", "S4@page=2"),
C("Die Ablehnung „Kunde nicht identifizierbar“ bedeutet, dass Name, Anschrift oder Zählernummer von den Stammdaten des Netzbetreibers abweichen.", "S4@page=2"),
C("Melden zwei Lieferanten dieselbe Marktlokation zum selben Termin an, gilt die zuerst eingegangene Anmeldung.", "S4@page=2"),
"## Abschluss",
C("Der bisherige Lieferant erstellt die Schlussrechnung spätestens sechs Wochen nach Lieferende (§ 40c Abs. 2 EnWG).", "S4@page=2"),
C("Den Zählerstand zum Wechseltermin meldet der Kunde im Zeitraum von fünf Werktagen vor bis fünf Werktagen nach dem Lieferbeginn.", "S4@page=2"),
"Scheitert der Wechsel, greift die [[wiki/concepts/ersatzversorgung]]. Die nötige Kennung erklärt [[wiki/concepts/marktlokation]].",
     ])

page("wiki/topics/umzug.md", "Umzug",
     "Pflichten und Möglichkeiten des Kunden bei Auszug und Einzug: Anzeige, Vertragsmitnahme, Zählerstand.",
     cluster="vertrag", gt="vkfz",
     body=[
"## Kern",
"Ein Umzug beendet den Stromliefervertrag nicht automatisch. Im Sondervertrag zieht der Vertrag grundsätzlich mit um; nur wenn die neue Adresse nicht beliefert werden kann, darf der Kunde vorzeitig aussteigen.",
C("Der Kunde muss dem Lieferanten einen Umzug mit einer Frist von sechs Wochen unter Angabe der neuen Anschrift und des Auszugsdatums anzeigen.", "S1@page=4"),
C("Der Vertrag wird an der neuen Entnahmestelle zu unveränderten Bedingungen fortgesetzt, sofern sie im Netzgebiet Lindenau liegt.", "S1@page=4"),
C("Kann der Lieferant die neue Entnahmestelle nicht beliefern, darf der Kunde mit einer Frist von sechs Wochen außerordentlich kündigen (§ 41b Abs. 5 EnWG).", "S1@page=4"),
"## Anmeldung und Zählerstand",
C("Ein- und Auszüge können seit Einführung von LFW24 nicht mehr rückwirkend gemeldet werden; die Anmeldung muss spätestens am Tag vor dem Einzug beim Netzbetreiber eingehen.", "S4@page=3"),
C("Beim Auszug meldet der Kunde den Zählerstand vom Tag der Wohnungsübergabe; das Übergabeprotokoll des Vermieters wird als Nachweis anerkannt.", "S4@page=3"),
C("Wer sich nach dem Einzug verspätet anmeldet, wird für die Zwischenzeit vom Grundversorger beliefert.", "S4@page=3"),
"Für die Zwischenzeit gelten die Regeln der [[wiki/concepts/ersatzversorgung]] oder der [[wiki/concepts/grundversorgung]]. Das Kündigungsrecht ist unter [[wiki/concepts/sonderkuendigungsrecht]] erläutert.",
     ])

page("wiki/topics/jahresverbrauchsabrechnung.md", "Jahresverbrauchsabrechnung",
     "Inhalt, Fristen und Fälligkeiten der jährlichen Stromabrechnung.",
     cluster="abrechnung", gt="fp",
     body=[
"## Kern",
"Einmal im Jahr wird der tatsächliche Verbrauch den geleisteten Abschlägen gegenübergestellt. Daraus ergibt sich ein Guthaben oder eine Nachzahlung.",
C("Der Abrechnungszeitraum umfasst höchstens zwölf Monate.", "S5@page=3"),
C("Die Rechnung muss dem Kunden spätestens sechs Wochen nach Ende des Abrechnungszeitraums zugehen.", "S5@page=3 | S1@page=3"),
C("Pflichtangaben nach § 40 EnWG sind unter anderem der Verbrauch, der Vergleich mit dem Vorjahr und mit Vergleichskundengruppen, die Stromkennzeichnung und die MaLo-ID.", "S5@page=3"),
"## Zahlung und Einwände",
C("Eine Nachzahlung ist 14 Tage nach Zugang der Rechnung fällig.", "S5@page=3"),
C("Ein Guthaben wird binnen zwei Wochen nach Rechnungsstellung ausgezahlt oder mit dem nächsten Abschlag verrechnet.", "S1@page=3"),
C("Einwände gegen die Rechnung können innerhalb von drei Jahren erhoben werden; sie berechtigen nur bei der ernsthaften Möglichkeit eines offensichtlichen Fehlers zum Zahlungsaufschub.", "S5@page=3"),
C("Auf Wunsch des Kunden wird monatlich, vierteljährlich oder halbjährlich abgerechnet (§ 40b EnWG).", "S1@page=3"),
"Grundlage ist der [[wiki/concepts/zaehlerstand]]. Hohe Nachzahlungen können über die [[wiki/topics/ratenzahlung]] gestreckt werden.",
     ])

page("wiki/topics/zahlungsverzug-und-mahnwesen.md", "Zahlungsverzug und Mahnwesen",
     "Mahnlauf, Mahnkosten und Verzugszinsen, wenn fällige Beträge nicht eingehen.",
     cluster="abrechnung", gt="fp",
     body=[
"## Mahnlauf",
"Geht ein Abschlag oder eine Nachzahlung nicht rechtzeitig ein, startet ein gestufter Mahnlauf. Ziel ist, den Kunden früh zu erreichen und eine Lösung zu finden, bevor weitere Kosten entstehen.",
C("Sieben Tage nach Fälligkeit wird eine kostenfreie Zahlungserinnerung versandt.", "S5@page=4"),
C("Die erste Mahnung folgt 14 Tage nach der Zahlungserinnerung, die zweite Mahnung weitere 14 Tage später.", "S5@page=4"),
C("Kunden mit erteiltem SEPA-Lastschriftmandat durchlaufen den Mahnlauf nur nach einer Rücklastschrift.", "S5@page=4"),
"## Kosten",
C("Ab der zweiten Mahnung wird eine Mahnpauschale von 2,50 EUR je Mahnschreiben berechnet.", "S1@page=3"),
C("Verzugszinsen fallen in Höhe von fünf Prozentpunkten über dem Basiszinssatz an.", "S1@page=3"),
C("Für eine vom Kunden zu vertretende Rücklastschrift werden 4,00 EUR zuzüglich der Bankgebühr berechnet.", "S1@page=3"),
"## Wie es weitergeht",
"Bleibt auch die zweite Mahnung ohne Erfolg, droht in der Grundversorgung die [[wiki/concepts/versorgungsunterbrechung]]. Vorher sollte dem Kunden aktiv eine [[wiki/topics/ratenzahlung]] angeboten werden.",
     ])

page("wiki/topics/ratenzahlung.md", "Ratenzahlung",
     "Ratenplan und Zahlungsaufschub für Kunden, die eine Nachzahlung nicht auf einmal leisten können.",
     cluster="abrechnung", gt="f",
     body=[
"## Kern",
"Eine Ratenzahlung verteilt eine offene Forderung auf mehrere Monate. Sie ist das wichtigste Werkzeug des Kundenservice, um Mahnkosten und eine Unterbrechung der Lieferung zu vermeiden.",
C("Bei einer Nachzahlung von mehr als 100,00 EUR wird auf Wunsch ein Ratenplan mit bis zu sechs zinsfreien Monatsraten angeboten.", "S5@page=4"),
C("Eine Verlängerung auf bis zu zwölf Raten bedarf der Zustimmung der Teamleitung.", "S5@page=4"),
C("Ein Zahlungsaufschub ist für höchstens 30 Tage möglich.", "S5@page=4"),
C("Während eines laufenden Ratenplans müssen die regulären Abschläge pünktlich weitergezahlt werden; andernfalls wird der gesamte Restbetrag sofort fällig.", "S5@page=4"),
"## Verhältnis zur Abwendungsvereinbarung",
C("In der Grundversorgung muss mit der Androhung einer Unterbrechung eine Abwendungsvereinbarung mit zinsfreier Ratenzahlung angeboten werden.", "S2@page=3"),
"Der freiwillige Ratenplan des Kundenservice und die gesetzliche Abwendungsvereinbarung verfolgen dasselbe Ziel, haben aber unterschiedliche Auslöser: Der Ratenplan setzt nur eine hohe Nachzahlung voraus, die Abwendungsvereinbarung eine bereits angedrohte [[wiki/concepts/versorgungsunterbrechung]]. Den Weg dorthin zeigt [[wiki/topics/zahlungsverzug-und-mahnwesen]].",
     ])

page("wiki/topics/vertragsschluss-im-fernabsatz.md", "Vertragsschluss im Fernabsatz",
     "Wie ein Stromliefervertrag online oder am Telefon wirksam zustande kommt.",
     cluster="vertrag", gt="vf",
     body=[
"## Kern",
"Die meisten Verträge werden heute online oder telefonisch geschlossen. Dafür gelten besondere Formvorschriften, und der Kunde hat ein [[wiki/concepts/widerrufsrecht]].",
C("Der Vertrag kommt zustande, sobald der Lieferant dem Kunden die Vertragsbestätigung in Textform übermittelt, spätestens mit Aufnahme der Belieferung.", "S1@page=1"),
C("Die Belieferung beginnt frühestens nach Ablauf der Widerrufsfrist, es sei denn, der Kunde verlangt ausdrücklich einen früheren Lieferbeginn.", "S1@page=1"),
C("Der Kunde erhält mit der Vertragsbestätigung die Widerrufsbelehrung und das Muster-Widerrufsformular.", "S8@page=1"),
"## Telefon",
C("Stromlieferverträge mit Haushaltskunden außerhalb der Grundversorgung bedürfen der Textform (§ 41 Abs. 1 Satz 1 EnWG).", "S8@page=2"),
C("Ein allein am Telefon abgegebenes Einverständnis genügt nicht; der Kunde muss das Angebot in Textform bestätigen.", "S8@page=2"),
C("Werbeanrufe bei Verbrauchern sind nur mit vorheriger ausdrücklicher Einwilligung zulässig (§ 7 Abs. 2 UWG).", "S8@page=2"),
"Vor der Bestätigung steht bei Sonderverträgen die [[wiki/concepts/bonitaetspruefung]].",
     ])

page("wiki/topics/neukundenbonus.md", "Neukundenbonus und Sofortbonus",
     "Höhe, Voraussetzungen und Auszahlung der Boni für neue Stromkunden.",
     cluster="preise", gt="pv",
     body=[
"## Kern",
"Die Stadtwerke gewähren zwei Boni, um neue Kunden für die Festpreistarife zu gewinnen. Beide sind an Bedingungen geknüpft, die im Kundengespräch häufig zu Rückfragen führen.",
C("Der Neukundenbonus beträgt 75,00 EUR und wird nach zwölf Monaten ununterbrochener Belieferung mit der ersten Jahresverbrauchsabrechnung verrechnet.", "S1@page=4"),
C("Der Sofortbonus beträgt 40,00 EUR und wird innerhalb von 60 Tagen nach Lieferbeginn überwiesen.", "S1@page=4"),
C("Neukunde ist, wer in den letzten sechs Monaten vor Vertragsschluss nicht vom Lieferanten mit Strom beliefert wurde.", "S1@page=4", kind="definition"),
"## Geltungsbereich",
C("Beide Boni gelten für die Tarife Fix12 und Öko.", "S9@page=3"),
C("Im Tarif Flex gibt es keinen Neukundenbonus.", "S9@page=1"),
C("Bei Vertragsabschluss über Vergleichsportale wird kein Sofortbonus gewährt.", "S9@page=3"),
"Offen ist, was mit dem Sofortbonus geschieht, wenn der Kunde vor Ablauf der zwölf Monate kündigt oder der Vertrag widerrufen wird; die Lieferbedingungen regeln das nicht ausdrücklich. Die Frage ist in der Liste der offenen Punkte vermerkt. Bis zur Klärung sollte im Gespräch keine Zusage gemacht werden. Die Tarife selbst sind unter [[wiki/entities/tarif-lindenstrom-fix12]] und [[wiki/entities/tarif-lindenstrom-oeko]] beschrieben.",
     ])
