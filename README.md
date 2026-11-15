# SkillSafeWerkstatt: Pflege- und Lese-Skills

Diese Distribution enthält zwei zusammengehörige Agent Skills für einen portablen, quellennahen Wissensraum aus Markdown-Dateien:

- [maintain-llm-wiki](maintain-llm-wiki/SKILL.md) erstellt, pflegt, prüft, veröffentlicht und exportiert ein Wiki.
- [query-llm-wiki](query-llm-wiki/SKILL.md) liest ein veröffentlichtes Wiki, sucht darin und beantwortet Fragen mit nachvollziehbaren Belegen.

Ein gepflegtes Wiki ist außerdem **exportierbar**: Jeder verifizierte Release lässt sich als Bündel im [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format) ausgeben — dem herstellerneutralen Standard von Google Cloud für Wissen als Markdown. Das Wissen bleibt damit nicht in diesem Werkzeug gefangen. Abschnitt 4.21 beschreibt den Export, seine Grenzen und was er bewusst nicht mitnimmt.

Die installierbaren Pakete liegen als [maintain-llm-wiki.skill](maintain-llm-wiki.skill) und [query-llm-wiki.skill](query-llm-wiki.skill) vor. Die danebenliegenden Ordner enthalten dieselben Skills entpackt und sind für Prüfung, Weiterentwicklung oder lokale Installation gedacht.

Beide Skills sind organisationsneutral, verwenden innerhalb erzeugter Artefakte ausschließlich portable relative Pfade und folgen mit `SKILL.md`, `scripts/`, `references/` und `assets/` dem von Claude Code verwendeten Agent-Skills-Aufbau. Sie funktionieren außerdem in Claude Cowork und Codex. Die deterministischen Helfer sind Bestandteil der Skills. Der Anwender formuliert seine Wünsche in natürlicher Sprache und muss weder Python noch einzelne Skripte selbst aufrufen.

## 1. Grundidee

Das System trennt konsequent zwischen vier Ebenen:

1. **Originale außerhalb des Wikis:** PDF-, Office-, Bild-, Audio- oder sonstige Ausgangsdateien bleiben an ihrem bisherigen Ort.
2. **Quellen als treues Markdown:** Lesbarer Inhalt wird ohne Synthese in Markdown umgewandelt und unter `sources/` registriert. Dieses Markdown ist die nachweisbare Quellenebene im Wiki.
3. **Kuratierte Wissensseiten:** Unter `wiki/` entsteht eine thematisch gepflegte, verlinkte und in der festgelegten Wiki-Sprache geschriebene Wissensschicht.
4. **Abgeleitete Darstellung:** Unter `graph/` entsteht eine statische Website mit Graph, Clustern und HTML-Leseansichten. Diese Dateien können jederzeit aus dem Markdown neu erzeugt werden.
5. **Ausgang in den Standard:** Aus einem verifizierten Release entsteht auf Wunsch ein OKF-v0.2-Bündel in einem beliebigen Zielverzeichnis. Es ist eine Kopie, keine zweite Wahrheit, und es beschreibt selbst, was es gegenüber dem Wiki verliert.

```text
Ausgangsmaterial außerhalb des Wikis
                 |
                 v
      treue Markdown-Extraktion
                 |
                 v
        sources/ + Quellenregister
                 |
                 v
     claim-basierte Kuration in wiki/
                 |
        +--------+---------+
        |                  |
        v                  v
  Graph + HTML         Lint + Release
                           |
                           v
                 verifizierter Lesestand
                           |
                           v
                    query-llm-wiki
```

Das Zielverzeichnis ist die kanonische Arbeitskopie. Ob es später lokal bleibt, über OneDrive synchronisiert, in SharePoint gespeichert oder mit Git versioniert wird, ist für das Dateiformat unerheblich.

## 2. Zuständigkeit der beiden Skills

| Bereich | `maintain-llm-wiki` | `query-llm-wiki` |
|---|---:|---:|
| Wiki initialisieren | Ja | Nein |
| Material in Markdown aufnehmen | Ja | Nein |
| Quellen registrieren | Ja | Nein |
| Wissensseiten kuratieren | Ja | Nein |
| Cluster und Begriffswelten pflegen | Ja | Nein |
| Metadaten inventarisieren | Ja, auf dem gesperrten Arbeitsstand | Ja, auf einem verifizierten Release |
| Frontmatter ändern oder bereinigen | Ja, über Plan/Apply | Nein |
| Seiten verschieben und Links nachführen | Ja, nach Vorschau und Bestätigung | Nein |
| Snapshots und Restore | Ja | Nein |
| Graph und HTML-Seiten erzeugen | Ja | Nein |
| Qualität und Cleaning prüfen | Ja, inklusive Review-Aufzeichnung | Nur Status lesen und Hinweise geben |
| Release erzeugen | Ja | Nein |
| Fragen beantworten | Nur soweit für die Pflege erforderlich | Ja |
| Metadatenfilter und Facetten | Für Auswahl und Pflege | Für Suche und Auswertung |
| Suche mit Zählwerk (`coverage`) | Nein; ein exportierter Wissens-Skill nutzt denselben Suchkern | Ja, in jeder Suche |
| Eingefrorenen Wissens-Skill exportieren | Ja | Nein |
| Seiten als geprüft aufzeichnen | Ja, mit Bestätigung | Nein, nur Stufe lesen und nennen |
| Konfliktkopien auflösen | Ja, nach Vergleich und Bestätigung | Nein, nur melden |
| OKF-Bündel exportieren | Ja, aus verifiziertem Release, mit Quellen | Nein |
| Beobachtungen als Quelle registrieren | Ja, mit Akteur und Anlass | Nein |
| Bestehende Markdown-Sammlung übernehmen | Ja, als Quellen, über Plan/Apply | Nein |
| Ablaufdatum einer Seite | Setzen und melden | Nur nennen, nie filtern |
| Wiki verändern | Ja, kontrolliert | Niemals |

Diese Trennung verhindert, dass eine normale Wissensabfrage versehentlich Dateien verändert oder einen Pflegeprozess auslöst.

## 3. Typischer Aufbau eines erzeugten Wikis

```text
<wiki>/
|-- .llmwiki.lock/             Claims der Maintainer; nur während einer aktiven Pflege
|   `-- claim-<maintainer>.json
|-- WIKI.md                    Einstieg und Zweck des Wikis
|-- WIKI_VERSION               veröffentlichte semantische Version
|-- SOUL.md                    bestätigte Identität und Antwortform
|-- schema/
|   |-- WIKI_RULES.md          lokale Regeln und Inhaltsvertrag
|   |-- WIKI_PROFILE.md        Wiki-Sprache und Profil
|   |-- CONTENT_POLICY.md      Historie, Ersetzung und Konflikte
|   |-- CLUSTERS.md            Navigation, Graph-Gruppen, optionale Verzeichnisse
|   |-- CONCEPTS.md            kontrollierte Begriffswelten und Synonyme
|   `-- QUALITY_POLICY.md      Intervalle für Qualität, Cleaning und Snapshot-Alter
|-- sources/
|   `-- src-<hash>-<slug>.md   treue Markdown-Quellen
|-- wiki/
|   |-- index.md               Wiki-Einstieg
|   |-- overview.md
|   |-- concepts/
|   |   `-- index.md           erzeugte Gruppenübersicht
|   |-- entities/
|   |-- topics/
|   `-- comparisons/
|-- meta/
|   |-- sources.jsonl          registrierte Quellen und Versionen
|   |-- changes.md             nachvollziehbares Änderungsprotokoll
|   |-- questions.md           offene Fragen und fehlende Belege
|   |-- lint-report.json       letzter Strukturbericht
|   |-- releases.jsonl         unveränderliche Release-Einträge
|   |-- quality-reviews.jsonl  tatsächlich durchgeführte Reviews
|   |-- quality-status.json    veröffentlichter Qualitätsstatus
|   |-- findability-questions.jsonl  optionale Auffindbarkeitsfragen; nur für Pfleger, nie im Release
|   |-- manifest.json          Hash-Grenze des aktuellen Releases
|   `-- history/
|       `-- <snapshot-id>/     Wiederherstellungspunkte mit eigenem Manifest
`-- graph/
    |-- index.html             interaktiver Wissensgraph
    |-- graph.json             erzeugte Knoten- und Kantendaten
    `-- pages/                 statische HTML-Leseansichten
```

Die kanonische Wissens- und Quellenebene bleibt normales Markdown. JSON-Dateien dienen nur als maschinenlesbare Register und Integritätsdaten; der Graph und seine HTML-Seiten sind eine komfortable Ansicht, aber keine zweite bearbeitbare Wahrheit.

## 4. Der Pflege-Skill `maintain-llm-wiki`

### 4.1 Initialisierung

Bei einem neuen Wiki benötigt der Skill:

- ein vom Anwender festgelegtes Zielverzeichnis;
- Titel und Themenabgrenzung;
- die Sprache, in der das kuratierte Wiki gepflegt wird;
- eine ausdrücklich bestätigte Identität für Zweck, Wissensarten, Zielgruppe, Tonalität, Antwortstil, Grenzen und Tabus;
- eine ausdrücklich bestätigte Inhaltsrichtlinie für aktuellen Stand, Historisierung, Ersetzung und Konflikte;
- auf Wunsch angepasste Prüfintervalle.

Vor Lock und Dateischreibzugriff beginnt der Skill mit einer kurzen Einladung zur gemeinsamen Identitätsklärung und stellt danach jeweils nur eine gezielte Frage. Er zeigt anschließend die vollständige vorgeschlagene `SOUL.md`, die wesentlichen Entscheidungen für `schema/CONTENT_POLICY.md` und einen Hash. Erst die ausdrückliche Bestätigung dieses unveränderten Vorschlags erlaubt die Initialisierung; Schweigen gilt nicht als Zustimmung.

Als Vorschlag verwendet der Skill 30 Tage für eine semantische Qualitätsprüfung, 90 Tage für eine optionale Cleaning-Prüfung und 60 Tage als Hinweisgrenze für das Alter eines eingefrorenen Wissens-Snapshots. Diese Werte sind keine automatischen Lösch- oder Änderungsfreigaben.

Die Initialisierung baut das vollständige Wiki zunächst außerhalb des Zielverzeichnisses, erzeugt Graph und Leseansichten, prüft alles und veröffentlicht Version `0.1.0`. Erst danach werden alle Dateien und auch leere Pflichtverzeichnisse übernommen. Ein Fehler lässt keinen halbfertigen Wiki-Inhalt zurück; ein bestehendes oder nicht leeres Ziel wird nicht überschrieben.

### 4.2 Aufnahme von Quellen

„Ingest“ bedeutet in diesem System die kontrollierte Aufnahme neuen Materials:

1. Das Ausgangsmaterial wird in einem temporären Arbeitsbereich gelesen.
2. Der Inhalt wird möglichst treu in Markdown umgewandelt.
3. Sprache, Überschriften, Listen, Tabellen, Zitate, Kennungen sowie Seiten-, Folien-, Abschnitts- oder Zeitmarken bleiben erhalten, soweit sie auslesbar sind.
4. Eine Vorprüfung erkennt leere oder beschädigte Extrakte, extreme Fließzeilen, ungeschlossene Codeblöcke sowie auffällige Überschriften, Tabellen und fehlende Seitenmarken. Zugangsdaten wie private Schlüssel, Token oder URLs mit Passwort weist sie zurück; der Lint prüft dasselbe für das gesamte Wiki. Gemeldet werden Datei, Zeile und Art, nie der Wert selbst.
5. Die Markdown-Fassung wird mit einer stabilen `source_id` unter `sources/` registriert; Quelle und Registereintrag werden gemeinsam veröffentlicht oder gemeinsam verworfen.
6. Wenn Originalbytes verfügbar sind, kann ihr Hash ermittelt werden; ein lokaler absoluter Dateipfad wird trotzdem nicht im Wiki gespeichert.
7. Erst danach wird der Inhalt in die gepflegte Wissensschicht eingeordnet und synthetisiert.

Seiten- und Foliengrenzen stehen als `<!-- page: N -->` beziehungsweise `<!-- slide: N -->` auf einer eigenen Zeile. Die Vorprüfung warnt, wenn eine solche Marke mitten in einer Zeile steht, denn dort findet sie weder die Leseansicht noch die Locator-Prüfung. Gängige Konverter schreiben diese Marken nicht von sich aus; der Skill wandelt deshalb seitenweise um oder ersetzt die Seitenumbrüche des Konverters durch die Markenzeile.

`sources/` enthält damit das **aus dem Original erkannte, treue Markdown**, nicht zwingend die Originaldatei selbst. Das Original darf außerhalb des Wikis verbleiben. Unvollständig lesbares Material wird als `partial` gekennzeichnet und nicht als vollständig extrahiert ausgegeben.

Eine Quelle wird ausschließlich über ihren aktuellen Anhangspfad oder einen ausdrücklich vom Anwender gewählten Pfad geöffnet. Fehlt dieser Pfad oder ist er nicht zugreifbar, fragt der Skill nach erneutem Anhängen beziehungsweise eng begrenztem Zugriff. Er durchsucht weder das gesamte Benutzerverzeichnis noch den Rechner nach einem vermuteten Dateinamen und konstruiert keinen Ersatzpfad.

`sources/` ist ein flaches Verzeichnis nur für registrierte `.md`-Extraktionen. Ein Unterordner `sources/raw/` sowie PDF-, Office-, Bild-, Audio-, Archiv- oder andere Originaldateien im Wiki sind unzulässig und werden vom Linter beanstandet. Muss eine unvollständige Extraktion anhand des Originals ergänzt werden, ist das Original erneut explizit bereitzustellen; sein Vorhandensein wird nicht aus Titel oder `original_ref` abgeleitet.

Byte-identische Quellen werden nicht doppelt aufgenommen. Für Referenzen eignen sich relative Namen, URLs, SharePoint-Element-IDs oder andere portable logische Bezeichnungen.

### 4.3 Wiki-Sprache

Die gepflegte Wiki-Sprache wird bei der Einrichtung ausdrücklich festgelegt und in `schema/WIKI_PROFILE.md` gespeichert.

- Quellen bleiben in `sources/` in ihrer Originalsprache.
- Wiki-Seiten, Zusammenfassungen, Claim-Texte, Clusterbeschreibungen und bevorzugte Begriffe werden in der festgelegten Wiki-Sprache gepflegt.
- Anderssprachige Fachausdrücke können als Aliase in den Begriffswelten erhalten bleiben.
- Auch erzeugte Prosa folgt der Wiki-Sprache: die Überschriften und der Erklärtext von `SOUL.md` und `schema/CONTENT_POLICY.md` sowie die generierten Verzeichnisindizes. Deutsch und Englisch sind eingebaut, andere Sprachcodes bekommen ein englisches Gerüst um die unveränderten Feldwerte.
- Eine spätere Sprachänderung ist möglich, gilt aber als vollständige Migration mit Auswirkungsplan, Bestätigung, Snapshot, vollständiger Übersetzung, neu gerenderten Identitätsdateien, neuem Graph, Prüfung und Major-Release.

Eine teilweise übersetzte aktive Wissensschicht darf nicht veröffentlicht werden.

### 4.4 Kuration statt Dokumentablage

Das Wiki ist keine Sammlung aus jeweils einer Zusammenfassung pro Dokument. Der Skill prüft bei jeder Aufnahme, ob das Material:

- eine vorhandene Wissensseite erweitert;
- eine bestehende Aussage präzisiert oder widerspricht;
- eine neue, dauerhaft eigenständige Seite rechtfertigt;
- eine offene Frage oder eine erkennbare Evidenzlücke erzeugt;
- bestehende Cluster oder Begriffswelten berührt.

Bevor neue Seiten angelegt werden, liest der Skill Index, passende vorhandene Seiten, Cluster, Begriffswelten und die neue Quelle. Dadurch sollen semantische Dubletten und isolierte Dokumentzusammenfassungen vermieden werden.

Blöcke zwischen `<!-- human:keep -->` und `<!-- /human:keep -->` sind geschützt. Der Skill darf menschliche Korrekturen dort nicht stillschweigend überschreiben.

### 4.5 Claim-basierte Belege

Materielle Aussagen auf aktiven Wiki-Seiten werden in Claim-Blöcken geführt. Ein Claim besitzt insbesondere:

- eine global eindeutige `claim_id`;
- eine Art wie Fakt, Beobachtung, Definition, Interpretation oder Empfehlung;
- einen Status wie aktiv, strittig, abgelöst oder unbelegt;
- eine oder mehrere `source_id@locator`-Angaben;
- optional Beziehungen zu ersetzten oder widersprechenden Claims.

Für Locator gibt es kanonische Formen, die der Lint gegen die registrierte Extraktion auflöst: `page=N` oder `page=A-B` (Seitenmarken), `slide=N` (Folienmarken), `section=…`, `heading=…` oder `sheet=…` (eine Überschrift der Extraktion; `section=Preise` passt auf „§ 3 Preise“, wenn nur eine Überschrift so heißt), `timestamp=…` (eine Zeitmarke wie `00:12:30` im Text oder in einer Überschrift) und `document`. Löst ein solcher Locator nicht auf, meldet der Lint eine Warnung mit Claim, Locator und Grund. Gründe sind etwa Seite 7 in einer vierseitigen Extraktion, eine Seitenangabe in einer Extraktion ohne Seitenmarken, ein umgedrehter Bereich oder eine Überschrift, die es nicht oder mehrfach gibt. Hat eine Extraktion gar keine Seitenmarken, fasst der Lint alle Seitenangaben auf diese Quelle in einer Warnung zusammen und nennt die Claims in der Statistik. Andere Schreibweisen wie `S. 12` bleiben zulässig, werden aber nur gezählt, nicht geprüft. Eine unbekannte Quell-ID bleibt ein Fehler. Keine dieser Warnungen blockiert einen Release. In den HTML-Leseansichten springt ein Beleg mit `page=N` jetzt auf die Seitenmarke.

Eine neuere Quelle macht eine ältere Aussage nicht automatisch ungültig. Ersetzung, Gültigkeitsbereich und Widerspruch werden ausdrücklich dokumentiert. Bei einem Konflikt bleiben beide belegten Positionen sichtbar, solange keine belastbare Auflösung vorliegt.

### 4.6 Cluster und Begriffswelten

Cluster und Begriffswelten sind bewusst getrennt:

**Cluster** steuern Navigation, visuelle Gruppierung im Graph, Kuration und optional die Verzeichnisstruktur. Ein bestätigter Primär-Cluster kann bestimmen, in welchem Unterordner eine Wiki-Seite liegt.

**Begriffswelten** bilden kontrolliertes Vokabular für Suche und Terminologie. Sie enthalten einen bevorzugten Begriff, Definitionen, Aliase und optionale Beziehungen zu übergeordneten oder verwandten Begriffen. Nur sie erweitern eine Anfrage um andere Wörter; Formen desselben Wortes, Kompositumteile und Tippfehler behandelt die Suche selbst (Abschnitt 5.4). Jede neue `CONCEPTS.md` nennt diese Regel. Steht in einer bestehenden `CONCEPTS.md` noch der alte Satz „Search may expand a query only through confirmed preferred terms and aliases.", meldet der Lint eine Warnung mit dem neuen Wortlaut. Sie blockiert keinen Release.

Seiten-Aliase in der Sprache der Nutzer folgen drei Regeln: Wörter der Nutzer statt Wörter des Wikis (keine Wortformen), eindeutig im Fachgebiet, ein Alias auf genau einer Seite und vom Anwender bestätigt. Lint legt unter `stats.alias_review` häufige Alias-Wörter (in mindestens 10 % der Inhaltsseiten, mindestens 3) und mehrfach vergebene Aliase zur Bestätigung vor; das ist kein Fehler und blockiert keinen Release.

Jede Begriffswelt beginnt mit einer Überschrift zweiter Ebene, die ihre stabile ID trägt. Jede andere Überschrift, die mit `#` beginnt, beendet die laufende Begriffswelt; Felder darunter gehören zu keiner. Bisher hängte eine Zwischenüberschrift wie „## Hinweise“ ihre Felder still an die Begriffswelt darüber, und ein `- Status: draft` darunter nahm diese Begriffswelt aus der Suche. Steht ein solches Feld unter einer fremden Überschrift, meldet der Lint einen Fehler mit Zeilennummer; erklärende Abschnitte ohne Felder bleiben erlaubt, ebenso Listenpunkte mit anderen Schlüsseln wie `- Hinweis: …`. Zeilen in Codeblöcken (mit Backticks oder Tilden) und in mehrzeiligen HTML-Kommentaren zählen nicht mit. Sollte eine Überschrift wie „## Preisbestandteile“ eine neue Begriffswelt beginnen, braucht sie eine stabile ID in Kleinbuchstaben („## preisbestandteile“); die Meldung sagt das, statt die Felder in die Begriffswelt darüber verschieben zu lassen, wo sie deren Begriffe überschreiben würden. Für `CLUSTERS.md` gilt dieselbe Regel. Lint, Suche, Graph und jeder neu exportierte Wissens-Skill lesen beide Dateien mit demselben Code; bereits exportierte Wissens-Skills lesen bis zum nächsten Export wie bisher.

Eine Änderung der Begriffswelt verschiebt keine Datei. Eine bestätigte Änderung des Primär-Clusters kann dagegen eine Seitenverschiebung auslösen. Der Skill schlägt Cluster und Begriffe mit Abgrenzung, Überlappungen und Beispielen vor und lässt den Anwender sie bestätigen, umbenennen, zusammenführen, teilen, neu einfärben, verknüpfen oder ablehnen.

### 4.7 Frontmatter-Vertrag

Alle Helfer verwenden denselben bewusst eingeschränkten Frontmatter-Parser. Unterstützt werden:

- genau eine oberste Zuordnungsebene;
- sichere Eigenschaftsnamen;
- Strings, Ganzzahlen, endliche Dezimalzahlen, Boolesche Werte und `null`;
- flache Listen dieser Skalartypen;
- zweistufig eingerückte Blocklisten und nicht verschachtelte Inline-Listen;
- vollständige Kommentarzeilen am Anfang des Frontmatter-Blocks.

Abgelehnt werden unter anderem:

- doppelte Schlüssel;
- verschachtelte Objekte oder Listen;
- YAML-Anker, Aliase und Tags;
- Blockskalare;
- Tabulator-Einrückung;
- unsichere Schlüssel wie `__proto__`, `constructor` oder `prototype`;
- fehlerhafte Anführungszeichen.

Fehler werden mit Zeilenbezug gemeldet. Der Skill rät bei nicht unterstütztem YAML nicht, sondern stoppt die betreffende Massenoperation oder Veröffentlichung.

Ein einzelner Wert `aliases: Foo` statt einer Liste wird von der Suche als ein Alias gelesen; Lint warnt, bis er als Liste geschrieben ist.

Eine typische Wiki-Seite verwendet beispielsweise:

```yaml
---
id: "concept-example"
title: "Beispiel"
type: "concept"
status: "active"
created: "2026-08-21"
updated: "2026-08-21"
description: "Kurze Beschreibung für Index und Graph."
language: "de"
aliases:
  - "Alternativer Begriff"
sources:
  - "[[sources/src-0123456789abcdef-beispiel|Beispielquelle]]"
clusters:
  - "example-domain"
concepts:
  - "example-concept"
tags:
  - "type/wiki-concept"
---
```

### 4.8 Inventar und Drift-Bericht

Vor breiten Schemaänderungen oder Bereinigungen erstellt der Pflege-Skill ein strukturelles Inventar. Es enthält:

- Anzahl und Klassen der untersuchten Dokumente;
- vorkommende Eigenschaften und Nutzungshäufigkeit;
- beobachtete Werttypen;
- begrenzte repräsentative Wertbeispiele;
- fehlende Pflichtfelder;
- Typabweichungen;
- nicht kanonische oder abweichende Eigenschaftsnamen;
- kompatible Erweiterungsfelder;
- Parserfehler.

Ein sauberes Inventar beweist nur strukturelle Konsistenz. Es beweist weder inhaltliche Richtigkeit noch Aktualität oder Vollständigkeit.

### 4.9 Kontrollierte Frontmatter-Änderungen

Massenänderungen folgen immer dem Muster **Auswahl → Aktion → Plan → Bestätigung → Apply**.

Mögliche Aktionen sind:

- Wert setzen;
- Eigenschaften löschen;
- Eigenschaft umbenennen;
- Wert in eine andere Eigenschaft kopieren;
- mehrere Eigenschaften zusammenführen;
- Werte trimmen, in Groß-/Kleinschreibung vereinheitlichen oder Diakritika entfernen;
- konkrete Werte über eine Mapping-Liste ersetzen oder aus Listen entfernen;
- Wikilinks identitätsbewusst deduplizieren.

Auswahlen können alle Dateien, eine explizite Pfadliste oder einen validierten Metadatenfilter umfassen. Filter unterstützen `AND` und `OR`, definierte Vergleichsoperatoren und virtuelle Felder wie Pfad, Ordner, Dateiname und Erweiterung. Reguläre Ausdrücke oder ausführbare Bedingungen sind absichtlich ausgeschlossen.

Der Plan enthält nur relative Pfade, die normalisierte Auswahl und Aktion, Vorher-/Nachher-Frontmatter, Änderungs- und Überspringungsgründe sowie Datei-Hashes. Zusätzlich besitzt der vollständige Plan einen eigenen `plan_sha256`.

Beim Anwenden gilt:

- Es darf ausschließlich der ausdrücklich bestätigte Plan-Hash verwendet werden.
- Alle betroffenen Dateien müssen noch exakt ihrem Vorher-Hash entsprechen.
- Eine veraltete oder manipulierte Planung führt zu `stale_plan` beziehungsweise Ablehnung und **null Schreibvorgängen**.
- Unmittelbar vor jeder einzelnen Änderung wird erneut geprüft.
- Vor der ersten Änderung entsteht automatisch ein gezielter Wiederherstellungs-Snapshot.

Stabile IDs, Claim-Texte, Quellentitel, Locatoren, Hashes, `original_ref` und geschützte menschliche Inhalte werden nicht aus rein optischen Gründen normalisiert.

### 4.10 Linkbereinigung und Seitenverschiebung

Die Linkbereinigung berücksichtigt Zielpfad, Unterpfad und sichtbaren Alias getrennt. Sie führt nur Links zusammen, deren Identität bewiesen ist. Nicht auflösbare Links werden nur dann dedupliziert, wenn ihre Rohtexte exakt identisch sind.

Bei einer Seitenverschiebung zeigt der Skill zunächst:

- alten und neuen relativen Pfad;
- alle betroffenen eingehenden Wikilinks;
- betroffene Indexeinträge;
- Datei-Vorbedingungen und Vorschau-Hash;
- das Risiko für Links außerhalb des Wikis.

Erst nach Bestätigung darf dieselbe Vorschau angewendet werden. Dabei wird automatisch ein Snapshot erzeugt, ein vorhandenes Ziel niemals überschrieben und interne Wikilinks werden nachgeführt. Externe Links kann das Dateisystem naturgemäß nicht reparieren.

### 4.11 Snapshots und gezieltes Restore

Snapshots liegen unter `meta/history/` und besitzen ein eigenes Manifest mit:

- Snapshot-ID und Zeitpunkt;
- Art der Operation;
- öffentlicher Lock-ID;
- relativen Dateipfaden;
- Größen und SHA-256-Hashes;
- ausdrücklich als fehlend dokumentierten Zielpfaden.

Die Historie wird nicht automatisch bereinigt.

Ein Restore erfolgt ebenfalls als Plan/Apply-Transaktion. Der Anwender sieht die ausgewählten Dateien und Hashes vorab. Beim Anwenden werden aktueller Zustand, Restore-Plan und Snapshot erneut geprüft. Zusätzlich entsteht zuerst ein Recovery-Snapshot des Zustands unmittelbar vor dem Restore.

Ein Restore löscht keine aktuelle Datei nur deshalb, weil diese in einem älteren Snapshot nicht vorhanden war. Wiederhergestellte Dateien bilden zunächst einen unveröffentlichten Pflegezustand; Graph, Lint und Release müssen anschließend erneut konsistent hergestellt werden.

### 4.12 Qualitäts- und Cleaning-Zyklus

Der Skill unterscheidet drei Dinge:

1. **Lint:** deterministische Strukturprüfung bei jedem Release.
2. **Qualitätsreview:** semantische Prüfung von Belegen, Gültigkeit, Dubletten, offenen Fragen, Sprache, Seitengrenzen, Clustern und Begriffswelten, Quellenabdeckung und, falls vorhanden, Auffindbarkeitsfragen (Abschnitt 4.26).
3. **Cleaning-Review:** optionale Suche nach Konsolidierungs-, Entfernungs- oder Reorganisationskandidaten.

Ein fälliges Cleaning ist nur eine Erinnerung. Es löscht oder verändert nichts automatisch. Der Skill beginnt mit einer Vorschau und fragt bei bedeutungsändernden oder destruktiven Vorschlägen nach Bestätigung.

Review-Einträge werden nur dann geschrieben, wenn die betreffende Prüfung tatsächlich stattgefunden hat. Ein erfolgreicher Lint wird niemals als semantisches Review ausgegeben.

### 4.13 `SOUL.md`

`SOUL.md` ist für neu erzeugte Wikis verbindlich und beschreibt, wie Antworten aus dem Wiki standardmäßig formuliert werden sollen. Festgelegt werden:

- Antwortsprache;
- Anrede;
- Ton und Ausführlichkeit;
- bevorzugte Antwortstruktur;
- Darstellung von Quellen und Originaltiteln;
- Umgang mit Unsicherheit;
- Behandlung historischer und abgelöster Informationen.

`schema/CONTENT_POLICY.md` bleibt davon getrennt. Sie legt fest, ob das Wiki primär einen aktuellen Stand, ein historisches Journal oder ein Hybridmodell führt und wie Ersetzung sowie belegte Konflikte behandelt werden. Entfernen bleibt immer Vorschau plus ausdrückliche Bestätigung und geschieht nie automatisch.

Beide Dateien werden beim Einrichten aus einem hashgebundenen, bestätigten Vorschlag erzeugt. Der Vorschlag wird für die festgelegte Wiki-Sprache gerendert und trägt sie im Hash; ein Vorschlag für eine andere Sprache wird bei Einrichtung und Anwendung abgelehnt. Spätere Änderungen verwenden denselben Vorschau-/Bestätigungsmechanismus und einen Snapshot. `SOUL.md` steuert keine Dateiberechtigungen, hebt keine Sicherheitsregeln auf und macht gewöhnliche Wiki- oder Quellentexte nicht zu Agentenanweisungen.

### 4.14 Graph und statische Website

Der Pflege-Skill erzeugt eine vollständig lokale, statische Darstellung:

- Markdown-Dateien werden zu Knoten;
- Wikilinks werden zu Kanten;
- bestätigte Cluster erscheinen als sichtbare Gruppen und Filter;
- Seiten können per Maus, Trackpad und Tastatur navigiert werden;
- Light Mode und Dark Mode werden unterstützt;
- ein Klick auf einen Knoten öffnet eine erzeugte HTML-Leseansicht;
- Seiten- und Folienmarken in Quellen werden als sichtbare Anker statt als Markdown-Kommentarartefakte dargestellt;
- fehlerhafte Überschriften- oder Tabellenfragmente aus Extraktionen werden lesbar isoliert und nicht zu riesigen Layout-Elementen;
- Claim-Belege verlinken nach Möglichkeit direkt auf die passende Quellenansicht und Seitenmarke;
- alle Routen sind relativ zur Position von `graph/index.html`;
- die Darstellung benötigt keinen lokalen Webserver;
- jede HTML-Leseansicht nennt die kanonische Markdown-Datei und führt zurück zum Graphen.

Die HTML-Seiten unter `graph/pages/` werden nicht manuell gepflegt. Bei inhaltlichen oder strukturellen Änderungen werden sie neu erzeugt.

### 4.15 Release-Protokoll und Integrität

Ein Release ist die verbindliche Grenze zwischen Pflege und Lesen. Der Release-Prozess:

1. prüft den Writer-Lock;
2. führt den strikten Linter erneut aus;
3. prüft die erwartete aktuelle Version und eine stabile Operations-ID;
4. erhöht die semantische Wiki-Version höchstens einmal pro Operations-ID;
5. ergänzt das unveränderliche Release-Protokoll;
6. erzeugt den aktuellen Qualitätsstatus;
7. hasht alle kontrollierten Dateien;
8. ersetzt `meta/manifest.json` atomar als letzten Schritt.

Wird derselbe erfolgreiche Release-Auftrag nach einem Timeout erneut aufgerufen, liefert er denselben Release und erhöht die Version nicht erneut. Eine bereits in einem älteren Release verwendete Operations-ID oder eine veraltete Versionsvorbedingung wird abgelehnt.

Übliche Inhaltsänderungen erhöhen die Patch-Version. Kompatible Schemaerweiterungen erhöhen Minor. Bewusst inkompatible Änderungen und vollständige Wiki-Sprachmigrationen erhöhen Major.

Leser akzeptieren ausschließlich einen durch dieses Manifest verifizierten Stand. Dadurch werden halbfertige Pflegezustände und Mischstände nicht als gültiges Wiki ausgegeben.

Die Release-Ausgabe enthält die Lint-Statistiken, darunter die Quellenabdeckung; in `meta/quality-status.json` steht sie nicht.

### 4.16 Eingefrorener Wissens-Skill

Der Pflege-Skill kann einen verifizierten Release als eigenständigen Wissens-Skill exportieren. Dieser Export:

- enthält genau einen veröffentlichten Wiki-Stand;
- ist unveränderlich und nicht selbstpflegend;
- besitzt keinen Ingest-, Pflege-, Release-, Lock- oder Restore-Code;
- enthält nur Verifikation, Suche und Qualitätsbewertung sowie benötigte read-only Bibliotheken; welche das sind, ermittelt der Exporter aus den Importen selbst; mitkommen darf nur, was auf seiner Liste geprüfter lesender Bibliotheken steht, und jeder Import der Standardbibliothek muss auf einer zweiten geprüften Liste stehen, sodass weder ein Pflegewerkzeug noch schreibender Code in einen Export gelangt; ein neuer Import ohne Prüfung wird mit Namen abgelehnt statt stillschweigend vergessen;
- wird erst gemeldet, wenn jedes mitgelieferte Werkzeug im erzeugten Ordner fehlerfrei gelaufen ist, auch die Suche mit Metadatenfilter; der Selbsttest ruft die Suche auch mit einer JSON-Anfrage über die Standardeingabe auf und auch mit `--exhaustive`; scheitert das oder irgendein späterer Schritt, werden Ordner und Paket wieder entfernt;
- sucht mit demselben Suchkern wie der Lese-Skill (`search_core.py` mit `bm25.py` und `wordforms.py`, byte-identisch) und liefert auf demselben Release dieselbe Rangliste, dieselben Wortformen und dasselbe Zählwerk (Abschnitt 5.4) und nimmt wie der Lese-Skill Umformulierungen an (`--also`, `--request -`), einschließlich der abgesicherten Fehlanzeige (`--exhaustive`, `absence_check`, `search_record`); Ergebnispfade beginnen mit `references/knowledge/`, und weil die Historie nicht zum Abzug gehört, weist das Zählwerk sie als nicht mitgeliefert aus; der Export hat keine Historie, und die Prüfung über Wiki und Quellen kann vollständig sein;
- erzeugt seine `SKILL.md` aus der Vorlagendatei `assets/knowledge-skill/SKILL.template.md`, in der nur Name und Beschreibung ersetzt werden; sie weist den Agenten an, die Werkzeuge mit vollem Pfad aus dem eigenen Skill-Ordner aufzurufen und das Zählwerk nach festen Regeln zu lesen;
- bindet alle Inhalte über das ursprüngliche Release-Manifest;
- enthält keine absoluten Quellpfade, Tokens oder transienten Locks;
- wird als Skill-Ordner und `.skill`-Paket erzeugt.

Soll der Inhalt aktualisiert werden, wird das kanonische Wiki gepflegt und veröffentlicht. Danach wird ein neuer eingefrorener Skill-Abzug erstellt; der alte Export wird nicht direkt bearbeitet. Auffindbarkeitsfragen liegen außerhalb des Releases und kommen nie in einen Export.

**Skalare Aliase:** Neu exportierte Wissens-Skills lesen einen einzelnen Wert `aliases: Foo` als einen Alias, wie der Lese-Skill. Bereits installierte Exporte ignorieren ihn, bis sie neu exportiert werden. Für Wikis, die Aliase als Liste schreiben, ändert sich die Rangliste nicht.

**Verhaltensänderung der exportierten Suche:** Exporte vor der Einführung des gemeinsamen Suchkerns rankten mit einer eigenen, additiven Heuristik ohne BM25. Neu exportierte Wissens-Skills ranken wie der Lese-Skill; bereits installierte Exporte behalten ihr altes Verhalten, bis sie neu exportiert werden. Auf dem Test-Wiki des Präzisionstors fand die alte Heuristik knapp mehr: 49, 58 und 64 statt 47, 57 und 62 von 107 Fragen unter den ersten 3, 12 und 100, bei 17 statt 20 Top-3-Plätzen für Navigationsseiten und gleich vielen Treffern für fehlende Themen (16). Der Wechsel ist trotzdem gewollt: Es gibt nur noch eine Suche, die das Präzisionstor misst, und jede Verbesserung erreicht beide Skills.

### 4.17 Gestufte Orientierung

Ein einziger Wurzelindex muss jede Seite auflisten. Die Kosten, sich in einem Wiki zu orientieren, wachsen damit mit seiner Größe — und zwar **bevor** eine einzige Seite gelesen wurde. Jedes befüllte Unterverzeichnis unter `wiki/` trägt deshalb eine erzeugte `index.md` mit den Seiten seiner Gruppe.

Der Lese-Skill liest gestuft: Wurzelindex → passender Zweigindex → Seiten. Eine Seite gilt als aufgeführt, wenn der für sie zuständige Index sie nennt. Ein Wurzelindex, der weiterhin alles auflistet, bleibt gültig — bestehende Wikis brechen nicht.

**Diese Dateien werden erzeugt, nicht gepflegt.** Der Graphlauf schreibt sie, eine Handänderung überlebt den nächsten Lauf nicht, und der Linter meldet einen veralteten, fehlenden oder verwaisten Index genauso wie einen veralteten Graphen.

Das war eine bewusste Ausnahme: Es sind die ersten erzeugten Dateien in der kuratierten Schicht `wiki/`. Zwei Gründe geben den Ausschlag. `wiki/index.md` liegt bereits dort und ist bereits Navigation statt Wissen — ein Zweigindex erweitert also eine vorhandene Kategorie, statt eine neue zu schaffen. Und unter `graph/` erzeugt würden die Indizes nicht reduzieren, was der Lese-Skill als Markdown lädt; genau das war der Zweck.

Ein Index nennt nur, **was vom Normalfall abweicht**. Eine Beschreibung trägt jede Seite, gekappt auf 100 Zeichen. Der Status erscheint nur, wenn die Seite nicht `active` ist, die Vertrauensstufe nur, wenn eine Bestätigung vorliegt. `active` und `unverified` auf jeder Zeile zu wiederholen würde Tokens kosten, um nichts zu sagen — und die eine abgelöste oder tatsächlich geprüfte Seite unsichtbar machen.

**Der Gewinn ist bedingt, und das gehört gesagt.** Bei einer Handvoll Seiten in einer Gruppe kostet ein Zweigindex mehr als ein flacher Wurzelindex, weil er je Seite eine Beschreibung trägt. Zwei Eigenschaften gelten aber immer: Ein Wurzelindex, der auf Zweige verweist, wächst nicht mit der Seitenzahl. Und ein Zweigindex ist deutlich billiger als die Seiten, die er beschreibt — gemessen unter der Hälfte. Beides ist als Test festgehalten.

Die einzige Ausnahme ist die vollständige Prüfung vor einer Fehlanzeige: ein Aufruf mit `--exhaustive`, der alle Passagen im Helfer durchsucht und höchstens 100.000 Zeichen Treffer zurückgibt (Abschnitt 5.4). Der Agent öffnet dafür keine Indizes oder Seiten der Reihe nach.

### 4.18 Vertrauensstufen pro Seite

Ein Qualitätsreview hält fest, **wann** zuletzt jemand ins Wiki geschaut hat. Es kann nicht festhalten, **welche Seiten** dabei geprüft wurden. Deshalb tragen Seiten ihre Bestätigung selbst.

Vier optionale Frontmatter-Felder halten sie:

```yaml
generated_by: "agent/claude-opus-5"
generated_at: "2026-09-06T09:00:00Z"
verified_by: "human:mzi"
verified_at: "2026-09-06T10:00:00Z"
```

Ein Akteur ist `agent/<name>`, `human:<id>` oder `process:<id>`. Die Vertrauensstufe wird daraus **abgeleitet** und nie gespeichert:

| Bestätigung | Stufe |
|---|---|
| keine | `unverified` |
| nicht-menschlicher Akteur | `machine-confirmed` |
| menschlicher Akteur | `human-reviewed` |

Nicht auswertbares Frontmatter zählt als keine Bestätigung. Eine fehlerhafte Angabe kann eine Stufe also niemals anheben.

Das Aufzeichnen läuft als hash-gebundene Plan/Apply-Transaktion mit automatischem Snapshot und null Schreibvorgängen bei veraltetem Plan. Ein `human:`-Akteur verlangt zusätzlich eine ausdrückliche Bestätigung: **Ein Agent kann seine eigene Arbeit nicht als von einem Menschen gelesen markieren.** Ein Index trägt keine Aussagen und kann nicht bestätigt werden.

Eine Vertrauensstufe sagt, wer wann geprüft hat. Sie sagt **nicht**, dass eine Seite richtig, vollständig oder aktuell ist, und sie ersetzt keine Belege. Eine gut belegte, ungeprüfte Seite kann die bessere Antwort tragen als eine geprüfte mit schwachen Quellen. Die Verteilung steht im veröffentlichten Qualitätsstatus, sodass der Lese-Skill sagen kann, wie viel eines Wikis eine Prüfung tatsächlich abgedeckt hat.

### 4.19 Synchronisierte Ablagen und Konfliktkopien

Ein OneDrive- oder SharePoint-Client ist ein **Schreiber auf dem Wiki-Verzeichnis**, nicht nur ein Transportweg. Er legt eigenständig Dateien an und verzögert Schreibvorgänge unbestimmt. Der Skill kennt drei Klassen:

- **Konfliktkopie:** Der Client führt niemals zusammen. Haben zwei Geräte dieselbe Datei geändert, bleiben beide erhalten und eine wird nach dem Gerät umbenannt. Das Lesen stoppt, denn die Kopie kann Arbeit enthalten, die sonst niemand hat. Die Auflösung läuft über Plan/Apply: Der Plan stellt beide Seiten mit Hash, Größe und Änderungszeit gegenüber, eine inhaltsgleiche Kopie wird zum Entfernen empfohlen, eine abweichende bleibt Entscheidung des Anwenders. Vor dem Anwenden entsteht ein Snapshot. **Ohne Bestätigung wird nie gelöscht.**
- **Betriebssystemartefakt** wie `.DS_Store`, `Thumbs.db`, `desktop.ini` oder `~$`-Dateien: trägt keinen Inhalt. Es wird gemeldet und ansonsten ignoriert — es blockiert keinen Leser, lässt keinen Lint scheitern und gelangt nie in ein Release-Manifest. Ein Blick in `sources/` im Finder darf ein Wiki nicht stilllegen.
- **Gesperrter Name oder Zeichen:** Namen wie `.lock`, `CON`, `AUX`, `NUL`, `COM0`–`COM9`, `LPT0`–`LPT9`, `_vti_` an beliebiger Stelle, die Zeichen `" * : < > ? / \ |`, führende und schließende Leerzeichen sowie ein schließender Punkt. Das sind Lint-Fehler, weil solche Dateien die Ablage stillschweigend nie erreichen. `desktop.ini` und `~$`-Namen verweigert die Ablage ebenfalls, sie gelten hier aber als das, was sie sind — Betriebssystemartefakte — und bleiben ignorierbar: Sie tragen keinen Inhalt, also kostet die Verweigerung auch nichts. Die Artefaktregel wird zuerst geprüft und ist für diese Namen die einzige.

Zusätzlich geprüft werden Pfade, die sich nur in der Groß-/Kleinschreibung unterscheiden — SharePoint kann beide nicht gleichzeitig halten. Trägt `schema/WIKI_PROFILE.md` einen `storage_path_prefix`, wird außerdem die 400-Zeichen-Grenze als Fehler und die Windows-Grenze von 260 Zeichen als Warnung geprüft.

Die Erkennung synchronisierter Ablagen ist eine **Heuristik** auf sichtbaren Pfadnamen und den Umgebungsvariablen des Clients. Es gibt keine unterstützte Schnittstelle, um den Zustand eines Sync-Clients abzufragen. Der Skill stellt sie deshalb nie als Tatsache dar.

### 4.20 Ehrliche Persistenzmeldung

`fsync` macht einen Schreibvorgang auf **dieser Platte** dauerhaft — nicht hochgeladen. Auf einer offenbar synchronisierten Ablage meldet ein erfolgreicher Release seinen entfernten Zustand als `unconfirmed` und weist darauf hin, anderen die Verfügbarkeit erst zuzusagen, wenn der Client den Ordner als vollständig synchronisiert zeigt.

### 4.21 Open Knowledge Format v0.2: der Weg nach draußen

Der OKF-Export ist ein **eigenständiges Ziel** dieser Distribution, keine Kompatibilitätsnotiz. Ein Wissensraum, aus dem man sein Wissen nicht wieder herausbekommt, ist eine Falle — auch dann, wenn er intern noch so sauber gebaut ist. Deshalb kann jeder verifizierte Release als Bündel im Open Knowledge Format v0.2 ausgegeben werden, dem herstellerneutralen Markdown-Standard von Google Cloud.

**Was ein Bündel enthält.**

```text
<ziel>/
|-- index.md        Wurzelindex; trägt laut Spezifikation nur okf_version
|-- log.md          reserviertes Änderungsjournal aus meta/changes.md
|-- README.md       was dieses Bündel ist und was es nicht ist
|-- overview.md     Wissensseiten als OKF-Konzepte
|-- concepts/
|-- entities/
|-- topics/
|-- comparisons/
`-- sources/        registrierte Extraktionen als type: Source
```

Das Bündel ist **standardmäßig selbsttragend**: Die registrierten Quellenextraktionen wandern mit. Ein Bündel, dessen Konzepte auf Quellen verweisen, die es nicht enthält, hat seine Belegkette in dem Moment verloren, in dem es den Rechner verlässt. Wer bewusst nur die Konzepte will, kann die Quellen abwählen.

**Was abgebildet wird.**

| SkillSafeWerkstatt | OKF v0.2 | Anmerkung |
|---|---|---|
| `type`, `title`, `description`, `tags` | gleichnamig | direkt |
| `status: active` | `status: stable` | Abbildung |
| `status: superseded` | `status: deprecated` | Abbildung |
| `status: disputed` | `status: draft` | **verlustbehaftet**, wird im Bündel protokolliert |
| Quelle mit `status: partial` | `status: draft` | **verlustbehaftet**, wird protokolliert |
| `generated_by` + `generated_at` | `generated: { by, at }` | flach gespeichert, beim Export verschachtelt |
| `verified_by` + `verified_at` | `verified: { by, at }` | ebenso |
| registrierte Quellen | `sources: [{id, title, resource}]` | angereichert aus dem Quellenregister |
| Wikilinks | bündelrelative Markdown-Links | umgeschrieben |
| Claim-Text | gewöhnlicher Fließtext | Aussage bleibt, Marker fällt weg |

**Was nicht mitkommt.** Der Export ist konstruktionsbedingt ärmer als das Wiki, und das Bündel sagt das selbst in seiner `README.md`: Claim-Blöcke mit ihren `source_id@locator`-Belegen, das Release-Manifest und seine Hash-Grenze, Snapshots, `SOUL.md`, kontrollierte Begriffswelten, Cluster und Graph sowie die strenge Frontmatter-Teilmenge. Ein OKF-Konsument muss laut Spezifikation unbekannte Schlüssel und gebrochene Querverweise akzeptieren — das ist bewusst permissiver als dieses Wiki.

**Wie der Export sich selbst prüft.** Nach dem Schreiben validiert der Export das erzeugte Bündel gegen die Konformitätsregeln: Wurzelindex mit `okf_version` und sonst nichts, jede nicht reservierte Markdown-Datei mit lesbarem Frontmatter und nicht leerem `type`. Scheitert diese Prüfung, wird das Bündel entfernt und kein Erfolg gemeldet.

Bemerkenswert dabei: Die Prüfung kann **nicht** mit dem Frontmatter-Parser des Wikis erfolgen. Der lehnt verschachtelte Strukturen bewusst ab — genau die, die OKF für `generated`, `verified` und `sources` verlangt. Der Export bringt deshalb einen eigenen Leser für die OKF-Teilmenge mit. Das ist keine Doppelung, sondern die ehrliche Konsequenz aus zwei unterschiedlich strengen Formaten.

**Was nie erfunden wird.** Fehlt ein empfohlenes Feld im Wiki, bleibt es im Bündel leer und wird in der `README.md` als nicht füllbar aufgeführt. Für eine kuratierte Wissensseite existiert etwa keine `resource`-URI; der Export konstruiert dafür keine.

**Der Bericht.** Unabhängig vom Export bewertet ein reiner Bericht die Kompatibilität: Pflichtfeld `type`, empfohlene `title`, `description`, `resource` und `tags` sowie die v0.2-Ergänzungen `status`, `stale_after`, `generated` und `verified`. Er verändert nichts und schlägt nur vor.

### 4.22 Ablaufdatum pro Seite

Das Wiki regelt Frische bisher **wiki-weit**: Wie oft jemand hinschauen soll, wie oft aufgeräumt wird. Das ist das richtige Instrument für einen Prüfrhythmus und das falsche für eine Seite, deren Inhalt ein echtes Enddatum hat — eine Preisliste bis Jahresende, ein Zertifikat, eine Regelung, die an einem bekannten Tag abgelöst wird.

Dafür gibt es das optionale Feld `stale_after`, ein ISO-Datum oder ein ISO-8601-Zeitpunkt, übernommen aus OKF v0.2. Es ist optional und bleibt es: Das meiste Wissen hat kein Ablaufdatum, und eines zu erfinden wäre schlechter, als keines zu haben. Ein unlesbarer Wert lässt den Linter fehlschlagen, statt die Seite still ablaufen zu lassen.

Entscheidend ist, was ein überschrittenes Datum **nicht** ist:

> Ein abgelaufenes `stale_after` ist eine **Offenlegung, kein Urteil**. Es sagt, dass die Seite ein Enddatum genannt hat und dieses vorbei ist. Es sagt nicht, dass der Inhalt falsch ist.

Deshalb filtert nichts eine abgelaufene Seite heraus — nicht der Release, nicht der Index, nicht die Suche, nicht die Antwort. Eine abgelöste Regelung ist häufig genau das, wonach jemand gefragt hat. Der Linter zählt Seiten mit und über ihrem Ablaufdatum, der Release veröffentlicht diese Zahlen im Qualitätsstatus, die Suche markiert betroffene Treffer, und der Lese-Skill benennt es in der Antwort. Gelöscht, versteckt oder umgeschrieben wird deswegen nie etwas.

### 4.23 Beobachtungen als Quellen

Nicht jeder Beleg ist ein Dokument. Eine Entscheidung in einer Besprechung, das Ergebnis eines Laufs, etwas, das der Anwender während der Arbeit festgestellt hat: Solches Wissen entsteht ohne PDF, und ohne einen Weg hinein bekommt die Belegkette an genau dieser Stelle eine Lücke — oder das Wissen landet unbelegt auf einer Seite.

`--source-type observation` registriert es als vollwertige Quelle. Zwei zusätzliche Felder sind dabei **Pflicht**, und die Registrierung verweigert ohne sie:

| Feld | Bedeutung | Notation |
|---|---|---|
| `observed_by` | Wer hat es beobachtet | `human:<id>`, `agent/<name>`, `process:<id>` |
| `occasion` | Was es hervorgebracht hat | Freitext, z. B. „Architekturrunde 2026-09-06" |

Beide Felder gehören ausschließlich zu Beobachtungen; wer sie an einer anderen Quellenart mitgibt, bekommt einen Fehler statt stiller Ignoranz. Der Linter prüft die Registrierung gegen dieselbe Regel.

Eine Beobachtung ist damit **gewöhnliche Evidenz, keine Abkürzung an ihr vorbei**. Sie trägt eine eigene ID, ein eigenes Markdown-Extrakt und einen eigenen Hash, und eine Seite zitiert sie wie ein PDF. Was sie nicht ist: eine Erlaubnis, aufzuschreiben, was ein Agent glaubt. Sie wird registriert, weil ein benannter Akteur bei einem benannten Anlass etwas festgestellt hat. Lässt sich niemand benennen, gibt es keine Beobachtung zu registrieren.

### 4.24 Übernahme einer bestehenden Sammlung

Wer bereits einen Obsidian-Vault, einen Dokumentationsordner oder ein älteres Wiki pflegt, soll dieses Material nicht Datei für Datei von Hand nachtragen müssen. `adopt_directory.py` übernimmt es als Plan/Apply-Transaktion aus einem Verzeichnis, das außerhalb des Wikis liegen muss.

Der heikle Punkt daran ist offensichtlich: Ein Massenimport ist genau die Form von Fehler, gegen die dieses Wiki gebaut ist — Inhalt unter `wiki/`, hinter dem nichts steht. Die Übernahme löst das, indem sie **Belege importiert, kein Wissen**:

- Jede angenommene Datei wird als Quelle vom Typ `adopted` registriert — durch denselben Registrierungs-Helfer wie jede handgepflegte Quelle, mit eigener ID, eigenem Hash und portabler Referenz.
- Unter `wiki/` entsteht dabei **nichts**. Keine Seite, keine Behauptung.
- Daraus Seiten zu machen, bleibt Kuration wie bisher: mit Claims, mit `source_id@locator`.

Der Plan liest nur. Er nennt zu jeder `*.md`-Datei den Titel, den das Dokument selbst trägt (Frontmatter, dann erste Überschrift, dann Dateiname), Hash, Größe, Blocker und Hinweise. Blockiert sind leere und unlesbare Dateien, Symlinks, Betriebssystem-Artefakte sowie Inhalte, die byte-identisch bereits registriert sind. Hinweise nennen einen für OneDrive oder SharePoint problematischen Originalnamen und Frontmatter außerhalb der Teilmenge des Wikis, das nicht übernommen wird. Nicht-Markdown-Dateien werden als übersprungen ausgewiesen, statt stillschweigend zu verschwinden.

Das Anwenden nimmt nur Pfade an, die im bestätigten Plan stehen und übernehmbar sind, prüft vor dem ersten Schreiben jeden Hash erneut und verweigert bei Abweichung die **gesamte** Auswahl — eine Drift wendet nie zur Hälfte an. Ein Snapshot geht dem ersten Schreibvorgang voraus.

### 4.25 Selbstbeschreibender Aktionskatalog

Der Skill kann seine vollständige Funktionsoberfläche maschinenlesbar beschreiben. Der Katalog weist pro Aktion unter anderem aus:

- Parameter;
- lesend oder schreibend;
- destruktiv oder nicht destruktiv;
- Vorschau-Unterstützung;
- Snapshot-Verhalten;
- Bestätigungspflicht;
- Lock-Pflicht;
- verfügbare Filteroperatoren.

Der Katalog beschreibt Fähigkeiten, erteilt aber keine Berechtigung. Bestätigungs- und Sicherheitsregeln bleiben unverändert.

### 4.26 Quellenabdeckung und Auffindbarkeitsfragen

**Quellenabdeckung.** Was nie in einen Claim überführt wurde, findet die Wiki-Suche nie. Der Lint zählt deshalb unter `stats.source_coverage`, welche registrierten Quellen und welche ihrer Einheiten kein aktiver oder strittiger Claim zitiert. Einheiten sind Seiten oder Folien, wenn die Extraktion Marken hat, sonst Abschnitte (je Überschrift), sonst das ganze Dokument. Der eigene Text einer Titelüberschrift, die alle Abschnitte umspannt, ist keine Einheit, weil nur ein breiter Beleg ihn nennen könnte. Ein Locator, der eine mehrseitige Quelle als Ganzes nennt (`document` oder die Titelüberschrift), zählt als breiter Beleg und deckt keine Einheit ab. Bewertet werden Quellen mit Status `active` oder `partial`. Die Liste nennt zuerst ganz unzitierte Quellen, dann teilweise zitierte, höchstens 50, je höchstens 20 Einheiten; aufeinanderfolgende Seiten erscheinen als Bereich (`page=4-9`). Für den Vergleich vor dem Release führt die Statistik jede zitierte Quelle mit ihren Zahlen. Das ist eine Statistik für den Pfleger, keine Warnung. Hintergrundmaterial oder eine frisch übernommene Sammlung bleibt zu Recht unzitiert, und eine Warnung, die sich nie abstellen lässt, stumpft ab. Die Statistik blockiert keinen Release. Sie steht in der Release-Ausgabe, nie in `quality-status.json` oder in der Qualitätszeile für Leser. Vor dem Release vergleicht der Skill sie mit der Ausgangsprüfung, legt neu unzitierte Quellen dem Anwender vor und hält dessen Entscheidung in `meta/changes.md` fest. Auf dem Test-Wiki meldet sie 2 unzitierte Quellen und eine unzitierte Seite einer dritten; dort liegen 7 der 8 Fakten, die nur in Quellen stehen. Der achte steht auf einer Seite, die ein anderer Claim zitiert: Die Abdeckung ist nur so fein wie die Locator.

**Auffindbarkeitsfragen (optional).** Ob die Wörter echter Nutzer einen Fakt noch erreichen, misst eine kleine Sammlung von höchstens 200 Fragen in `meta/findability-questions.jsonl`. Der Skill nimmt eine Frage nur auf, wenn Eigentümer oder Nutzer sie wörtlich geliefert haben, nie vom Agenten formuliert: Fragen, die der Agent mit offener Seite schreibt, bestehen immer. Prüfen kann das Werkzeug diese Zusicherung nicht. Jede Frage zielt auf einen Claim, nicht nur auf eine Seite; sonst bliebe sie grün, nachdem der Fakt gelöscht wurde. Der Skill nimmt eine Frage nur mit bestätigtem Ziel-Claim auf, übernimmt Tippfehler und Umgangssprache unverändert, übernimmt aus einer längeren Nachricht nur ganze Sätze und speichert als Autor nur die Rolle (`owner` oder `user`). Den Wortlaut bekommt das Werkzeug über die Standardeingabe; ein echtes „?“ direkt vor einem Buchstaben („kündigen?danke“) schickt der Agent als `\u003f`, sonst hält die Prüfung es für ein unterwegs beschädigtes Zeichen. `findability_questions.py check` stellt jede Frage mit dem Suchkern des Lese-Skills auf den Arbeitsdateien und meldet, ob ihr Claim unter den ersten 12 Treffern zurückkommt. Möglich sind `found`, `found_page_only`, `not_found`, `target_missing` und `target_inactive`. Vor dem Release vergleicht der Skill mit der Ausgangsprüfung und legt verlorene Fragen dem Anwender vor; blockieren kann eine Frage den Release nicht. Die Datei liegt im Wiki-Ordner, aber außerhalb der Release-Grenze: Sie wird nicht gehasht, nicht verifiziert, nicht in den Standard-Snapshot aufgenommen und nie exportiert, und der Lese-Skill liest sie nicht. Vertraulich ist sie damit nicht: Wer den Wiki-Ordner lesen kann, kann auch sie lesen.

## 5. Der Lese-Skill `query-llm-wiki`

Der Lese-Skill ist technisch und fachlich read-only. Er verändert weder Wiki-Dateien noch Reviews, Sperren, Graphen oder Release-Daten.

### 5.1 Integritätsprüfung vor und nach jeder Antwort

Zu Beginn einer Anfrage prüft der Skill:

- ob die Pflichtstruktur vorhanden ist;
- ob kein Pflege-Lock aktiv ist;
- ob `meta/manifest.json` ein gültiges Release beschreibt;
- ob Größen und Hashes aller veröffentlichten Dateien übereinstimmen.

Er merkt sich den Hash des Manifests und prüft ihn direkt vor der Antwort erneut.

Mögliche Zustände sind:

- `ready`: Der Release ist stabil und kann gelesen werden.
- `wiki_busy`: Eine Pflege besitzt den Lock; es wird kein möglicher Mischstand gelesen.
- `snapshot_changed`: Der Stand hat sich während der Anfrage geändert; der Entwurf wird verworfen.
- `invalid_wiki`: Release oder Dateien sind nicht verifizierbar; daraus wird keine Sachantwort erzeugt. Hierher gehört auch eine Datei mit einem Namen, den die Ablage verweigert (etwa `wiki/.lock` oder `wiki/CON.md`): Sie liegt lokal vor, erreicht die Ablage aber nie — dieser Stand ist also nicht der, den ein anderes Gerät sieht. Die Meldung nennt Pfad und Grund.
- `sync_artifacts_present`: Der Sync-Client hat eine Konfliktkopie neben einer veröffentlichten Datei behalten. Der Release selbst ist intakt, aber zwei Geräte halten verschiedene Inhalte. Der Pflege-Skill löst das auf.
- `sync_in_progress`: Das Manifest ist neuer als die Dateien, die es beschreibt. Das ist eine laufende Übertragung, keine Beschädigung — Warten hilft, Reparieren nicht.
- `hydration_required`: Veröffentlichte Dateien haben keinen lokalen Inhalt, weil die Ablage sie in der Cloud hält. Sie zu prüfen würde das Wiki herunterladen und schlägt offline fehl. Der Skill meldet Anzahl und geschätztes Volumen und fragt, statt den Download zu starten.

Diese Trennung ist der Kern: Eine Speicherbedingung, die Warten oder ein Pflegelauf behebt, wird nicht als beschädigtes Wiki gemeldet — und umgekehrt.

### 5.2 Qualitätsstatus

Nach erfolgreicher Integritätsprüfung bewertet der Skill getrennt:

- technische Lint-Gültigkeit;
- Alter und Ergebnis des semantischen Qualitätsreviews;
- Alter und Ergebnis des optionalen Cleaning-Reviews;
- Zahl offener Fragen;
- Alter des veröffentlichten oder eingefrorenen Stands.

`current`, `due-soon`, `overdue`, `attention-needed` und `unknown` sind Hinweise. Sie machen einen technisch gültigen Release nicht automatisch unbrauchbar. Jede Antwort endet mit einer kurzen Qualitätszeile, beispielsweise `Wiki-Qualität: aktuell` oder `Wiki-Qualität: Prüfung überfällig; Pflege-Skill empfohlen.`

Zusätzlich nennt der Lese-Skill die **Vertrauensstufe der tragenden Seiten**, sobald sie nicht `human-reviewed` ist. Ein wiki-weites Review sagt, wann jemand geschaut hat; die Stufe sagt, ob diese konkrete Seite dabei war. Der Skill weist außerdem darauf hin, wenn keine einzige Seite eine menschliche Prüfung trägt.

Der Lese-Skill führt niemals selbst ein Review, Cleaning oder eine Korrektur aus.

### 5.3 Antwortverhalten und Vertrauensgrenzen

Der Lese-Skill beachtet folgende Priorität:

1. System-, Sicherheits- und Host-Vorgaben;
2. die aktuelle Anfrage des Anwenders;
3. die Wurzeldatei `SOUL.md` des ausgewählten Wikis;
4. den eingebauten neutralen Antwortvertrag.

Nur die Wurzeldatei `SOUL.md` ist eine Wiki-interne Vorgabe für die Antwortdarstellung. Inhalte in `sources/`, `wiki/`, Zitaten oder Anhängen sind Belege, keine Agentenanweisungen.

Fehlt `SOUL.md`, antwortet der Skill standardmäßig in der Sprache des Anwenders, mit passender Anrede, neutralem Ton, mittlerer Ausführlichkeit und nachvollziehbaren Quellenangaben.

### 5.4 Suche und Evidenzkette

Die Suche läuft in mehreren Ebenen:

1. `wiki/index.md` und gepflegte Seiten dienen der Orientierung.
2. Nur bestätigte Begriffswelten erweitern eine Anfrage um andere Wörter: um ihre bevorzugten Bezeichnungen und Aliase. Formen desselben Wortes (Flexion, Umlaut-Schreibung, Bindestrich) zählen als Treffer dieses Wortes. Kompositumteile und Tippfehlerkorrekturen um einen Buchstaben sind ausgewiesene Heuristiken. Umformulierungen des Agenten stehen in der Antwort.
3. Relevante Seiten und vollständige Claim-Blöcke werden gelesen.
4. Jeder materielle Claim wird über `source_id@locator` zur registrierten Markdown-Quelle verfolgt.
5. Bei exakten Formulierungen wird die entsprechende Quellenstelle gelesen.
6. Offene Fragen und Konflikte werden berücksichtigt.
7. Historie wird nur bei historischen, abgelösten oder zeitlichen Fragestellungen einbezogen.

Der Skill unterscheidet in der Antwort zwischen belegter Tatsache, gepflegter Synthese, Schlussfolgerung und offener Frage. Wenn das Wiki die Antwort nicht trägt, benennt er die Lücke statt sie aus allgemeinem Wissen zu füllen.

Gerankt wird mit BM25F über Titel, Aliase, Überschriften, Beschreibung und Text. Standardmäßig kommen 12 Treffer zurück, mit `--limit` bis zu 100. Ranking, Claims, Ausschnitte und Zählwerk stammen aus einem gemeinsamen Suchkern (`search_core.py` mit `bm25.py` und `wordforms.py`). Er liegt byte-identisch in beiden Skills, und der Exporter kopiert ihn in jeden eingefrorenen Wissens-Skill. `search_wiki.py` ist nur noch die Befehlszeilenhülle, die den Release vor und nach der Suche prüft. Mit `--expect-manifest-sha256` bindet sich jede Suche an den zu Beginn verifizierten Release; ein anderer Stand meldet `snapshot_changed`, sodass eine Antwort nicht unbemerkt zwei Releases mischt.

**Wortformen.** Eine Suche nach „Tarife" findet auch eine Seite, auf der nur „Tarif" steht. Dafür wird jedes Suchwort zu einer Gruppe von Wörtern, die in den durchsuchten Dateien wirklich vorkommen. Jedes Mitglied der Gruppe trägt eine Regel und ein Gewicht. Das Wort selbst zählt voll (1,0), jede andere Regel weniger. Die Gruppe entsteht bei jeder Suche neu im Speicher; es wird kein Index und keine Datei geschrieben. Die Regeln, in vier Stufen:

1. **Schreibung** (`fold`, 0,9): „Kuendigung" und „Kündigung", „E-Mail" und „EMail" sind dasselbe Wort; ß und ss sind es schon immer. Weiche Trennzeichen, unsichtbare Zeichen und Trennstriche am Zeilenende werden vorher repariert, sodass „Kündi-" und „gung" auf zwei Zeilen wieder „Kündigung" ergeben. Ebenso liest die Suche HTML-Zeichenreferenzen als die Zeichen, für die sie stehen („K&uuml;ndigung" und „K&#252;ndigung" sind „Kündigung", „&shy;" ist ein weiches Trennzeichen, „&nbsp;" ein Leerzeichen), zieht ein Tiefgestelltes an das Wort heran („CO~2~" und „CO<sub>2</sub>", wie Pandoc ein tiefgestelltes Zeichen aus Word schreibt, sind wie „CO₂" „CO2") und entfernt eine Hervorhebung mitten im Wort („**Kündigungs**frist" ist „Kündigungsfrist"; „Kund*innen und Kolleg*innen" bleibt, wie es ist). Ein Hochgestelltes in Markdown („m^2^", „m<sup>2</sup>") zählt getrennt und zusammengeschrieben („m", „2" und „m2"), sodass eine Fußnotenziffer das Wort nicht verdeckt und „m²" trotzdem trifft. Zahlen bringt die Suche vorher in eine Schreibweise: Tausendertrennzeichen (Punkt, Leerzeichen, geschütztes oder schmales Leerzeichen, Apostroph) fallen weg, wenn jede weitere Gruppe genau drei Ziffern hat, und eine direkt angehängte Einheit aus mindestens zwei Buchstaben wird abgetrennt; „2.500 kWh", „2 500 kWh" und „2500kWh" sind so alle „2500 kWh", in der Frage wie auf der Seite. Ein Dezimalkomma („2,50") und ein Datum („31.12.2025") bleiben, wie sie sind, und ein einzelner Buchstabe bleibt an der Zahl („§ 14a", „800W"). Die Stoppwortliste wird wie die Suchwörter geschrieben verglichen, „für" fällt also wieder weg. Funktionswörter (Artikel, Pronomen, Präpositionen, Konjunktionen, Hilfs- und Modalverben, Fragewörter, „nicht") treffen nur wörtlich.
2. **Flexion** (`stem`, 0,6, und `verb`, 0,5): „Netzentgelten" findet „Netzentgelt", „widerruft" findet „Widerruf". Abgeschnitten wird höchstens eine Endung, nie eine Ableitung wie „-ung", und bei Substantiven nie „-er": „Zähler" ist nicht „zahlen", und „Hersteller", „Herstellers" und „Herstellern" finden einander, aber nicht „herstellen". Die Verbendung „-et" zählt nur, wo das Deutsche das e schreibt („meldet", „rechnet"), deshalb sind „Planet", „Market" und „Internet" keine Verbformen. Eine Verbform auf „-t" aus dem Wiki gilt nur für ein Suchwort, das selbst ein Verb sein kann (Infinitiv auf „-n" oder der bloße Stamm): „ändert" passt zu „ändern", nicht zu „andere".
3. **Kompositumteile** (`compound_head`, 0,45, `compound_modifier`, 0,35, `query_part`, 0,35): „Gebühr" findet „Durchleitungsgebühr", „Vertrag" findet „Vertragslaufzeit", aber nur, wenn der Rest des Wortes selbst aus Wörtern des Wikis besteht. Jeder Teil braucht mindestens vier Buchstaben: „Gas" findet „Gastarif" im Ranking nicht; die vollständige Prüfung findet ein Wort aus zwei oder drei Buchstaben als ausgewiesene Heuristik `short_part`. Ein Suchwort, das nirgends vorkommt, wird höchstens an seinem Kopf zerlegt, also am längsten hinteren Teil, dessen Rest aus Wörtern des Wikis besteht: „Wärmepumpenstromtarif" sucht dann „Stromtarif", nie „Wärmepumpe" allein. Wörter mit mehr als 64 Buchstaben zerlegt die Suche gar nicht; eine endlose Buchstabenkette kann sie so weder abstürzen lassen noch ausbremsen.
4. **Tippfehler** (`typo`, 0,3): Ein Suchwort ab 8 Buchstaben, das nach allen anderen Regeln nichts trifft, findet Wörter, die genau eine Änderung entfernt sind („Netzentgeld" findet „Netzentgelt"). Steht das Suchwort selbst oder eine seiner Wortformen in den nicht durchsuchten Quellen, wird es nicht korrigiert: Ein Wort, das es im Release gibt, ist kein Tippfehler. „verjähren" wird dann nicht zu „Verfahren", sondern landet in `terms_only_in_unsearched.sources`.

Schreibung und Flexion sind Formen desselben Wortes. Kompositumteile und Tippfehler sind ausgewiesene Heuristiken: Sie machen ein Wort nie häufiger, als seine Formen es machen, es sei denn, es gibt im Wiki gar keine Form des Wortes; dann bestimmen sie seine Seltenheit. Auf einer Seite kommen sie zu den Formen hinzu, und ihr Gewicht wirkt erst nach der BM25-Sättigung, sodass ein Kompositumteil im Titel nur 35 bis 45 Prozent eines exakten Titeltreffers erreicht. Den Phrasenbonus gibt es nur für die wörtlichen Suchwörter auf ganzen Wortgrenzen. Link-Ziele werden nie an Bindestrichen zerlegt, und bei einem Link mit Beschriftung zählt nur die Beschriftung. Auf Navigationsseiten zählt nur das Wort selbst, in der Rangliste wie in `match_rules` und in den Dateizahlen unter `forms`. Begriffswelten werden nur über das Wort selbst, seine Schreibung (`fold`) und seine Flexionsendung (`stem`) ausgelöst, nie über Verbformen, Kompositumteile oder Tippfehler: „Widerrufe" löst eine Begriffswelt mit dem Alias „Widerruf" aus, „widerruft" nicht.

Was die Schicht nicht kann: Synonyme, Umschreibungen, andere Sprachen und unregelmäßige Formen. „Ökostrom" findet „Grünstrom" nicht, „grid fee" findet „Netzentgelt" nicht, und „umgezogene" findet „Umzug" nicht. Auch Plurale auf „-er" („Häuser" zu „Haus", „Kinder" zu „Kind") und die Formen von Wörtern mit einem Stamm unter vier Buchstaben („Tag", „Tage", „Tagen"; „Rate", „Raten") findet das Ranking nicht, weil die Flexionsregel bei Substantiven „-er" nie abschneidet und mindestens vier Buchstaben stehen lässt; die vollständige Prüfung findet sie als ausgewiesene Heuristik `ending`. Ebenso wenig findet das Ranking Plurale auf „-s" nach einem Vokal, auf „-se" und auf „-nen" („Autos", „Ergebnisse", „Kundinnen") und die Kasusendungen „-er" und „-em" eines Adjektivs ohne Adjektivsuffix („intelligentem" zu „intelligenten", „fester" zu „festen"); die vollständige Prüfung findet sie als `ending`. Auch die Verbformen eines regelmäßigen Verbs mit vierbuchstabigem Stamm („senkt" und „senken", „zahlt" und „zahlen") findet das Ranking nicht, weil die Verbregel mindestens fünf Buchstaben stehen lässt, und ebenso wenig Partizip und zu-Infinitiv eines trennbaren Verbs („abgeschaltet" und „abzuschalten" zu „abschalten"), weil sie „ge-" nur am Wortanfang erkennt; die vollständige Prüfung findet beides als ausgewiesene Heuristik `verb_ending`. Eine Zahl in Worten oder in einer anderen Einheit („2,5 MWh" für „2500 kWh") findet keine der beiden. Dafür bleiben Seiten-Aliase, Begriffswelten und Umformulierungen durch den Agenten zuständig. Auch eine Tippfehlerkorrektur kann danebenliegen: Unter 130 korrekten, im Test-Wiki fehlenden Wörtern ab 8 Buchstaben wurden 3 falsch korrigiert, etwa „Abmeldung" zu „Anmeldung". Deshalb nennt jeder Treffer seine Regel, und der Agent prüft vor dem Zitieren, ob ein nur über Kompositumteil oder Tippfehler gefundener Treffer wirklich das gefragte Wort meint.

Gemessen auf dem Test-Wiki des Präzisionstors (107 beantwortbare Fragen) stieg die Zahl der Fragen mit einer Pflichtseite auf Rang 1 von 41 auf 56. Vollständig gefunden wurden unter den ersten 3 nun 64 statt 47 Fragen, unter den ersten 12 74 statt 57 und unter den ersten 100 84 statt 62. Je Kategorie unter den ersten 12: Flexion 8 statt 3 von 8, Komposita 6 statt 4 von 8, Tippfehler 6 statt 1 von 8, Umlaut-Schreibung 7 statt 6 von 7. Der Preis: Die sieben Fragen zu Themen, die das Wiki nicht enthält, liefern unter den ersten 12 zusammen 31 statt 16 Treffer, unter den ersten 100 41 statt 16. Navigationsseiten belegen 13 statt 20 Top-3-Plätze. Von 124 Pflichtseiten rückten 43 vor, 4 fielen zurück und 77 blieben, wo sie waren. Nur eine verlor dabei einen Platz unter den ersten 3 (br-05, Rang 3 auf 4); sie steht mit Begründung in `accepted_regressions`. Die drei anderen blieben in ihren Bändern: in-05 von Rang 5 auf 10, pa-07 von 15 auf 21, sh-06 von 8 auf 10. Eine Suche dauerte auf dem Test-Wiki im Mittel 47 statt 34 Millisekunden, auf einer 500-Seiten-Kopie 413 statt 341 und mit 7,7 MB Quell-Markdown 1,03 statt 0,91 Sekunden.

**Umformulierungen in einem Aufruf.** Die Suche ist lexikalisch; Synonyme, Umschreibungen und andere Sprachen steuert der Agent bei. Mit `--also` (bis zu viermal, je höchstens 200 Zeichen) oder `--request -` (ein JSON-Objekt `{"query", "also", "filter"}` über die Standardeingabe) sucht ein Aufruf die Frage und bis zu vier Umformulierungen in einem Prozess, über einen verifizierten Release und einen einmal eingelesenen Korpus. `results` bleibt genau die Rangliste der Frage; jeder Treffer nennt in `found_by`, welche Suche ihn auf welchem Rang fand. Seiten, die nur Umformulierungen innerhalb des Limits fanden, stehen getrennt in `reformulation_results`, reihum nach Rang gezogen, ohne Navigationsseiten, mit eigenem Limit. Der Agent bestätigt sie auf der Seite, bevor er sie verwendet, nennt jede Umformulierung in der Antwort, und eine Seite aus diesem Block allein hebt eine Fehlanzeige nie auf. Gleiche (nach Groß-/Kleinschreibung, Akzenten, Satzzeichen) und leere Umformulierungen werden nicht gesucht und in `dropped_formulations` genannt.

Reihum heißt: erst Rang 1 jeder Umformulierung, dann Rang 2 und so weiter. Scores verschiedener Suchen sind nicht vergleichbar, Ränge schon. Eine Seite, die die Frage schon unter ihren Treffern hat, kommt nicht noch einmal; `found_by` zeigt dann, dass auch Umformulierungen sie fanden. Ungültige Eingaben lehnt die Hülle ab, bevor sie das Wiki anfasst: mehr als vier Umformulierungen, eine über 200 Zeichen, unbekannte Schlüssel, doppelte Schlüssel, kein UTF-8, ein einzelnes Surrogat-Escape, unterwegs umkodierter Text (Abschnitt 9). Dann steht nichts auf der Standardausgabe, eine Zeile auf der Fehlerausgabe, und der Exit-Code ist 1. Ein Wert, der mit `-` beginnt, wird als `--also=<Wert>` übergeben.

Gemessen auf dem Test-Wiki mit zwei Sätzen von Umformulierungen, die Agenten blind geschrieben haben (sie kannten nur die Fragen, nie das Wiki, je bis zu vier pro Frage): Die Rangliste und das Zählwerk der Frage blieben in allen 228 Läufen unverändert. Als vollständig gefunden zählt eine Frage, wenn jede Pflichtseite unter den ersten N Treffern der Frage oder unter den ersten N Einträgen von `reformulation_results` steht. Diese Sicht umfasst bis zu 2N Seiten, im Mittel 5,3 bei N = 3 und rund 16 bei N = 12; der Vergleichswert ohne Umformulierungen zählt nur die N Treffer. So gezählt waren von den 107 beantwortbaren Fragen unter den ersten 3 nun 86 statt 64 vollständig gefunden (beide Sätze), unter den ersten 12 99 und 98 statt 74, unter den ersten 100 99 statt 84. Bei gleich vielen gelesenen Seiten, abwechselnd aus beiden Listen (Treffer 1, Block 1, Treffer 2, Block 2 und so weiter), sind es 83 statt 64 unter den ersten 3 und 89 statt 74 unter den ersten 12, in beiden Sätzen. In der Sicht aus beiden Listen gewannen unter den ersten 12 am meisten Fragen in anderer Sprache (8 statt 1 von 8), Umschreibungen (8 statt 3 von 8), freie Synonyme (8 statt 4 von 8), Komposita (8 statt 6 von 8), Tippfehler (8 statt 6 von 8) und breite Fragen (5 und 4 statt 1 von 5). Die acht Fragen, die nur die Quellen beantworten, fehlen ohne `--include-sources` weiter; mit dem Schalter findet sie schon die Frage allein unter den ersten 3. Der Preis: Für die sieben Fragen zu Themen, die das Wiki nicht enthält, liefert der Block 41 und 45 Seiten, bei 6 und 7 von 7 Fragen ist er nicht leer. Nur rund 6 Prozent der Block-Einträge beantwortbarer Fragen sind Seiten, die die Testdaten als passend führen. Deshalb gilt eine Seite aus dem Block erst als gefunden, wenn der Agent sie gelesen hat. Navigationsseiten im Block: 0. Ein Aufruf mit den Umformulierungen aus Satz A (meist vier) dauerte auf dem Test-Wiki im Mittel 48 statt 34 Millisekunden; die Frage und jede Umformulierung einzeln gesucht brauchten zusammen 164. Auf einer Kopie mit rund 4.500 Wiki-Seiten und 1.100 Quellen dauerte er etwa 3,1 Sekunden, fünf einzelne Aufrufe des bisherigen Suchkerns rund 19 Sekunden. Die einzelne Suche wurde schneller, weil Ausschnitte und Claims nur noch für ausgegebene Treffer entstehen: dort 2,8 statt 4,4 Sekunden. Die JSON-Ausgabe wird mit vier Umformulierungen etwa doppelt so groß (im Mittel 50 statt 24 KB). Die Sätze stammen aus derselben Modellfamilie, mit der sie gemessen werden; die Zahlen sind daher eher zu günstig.

**Abgesicherte Fehlanzeige.** Ob „nichts gefunden" heißt „nichts vorhanden", entscheidet nicht das Urteil des Agenten allein. Jede Suchausgabe trägt gleich nach dem Release `search_record` und `absence_check` (Format `lmwiki-absence-check/1`). `complete` ist nur dann `true`, wenn derselbe Aufruf mit `--exhaustive` lief, mindestens zwei Umformulierungen mit eigenen Wörtern gesucht wurden und alle Treffer ins Budget passten. Ein solcher Aufruf rankt zusätzlich die Quellen und durchsucht jede Passage der Wiki-Seiten, von `meta/questions.md` und des Quell-Markdowns nach allen Wörtern aller Formulierungen, in den Formen, die auch das Ranking zählt: Seitenkopf (Titel, Aliase, Beschreibung, Seiten- oder Quell-ID und die Quell-IDs, die die Seite nennt), Überschriften, Claims (mit ihrer ID und den Quell-, Ablöse- und Widerspruchs-IDs ihrer Metadaten), Absätze, Listenpunkte, Tabellen und offene Fragen. Ein Absatz endet nur an einer Leerzeile oder einer Strukturzeile. Ein Seiten- oder Folienmarker mitten im Absatz beendet ihn nicht: Der Absatz nennt dann beide Seiten als Locator (`page=3-4`), und ein Trennstrich am Zeilenende vor dem Marker wird zusammengezogen. Ein Absatz über 1.500 Zeichen wird in mehrere Passagen geteilt, immer am ersten Satzende danach, sodass kein Satz zerfällt; ein Punkt nach einer Zahl, einem einzelnen Buchstaben oder einer gängigen Abkürzung („Abs.", „z. B.") ist kein Satzende, und ohne jedes Satzende wird spätestens nach 3.000 Zeichen am Zeilenende geteilt. Eine rohe HTML-Tabelle, wie Pandoc sie für verbundene Zellen schreibt, und Pandocs Gitter-, Mehrzeilen- und einfache Tabellen (so schreibt Pandoc eine Word-Tabelle in Markdown) gelten als Tabelle mit ihrer ersten Zeile als Kopfzeile, wie eine Pipe-Tabelle; eine Tabellenzeile über mehrere Textzeilen oder mit Leerzeilen dazwischen bleibt eine Zeile. Eine Tabelle, deren Spalten nur mit Leerzeichen und ohne Strichlinie unter dem Kopf ausgerichtet sind, liest die Prüfung als Absätze, ohne Kopfzeile; eine HTML-Überschrift und die Zusammenfassung eines `<details>`-Blocks wirken wie Überschrift und Zwischenzeile. IDs und die Ziele von Links ohne Beschriftung treffen nur als ganzes Wort; Link-Ziele werden auch hier nie an Bindestrichen zerlegt. Ob ein Wort dabei Link-Ziel oder Text ist, entscheidet die Prüfung je Passage: Ein Link auf `wiki/concepts/sms-warndienst` schaltet `hyphen_part` für „SMS-Warndienst" im Text einer anderen Seite nicht ab. Navigationsdateien, `schema/`, `graph/` und der übrige Teil von `meta/` werden nicht durchsucht, die Snapshots unter `meta/history/` nur mit `--include-history`, weil sie außerhalb des Release-Manifests liegen. Eine Passage trifft eine Formulierung, wenn jedes Inhaltswort der Formulierung in ihr oder in ihrem Umfeld steht und mindestens eines in ihr selbst. Zum Umfeld gehören der Kopf ihrer Seite, die Überschriften darüber, eine Zwischenzeile darüber (eine eigene Zeile von höchstens 100 Zeichen, die nur fett gesetzt ist oder mit einem Doppelpunkt endet; sie gilt bis zur nächsten Überschrift oder Zwischenzeile), die übergeordneten Listenpunkte und bei einer Tabelle, die in mehrere Passagen zerfällt, deren erste Zeile. Mehr gehört nicht dazu: Eine Passage, die erst mit dem Absatz davor oder mit einem Satz jenseits eines Schnitts verständlich wird, trifft nicht. Funktionswörter wie „ans", „ab", „per", „pro", „je", „laut", „gemäß", „wofür", „wieviel" oder „bzw.", Partikeln wie „noch", „eigentlich" oder „nur", das Gradwort einer Frage mit „wie" („hoch", „viel", „lange", „oft", „teuer", „schnell") und die Hilfsverben einer Frage wie „gibt", „geht", „gilt", „steht" oder „passiert" muss sie nicht enthalten. Über die Wortformen des Rankings hinaus findet die Prüfung ein Wort als Teil eines Wortes mit Bindestrich („SMS" in „SMS-Warndienst", „E-Mail" in „E-Mail-Newsletter") und ein Wort mit Bindestrich auch getrennt geschrieben, als ausgewiesene Heuristik `hyphen_part`; ein Teil aus einem Buchstaben bleibt dabei bei seinem Nachbarn, „E-Mail-Adresse" und „E-Mail Adresse" finden einander, „E-Mobilität" aber nie „Mobilität" allein. Ebenso findet sie ein Wort, das mit dem Suchwort einen Stamm teilt, wo die Wortformen das nicht abdecken; Stamm heißt hier das Wort selbst oder das Wort ohne eine Endung (-e, -en, -n, -er, -ern, -es, -em, -s, -se, -sen, -nen). Das sind Plurale auf „-er" („Krankenhäuser" zu „Krankenhaus"), auf „-s" nach einem Vokal („Autos"), auf „-se" („Ergebnisse") und auf „-nen" („Kundinnen"), die Kasusendungen „-er" und „-em" eines Adjektivs ohne Adjektivsuffix („intelligentem" zu „intelligenten", „fester" zu „festen") und die Formen kurzer Stämme („Tage" zu „Tag", „Tag" zu „Tage"), als ausgewiesene Heuristik `ending`; weil sie auch Wörter trifft, die nur so aussehen („Zähler" zu „Zahl", „Lager" zu „Lage"), prüft der Agent solche Treffer im Text. Ebenso ausgewiesen sind `verb_ending` für eine andere Verbform eines regelmäßigen Verbs mit vierbuchstabigem Stamm („senken" zu „senkt", „zahlt" zu „zahlen", „geprüft" zu „prüft"; die Regel trifft auch „Marken" zu „Markt") und für Partizip und zu-Infinitiv eines trennbaren Verbs („abgeschaltet" und „abzuschalten" zu „abschalten", „angepasst" zu „anpassen" und umgekehrt), `short_part` für ein Wort aus zwei oder drei Buchstaben in einem längeren Wort, als erster Teil, wenn der Rest ein Wort der durchsuchten Dateien ist („Gas" in „Gaskunden"), oder als letzter Teil nach mindestens drei Buchstaben („Gas" in „Erdgas"; die Regel trifft auch „Beweis" zu „Eis"), `suspended_compound` für ein Kompositum mit Ergänzungsstrich („Grund- und Leistungspreis" enthält „Grundpreis", „Vertragsbeginn und -ende" enthält „Vertragsende") und `footnote_mark` für eine Fußnotenziffer, die ein Konverter an das Wort klebt („Kündigungsfrist2": so schreibt MarkItDown ein hochgestelltes `<sup>2</sup>`); eine hochgestellte Ziffer („Kündigungsfrist²") trennt die Prüfung ohnehin vom Wort, das zusammengeschriebene Token bleibt daneben erhalten, sodass „Fix12" weiter sich selbst findet; ein Hochgestelltes in Markdown („Kündigungsfrist^2^", „m<sup>2</sup>") zählt ebenso getrennt und zusammengeschrieben. Das Ranking kennt diese Regeln nicht. Die Treffer stehen seitenweise unter `exhaustive_hits` am Ende der Ausgabe, zusammen höchstens 100.000 Zeichen, so gezählt, wie die Ausgabe sie druckt; Claims, die schon unter den Ergebnissen stehen, werden nur verwiesen. Passt nicht alles hinein, ist die Prüfung unvollständig, und die Ausgabe nennt die nicht gezeigten Seiten. `absence_check.next_steps` sagt aus einem festen Vokabular, was vor einer Fehlanzeige zu tun ist; `search_record.line` ist die Prüfzeile, die eine Antwort zitiert. Ein Ergebnis gilt erst als nicht zutreffend, wenn der Agent es ganz gelesen hat, nicht nur den Ausschnitt; `read_results_without_claims` nennt deshalb jede Seite unter den Ergebnissen, die keine Claims druckt, etwa jede Quelle. `narrow_formulations` erscheint nur, solange die Treffer der Frage selbst ins Budget passen; sonst kann keine Umformulierung die Prüfung vollständig machen, und die Antwort bleibt bei „nicht gefunden". „Das Wiki enthält nichts zu X" darf der Agent nur bei `complete: true` sagen und nur, wenn kein Ergebnis und kein Treffer die Frage beantwortet; sonst heißt es „mit diesen Wörtern in Release V nicht gefunden". Für einen Teil der Frage gilt das nur, wenn alle Wörter für diesen Teil unter `absent_terms` stehen oder eine eigene Umformulierung nur diesen Teil geprüft hat. Eine Zahl unter `absent_terms` genügt dafür nie allein, denn eine Seite kann sie in Worten oder in einer anderen Einheit schreiben. Auch eine vollständige Prüfung zeigt nur, dass keine Passage die geprüften Wörter zusammen enthält; eine Seite, die die Antwort anders formuliert, kann fehlen, und das sagt die Antwort dazu. Der Aufruf ist die einzige Ausnahme vom gestuften Lesen und nur für Fehlanzeigen gedacht. Die übrige Ausgabe (Ergebnisse, Umformulierungsblock, Zählwerk, `absence_check`) kommt zu den Treffern hinzu; auf dem Test-Wiki sind das bei Limit 12 im Median etwa 57.000 Zeichen, in beiden Sätzen.

Ohne `--exhaustive` steht in `absence_check.reasons` nur `not_exhaustive`, die übrigen Felder sind `null` und `exhaustive_hits` ist `null`: Das ist der Normalfall und für sich kein Grund, vollständig zu prüfen. Das JSON-Objekt von `--request -` behält seine drei Schlüssel; `--exhaustive` gehört auf die Befehlszeile, und eine Anfrage mit dem Schlüssel `exhaustive` wird mit genau diesem Hinweis abgelehnt. Weil `--exhaustive` die Quellen mitrankt, endet ein solcher Aufruf mit Exit-Code 5 (`invalid_frontmatter`), wenn eine Quelle außerhalb des Frontmatter-Vertrags liegt, so wie `--include-sources` schon bisher; mit `--include-history` gilt das auch für Snapshots.

| Feld | Bedeutung |
|---|---|
| `search_record` | die Prüfzeile `line`: Release-Version, Release-ID, die ersten 12 Zeichen des Manifest-Hashs, die Frage (höchstens 200 Zeichen), die Zahl der Umformulierungen, die gerankten Schichten, ob vollständig geprüft wurde, Ergebnisse, Treffer und `complete`; eine Antwort zitiert sie bei jeder Fehlanzeige |
| `absence_check.complete` / `reasons` / `next_steps` | ob eine Fehlanzeige erlaubt ist; sonst die Gründe in fester Reihenfolge (`not_exhaustive`, `too_few_reformulations`, `no_content_words`, `budget_exhausted`) und, nur bei `--exhaustive`, die Schritte vor einer Fehlanzeige (`read_withheld_claims`, `read_results_without_claims`, `read_reformulation_results`, `read_exhaustive_hits`, `add_reformulations`, `narrow_formulations`) |
| `reformulations_counted` / `formulations` | wie viele Umformulierungen zählen; je Suche ihre Inhaltswörter, ob sie als eigene Umformulierung zählt (sie zählt nicht, wenn sie alle Inhaltswörter der Frage oder einer anderen Umformulierung enthält, gleich an welcher Stelle diese steht: in anderer Reihenfolge, in einer anderen Schreibung, Beugung oder Verbform, die die Prüfung als dasselbe Wort findet, auch über `ending` und `verb_ending`, als anderer bestätigter Begriff einer Begriffswelt, die dieselben Wörter schon auslösen, oder um Wörter erweitert; von Umformulierungen, die einander enthalten, zählt nur die erste, die Reihenfolge ändert die Zahl also nie; ein Wort mit Bindestrich ist dasselbe Wort wie seine zusammengeschriebene Form und seine getrennt geschriebenen Teile, wobei ein Teil aus einem Buchstaben bei seinem Nachbarn bleibt) und wie viele Passagen sie trifft |
| `scopes` | je Schicht durchsucht oder nicht, mitgeliefert oder nicht, Zahl der Dateien, der übersprungenen Navigationsdateien, der Passagen und der Zeichen |
| `terms` / `absent_terms` | je Wort die Passagen und Dateien je Schicht und höchstens 10 gezählte Formen; die Inhaltswörter, die in keiner durchsuchten Passage vorkommen |
| `counts` / `budget` / `omitted_pages` | Treffer und Seiten insgesamt, zurückgegeben, über Wortformen oder nur heuristisch, schon gedruckt (`hits_already_printed`), Seiten, die das Budget abschnitt (`pages_partial`); verbrauchte und benötigte Zeichen; höchstens 20 Seiten, die nicht mehr hineinpassten |
| `exhaustive_hits` | die Treffer seitenweise mit Art der Passage, Zeile, Locator (Claim-ID oder `page=`/`slide=`, bei einem Absatz über einen Seitenwechsel ein Bereich wie `page=3-4`), Status, Formulierungen, Stärke und Text (höchstens 400 Zeichen um den ersten Treffer, `text_chars` nennt die volle Länge); `hits_total` je Seite zählt alle ihre Treffer; `matched` nur bei heuristischen Treffern, mit Wort, Token, Regel und Fundort; ein schon gedruckter Claim nur als Verweis `shown_in`; mit `--filter-json` trägt jede Seite `selected`, denn die Prüfung gilt dem ganzen Release, und ein Treffer auf einer Seite mit `selected: false` liegt außerhalb der gewünschten Teilmenge; `null` ohne `--exhaustive`, `[]` ohne Treffer |
| `boundary` | fester Satz, was eine vollständige Prüfung zeigt und was nicht |

Gemessen auf dem Test-Wiki mit beiden blinden Sätzen von Umformulierungen (Satz A und Satz B): Die Prüfung war in beiden Sätzen bei 110 von 114 Fragen vollständig. Unvollständig blieben id-04 in Satz A, die nur eine Umformulierung hat, id-06 („OBIS 1.8.1"), deren Umformulierungen der Frage meist nur Wörter hinzufügen, etwa „OBIS-Kennzahl 1.8.1", ex-01 („Netzentgelt") und ty-01 („Netzentgeld") in beiden Sätzen und cl-06 („grid fee for household customers") in Satz B. Deren Umformulierungen sind meist Begriffe derselben Begriffswelt („Netznutzungsentgelt", „Netzgebühren") oder enthalten eine andere Umformulierung ganz („Netzentgelte Höhe" neben „Netzentgelt"); die Prüfung trifft mit ihnen keine anderen Passagen. Alle melden `too_few_reformulations`. Alle sieben Fragen zu Themen, die das Wiki nicht enthält, endeten vollständig und ohne einen Treffer über Wortformen. Einen heuristischen Treffer gab es bei ne-01 („Fernwärme Anschlusskosten"), in beiden Sätzen derselbe: ein Absatz einer Quelle über das Wiederherstellen eines gesperrten Stromanschlusses, gefunden über „Anschlusses" als Teil von „Fernwärmeanschluss". Er beantwortet die Frage nicht. In Satz B kam bei ne-04 („Ladesäule öffentliches Laden Preise") ein zweiter hinzu: ein Absatz über den dynamischen Tarif Flex, der das nächtliche Laden eines Elektroautos zu Hause nennt, gefunden über „Elektroautos" (`ending`) aus der Umformulierung „Elektroauto Laden Kosten". Auch er beantwortet die Frage nicht. Bei ne-02 („Gastarif Kündigungsfrist") stehen alle Gas-Wörter unter `absent_terms` (erdgas, gaslieferung, gastarif, gasvertrag); die Antwort darf also sagen, dass das Wiki Kündigungsfristen für Strom behandelt, aber nichts zu Gastarifen. Jede Pflichtseite der 107 beantwortbaren Fragen stand in beiden Sätzen in den Ergebnissen, im Umformulierungsblock oder unter den zurückgegebenen Treffern, und bei allen acht Fragen, deren Antwort in einem späten Claim steht, war dieser Claim gedruckt. Ergebnisse, Block und Zählwerk waren in allen 228 Läufen genau die der gleichen Suche mit `--include-sources`. Der Platz reichte auf dem Test-Wiki immer: Die Treffer brauchten im Median 5.600 und 5.500 Zeichen, bei 90 Prozent der Fragen höchstens 20.300 und 24.000, am meisten br-01 mit 66.300 und 67.700. `next_steps` nannte `read_withheld_claims` bei 113 und 114 Fragen, `read_results_without_claims` bei 113 und 113, `read_reformulation_results` bei 108 und 111, `read_exhaustive_hits` bei 103 und 104, `add_reformulations` je viermal und `narrow_formulations` nie. Auf einer 500-Seiten-Kopie, die jede Seite etwa elfmal wiederholt, sind die Trefferzahlen eine Obergrenze; dort passten 72 von 114 Fragen in beiden Sätzen ins Budget (vollständig waren 70 und 71), die übrigen 42 enden mit `budget_exhausted`, 32 davon mit `narrow_formulations`; bei den anderen 10 überschreiten schon die Treffer der Frage selbst das Budget. Alle sieben Fragen zu fehlenden Themen waren dort vollständig (ne-01 mit 11 heuristischen Treffern, in Satz B auch ne-04 mit 11, den Kopien des Absatzes zum Tarif Flex). Mit 7,6 MB zusätzlichem Quell-Markdown passten 23 und 20 von 114 Fragen, und ne-01 brachte 220 heuristische Treffer auf 11 Seiten, von denen 6 hineinpassten: unvollständig, mit dem Schritt `narrow_formulations`. Eine unvollständige Prüfung bei einer beantwortbaren Frage schadet nicht, weil deren Ergebnisse sie beantworten. Ein Aufruf mit `--exhaustive` brauchte auf dem Test-Wiki 0,08 bis 0,09 statt 0,04 bis 0,06 Sekunden Rechenzeit wie mit `--include-sources`, auf der 500-Seiten-Kopie 0,7 bis 0,8 statt 0,3 bis 0,4 und mit 7,6 MB Quell-Markdown 3,4 bis 3,8 statt 1,3 bis 1,5 Sekunden (Median aus fünf Läufen im Prozess), also höchstens das 2,6-Fache. Den größten Teil kostet das Zerlegen in Passagen; jede Datei wird dabei nur einmal gelesen. Die einheitliche Schreibweise für Zahlen kostet auch die gewöhnliche Suche Zeit: Mit `--include-sources` dauerte ein Aufruf auf der Kopie mit 7,6 MB Quell-Markdown 1,4 bis 1,5 statt 1,1 bis 1,3 Sekunden, auf dem Test-Wiki und der 500-Seiten-Kopie höchstens 0,06 Sekunden länger.

**Zählwerk: was die Trefferliste nicht zeigt.** Jede Suchausgabe trägt einen Block `coverage` (Format `lmwiki-search-coverage/3`). Er ergänzt nur Schlüssel; welche Treffer in welcher Reihenfolge und mit welchem Score zurückkommen, ändert er nicht. Format 3 zählt zusätzlich je Suche, also für die Frage und jede Umformulierung; Format 2 zählte die Formen eines Wortes mit; Format 1 zählte nur das Wort selbst. Er zählt, was sonst still verloren ginge:

| Feld | Bedeutung |
|---|---|
| `matched`, `returned`, `truncated`, `omitted_count` | Treffer insgesamt, zurückgegeben, ob abgeschnitten wurde und wie viele fehlen; es gilt `returned + omitted_count = matched` |
| `omitted_top` | höchstens 20 der nächsten Treffer mit Pfad und Score |
| `scopes` | je Schicht (Wiki, Quellen, Historie): durchsucht oder nicht, Zahl der Dateien und Zahl der Dateien mit einem Suchwort; Quellen werden immer gezählt, die Historie nur, wenn sie durchsucht wird |
| `query_terms` | jedes Suchwort mit Herkunft (`query` oder `concept-expansion`), Dateizahl je Schicht (Dateien mit dem Wort oder einer seiner Formen) und unter `forms` höchstens 10 Formen mit Regel, Gewicht und Dateizahl; die Dateizahl einer Form zählt die durchsuchten Dateien, in denen sie zählt, eine andere Form als das Wort selbst also nicht auf Navigationsseiten; `forms_total` nennt, wie viele Formen es insgesamt sind |
| `dropped_terms` | Wörter der Frage, die nicht gesucht wurden (Stoppwort, Einzelzeichen) |
| `unmatched_terms` | Wörter der Frage, die in keiner durchsuchten Datei zählen, auch in keiner ihrer Formen; eine Form, die nur auf Navigationsseiten steht, zählt nicht; die vollständige Prüfung kann sie über ihre eigenen Heuristiken dennoch finden, ihr Urteil steht unter `absent_terms` |
| `form_only_terms` | Wörter der Frage, die nur über eine andere Form, einen Kompositumteil oder eine Tippfehlerkorrektur getroffen haben, nie wörtlich |
| `terms_only_in_unsearched.sources` | Suchwörter, die selbst oder in einer Wortform nur in den nicht durchsuchten Quellen stehen; ein Kompositum- oder Tippfehlertreffer im Wiki gilt dabei nicht als das Wort |
| `formulations` | je Suche (0 ist die Frage) `matched`, `within_limit`, `truncated`, `contributed` (wie viele Einträge in `reformulation_results` diese Suche innerhalb des Limits fand), dazu ihre `query_terms` ohne `forms`, `dropped_terms`, `unmatched_terms`, `form_only_terms` und `terms_only_in_unsearched`; Eintrag 0 stimmt mit den Werten der Frage überein |
| `reformulation_results` | Zählung des Blocks: `returned`, `candidates`, `truncated`, `omitted_count`, `omitted_top` (höchstens 20 mit Pfad, Umformulierung und Rang), `navigation_skipped` und ein fester Satz, dass der Block weder Abdeckung noch Fehlen beweist |
| `found_by` (am Treffer) | jede Suche, die die Seite fand, mit ihrem Rang dort; der erste Eintrag eines Treffers in `results` ist immer die Frage mit seinem Rang |
| `boundary` | fester Satz: Die Zahlen beschreiben Übereinstimmungen der genannten Wörter samt den unter `forms` genannten Formen und ausgewiesenen Kompositum- und Tippfehlertreffern und beweisen nicht, dass das Thema fehlt; andere Wörter, unregelmäßige Formen und andere Sprachen zählen nicht mit |

Jeder Treffer nennt zusätzlich `matched_terms` (welche Suchwörter auf dieser Seite getroffen haben), `match_rules` (je Suchwort die Wörter dieser Seite, die gezählt haben, mit Regel und Gewicht), `claims_total` und `claims_returned` (pro Seite kommen höchstens acht Claims zurück) sowie `navigation` für `WIKI.md`, jede `index.md` und `meta/questions.md`. Navigationsseiten bleiben in der Rangliste, damit sich das Ranking nicht ändert, werden aber nie als Beleg zitiert. Die Wortzählungen ignorieren einen Metadatenfilter; wie viele Dateien er ausgeschlossen hat, steht in `filtered_out`.

Daraus folgen feste Leseregeln, die in `SKILL.md`, im Antwortvertrag und in der exportierten `SKILL.md` stehen: Bei `truncated` erhöht der Agent `--limit` (höchstens 100) oder sagt, dass es weitere Treffer gibt. Vor einer Antwort aus einer Seite mit zurückgehaltenen Claims liest er alle ihre Claim-Blöcke. Bei `unmatched_terms` sucht er mit anderen Wörtern weiter, bevor er etwas folgert, und nennt diese Wörter in der Antwort. Bei `form_only_terms` prüft er, ob die gezählten Formen gemeint sind. Bei `terms_only_in_unsearched.sources` wiederholt er die Suche mit `--include-sources`. Trägt nur ein Kompositumteil oder eine Tippfehlerkorrektur das entscheidende Wort, prüft er im Seitentext, ob es um das gefragte Wort geht, und sagt in der Antwort, wodurch der Treffer zustande kam. Die Zahlen gelten nie als Beweis, dass das Wiki zu einem Thema nichts enthält: Eine Seite mit anderen Wörtern, einer unregelmäßigen Form oder in einer anderen Sprache zählt nicht mit.

Weil die Quellen auch ohne `--include-sources` gezählt werden, liest jede Suche alle Quelldateien. Der Lese-Skill schreibt weder Index noch Cache, also zahlt jede Suche diese Arbeit neu, und sie wächst mit der Menge an Quell-Markdown. Auf dem Entwicklungsrechner kostete das Zählen bei 7,7 MB Quell-Markdown rund 0,5 Sekunden je Suche, also etwa 0,07 Sekunden je Megabyte; eine Suche mit `--include-sources` dauerte dort etwa doppelt so lange.

Ein Präzisionstor (`tests/test_search_quality.py`, Abschnitt 15) misst die Suche auf einem synthetischen Test-Wiki mit 114 Fragen. Es schlägt fehl, wenn eine Frage, deren erster Treffer bei der Aufzeichnung eine Pflichtseite war, keine Pflichtseite mehr auf Rang 1 hat, wenn eine Pflichtseite die ersten 3 oder die ersten 12 verlässt, in denen sie stand, oder wenn eine aufgezeichnete Unter- oder Obergrenze verletzt wird. Verschiebungen innerhalb dieser Bänder, etwa von Rang 2 auf Rang 3 oder von Rang 4 auf Rang 9, erkennt es nicht.

### 5.5 Metadatenfilter und Facetten

Der Lese-Skill kann Suchmengen kontrolliert einschränken, beispielsweise nach:

- `type`;
- `status`;
- `language`;
- `clusters`;
- `concepts`;
- `sources`;
- `tags`;
- Datum oder Aktualisierungsfeldern;
- relativem Pfad, Ordner, Dateiname oder Erweiterung.

Unterstützt werden definierte Operatoren für Existenz, Gleichheit, Ungleichheit, Enthaltensein, Präfixe, Suffixe, leere Werte, Listen- und Stringtypen sowie Pfadzugehörigkeit. Mehrere Bedingungen können mit `AND` oder `OR` verbunden werden. Reguläre Ausdrücke und ausführbarer Filtercode sind nicht zulässig.

Das Ergebnis enthält außerdem Facetten für Typ, Status, Sprache, Cluster und Begriffe. Facetten beschreiben die gefundene Ergebnismenge, sind aber selbst kein Beleg für eine inhaltliche Aussage.

Ein Filter kann historische oder widersprechende Informationen ausblenden. Wenn diese Einschränkung die Antwort beeinflusst, muss der Skill sie nennen. Eine leere gefilterte Ergebnismenge bedeutet nur, dass der gewählte Ausschnitt keinen Beleg enthält.

### 5.6 Quellenangaben, Status und Chronologie

Ohne abweichende Vorgabe in `SOUL.md` nennt eine Quellenangabe:

```text
claim_id — Originaltitel — source_id@locator — relativer Quellenpfad
```

Zusätzlich werden Version oder Datum genannt, wenn sie für Gültigkeit und Einordnung wichtig sind.

Der Skill bevorzugt für Fragen zum aktuellen Stand aktive Inhalte, kennzeichnet Entwürfe und unvollständige Quellen, und behandelt abgelöste Inhalte als historische Evidenz. Ein neueres Datum allein beweist keine Ablösung. Bei Konflikten werden die unterschiedlichen Positionen mit Datum, Status und Quellenidentität offengelegt.

### 5.7 Frontmatter-Inventar im Lesemodus

Der Lese-Skill kann den veröffentlichten Stand strukturell inventarisieren, ohne ihn zu verändern. Das ist nützlich, um vorhandene Metadatenfelder, Typen, mögliche Filter und Drift zu verstehen.

Parserfehler, fehlende Pflichtfelder oder Namensabweichungen werden als Qualitätsbefund gemeldet. Eine Reparatur erfolgt ausschließlich mit dem Pflege-Skill.

### 5.8 Selbstbeschreibender Read-only-Katalog

Der Lese-Skill beschreibt maschinenlesbar genau fünf Aktionsgruppen:

- Release verifizieren;
- bestätigte Identität und Inhaltsrichtlinie prüfen;
- Qualitätsstatus beurteilen;
- Frontmatter inventarisieren;
- suchen und filtern.

Für die Suche nennt der Katalog alle Parameter, die der Helfer annimmt, auch `--limit` und `--expect-manifest-sha256`. Nur das Ziel `--target`, das jede Aktion verlangt, steht wie bei allen Aktionen in keinem Eintrag. Der Katalog enthält keine Pflege-, Cleaning-, Snapshot-, Restore-, Lock- oder Schreibaktion.

## 6. Vollständiger Arbeitszyklus

### Neues Wiki

1. Der Anwender nennt Ziel, Titel, Themenrahmen und Wiki-Sprache.
2. Der Pflege-Skill klärt die Identität mit wenigen Einzelfragen und zeigt `SOUL.md` plus Inhaltsrichtlinie als hashgebundenen Vorschlag.
3. Erst nach ausdrücklicher Bestätigung initialisiert er den vollständigen, extern gestaffelten Stand unter exklusivem Lock.
4. Quellen werden treu in Markdown umgewandelt, vorgeprüft und transaktional registriert.
5. Cluster und Begriffswelten werden vorgeschlagen und bestätigt.
6. Der Skill kuratiert Wissensseiten und Claim-Belege über vollständig validierte Seitenbatches.
7. Index, Graph und HTML-Leseansichten werden erzeugt.
8. Lint und Qualitätsgrenzen werden geprüft.
9. Genau ein idempotenter Release mit Version und Manifest wird veröffentlicht.
10. Lock und private Runtime-Datei werden freigegeben.
11. Der Lese-Skill kann den verifizierten Stand konsumieren.

### Bestehendes Wiki erweitern

1. Der Pflege-Skill erwirbt den Lock, bevor er Inhalte untersucht oder konvertiert.
2. Er prüft bestehende Regeln, Profil, Index, Cluster, Begriffe und relevante Seiten; vorhandene Auffindbarkeitsfragen werden als Ausgangsstand geprüft.
3. Neue Quellen werden registriert; Duplikate werden übersprungen.
4. Vor direkten Änderungen entsteht ein Snapshot.
5. Inhalte werden inkrementell ergänzt, Konflikte und offene Fragen werden dokumentiert.
6. Betroffene Navigation und Graphansichten werden aktualisiert.
7. Lint und Release veröffentlichen genau einen neuen konsistenten Stand. Vor dem Release legt der Skill neue Locator-Warnungen, neu unzitierte Quellen und verlorene Auffindbarkeitsfragen vor.
8. Erst danach wird der Lock freigegeben.

### Metadaten bereinigen

1. Inventar und Drift-Bericht erzeugen.
2. Auswahl und beabsichtigte Aktion mit dem Anwender abstimmen.
3. Hash-gebundenen Vorher-/Nachher-Plan erzeugen.
4. Bedeutungsändernde oder destruktive Unterschiede bestätigen lassen.
5. Exakt den bestätigten Plan anwenden; bei Drift null Schreibvorgänge.
6. Snapshot, Graph, Lint, Release und Verifikation abschließen.

### Wiederherstellen

1. Verfügbare Snapshots und ihre Gültigkeit prüfen.
2. Gewünschte Dateien und den Ziel-Snapshot auswählen.
3. Hash-gebundenen Restore-Plan vorlegen.
4. Nach Bestätigung einen Recovery-Snapshot des aktuellen Zustands erstellen.
5. Nur die ausgewählten Dateien wiederherstellen.
6. Abgeleitete Ansichten neu erzeugen und einen neuen Release veröffentlichen.

### Wissen abfragen

1. Lese-Skill mit Wiki-Verzeichnis und Frage ansprechen.
2. Release und Qualitätsstatus werden intern geprüft.
3. `SOUL.md`, Profil, Index und Begriffswelten werden berücksichtigt.
4. Der Agent formuliert die Frage bei Bedarf in der Wiki-Sprache um (höchstens vier Umformulierungen). Relevante Claims und Quellenstellen werden vollständig gelesen.
5. Beantwortet kein Ergebnis die Frage, prüft der Agent mit `--exhaustive` vollständig, bevor er eine Fehlanzeige meldet.
6. Die Antwort nennt Unsicherheit, Konflikte und Quellen nachvollziehbar.
7. Eine zweite Release-Prüfung verhindert eine Antwort aus einem veränderten Mischstand.

## 7. Sperr- und Nebenläufigkeitsmodell

### 7.1 Ein Claim je Maintainer

Ein Wiki auf einer SharePoint- oder OneDrive-Bibliothek wird von einem Team gepflegt, nicht von einem Rechner. Der Lock ist deshalb kein einzelner Platz, den der Nächste überschreiben muss, sondern das Verzeichnis `<wiki>/.llmwiki.lock/`. Darin besitzt jeder Maintainer **genau eine** Datei — `claim-<maintainer>.json` im Format `lmwiki-lock-claim/1` — und schreibt, erneuert und entfernt ausschließlich diese eine.

Der Grund liegt in der Ablage, nicht im Geschmack: Ein Synchronisationsclient kennt kein Compare-and-Swap. Zwei Geräte, die denselben Pfad schreiben, erzeugen einen verlorenen Schreibvorgang oder eine Konfliktkopie — und der Verlierer merkt es erst, nachdem er das Wiki bereits verändert hat. Zwei Geräte, die zwei Pfade schreiben, erzeugen zwei Dateien: einen Sachverhalt, den beide Seiten sehen können. Der gemeinsam genutzte Einzelplatz war also der Fehler, nicht die gemeinsame Nutzung.

Der Claim enthält Claim-ID, Maintainer-Kennung, Lauf-Label, Operation, Erwerbszeit, letzten Heartbeat, Leihdauer, Host und nur den Hash eines privaten Besitz-Tokens. Die Maintainer-Kennung ist standardmäßig `<benutzer>@<host>` und identifiziert damit eine Person an einem Rechner — die Einheit, die tatsächlich pflegt. Das Token liegt in einer privaten Runtime-Datei außerhalb des Wikis, wird nur durch den eingeschränkten Helper-Wrapper eingelesen und weder ausgegeben noch in Prompts, Delegationen, Wiki-Inhalte oder Berichte übernommen. Es gibt **keine** vorab zu pflegende Liste zugelassener Maintainer: Wer das Verzeichnis beschreiben darf, kann eine solche Liste auch ändern, sie wäre also der Anschein einer Zugriffskontrolle ohne deren Substanz. Registriert ist, wer einen Claim hält.

### 7.2 Wer darf schreiben

Die Entscheidung fällt deterministisch über die sichtbaren Claims und im Zweifel gegen das Schreiben:

- **Genau ein wirksamer Claim, und es ist der eigene** — schreiben erlaubt.
- **Zwei wirksame Claims** — niemand schreibt. Auf einer synchronisierten Ablage sehen „Ich bin der einzige Claim" und „Der andere Claim ist noch nicht angekommen" identisch aus. Das Wiki bleibt stehen, statt zwei Kuratoren im Glauben zu lassen, sie seien allein.
- **Konfliktkopie eines Claims, unlesbarer Claim, Zeitstempel aus der Zukunft** — niemand schreibt, weil der Beleg selbst beschädigt ist.

Erwerben zwei Maintainer im selben Augenblick, liest der Erwerb den Lock zurück, bevor er Erfolg meldet, und nimmt den eigenen, frisch geschriebenen Claim wieder zurück, wenn er nicht allein ist. Zu diesem Zeitpunkt wurde noch nichts geschrieben, also kostet die Kollision einen erneuten Versuch statt zweier Aufräumbefehle — und ein gemeldetes „erworben" wird nie nachträglich vom ersten Helferaufruf widerrufen.

Der Stoppzustand heißt `contended`, nennt die beteiligten Maintainer und verlangt eine Entscheidung zwischen Menschen: Alle außer einem führen auf dem **eigenen** Rechner `wiki_lock.py withdraw --reason …` aus. Dieser Befehl entfernt nur Claims, die dieser Rechner geschrieben hat — und dazu die Konfliktkopien des eigenen Claims. Er ist damit auch die Antwort auf einen abgestürzten Lauf, dessen Runtime-Token verloren ist: kein Override nötig.

### 7.3 Leihdauer und Übergabe

Alter allein begründet weiterhin keine Übernahme. Jeder Claim trägt eine Leihdauer, die jeder gelockte Helferaufruf und `wiki_lock.py heartbeat` erneuern. Als abgelaufen gilt ein Claim erst, wenn **sowohl** sein eingetragener Heartbeat **als auch** die lokale Änderungszeit seiner Datei älter sind als Leihdauer plus Synchronisationskarenz — die beiden Uhren zweier Geräte dürfen sich also unterscheiden, ohne dass jemand fälschlich für verwaist erklärt wird.

Ein abgelaufener Claim hält das Wiki weiterhin. Er wird lediglich übergabefähig, und die Übergabe ist zweistufig und aktenkundig:

1. `acquire --take-over --reason …` schreibt eine **tokenlose Erklärung** in das Wiki. Sie sperrt nichts, ist aber für die andere Person sichtbar und nennt den Zeitpunkt, ab dem sie wirkt.
2. Derselbe Aufruf nach Ablauf des Wartefensters vollzieht die Übernahme und setzt den alten Claim ausdrücklich außer Kraft.

Meldet sich die andere Person in der Zwischenzeit zurück — ein einziger Heartbeat genügt —, verfällt die Erklärung automatisch. Die Erklärung hält dafür fest, wie lebendig der benannte Claim beim Erklären aussah; jede Bewegung dieses Zeitstempels macht sie zunichte. Das gilt auch dann, wenn die Uhr des anderen Rechners nachgeht und seine Heartbeats deshalb dauerhaft alt aussehen. Und die betroffene Person erfährt von der Erklärung durch den Aufruf, den sie ohnehin ausführt (`takeover_notice`), nicht erst durch ein `status`, an das sie denken müsste.

Ein außer Kraft gesetzter Lauf erfährt das beim nächsten Helferaufruf (`state: superseded`) und hält an, bevor er schreibt. Vollzogene Übergabe und bestätigter Override **entfernen** den ersetzten Claim: Stünde die Verdrängung nur im neuen Claim, hielte sie exakt so lange wie dieser — seine Freigabe gäbe das Wiki an den gerade gestoppten Lauf zurück, mitsamt einem noch gültigen Token.

Der Notfall-Override bleibt daneben bestehen: `acquire --force --reason …` setzt jeden Claim sofort außer Kraft, aber nur nach ausdrücklicher Anwenderbestätigung und mit dokumentiertem Grund. Er beendet keinen bereits laufenden fremden Prozess; darauf weist der Skill vor der Bestätigung hin. Er ist zugleich der einzige Weg, eine Konfliktkopie des Locks selbst zu entfernen — sonst bliebe das Wiki ausweglos in `contended`. Eine solche Konfliktkopie kann auch ein **Verzeichnis** sein: Das Lock-Verzeichnis wird laufend angelegt und wieder entfernt, und genau daraus macht ein Synchronisationsclient eine Ordnerkopie. Das Wurzelverzeichnis wird deshalb auf beide Formen geprüft, und eine kopierte Ordnerfassung wird mit den Claims gemeldet, die sie enthält. Was dabei entfernt wurde, meldet der Erwerb mit Pfad, Prüfsumme und öffentlichem Inhalt, damit der Beleg in den Änderungsbericht wandert statt verloren zu gehen.

### 7.4 Bestehende Ein-Personen-Wikis

Ein Wiki, das noch den alten Einzeldatei-Lock im Format 1 trägt, läuft **ohne Migration** weiter. Er wird als ein einzelner Alt-Claim gelesen, läuft nie ab, sperrt einen zweiten Maintainer wie bisher und wird nur durch sein eigenes Token oder einen bestätigten Override frei. Der nächste Erwerb danach verwendet das Claim-Verzeichnis. Neu ist nur: Eine Konfliktkopie dieses Einzelplatz-Locks im Wiki-Wurzelverzeichnis — der sichtbare Beweis, dass zwei Rechner ihn gleichzeitig hielten — wird jetzt gemeldet, statt unsichtbar zu bleiben.

### 7.5 Was der Lock nicht leistet

Ein Lock, den ein **anderes Gerät** geschrieben hat, wird als solcher ausgewiesen. Auf einer synchronisierten Ablage kann eine Freigabe verspätet ankommen, sodass ein sichtbarer Claim andernorts längst nicht mehr existiert. Der Skill sagt das ausdrücklich — und ebenso, dass Alter allein nie beweist, dass ein Claim verwaist ist. Beim Erwerb auf einer offenbar synchronisierten Ablage weist er einmalig darauf hin, dass der Lock geräteübergreifend nicht erzwingt.

Der Lese-Skill erwirbt keinen Writer-Lock. Er verweigert das Lesen, solange das Claim-Verzeichnis existiert; der letzte ausscheidende Claim entfernt es samt der Betriebssystem-Artefakte, die ein Dateibrowser darin hinterlassen hat, damit kein Leser dauerhaft `wiki_busy` sieht. Bleibt etwas übrig, das der Helfer nicht löschen darf — etwa die temporäre Datei eines abgestürzten Schreibvorgangs —, meldet die Freigabe das ausdrücklich (`lock_directory_remains`) und `status` weist dasselbe Verzeichnis als leserblockierend aus, statt ohne Hinweis `free` zu melden.

Wichtig bei OneDrive oder SharePoint: Das Claim-Modell beseitigt den verlorenen Schreibvorgang und die stille Verdrängung, die der gemeinsame Einzelplatz verursacht hat. Es macht aus dem Synchronisationsclient aber keinen verteilten Lock-Dienst. Zwei zeitweise offline arbeitende Geräte sehen jeweils nur den eigenen Claim und halten sich bis zum Abgleich für allein. Für strikt gleichzeitige Pflege auf mehreren Rechnern wäre eine zentrale Koordination erforderlich.

## 8. Release-, Snapshot- und Historienmodell

Die drei Begriffe erfüllen unterschiedliche Zwecke:

- **Snapshot:** Wiederherstellungspunkt vor einer Pflegeänderung; liegt unter `meta/history/` und gehört nicht zum aktiven Release. Die vollständige Prüfung (`--exhaustive`) durchsucht Snapshots nur zusammen mit `--include-history`.
- **Release:** veröffentlichter, vollständig geprüfter Wissensstand mit semantischer Version und Manifest.
- **Historisierung von Wissen:** ältere oder widersprechende Claims und Seiten bleiben fachlich nachvollziehbar und werden über Status, `replaces` und `contradicts` verbunden.

Das Manifest ist die atomare Lesegrenze. Der Release-Eintrag beschreibt, wann und warum ein neuer Stand veröffentlicht wurde. Snapshots dienen der technischen Wiederherstellung. Claim- und Seitenstatus bilden die fachliche Entwicklung ab. Dadurch wird weder eine reine Dateisicherung mit fachlicher Historie verwechselt noch ein neueres Dokument automatisch zur Wahrheit erklärt.

## 9. Plattform- und Speicherkompatibilität

### Claude Code

Für eine persönliche Installation werden die entpackten Skill-Ordner im persönlichen Claude-Code-Konfigurationsverzeichnis unter `skills/` abgelegt:

```text
skills/maintain-llm-wiki/SKILL.md
skills/query-llm-wiki/SKILL.md
```

Für eine projektbezogene, gemeinsam versionierbare Installation werden sie stattdessen unterhalb des Projekts abgelegt:

```text
.claude/skills/maintain-llm-wiki/SKILL.md
.claude/skills/query-llm-wiki/SKILL.md
```

Claude Code erkennt die Skills über Verzeichnisname und `description`. Die Beschreibungen nennen deshalb die relevanten Pflege- und Lesesituationen ausdrücklich. Beide Skills können automatisch aktiviert oder direkt als `/maintain-llm-wiki` und `/query-llm-wiki` aufgerufen werden.

Gebündelte Helfer und Referenzen werden über `${CLAUDE_SKILL_DIR}` oder relativ zur geladenen `SKILL.md` aufgelöst. Es gibt keine Abhängigkeit vom aktuellen Arbeitsverzeichnis und keine OpenAI-spezifische Metadatendatei im Skill. Das Frontmatter beschränkt sich auf die portablen Felder `name` und `description`, sodass derselbe Skill-Ordner lokal in Claude Code und als hochladbares Skill-Paket verwendet werden kann.

Die `evals/`-Verzeichnisse in den entpackten Entwicklungsordnern enthalten Testszenarien. Sie werden nach der Konvention des offiziellen Anthropic-Packagers nicht in die installierbaren `.skill`-Pakete aufgenommen.

### macOS und Windows

Die eingebauten Helfer verwenden Python 3.9 oder neuer und ausschließlich die Standardbibliothek. Sie sind nicht auf Bash, POSIX-Shebangs oder ausführbare Dateirechte angewiesen. Pfade werden intern plattformgerecht aufgelöst und in erzeugten Daten als relative POSIX-Pfade gespeichert.

Zwei Zusagen gelten für jeden Helfer, den ein Agent direkt aufruft, auch für die Werkzeuge eines exportierten Wissens-Skills:

- **Eigener Suchpfad.** Jeder Helfer setzt sein eigenes Verzeichnis an den Anfang von `sys.path`, bevor er ein Nachbarmodul importiert. Er läuft deshalb auch unter `python -I`, das Sicherheitsleitfäden für Code aus entpackten Archiven empfehlen, sowie ab Python 3.11 unter `python -P` und `PYTHONSAFEPATH=1`. Diese Modi nehmen das Skriptverzeichnis vom Suchpfad; vorher brach dann jeder Helfer mit Nachbarmodulen mit `ModuleNotFoundError` ab. Der Selbsttest des Exporters ruft die exportierten Werkzeuge mit `PYTHONSAFEPATH=1` auf.
- **UTF-8-Ausgabe.** Jeder Helfer stellt beim Start Standardausgabe und Standardfehler auf UTF-8 um, sofern der Datenstrom das erlaubt. Unter Windows schreibt Python umgeleitete Ausgabe sonst in der ANSI-Codepage, und schon ein Zeichen wie „≥" in einer Seite brach die JSON-Ausgabe ab. Helfer, die andere Helfer aufrufen, lesen deren Ausgabe ebenfalls als UTF-8.

`tests/test_entrypoints.py` prüft beides für jeden Einstieg statisch, ruft die Suche beider Skills mit `python -I` auf, liest ihre Ausgabe über eine simulierte cp1252-Umleitung und schickt beiden eine Anfrage über die Standardeingabe in derselben Umgebung.

**Anfrage über die Standardeingabe.** `--request -` liest Bytes, entfernt ein UTF-8-BOM, erkennt UTF-16 und lehnt Nicht-UTF-8 ab. Windows PowerShell 5.1 macht aus Nicht-ASCII-Zeichen in einer Pipe „?"; deshalb schreibt der Agent sie als `\u00fc`-Escapes. Ein „?" direkt vor einem Buchstaben (aus „Kündigung" wird „K?ndigung", aus „Ökostrom" „?kostrom") oder U+FFFD gilt als unterwegs umkodiert und wird abgelehnt. Ein beschädigtes Zeichen am Wortende (aus „süß" wird „s??") fällt dabei nicht auf; verlässlich schützen nur die Escapes. Abgelehnt wird auch ein einzelnes Surrogat-Escape (`\ud800` bis `\udfff` ohne Partner), weil keine UTF-8-Ausgabe es tragen kann. Exit 2 ohne Ausgabe ist ein Aufruffehler, Exit 2 mit Release-JSON `wiki_busy`.

Der konkrete Aufruf der Helfer ist Aufgabe des ausführenden Agenten. Unter Claude Code dient `${CLAUDE_SKILL_DIR}` zur Auflösung des Skill-Verzeichnisses; andere Agent-Skills-Hosts lösen Dateien relativ zur geladenen `SKILL.md` auf.

### SharePoint und OneDrive

Ein Wiki kann in einem lokal synchronisierten SharePoint-/OneDrive-Ordner liegen. Lesen und Schreiben auf Dateiebene folgen dann den Berechtigungen und der Synchronisation dieser Ablage. Die Skills implementieren keine eigene Benutzer- oder Rechteverwaltung.

Der Sync-Client ist dabei ein **zweiter Schreiber** auf demselben Verzeichnis. Die Skills behandeln das ausdrücklich statt es zu ignorieren — Einzelheiten in den Abschnitten 4.19 und 4.20. Kurz:

| Situation | Verhalten |
|---|---|
| Konfliktkopie im Wiki | Lesen stoppt, Release bleibt intakt, Auflösung über Plan/Apply mit Snapshot |
| `.DS_Store`, `Thumbs.db`, `desktop.ini`, `~$…` | wird gemeldet und ignoriert; blockiert nichts und gelangt nie ins Manifest |
| Manifest schon da, Inhalte noch nicht | `sync_in_progress`; Warten statt Reparieren |
| Dateien nur in der Cloud | `hydration_required`; Volumen wird gemeldet, Download nur nach Entscheidung |
| Name oder Pfad, den die Ablage ablehnt | Lint-Fehler, bevor die Datei entsteht |
| Claim von einem anderen Gerät | wird als solcher ausgewiesen; Alter beweist nichts |
| Zwei wirksame Claims | `contended`; niemand schreibt, bis das Team entschieden hat |
| Konfliktkopie eines Claims oder des alten Einzelplatz-Locks | wird gemeldet statt übersehen; der eigene Rechner räumt sie mit `withdraw` weg |
| Release auf synchronisierter Ablage | lokal dauerhaft, Übertragung ausdrücklich unbestätigt |
| Sperrverletzung durch Client oder Virenscanner | begrenzter Wiederholungsversuch, danach klare Ursache |

Empfohlen ist:

- Pflege nur durch klar koordinierte Prozesse;
- Konsum aus einem verifizierten Release;
- keine gleichzeitige Offline-Pflege auf mehreren Geräten;
- SharePoint-Berechtigungen passend zur Rolle vergeben;
- `meta/manifest.json` und die Markdown-Inhalte gemeinsam synchronisieren lassen.

### Skill-only: keine Serverkomponente

Diese Distribution besteht aus **Agent Skills und sonst nichts**. Kein MCP-Server, kein Dienst, kein Hintergrundprozess — auch nicht optional, auch nicht später.

Das ist eine bewusste Produktentscheidung, keine offene Lücke. Ein Wiki ist ein Verzeichnis aus Markdown-Dateien; wer es lesen kann, kann es nutzen. Eine Serverkomponente würde dem Ganzen eine Betriebs-, Update- und Angriffsfläche hinzufügen, die das Dateiformat gerade nicht braucht — und sie würde die Zusicherung aufweichen, dass ein Wiki auch ohne laufende Software vollständig lesbar bleibt.

Praktisch heißt das: Für den Dateizugriff ist ohnehin kein Server nötig. Die Reichweite bleibt damit auf Hosts beschränkt, die Agent Skills laden — Claude Code, Claude Cowork und Codex. Diese Beschränkung wird in Kauf genommen; Tiefe geht hier vor Breite.

## 10. Natürlichsprachliche Verwendung

Der Anwender spricht immer mit dem jeweiligen Skill, nicht mit dessen Skripten.

Beispiele für den Pflege-Skill:

- „Initialisiere in diesem Zielordner ein deutsch gepflegtes Wiki über Vertragswissen.“
- „Nimm diese Dokumente auf und erweitere das bestehende Wiki, ohne Originaldateien hineinzukopieren.“
- „Zeige mir zuerst mögliche Cluster und Begriffswelten und besprich sie mit mir.“
- „Inventarisiere das Frontmatter und zeige mir Abweichungen, aber ändere noch nichts.“
- „Vereinheitliche bestätigte Tag-Werte über einen Plan und zeige mir die Unterschiede vor dem Anwenden.“
- „Verschiebe diese Seite in den bestätigten Cluster und führe alle internen Links nach.“
- „Prüfe, ob ein Cleaning-Review fällig ist, und zeige nur Kandidaten.“
- „Stelle diese beiden Dateien aus Snapshot X wieder her.“
- „Ändere die gepflegte Wiki-Sprache vollständig auf Englisch.“
- „Erzeuge aus dem aktuellen Release einen unveränderlichen Wissens-Skill.“
- „Exportiere das Wiki als Open-Knowledge-Format-Bündel, damit ein anderes Team damit arbeiten kann.“
- „Wie kompatibel ist mein Wiki zum Open Knowledge Format, und was ginge beim Export verloren?“
- „Welche Quellen sind im Wiki noch gar nicht ausgewertet?“
- „Ein Kunde hat gefragt: ‚…‘. Das soll das Wiki immer finden.“
- „Prüfe vor dem Release, ob unsere Auffindbarkeitsfragen noch funktionieren.“

Beispiele für den Lese-Skill:

- „Beantworte diese Frage ausschließlich aus dem Wiki und nenne die Originalquellen.“
- „Was sagt das Wiki zum aktuellen Stand, und welche Aussagen sind strittig?“
- „Zeige nur aktive Inhalte aus dem Cluster Governance.“
- „Vergleiche die historische und die aktuelle Regelung.“
- „Welche Frontmatter-Felder kann ich für Filter verwenden?“
- „Wie aktuell sind Qualitäts- und Cleaning-Prüfung?“
- „Die Frage ist auf Englisch – antworte trotzdem aus dem deutschen Wiki.“
- „Steht im Wiki wirklich nichts zum Balkonkraftwerk?“

## 11. Funktionskatalog des Pflege-Skills

| Funktion | Wirkung | Vorschau/Schutz |
|---|---|---|
| Initialisieren | Wiki-Struktur, Graph, Lint und Erst-Release | Exklusiver Lock, bestehendes Wiki wird nicht überschrieben |
| Quelle registrieren | Treues Markdown und Quellenregister | Duplikatprüfung, portable Referenz |
| Frontmatter inventarisieren | Felder, Typen, Beispiele und Drift | Nur Bericht |
| Frontmatter planen | Auswahl und Vorher/Nachher berechnen | Plan-Hash und Datei-Hashes |
| Frontmatter anwenden | Bestätigte Metadatenänderung | Bestätigung, Hash-Schutz, Snapshot |
| Snapshot erstellen | Wiederherstellungspunkt | Manifest mit Pfaden und Hashes |
| Snapshots auflisten | Verfügbare und ungültige Snapshots | Nur Bericht |
| Restore planen | Gezielte Wiederherstellung vorschlagen | Plan-Hash und Dateivorbedingungen |
| Restore anwenden | Bestätigte Dateien wiederherstellen | Recovery-Snapshot, Hash-Schutz |
| Seite verschieben | Pfad ändern und interne Links nachführen | Vorschau-Hash, Bestätigung, Snapshot |
| Sprachmigration planen | Vollständige Auswirkung ermitteln | Keine Teilmigration |
| Lint | Struktur und Verträge prüfen; Locator-Auflösung, Alias-Statistik zur Bestätigung, Quellenabdeckung als Statistik | Nur sichere deterministische Reparaturen |
| Graph bauen | Graphdaten, HTML-Leseansichten und Gruppenübersichten erzeugen | Nur abgeleitete Dateien |
| Review aufzeichnen | Tatsächliche Qualitäts-/Cleaning-Prüfung dokumentieren | Kein erfundener Zeitstempel |
| Release | Version, Protokoll, Qualität und Manifest veröffentlichen | Strikter Lint, Manifest zuletzt |
| Release verifizieren | Hash-Grenze prüfen | Read-only |
| Wissens-Skill exportieren | Unveränderlichen Release-Abzug erzeugen | Doppelte Manifestprüfung, Selbsttest aller mitgelieferten Werkzeuge |
| Seiten als geprüft aufzeichnen | Vertrauensstufe pro Seite | Plan/Apply, Snapshot, Extra-Bestätigung für `human:` |
| Konfliktkopie auflösen | Sync-Konflikt entscheiden | Beide Seiten im Vergleich, Bestätigung, Snapshot |
| OKF berichten | Kompatibilität mit v0.2 bewerten | Read-only, keine erfundenen Werte |
| OKF-Bündel exportieren | Verifizierten Release als selbsttragendes OKF-v0.2-Bündel schreiben | Read-only, leeres Ziel außerhalb, Selbstvalidierung, Verlustliste im Bündel |
| Beobachtung registrieren | Ereigniswissen als Quelle aufnehmen | Akteur und Anlass sind Pflicht, sonst Ablehnung |
| Sammlung übernehmen (Plan) | Bestehende Markdown-Sammlung berichten | Read-only, Titel aus dem Dokument, Blocker und Hinweise |
| Sammlung übernehmen (Apply) | Bestätigte Dateien als Quellen registrieren | Hash-Bindung, Snapshot, keine Seite unter `wiki/` |
| Auffindbarkeitsfrage aufnehmen | Wörtliche Frage von Eigentümer oder Nutzer mit Ziel-Claim | Nur mit Bestätigung des Ziels, nie vom Agenten formuliert, außerhalb des Releases |
| Auffindbarkeitsfrage entfernen | Eine Frage löschen | Bestätigung, Snapshot der Datei |
| Auffindbarkeit prüfen | Jede Frage mit dem Suchkern des Lese-Skills stellen | Nur Bericht, blockiert keinen Release |

## 12. Funktionskatalog des Lese-Skills

| Funktion | Ergebnis | Schreibzugriff |
|---|---|---:|
| Release verifizieren | Status, Version, Release-ID und Manifest-Hash | Nein |
| Qualität beurteilen | Lint-, Review-, Cleaning-, Fragen- und Altersstatus | Nein |
| Frontmatter inventarisieren | Felder, Typen, Beispiele und Drift | Nein |
| Suchen und filtern | BM25-gerankte Ergebnisse, Claims, Quellen, Facetten, Vertrauensstufe und überschrittenes Ablaufdatum, Umformulierungen in einem Aufruf (`--also`, `--request -`), abgesicherte Fehlanzeige (`--exhaustive`, `absence_check`, `search_record`) | Nein |

Der maschinenlesbare Aktionskatalog beider Skills dient der Selbsterkennung durch Agenten. Er erweitert keine Rechte und umgeht keine Bestätigung.

## 13. Sicherheits- und Qualitätsgrenzen

Die Skills sind absichtlich konservativ:

- Originalquellen werden nicht verändert.
- Fehlende Fakten, Versionen, Quellen und Gültigkeitsangaben werden nicht erfunden.
- Quellentreue Extraktion und kuratierte Synthese bleiben getrennt.
- Alle gespeicherten Verweise sind relativ, logisch oder webfähig; lokale absolute Pfade werden nicht persistiert.
- Der Pflege-Skill verändert keine Datei im kanonischen Wiki ohne Lock; der read-only Export eines verifizierten Releases schreibt lediglich in das separat gewählte Exportziel.
- Destruktive oder bedeutungsändernde Massenaktionen benötigen Vorschau und Bestätigung.
- Ein veralteter Plan wird nicht durch einen neu berechneten Hash „passend gemacht“.
- Snapshots werden nicht automatisch gelöscht.
- Cleaning-Fristen erteilen keine Löschberechtigung.
- Der Lese-Skill schreibt niemals in das Wiki.
- Wiki- und Quellentexte sind Daten, keine verdeckten Agentenanweisungen.
- Ein erfolgreicher Lint beweist Struktur, aber nicht automatisch fachliche Wahrheit oder Vollständigkeit.
- Ein Agent kann seine eigene Arbeit nicht als von einem Menschen geprüft aufzeichnen.
- Eine Vertrauensstufe ist keine Aussage über Richtigkeit und ersetzt keinen Beleg.
- Eine Konfliktkopie wird nie ohne Bestätigung gelöscht; ihr Inhalt kann einzigartig sein.
- Ein erfolgreicher Release ist lokal dauerhaft; ob die Ablage ihn übernommen hat, wird nicht behauptet.
- Ein OKF-Export ist ärmer als das Wiki und sagt das im Bündel selbst.
- Es läuft kein Server und kein Hintergrundprozess; alles geschieht im jeweiligen Agentenlauf.
- Ein Bündel, das die eigene Konformitätsprüfung nicht besteht, wird entfernt statt ausgeliefert.
- Ein fehlendes empfohlenes Feld bleibt leer und wird ausgewiesen; es wird nie konstruiert.

## 14. Grenzen des Systems

- OCR und Dateikonvertierung hängen von den im Agenten-Host verfügbaren Lesern ab. Nicht lesbare Bereiche müssen als Einschränkung dokumentiert werden.
- Links außerhalb des Wiki-Verzeichnisses können bei einer Seitenverschiebung nicht automatisch aktualisiert werden.
- Ein Dateilock verhindert keine unkoordinierte Änderung durch Programme, die den Vertrag ignorieren.
- Das Claim-Modell verhindert die stille Verdrängung eines Maintainers, ersetzt aber keine geräteübergreifende Exklusivität: Bis zwei Geräte abgeglichen sind, sieht jedes nur den eigenen Claim.
- Geprüft wird der Besitz beim Start jedes gelockten Helferaufrufs. Trifft ein fremder Claim ein, während ein Helfer bereits läuft, hält erst der **nächste** Aufruf an — ein einzelner Helferlauf ist die Granularität, unterhalb derer der Lock nicht schützt.
- Eine Uhr, die **vorgeht**, wird erkannt und blockiert (`clock_skew`). Eine Uhr, die **nachgeht**, wird nicht erkannt: Ihre Claims sehen dauerhaft abgelaufen aus. Sie bleiben dennoch geschützt, solange dort gearbeitet wird — jede Bewegung des Heartbeats macht eine Übernahmeerklärung zunichte —, aber ein Claim von einem nachgehenden Rechner, an dem gerade **niemand** arbeitet, wird früher übergabefähig als beabsichtigt.
- OneDrive- und SharePoint-Synchronisation ersetzen keine globale Transaktions- oder Lock-Datenbank.
- Ein eingefrorener Wissens-Skill kennt nur seinen enthaltenen Release und kann nicht feststellen, ob das kanonische Wiki inzwischen weiterentwickelt wurde.
- Metadatenfilter grenzen Suchmengen ein, beweisen aber weder Wahrheit noch Vollständigkeit.
- Die Suche ist lexikalisch: Sie findet Wörter und ihre regelmäßigen Formen, keine Bedeutungen. Synonyme, Umschreibungen und andere Sprachen erreichen die Suche nur über Seiten-Aliase, Begriffswelten und die Umformulierungen des Agenten; Treffer nur aus Umformulierungen sind so gut wie diese und werden getrennt ausgewiesen. Ein leeres Ergebnis beweist nicht, dass ein Thema fehlt; auch die vollständige Prüfung mit `--exhaustive` zeigt nur, dass keine Passage die geprüften Wörter zusammen enthält. Kompositumteile und Tippfehlerkorrekturen sind Heuristiken und können danebenliegen; jeder Treffer nennt deshalb seine Regel. Gemessene Lücken und ein Stufenplan ohne Embedding-Suche stehen in [docs/bedeutungssuche-und-vollstaendigkeit.md](docs/bedeutungssuche-und-vollstaendigkeit.md).
- Automatische Strukturprüfungen ersetzen kein fachliches Review durch einen zuständigen Menschen.
- Die Quellenabdeckung ist nur so fein wie die Locator: Ein Abschnitt auf einer Seite, die ein anderer Claim zitiert, gilt als abgedeckt, Text vor der ersten Seitenmarke zählt zu keiner Einheit, und eine zitierte Seite beweist nicht, dass jeder Fakt darauf übernommen wurde. Auffindbarkeitsfragen messen nur die gespeicherten Formulierungen.
- Die Erkennung einer synchronisierten Ablage ist eine Heuristik auf Pfadnamen und Umgebungsvariablen; es gibt keine unterstützte Schnittstelle zum Zustand eines Sync-Clients.
- Ob eine veröffentlichte Datei die Ablage erreicht hat, kann der Skill nicht feststellen — nur prüfen und warnen.
- Die Erkennung datenloser Dateien ist plattformabhängig und liefert dort, wo kein Signal existiert, ausdrücklich „unbekannt" statt einer Vermutung.
- Vier Punkte des Speicherverhaltens sind dokumentiert, aber nicht auf einer echten Ablage gemessen; sie stehen in [docs/sharepoint-onedrive-implikationen.md](docs/sharepoint-onedrive-implikationen.md) als ausdrücklich offen.

## 15. Dateien dieser Distribution

```text
README.md
docs/                          Analysen und Umsetzungspläne
tests/                         Testsuite; python3 tests/run_tests.py
tests/fixtures/search_quality/ Test-Wiki, Fragen, Umformulierungen und Erwartungen aller drei Tore
tools/package_skills.py        baut die .skill-Pakete reproduzierbar
maintain-llm-wiki.skill
maintain-llm-wiki/
|-- SKILL.md
|-- assets/
|-- evals/evals.json
|-- references/
`-- scripts/
query-llm-wiki.skill
query-llm-wiki/
|-- SKILL.md
|-- evals/evals.json
|-- references/
`-- scripts/
```

Die Testsuite läuft ohne Fremdbibliotheken mit `python3 tests/run_tests.py` und treibt die echten gebündelten Helfer über einen vollständigen Lebenszyklus. `tools/package_skills.py` baut beide `.skill`-Pakete reproduzierbar und schließt `evals/` aus; `--check` prüft, ob die eingecheckten Pakete aktuell sind.

Zur Testsuite gehört ein Präzisionstor für die Suche. `tests/fixtures/search_quality/` enthält ein synthetisches deutschsprachiges Test-Wiki eines fiktiven Stadtwerks (45 Inhaltsseiten, 11 Quellen, 8 Begriffswelten) als Python-Datenmodule, den Bauhelfer `build_fixture.py`, 114 Fragen mit Pflichtseiten (`ground_truth.json`) und die aufgezeichneten Erwartungen (`expectations.json`). Der Bauhelfer veröffentlicht das Wiki mit den echten Helfern in ein Verzeichnis außerhalb des Repositorys (`--out`) und schreibt nichts ins Repository, auch keine Bytecode-Caches neben den Helfern. `tests/test_search_quality.py` baut es in ein temporäres Verzeichnis, stellt alle Fragen und schlägt fehl, wenn

- eine Frage, deren erster Treffer eine Pflichtseite war, keine Pflichtseite mehr auf Rang 1 hat (zwei Pflichtseiten dürfen die Plätze tauschen),
- eine Pflichtseite ihren Platz unter den ersten 3 oder unter den ersten 12 verliert,
- weniger Fragen eine Pflichtseite auf Rang 1 haben oder vollständig gefunden werden als aufgezeichnet (heute 56 Fragen mit einer Pflichtseite auf Rang 1 sowie 64, 74 und 84 von 107 beantwortbaren Fragen unter den ersten 3, 12 und 100),
- die sieben Fragen zu Themen, die das Wiki nicht enthält, zusammen mehr als 31 Treffer unter den ersten 12 liefern oder
- Navigationsseiten mehr als 13 Top-3-Plätze belegen.

Eine bewusst hingenommene Verschlechterung steht mit Begründung in `accepted_regressions`. Nennt der Eintrag `accepted_rank`, gilt die Seite ab dann mit diesem Rang: Verlässt sie später das Band dieses Rangs (bei Rang 4 die ersten 12), schlägt das Tor wieder an. `tests/fixtures/search_quality/record_expectations.py` zeichnet die Erwartungen neu auf. Das ist eine bewusste Entscheidung, die die Messlatte für alle späteren Änderungen verschiebt; sie gehört mit Begründung in die Commit-Nachricht.

Ein zweites Tor misst die Umformulierungen. `reformulations.json` enthält zwei Sätze mit je bis zu vier Umformulierungen für jede der 114 Fragen. Agenten haben sie blind geschrieben: Sie kannten nur die Fragen, nie das Wiki, so wie ein echter Lese-Agent. `reformulation_expectations.json` hält je Satz fest, wo jede Pflichtseite in `results` und in `reformulation_results` stand. Die Klasse `ReformulationGate` in `tests/test_search_quality.py` stellt jede Frage einmal je Satz mit dessen Umformulierungen und schlägt fehl, wenn

- Umformulierungen die Treffer oder das Zählwerk der Frage selbst verändern (hart),
- weniger Fragen zusammen mit dem Block vollständig gefunden werden als aufgezeichnet (heute je Satz 86 unter den ersten 3, 99 und 98 unter den ersten 12, 99 unter den ersten 100),
- eine Pflichtseite ihren Platz unter den ersten 3 oder 12 verliert, wobei der bessere Wert aus Rang in `results` und Position im Block zählt,
- der Block der sieben Fragen zu fehlenden Themen größer wird (heute 41 und 45 Einträge) oder
- eine Navigationsseite in den Block gerät (hart).

`record_expectations.py --reformulations` zeichnet dieses Tor neu auf. Die Sätze stammen aus derselben Modellfamilie, mit der gemessen wird, die Zahlen sind daher eher zu günstig. Sie sind ein Regressionstor, nie ein Ziel, auf das die Suche abgestimmt wird. Ein Satz wird nie geändert, damit das Tor besteht; stattdessen kommt ein neuer Satz hinzu, und die Commit-Nachricht sagt, warum.

Ein drittes Tor prüft die abgesicherte Fehlanzeige. Die Klasse `AbsenceGate` stellt jede Frage einmal je Satz mit dessen Umformulierungen und `--exhaustive` und vergleicht mit `absence_expectations.json`. Sie schlägt fehl, wenn

- eine der sieben Fragen zu fehlenden Themen nicht mehr vollständig ist oder einen Treffer über Wortformen hat (hart),
- eine solche Frage einen heuristischen Treffer hat, der nicht mit Datei, Art und Zeile samt Begründung aufgezeichnet ist (heute nur der eine Absatz bei ne-01 in beiden Sätzen),
- eine Pflichtseite einer beantwortbaren Frage weder in den Ergebnissen noch im Umformulierungsblock noch unter den zurückgegebenen Treffern steht (hart; eine Ausnahme braucht einen Eintrag in `accepted` mit Begründung),
- der antwortende Claim einer der acht Fragen mit vielen Claims nicht erreichbar ist, also weder gedruckt noch als Treffer zurückgegeben noch auf einer gedruckten Seite mit zurückgehaltenen Claims (hart),
- weniger Prüfungen vollständig sind oder weniger antwortende Claims gedruckt oder getroffen werden als aufgezeichnet (heute je 110 vollständige Prüfungen und je 8 Claims),
- eine Navigationsdatei als Trefferseite erscheint (hart; das Tor erkennt `WIKI.md` und jede `index.md` selbst, nicht über den Suchkern, den es prüft) oder
- der Aufruf mit `--exhaustive` an Ergebnissen, Block oder Zählwerk etwas gegenüber derselben Suche mit `--include-sources` ändert (hart).

`record_expectations.py --absence` zeichnet dieses Tor neu auf. Ein neuer heuristischer Treffer bekommt dabei die Markierung `unjudged`; das Tor schlägt an, bis jemand die Passage gelesen und das Urteil als Begründung eingetragen hat. Das Tor braucht auf dem Entwicklungsrechner rund 10 Sekunden.

Die Dateien unter `scripts/` sind interne, deterministische Skill-Ressourcen. `references/` enthält die ausführlichen Verträge und Arbeitsregeln. `evals/evals.json` beschreibt repräsentative Prüfszenarien für die Weiterentwicklung und bleibt außerhalb des installierbaren Archivs. Die beiden `.skill`-Dateien sind die installierbaren ZIP-basierten Pakete mit jeweils genau einem Skill-Ordner als Archivwurzel.

## 16. Weiterentwicklung

Die beiden Rollen sollen auch bei späteren Erweiterungen getrennt bleiben:

- neue Pflege-, Migrations- oder Reparaturfähigkeiten gehören in `maintain-llm-wiki`;
- neue Such-, Filter-, Darstellungs- oder Quellenverfolgungsfähigkeiten ohne Schreibzugriff gehören in `query-llm-wiki`;
- ein zusätzlich exportierter Wissens-Skill ist ein unveränderlicher Abzug eines konkreten Wikis, keine dritte allgemeine Pflegekomponente;
- **Skill-only bleibt bindend.** Keine Erweiterung führt einen Server, Dienst, Hintergrundprozess oder MCP-Endpunkt ein. Wenn eine Fähigkeit ohne solche Komponente nicht geht, gehört sie nicht in diese Distribution;
- der OKF-Export bleibt ein eigenständiges Ziel: Wissen muss dieses Werkzeug wieder verlassen können. Neue Wiki-Fähigkeiten sind daraufhin zu prüfen, ob sie sich abbilden lassen — und wenn nicht, gehört das in die Verlustliste des Bündels statt stillschweigend zu verschwinden;
- Änderungen an gemeinsamen Verträgen wie Frontmatter, Release oder Filtern müssen in beiden Skills kompatibel umgesetzt und gemeinsam getestet werden.

So bleibt das System einfach verständlich: **ein Skill pflegt und veröffentlicht, ein Skill liest und belegt.**
