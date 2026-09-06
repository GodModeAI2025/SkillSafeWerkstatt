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
| Eingefrorenen Wissens-Skill exportieren | Ja | Nein |
| Seiten als geprüft aufzeichnen | Ja, mit Bestätigung | Nein, nur Stufe lesen und nennen |
| Konfliktkopien auflösen | Ja, nach Vergleich und Bestätigung | Nein, nur melden |
| OKF-Bündel exportieren | Ja, aus verifiziertem Release, mit Quellen | Nein |
| Wiki verändern | Ja, kontrolliert | Niemals |

Diese Trennung verhindert, dass eine normale Wissensabfrage versehentlich Dateien verändert oder einen Pflegeprozess auslöst.

## 3. Typischer Aufbau eines erzeugten Wikis

```text
<wiki>/
|-- .llmwiki.lock              nur während einer aktiven Pflege
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
4. Eine Vorprüfung erkennt leere oder beschädigte Extrakte, extreme Fließzeilen, ungeschlossene Codeblöcke sowie auffällige Überschriften, Tabellen und fehlende Seitenmarken.
5. Die Markdown-Fassung wird mit einer stabilen `source_id` unter `sources/` registriert; Quelle und Registereintrag werden gemeinsam veröffentlicht oder gemeinsam verworfen.
6. Wenn Originalbytes verfügbar sind, kann ihr Hash ermittelt werden; ein lokaler absoluter Dateipfad wird trotzdem nicht im Wiki gespeichert.
7. Erst danach wird der Inhalt in die gepflegte Wissensschicht eingeordnet und synthetisiert.

`sources/` enthält damit das **aus dem Original erkannte, treue Markdown**, nicht zwingend die Originaldatei selbst. Das Original darf außerhalb des Wikis verbleiben. Unvollständig lesbares Material wird als `partial` gekennzeichnet und nicht als vollständig extrahiert ausgegeben.

Eine Quelle wird ausschließlich über ihren aktuellen Anhangspfad oder einen ausdrücklich vom Anwender gewählten Pfad geöffnet. Fehlt dieser Pfad oder ist er nicht zugreifbar, fragt der Skill nach erneutem Anhängen beziehungsweise eng begrenztem Zugriff. Er durchsucht weder das gesamte Benutzerverzeichnis noch den Rechner nach einem vermuteten Dateinamen und konstruiert keinen Ersatzpfad.

`sources/` ist ein flaches Verzeichnis nur für registrierte `.md`-Extraktionen. Ein Unterordner `sources/raw/` sowie PDF-, Office-, Bild-, Audio-, Archiv- oder andere Originaldateien im Wiki sind unzulässig und werden vom Linter beanstandet. Muss eine unvollständige Extraktion anhand des Originals ergänzt werden, ist das Original erneut explizit bereitzustellen; sein Vorhandensein wird nicht aus Titel oder `original_ref` abgeleitet.

Byte-identische Quellen werden nicht doppelt aufgenommen. Für Referenzen eignen sich relative Namen, URLs, SharePoint-Element-IDs oder andere portable logische Bezeichnungen.

### 4.3 Wiki-Sprache

Die gepflegte Wiki-Sprache wird bei der Einrichtung ausdrücklich festgelegt und in `schema/WIKI_PROFILE.md` gespeichert.

- Quellen bleiben in `sources/` in ihrer Originalsprache.
- Wiki-Seiten, Zusammenfassungen, Claim-Texte, Clusterbeschreibungen und bevorzugte Begriffe werden in der festgelegten Wiki-Sprache gepflegt.
- Anderssprachige Fachausdrücke können als Aliase in den Begriffswelten erhalten bleiben.
- Eine spätere Sprachänderung ist möglich, gilt aber als vollständige Migration mit Auswirkungsplan, Bestätigung, Snapshot, vollständiger Übersetzung, neuem Graph, Prüfung und Major-Release.

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

Der Locator verweist auf eine nachvollziehbare Stelle wie Seite, Folie, Tabellenblatt, Abschnitt, Überschrift, Absatz oder Zeitmarke in der registrierten Markdown-Quelle.

Eine neuere Quelle macht eine ältere Aussage nicht automatisch ungültig. Ersetzung, Gültigkeitsbereich und Widerspruch werden ausdrücklich dokumentiert. Bei einem Konflikt bleiben beide belegten Positionen sichtbar, solange keine belastbare Auflösung vorliegt.

### 4.6 Cluster und Begriffswelten

Cluster und Begriffswelten sind bewusst getrennt:

**Cluster** steuern Navigation, visuelle Gruppierung im Graph, Kuration und optional die Verzeichnisstruktur. Ein bestätigter Primär-Cluster kann bestimmen, in welchem Unterordner eine Wiki-Seite liegt.

**Begriffswelten** bilden kontrolliertes Vokabular für Suche und Terminologie. Sie enthalten einen bevorzugten Begriff, Definitionen, Aliase und optionale Beziehungen zu übergeordneten oder verwandten Begriffen.

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
2. **Qualitätsreview:** semantische Prüfung von Belegen, Gültigkeit, Dubletten, offenen Fragen, Sprache, Seitengrenzen, Clustern und Begriffswelten.
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

Beide Dateien werden beim Einrichten aus einem hashgebundenen, bestätigten Vorschlag erzeugt. Spätere Änderungen verwenden denselben Vorschau-/Bestätigungsmechanismus und einen Snapshot. `SOUL.md` steuert keine Dateiberechtigungen, hebt keine Sicherheitsregeln auf und macht gewöhnliche Wiki- oder Quellentexte nicht zu Agentenanweisungen.

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

### 4.16 Eingefrorener Wissens-Skill

Der Pflege-Skill kann einen verifizierten Release als eigenständigen Wissens-Skill exportieren. Dieser Export:

- enthält genau einen veröffentlichten Wiki-Stand;
- ist unveränderlich und nicht selbstpflegend;
- besitzt keinen Ingest-, Pflege-, Release-, Lock- oder Restore-Code;
- enthält nur Verifikation, Suche und Qualitätsbewertung sowie benötigte read-only Bibliotheken;
- bindet alle Inhalte über das ursprüngliche Release-Manifest;
- enthält keine absoluten Quellpfade, Tokens oder transienten Locks;
- wird als Skill-Ordner und `.skill`-Paket erzeugt.

Soll der Inhalt aktualisiert werden, wird das kanonische Wiki gepflegt und veröffentlicht. Danach wird ein neuer eingefrorener Skill-Abzug erstellt; der alte Export wird nicht direkt bearbeitet.

### 4.17 Gestufte Orientierung

Ein einziger Wurzelindex muss jede Seite auflisten. Die Kosten, sich in einem Wiki zu orientieren, wachsen damit mit seiner Größe — und zwar **bevor** eine einzige Seite gelesen wurde. Jedes befüllte Unterverzeichnis unter `wiki/` trägt deshalb eine erzeugte `index.md` mit den Seiten seiner Gruppe.

Der Lese-Skill liest gestuft: Wurzelindex → passender Zweigindex → Seiten. Eine Seite gilt als aufgeführt, wenn der für sie zuständige Index sie nennt. Ein Wurzelindex, der weiterhin alles auflistet, bleibt gültig — bestehende Wikis brechen nicht.

**Diese Dateien werden erzeugt, nicht gepflegt.** Der Graphlauf schreibt sie, eine Handänderung überlebt den nächsten Lauf nicht, und der Linter meldet einen veralteten, fehlenden oder verwaisten Index genauso wie einen veralteten Graphen.

Das war eine bewusste Ausnahme: Es sind die ersten erzeugten Dateien in der kuratierten Schicht `wiki/`. Zwei Gründe geben den Ausschlag. `wiki/index.md` liegt bereits dort und ist bereits Navigation statt Wissen — ein Zweigindex erweitert also eine vorhandene Kategorie, statt eine neue zu schaffen. Und unter `graph/` erzeugt würden die Indizes nicht reduzieren, was der Lese-Skill als Markdown lädt; genau das war der Zweck.

Ein Index nennt nur, **was vom Normalfall abweicht**. Eine Beschreibung trägt jede Seite, gekappt auf 100 Zeichen. Der Status erscheint nur, wenn die Seite nicht `active` ist, die Vertrauensstufe nur, wenn eine Bestätigung vorliegt. `active` und `unverified` auf jeder Zeile zu wiederholen würde Tokens kosten, um nichts zu sagen — und die eine abgelöste oder tatsächlich geprüfte Seite unsichtbar machen.

**Der Gewinn ist bedingt, und das gehört gesagt.** Bei einer Handvoll Seiten in einer Gruppe kostet ein Zweigindex mehr als ein flacher Wurzelindex, weil er je Seite eine Beschreibung trägt. Zwei Eigenschaften gelten aber immer: Ein Wurzelindex, der auf Zweige verweist, wächst nicht mit der Seitenzahl. Und ein Zweigindex ist deutlich billiger als die Seiten, die er beschreibt — gemessen unter der Hälfte. Beides ist als Test festgehalten.

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
- **Gesperrter Name oder Zeichen:** Namen wie `.lock`, `CON`, `AUX`, `NUL`, `COM0`–`COM9`, `LPT0`–`LPT9`, `desktop.ini`, alles mit `~$` am Anfang oder `_vti_` an beliebiger Stelle, die Zeichen `" * : < > ? / \ |`, führende und schließende Leerzeichen sowie ein schließender Punkt. Das sind Lint-Fehler, weil solche Dateien die Ablage stillschweigend nie erreichen.

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

### 4.22 Selbstbeschreibender Aktionskatalog

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
- `invalid_wiki`: Release oder Dateien sind nicht verifizierbar; daraus wird keine Sachantwort erzeugt.
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
2. Bestätigte Begriffswelten erweitern Suchbegriffe um bevorzugte Bezeichnungen und Aliase.
3. Relevante Seiten und vollständige Claim-Blöcke werden gelesen.
4. Jeder materielle Claim wird über `source_id@locator` zur registrierten Markdown-Quelle verfolgt.
5. Bei exakten Formulierungen wird die entsprechende Quellenstelle gelesen.
6. Offene Fragen und Konflikte werden berücksichtigt.
7. Historie wird nur bei historischen, abgelösten oder zeitlichen Fragestellungen einbezogen.

Der Skill unterscheidet in der Antwort zwischen belegter Tatsache, gepflegter Synthese, Schlussfolgerung und offener Frage. Wenn das Wiki die Antwort nicht trägt, benennt er die Lücke statt sie aus allgemeinem Wissen zu füllen.

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

Der Katalog enthält keine Pflege-, Cleaning-, Snapshot-, Restore-, Lock- oder Schreibaktion.

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
2. Er prüft bestehende Regeln, Profil, Index, Cluster, Begriffe und relevante Seiten.
3. Neue Quellen werden registriert; Duplikate werden übersprungen.
4. Vor direkten Änderungen entsteht ein Snapshot.
5. Inhalte werden inkrementell ergänzt, Konflikte und offene Fragen werden dokumentiert.
6. Betroffene Navigation und Graphansichten werden aktualisiert.
7. Lint und Release veröffentlichen genau einen neuen konsistenten Stand.
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
4. Relevante Claims und Quellenstellen werden vollständig gelesen.
5. Die Antwort nennt Unsicherheit, Konflikte und Quellen nachvollziehbar.
6. Eine zweite Release-Prüfung verhindert eine Antwort aus einem veränderten Mischstand.

## 7. Sperr- und Nebenläufigkeitsmodell

Jeder Pflege-, Validierungs- oder Release-Lauf besitzt während seiner gesamten Dauer `<wiki>/.llmwiki.lock`. Der Lock enthält öffentliche Laufdaten und nur den Hash eines privaten Besitz-Tokens. Das Token liegt in einer privaten Runtime-Datei außerhalb des Wikis, wird nur durch den eingeschränkten Helper-Wrapper eingelesen und weder ausgegeben noch in Prompts, Delegationen, Wiki-Inhalte oder Berichte übernommen. Beim Freigeben werden Lock und Runtime-Datei entfernt.

Existiert bereits ein Lock, startet kein zweiter konformer Pflegeprozess. Der Skill nimmt nicht allein aufgrund des Alters an, dass ein Lock verwaist ist. Ein erzwungenes Übernehmen ist nur nach ausdrücklicher Anwenderbestätigung und mit dokumentiertem Grund zulässig.

Ein Lock, den ein **anderes Gerät** geschrieben hat, wird als solcher ausgewiesen. Auf einer synchronisierten Ablage kann eine Freigabe verspätet ankommen, sodass ein sichtbarer Lock andernorts längst nicht mehr existiert. Der Skill sagt das ausdrücklich — und ebenso, dass Alter allein nie beweist, dass ein Lock verwaist ist. Beim Erwerb auf einer offenbar synchronisierten Ablage weist er einmalig darauf hin, dass der Lock geräteübergreifend nicht schützt.

Der Lese-Skill erwirbt keinen Writer-Lock. Er verweigert das Lesen, solange ein Pflege-Lock existiert.

Wichtig bei OneDrive oder SharePoint: Der Dateilock ist ein kooperativer Lock auf dem sichtbaren Dateisystem. Synchronisationsclients sind kein verteilter Lock-Dienst. Zwei zeitweise offline arbeitende Geräte können theoretisch unabhängig lokale Lock-Dateien erzeugen. Für strikt gleichzeitige Pflege auf mehreren Rechnern wäre eine zentrale Koordination erforderlich. Für einen einzelnen Pflegeprozess auf einer synchronisierten Arbeitskopie ist keine zusätzliche Serverkomponente notwendig.

## 8. Release-, Snapshot- und Historienmodell

Die drei Begriffe erfüllen unterschiedliche Zwecke:

- **Snapshot:** Wiederherstellungspunkt vor einer Pflegeänderung; liegt unter `meta/history/` und gehört nicht zum aktiven Release.
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
| Lock von einem anderen Gerät | wird als solcher ausgewiesen; Alter beweist nichts |
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

Beispiele für den Lese-Skill:

- „Beantworte diese Frage ausschließlich aus dem Wiki und nenne die Originalquellen.“
- „Was sagt das Wiki zum aktuellen Stand, und welche Aussagen sind strittig?“
- „Zeige nur aktive Inhalte aus dem Cluster Governance.“
- „Vergleiche die historische und die aktuelle Regelung.“
- „Welche Frontmatter-Felder kann ich für Filter verwenden?“
- „Wie aktuell sind Qualitäts- und Cleaning-Prüfung?“

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
| Lint | Struktur und Verträge prüfen | Nur sichere deterministische Reparaturen |
| Graph bauen | Graphdaten, HTML-Leseansichten und Gruppenübersichten erzeugen | Nur abgeleitete Dateien |
| Review aufzeichnen | Tatsächliche Qualitäts-/Cleaning-Prüfung dokumentieren | Kein erfundener Zeitstempel |
| Release | Version, Protokoll, Qualität und Manifest veröffentlichen | Strikter Lint, Manifest zuletzt |
| Release verifizieren | Hash-Grenze prüfen | Read-only |
| Wissens-Skill exportieren | Unveränderlichen Release-Abzug erzeugen | Doppelte Manifestprüfung |
| Seiten als geprüft aufzeichnen | Vertrauensstufe pro Seite | Plan/Apply, Snapshot, Extra-Bestätigung für `human:` |
| Konfliktkopie auflösen | Sync-Konflikt entscheiden | Beide Seiten im Vergleich, Bestätigung, Snapshot |
| OKF berichten | Kompatibilität mit v0.2 bewerten | Read-only, keine erfundenen Werte |
| OKF-Bündel exportieren | Verifizierten Release als selbsttragendes OKF-v0.2-Bündel schreiben | Read-only, leeres Ziel außerhalb, Selbstvalidierung, Verlustliste im Bündel |

## 12. Funktionskatalog des Lese-Skills

| Funktion | Ergebnis | Schreibzugriff |
|---|---|---:|
| Release verifizieren | Status, Version, Release-ID und Manifest-Hash | Nein |
| Qualität beurteilen | Lint-, Review-, Cleaning-, Fragen- und Altersstatus | Nein |
| Frontmatter inventarisieren | Felder, Typen, Beispiele und Drift | Nein |
| Suchen und filtern | BM25-gerankte Ergebnisse, Claims, Quellen, Facetten und Vertrauensstufe | Nein |

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
- OneDrive- und SharePoint-Synchronisation ersetzen keine globale Transaktions- oder Lock-Datenbank.
- Ein eingefrorener Wissens-Skill kennt nur seinen enthaltenen Release und kann nicht feststellen, ob das kanonische Wiki inzwischen weiterentwickelt wurde.
- Metadatenfilter grenzen Suchmengen ein, beweisen aber weder Wahrheit noch Vollständigkeit.
- Automatische Strukturprüfungen ersetzen kein fachliches Review durch einen zuständigen Menschen.
- Die Erkennung einer synchronisierten Ablage ist eine Heuristik auf Pfadnamen und Umgebungsvariablen; es gibt keine unterstützte Schnittstelle zum Zustand eines Sync-Clients.
- Ob eine veröffentlichte Datei die Ablage erreicht hat, kann der Skill nicht feststellen — nur prüfen und warnen.
- Die Erkennung datenloser Dateien ist plattformabhängig und liefert dort, wo kein Signal existiert, ausdrücklich „unbekannt" statt einer Vermutung.
- Vier Punkte des Speicherverhaltens sind dokumentiert, aber nicht auf einer echten Ablage gemessen; sie stehen in [docs/sharepoint-onedrive-implikationen.md](docs/sharepoint-onedrive-implikationen.md) als ausdrücklich offen.

## 15. Dateien dieser Distribution

```text
README.md
docs/                          Analysen und Umsetzungspläne
tests/                         Testsuite; python3 tests/run_tests.py
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
