# Was SkillSafeWerkstatt von `okf-agent-memory` lernen kann

Analyse und Umsetzungsplan
Stand: 2026-09-06
Untersuchtes Fremdprojekt: <https://github.com/okf-memory/okf-agent-memory>
Zugrundeliegende Spezifikation: [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format), Google Cloud

---

## 1. Kurzfazit

Die beiden Projekte lösen **verschiedene Probleme** und sind daher nicht Konkurrenten, sondern
komplementär.

- `okf-agent-memory` ist ein **Agenten-Gedächtnis**: Es hält fest, was ein Agent während seiner
  eigenen Arbeit gelernt hat. Optimiert auf niedrige Schreibhürde, schnelles Wiederfinden und
  einen offenen Standard.
- SkillSafeWerkstatt ist eine **belegte Wissenskuration**: Sie überführt menschliches
  Ausgangsmaterial in eine geprüfte, quellenverankerte und versionierte Wissensschicht. Optimiert
  auf Nachweisbarkeit, Integrität und kontrollierte Veränderung.

In den Kerndisziplinen ist SkillSafeWerkstatt dem Fremdprojekt **deutlich überlegen**: Claim-Belege
mit Stellengenauigkeit, Release-Manifest als Hash-Grenze, Plan/Apply-Transaktionen,
Snapshot/Restore, Writer-Lock, bestätigte Identität. Nichts davon existiert in `okf-agent-memory`.

Der Lerngewinn liegt an anderer Stelle — in fünf Punkten, von denen zwei substanziell sind:

| # | Lernpunkt | Wert | Aufwand |
|---|---|---|---|
| 1 | **Vertrauensstufe pro Seite** (`generated` / `verified` / Trust-Tier) | hoch | mittel |
| 2 | **Progressive Disclosure** über Verzeichnis-Indizes | hoch | mittel |
| 3 | OKF v0.2 als echtes Export-/Interop-Ziel statt v0.1-Report | mittel | mittel |
| 4 | BM25 statt handgewählter Score-Gewichte | mittel | niedrig |
| 5 | Read-Before-Write als eigener Wissenspfad ohne Ausgangsdokument | mittel | niedrig |

Ein **struktureller Blocker** zieht sich durch die Punkte 1 und 3 und bestimmt den Plan: Der
Frontmatter-Parser von SkillSafeWerkstatt lehnt verschachtelte Strukturen hart ab
(`frontmatter_contract.py:119` „nested mappings are not supported"), während genau die neuen
OKF-v0.2-Vertrauensfelder verschachtelt sind. Abschnitt 5.1 behandelt diese Entscheidung.

---

## 2. Was `okf-agent-memory` ist

Ein Fünf-Schichten-Stapel um ein `knowledge/`-Verzeichnis aus Markdown mit YAML-Frontmatter:

1. **OKF v0.2** — normatives Format (Google Cloud, herstellerneutral)
2. **Agent Memory Convention** — Verhaltensregeln für Agenten
3. **Agent Skill** — Prompts und Arbeitsabläufe
4. **Go-Tooling** — Parser, Validator, Suche, MCP-Server als abhängigkeitsfreie Binärdatei
5. **Wissenskorpus** — projektspezifische OKF-Bündel

Verzeichnisaufbau:

```text
knowledge/
|-- index.md          Wurzelindex, trägt okf_version, kein sonstiges Frontmatter
|-- log.md            chronologisches Änderungsjournal
|-- project/
|   `-- index.md      Verzeichnisindex
|-- architecture/
|   `-- index.md
|-- convention/
`-- roadmap/
```

CLI-Oberfläche:

```text
okf validate knowledge --strict --drift
okf search "architecture layers" knowledge [--json]
okf show architecture/layers knowledge [--json]
okf create decisions/auth-flow knowledge --type Decision
okf update <id> knowledge --desc "..."
okf relate <src> <target> knowledge --desc "..."
okf bootstrap /path/to/project --name "My Project"
okf mcp knowledge
```

Beworbene Kennzahlen: Suche unter 300 µs über In-Memory-BM25, Prozessstart unter 4 ms, keine
API-Kosten, unter 15 MB Speicher.

### Die zehn Agentengarantien der Convention

1. Dauerhaftes Wissen gehört in den OKF-Korpus, nicht in den Gesprächsverlauf
2. Vor dem Schreiben suchen
3. Aktualisieren statt duplizieren
4. Keine Gedankenketten speichern, nur belastbare Fakten und Entscheidungen
5. Provenienz erhalten
6. Unsicherheit erhalten, Schlussfolgerung als solche kennzeichnen
7. Bedeutsame Historie erhalten statt stillem Überschreiben
8. Nach umfangreicher Arbeit ein Wissensreview durchführen
9. Änderungen validieren
10. Persistenz nie behaupten, ohne sie bestätigt zu haben

Die Punkte 2 bis 7 und 10 sind in SkillSafeWerkstatt bereits abgedeckt, teilweise strenger.
Punkt 8 ist der interessante: ein Review-Trigger, der an *Arbeit* hängt, nicht an einem Kalender.

### Die OKF-v0.2-Felder

```yaml
type: Decision                       # einzige Pflichtangabe
title: ...                           # empfohlen
description: ...                     # empfohlen
resource: https://...                # empfohlen, URI des zugrundeliegenden Assets
tags: [a, b]                         # empfohlen
status: draft | stable | deprecated  # Vorgabewert: stable
stale_after: 2026-12-31T00:00:00Z    # absoluter Zeitpunkt
generated: { by: agent/cli, at: 2026-09-04T08:43:46Z }
verified:  { by: human:ahormati, at: ... }   # auch als Liste zulässig
sources:
  - id: convention
    resource: ../../docs/CONVENTION.md
    title: OKF Agent Memory Convention v0.1
    author: ...
    usage_count: 3
    last_modified: 2026-08-27
usage_window: { from: ..., to: ... }
```

**Akteurskonvention:** `agent/<version>` für Agenten, `human:<id>` für Menschen, `process:<id>`
für automatisierte Prozesse.

**Abgeleitete Vertrauensstufe:** kein `verified` → *unverified*; nur nicht-menschliche Akteure →
*machine-confirmed*; mindestens ein menschlicher Akteur → *human-reviewed*.

**Konzepttyp „Attested Computation":** ein Wissensobjekt, das sanktionierten Rechencode plus
Verifikationslogik trägt. Der Agent füllt ausschließlich benannte Parameter, schreibt die
Berechnung nie um.

**Konformitätsregeln:** Konsumenten *dürfen nicht* ablehnen wegen fehlender optionaler Felder,
unbekannter `type`-Werte, unbekannter Zusatzschlüssel, gebrochener Querverweise oder fehlender
`index.md`. OKF ist bewusst permissiv.

---

## 3. Strukturvergleich

| Eigenschaft | SkillSafeWerkstatt | okf-agent-memory |
|---|---|---|
| Wissensherkunft | menschliches Ausgangsmaterial (PDF, Office, Audio) | Arbeit des Agenten selbst |
| Belegtiefe | Claim → `source_id@locator` → Seite/Folie/Zeitmarke | `sources` auf Dokumentebene |
| Belegpflicht | Linter erzwingt Quellen auf aktiven Seiten | keine |
| Statusmodell | active, disputed, superseded, unsourced + `replaces`/`contradicts` | draft, stable, deprecated |
| Vertrauensstufe pro Seite | **fehlt** | generated / verified / Trust-Tier |
| Verfallsdatum pro Seite | **fehlt** (global in `QUALITY_POLICY.md`) | `stale_after` |
| Nebenläufigkeit | kooperativer Writer-Lock mit Token-Hash | Git |
| Veröffentlichungsgrenze | Release + `meta/manifest.json` als Hash-Grenze | keine |
| Massenänderung | Plan/Apply, hash-gebunden, null Schreibvorgänge bei Drift | direktes Schreiben |
| Wiederherstellung | Snapshots + gezieltes Restore mit Manifest | `git checkout` |
| Identität/Antwortform | `SOUL.md`, bestätigt und hash-gebunden | keine |
| Rollentrennung | zwei Skills, Lesen ist technisch schreibunfähig | ein Werkzeug |
| Frontmatter | eingeschränkte, flache Teilmenge, strikt | volles YAML, permissiv |
| Suche | gewichtete Heuristik in Python | BM25 in Go |
| Progressive Disclosure | ein `wiki/index.md` | `index.md` je Verzeichnis |
| Fremdintegration | Skill-Hosts (Claude Code, Cowork, Codex) | zusätzlich MCP über stdio |
| Visualisierung | Graph + statische HTML-Leseansichten | keine |
| Standardbezug | eigener Vertrag + OKF-Bericht (v0.1-Niveau) | OKF v0.2 nativ |

Die Tabelle zeigt das Muster: SkillSafeWerkstatt ist überall dort stärker, wo es um **Nachweis und
Kontrolle** geht. `okf-agent-memory` ist dort stärker, wo es um **Interoperabilität, Zugriffskosten
und Selbstauskunft über Vertrauenswürdigkeit** geht.

---

## 4. Die Befunde im Einzelnen

### Befund 1 — Vertrauen ist wiki-global, nicht seitengenau

**Beobachtung.** Qualitätsreviews werden in `meta/quality-reviews.jsonl` als Ereignisse für das
gesamte Wiki geführt. Der Lese-Skill gibt daraus eine Zeile wie `Wiki-Qualität: aktuell` aus.

**Das Problem.** Ein Wiki mit 200 Seiten, von denen ein Mensch 12 gegengelesen hat, meldet
denselben Qualitätsstatus wie eines, in dem alle 200 geprüft wurden. Auf die Frage „Hat das
jemand geprüft?" kann das System heute nur mit „irgendwann wurde irgendetwas geprüft" antworten.
Für ein Produkt, dessen Name Sicherheit verspricht, ist das die größte inhaltliche Lücke.

**Was OKF besser macht.** `generated` und `verified` stehen im Frontmatter der einzelnen Seite,
mit Akteur und Zeitpunkt. Die Vertrauensstufe wird daraus abgeleitet, nicht separat gepflegt. Die
Akteurskonvention unterscheidet sauber zwischen Agent, Mensch und Prozess — und die Convention
verbietet ausdrücklich, Agentenarbeit als menschlich geprüft auszuweisen.

**Empfehlung.** Vertrauensstufe seitengenau einführen. Der Lese-Skill soll pro Antwort ausweisen
können, auf welcher Vertrauensstufe die tragenden Claims stehen. Das ist die wertvollste einzelne
Übernahme aus dem Fremdprojekt.

### Befund 2 — Progressive Disclosure fehlt

**Beobachtung.** `lint_wiki.py:30` führt genau eine Indexdatei als Pflicht: `wiki/index.md`. Die
Unterverzeichnisse `concepts/`, `entities/`, `topics/`, `comparisons/` haben keine eigenen Indizes.

**Das Problem.** Der Lese-Skill orientiert sich laut Antwortvertrag zuerst an `wiki/index.md`. Bei
wachsendem Wiki wächst diese eine Datei linear mit. Ab einigen hundert Seiten verbraucht die reine
Orientierung einen erheblichen Teil des Kontextfensters, bevor eine einzige Seite gelesen wurde.

**Was OKF besser macht.** Ein `index.md` je Verzeichnis. Der Agent lädt den Wurzelindex, wählt
einen Zweig, lädt dessen Index, und erst dann Seiten. Das Projekt beziffert die Ersparnis mit
80 Prozent — diese Zahl ist Eigenwerbung und ungeprüft, aber die Richtung stimmt.

**Empfehlung.** Verzeichnis-Indizes als generierte, nicht handgepflegte Artefakte einführen —
analog zu `graph/pages/`. Sie werden aus dem Frontmatter der enthaltenen Seiten erzeugt und beim
Release neu gebaut. Damit entsteht kein zusätzlicher Pflegeaufwand und keine zweite Wahrheit.

### Befund 3 — Der OKF-Bericht prüft gegen v0.1

**Beobachtung.** `report_okf.py:18` prüft `type` als Pflichtfeld und `title`, `description`,
`resource`, `tags`, `timestamp` als empfohlen. Das entspricht OKF v0.1.

**Das Problem.** Erstens ist `timestamp` kein OKF-v0.2-Feld — das Skript prüft gegen eine Kombination,
die die aktuelle Spezifikation so nicht kennt. Zweitens bleiben die eigentlich interessanten
v0.2-Felder ungeprüft: `generated`, `verified`, `status`, `stale_after`, `sources`, `okf_version`.
Drittens ist der Bericht reine Diagnose ohne Ausgabepfad — er sagt, was fehlen würde, erzeugt aber
kein OKF-Bündel.

**Was OKF besser macht.** Nichts, was SkillSafeWerkstatt nicht könnte. Der Befund ist schlicht,
dass das vorhandene Feature veraltet ist.

**Empfehlung.** Bericht auf v0.2 heben und um einen echten Export ergänzen: aus einem verifizierten
Release ein konformes OKF-Bündel schreiben. Das kostet wenig, weil die semantische Substanz — Typ,
Status, Quellen, Historie — bereits vorhanden ist; es ist überwiegend eine Abbildungsfrage.

Bereits sauber abbildbar:

| SkillSafeWerkstatt | OKF v0.2 | Anmerkung |
|---|---|---|
| `type` | `type` | direkt |
| `title` | `title` | direkt |
| `description` | `description` | direkt |
| `tags` | `tags` | direkt |
| `status: active` | `status: stable` | Abbildung |
| `status: superseded` | `status: deprecated` | Abbildung |
| `status: disputed` | `status: draft` + Hinweis | verlustbehaftet, dokumentieren |
| `sources: [[wikilink]]` | `sources: [{id, resource, title}]` | Anreicherung aus `meta/sources.jsonl` |
| Claim + Locator | — | **kein OKF-Gegenstück, geht beim Export verloren** |
| Review in `quality-reviews.jsonl` | `verified: {by, at}` | erst nach Befund 1 möglich |

Die Zeile „Claim + Locator" ist wichtig: Ein OKF-Export ist notwendigerweise **ärmer** als das
Original. Er ist eine Interoperabilitätsansicht, kein gleichwertiges Format. Das muss der Export
im erzeugten Bündel selbst dokumentieren.

### Befund 4 — Das Suchranking ist eine ungeeichte Heuristik

**Beobachtung.** `search_wiki.py:207` vergibt feste Gewichte: `6.0` für Trefferabdeckung, `8.0` für
einen weiteren Bonus, `12.0` je passendem Konzept, `3.0`, `-0.5`, `-2.0` für Statusanpassungen.

**Das Problem.** Der Score ist weder längennormalisiert noch IDF-gewichtet. Häufige Begriffe zählen
so viel wie seltene; lange Seiten sammeln mehr Treffer und ranken systematisch höher. Bei einem
kleinen Wiki fällt das nicht auf, bei einem großen sortiert es falsch.

**Was OKF besser macht.** BM25 löst genau diese beiden Probleme und ist ein etablierter, erklärbarer
Standard. Die Go-Laufzeit ist für SkillSafeWerkstatt irrelevant — der Algorithmus ist es nicht.

**Empfehlung.** BM25 als **Basis-Score** in reiner Standardbibliothek (etwa 40 Zeilen), die
bestehenden Konzept- und Status-Boni als **Aufschlag darauf** erhalten. Die Boni sind ein echter
Vorteil gegenüber dem Fremdprojekt, das kein kontrolliertes Vokabular kennt; sie dürfen nicht
wegoptimiert werden.

### Befund 5 — Kein Pfad für Wissen ohne Ausgangsdokument

**Beobachtung.** Der Wissenszufluss läuft ausschließlich über Ingest: Original → treues Markdown →
`sources/` → Kuration. Der Linter erzwingt konsequenterweise Quellen auf aktiven Seiten
(`lint_wiki.py:580`).

**Das Problem.** Erkenntnisse, die *bei der Arbeit* entstehen — eine getroffene Entscheidung, ein
im Gespräch geklärter Sachverhalt, eine beobachtete Eigenheit — haben kein Ausgangsdokument. Heute
müssen sie entweder künstlich zu einer Quelle gemacht oder weggelassen werden. In der Praxis heißt
das: Sie werden weggelassen.

**Was OKF besser macht.** Der Read-Before-Write-Loop macht das Festhalten solcher Erkenntnisse zum
Regelfall, mit expliziten Reflexionsfragen nach jeder größeren Arbeit („Was habe ich gelernt? Habe
ich wichtige Entscheidungen getroffen?"). Provenienz wird dabei nicht aufgegeben, sondern
umdefiniert: Der Agentenlauf *ist* die Quelle, ausgewiesen über `generated`.

**Empfehlung.** Einen Quellentyp „Beobachtung" einführen, der auf ein Ereignis statt auf ein
Dokument verweist. Entscheidend ist, dass die Belegpflicht dabei **nicht** aufgeweicht wird: Eine
so entstandene Seite ist eine registrierte Quelle mit Akteur und Zeitpunkt, sie steht auf der
Vertrauensstufe *unverified*, und der Lese-Skill weist sie als solche aus. Ohne Befund 1 sollte
dieser Punkt nicht umgesetzt werden — sonst entsteht unbelegtes Wissen ohne sichtbare Kennzeichnung.

### Befund 6 — Attested Computation als Wissensobjekt

**Beobachtung.** `run_locked.py:27` führt eine Allowlist erlaubter Helfer. Der Gedanke „nur
sanktionierter Code läuft" ist also vorhanden, aber als Implementierungsdetail des Skills.

**Was OKF besser macht.** OKF hebt denselben Gedanken auf die Wissensebene: Ein geprüfter Rechenweg
wird selbst zum Konzept, mit `runtime`, `parameters`, `computation`, `executor` und `attester`. Der
Agent füllt Parameterwerte, nie die Berechnung.

**Empfehlung.** Für Wikis mit Rechenlogik — Fristen, Umlagen, Schwellenwerte — wäre das ein
sinnvoller Seitentyp. Für die aktuelle Ausbaustufe ist es **nicht vorrangig**. Aufnehmen als
bewusst zurückgestellte Option, nicht in die Umsetzung.

### Befund 7 — Kein MCP-Zugang

**Beobachtung.** README §9 stellt zutreffend fest, dass für reinen Dateizugriff kein MCP-Server
nötig ist.

**Die Abwägung.** Das Argument ist für den *Dateizugriff* richtig und für die *Reichweite* falsch.
Ohne MCP ist das Wiki nur für Hosts nutzbar, die Agent Skills laden. Mit einem read-only
MCP-Server über einen verifizierten Release wäre es für jeden MCP-fähigen Agenten nutzbar — bei
unverändertem Sicherheitsmodell, weil der Server nur lesen kann.

**Empfehlung.** Aufnehmen als eigenständige Ausbaustufe nach den Befunden 1 bis 4. Nicht vorziehen:
Der Nutzen ist Reichweite, nicht Qualität, und die Qualitätslücken sind zuerst zu schließen.

### Befund 8 — Kein Adoptionspfad für bestehende Verzeichnisse

**Beobachtung.** Die Initialisierung baut außerhalb des Ziels auf und weigert sich, in ein nicht
leeres Verzeichnis zu schreiben. Das ist als Schutz richtig.

**Die Lücke.** `okf bootstrap` kann sich in ein bestehendes Projekt einfügen. SkillSafeWerkstatt hat
keinen Weg, eine vorhandene Markdown-Sammlung zu übernehmen — nur den Weg über erneuten Ingest.

**Empfehlung.** Ein *Adoptionsbericht* im Plan/Apply-Muster: Ein bestehendes Verzeichnis wird
analysiert, das Ergebnis zeigt, welche Dateien vertragskonform übernommen werden könnten, welche
Felder fehlen und welche Quellen nicht rekonstruierbar sind. Die Übernahme selbst bleibt bestätigt
und hash-gebunden. Niedrige Priorität, aber sauber in das vorhandene Muster einpassbar.

---

## 5. Was bewusst nicht übernommen werden sollte

Die folgenden Eigenschaften von `okf-agent-memory` sind für dessen Zweck richtig und für
SkillSafeWerkstatt schädlich:

- **Permissive Konformität.** OKF verbietet Konsumenten, wegen gebrochener Querverweise oder
  fehlender Indizes abzulehnen. Der strikte Linter ist der Kern des Produktversprechens und bleibt.
- **Git als Nebenläufigkeitsmodell.** Bei OneDrive- und SharePoint-Ablagen gibt es kein Git. Der
  kooperative Writer-Lock ist die richtige Antwort und dem Fremdprojekt in dieser Umgebung voraus.
- **Direktes Schreiben ohne Plan/Apply.** Die hash-gebundene Transaktion mit null Schreibvorgängen
  bei Drift ist ein Alleinstellungsmerkmal.
- **Verzicht auf eine Release-Grenze.** Ohne Manifest kann ein Leser einen Mischstand konsumieren.
  Genau das verhindert SkillSafeWerkstatt.
- **Go-Binärdatei.** Reine Python-Standardbibliothek ist für `.skill`-Pakete und plattformübergreifende
  Skill-Hosts die richtige Wahl. Eine kompilierte Binärdatei je Plattform würde die Portabilität
  zerstören, die das Projekt ausdrücklich anstrebt.
- **Verlust der Rollentrennung.** Ein Werkzeug, das liest und schreibt, kann versehentlich schreiben.
  Zwei Skills können das nicht.

### 5.1 Der strukturelle Blocker: verschachteltes Frontmatter

`frontmatter_contract.py` lehnt verschachtelte Mappings und Listen ausdrücklich ab (Zeilen 98, 116,
119, 182, 258, 261). Genau die OKF-v0.2-Vertrauensfelder sind verschachtelt:

```yaml
generated: { by: agent/cli, at: 2026-09-04T08:43:46Z }
sources:
  - id: convention
    resource: ../../docs/CONVENTION.md
```

Es gibt drei Wege. Die Entscheidung gehört an den Anfang der Umsetzung, weil alles Weitere darauf
aufbaut.

**Weg A — Flach speichern, beim Export verschachteln.**
Intern `generated_by`, `generated_at`, `verified_by`, `verified_at`; der OKF-Export baut daraus die
verschachtelte Form.
*Dafür:* Parser bleibt unangetastet, kein Risiko für vorhandene Wikis, sofort umsetzbar.
*Dagegen:* Mehrfache Verifikation durch verschiedene Personen ist nicht abbildbar; angereicherte
`sources`-Einträge bleiben unmöglich.

**Weg B — Eine Verschachtelungsebene für eine geschlossene Schlüsselliste zulassen.**
Nur `generated`, `verified`, `usage_window` und Einträge in `sources` dürfen genau eine Ebene tief
gehen, mit festgelegten erlaubten Unterschlüsseln. Alles andere bleibt verboten.
*Dafür:* OKF-treu, mehrfache Verifikation möglich, angereicherte Quellen möglich.
*Dagegen:* Eingriff in den Kernparser, den alle Helfer teilen; erfordert eine Migration und eine
Minor-Version des Wiki-Schemas.

**Weg C — Vollständiges YAML zulassen.**
*Bewertung:* Abzulehnen. Der eingeschränkte Parser ist eine Sicherheitseigenschaft, keine Einschränkung
aus Bequemlichkeit — er verhindert Anker, Aliase, Tags und unsichere Schlüssel.

**Empfehlung: Weg A für Stufe 1, Weg B als bewusste Entscheidung in Stufe 3.** Damit liefert die
erste Stufe sofortigen Nutzen ohne Risiko am Kernparser, und die Erweiterung erfolgt später mit
vollem Kontext darüber, welche Struktur in der Praxis tatsächlich gebraucht wird.

---

## 6. Umsetzungsplan

Vier Stufen, unabhängig lieferbar, nach absteigendem Nutzen je Aufwand geordnet. Jede Stufe ist für
sich abnehmbar; keine Stufe setzt eine spätere voraus.

### Stufe 1 — Vertrauensstufe pro Seite

*Adressiert Befund 1. Nutzen: hoch. Risiko: niedrig. Frontmatter-Weg A.*

**Schema.** Vier neue optionale Frontmatter-Felder auf Wiki-Seiten:

```yaml
generated_by: "agent/claude-opus-5"      # Akteurskonvention aus OKF
generated_at: "2026-09-06T10:00:00Z"
verified_by:  "human:mzi"                # optional
verified_at:  "2026-09-06T12:00:00Z"     # optional
```

Ableitungsregel, ohne eigenes gespeichertes Feld:

- kein `verified_by` → `unverified`
- `verified_by` beginnt nicht mit `human:` → `machine-confirmed`
- `verified_by` beginnt mit `human:` → `human-reviewed`

**Änderungen:**

| Datei | Änderung |
|---|---|
| `maintain-llm-wiki/references/wiki-contract.md` | Neuer Abschnitt „Vertrauensstufen"; Akteurskonvention; Regel, dass Agentenarbeit nie als `human:` ausgewiesen wird |
| `maintain-llm-wiki/scripts/lint_wiki.py` | Felder validieren: Akteursformat, ISO-8601-Zeitpunkt, `verified_at` nur zusammen mit `verified_by`; **keine** Pflicht auf Bestandsseiten |
| `maintain-llm-wiki/scripts/page_batch.py` | `generated_by`/`generated_at` beim Anlegen automatisch setzen |
| `maintain-llm-wiki/scripts/record_quality_review.py` | Neuer Modus: bestätigte Seitenliste als geprüft markieren, über Plan/Apply |
| `maintain-llm-wiki/scripts/release_wiki.py` | Verteilung der Vertrauensstufen in `meta/quality-status.json` aufnehmen |
| `query-llm-wiki/scripts/assess_quality.py` | Verteilung auslesen und ausgeben |
| `query-llm-wiki/references/answer-contract.md` | Qualitätszeile erweitert die Vertrauensstufe der tragenden Claims |
| `query-llm-wiki/scripts/wiki_filters.py` | Virtuelles Feld `trust_tier` für Filter und Facetten |
| `README.md` | Neuer Abschnitt; Ergänzung in den Funktionskatalogen |

**Abnahmekriterien.**

1. Ein bestehendes Wiki ohne die neuen Felder linted unverändert fehlerfrei — keine Rückwärtsinkompatibilität.
2. Eine neu erzeugte Seite trägt automatisch `generated_by` und `generated_at`.
3. `verified_by: "agent/x"` ergibt `machine-confirmed`, `verified_by: "human:x"` ergibt `human-reviewed`.
4. `verified_at` ohne `verified_by` wird vom Linter beanstandet.
5. Die Antwort des Lese-Skills nennt die Vertrauensstufe der tragenden Claims.
6. Ein Filter `trust_tier = human-reviewed` liefert genau die menschlich geprüften Seiten.
7. Kein Pfad markiert eine Seite ohne ausdrückliche Anwenderbestätigung als `human:`-verifiziert.

### Stufe 2 — Progressive Disclosure und BM25

*Adressiert Befunde 2 und 4. Nutzen: hoch. Risiko: mittel (Rankingänderung ist sichtbar).*

**2a — Verzeichnis-Indizes.** In jedem Unterverzeichnis unter `wiki/` entsteht ein generiertes
`index.md` mit `type: index` und je Seite Titel, Beschreibung, Status und Vertrauensstufe. Erzeugung
zusammen mit dem Graphen, nicht handgepflegt. Der Wurzelindex verweist auf die Verzeichnisindizes
statt auf jede Einzelseite.

Der Lese-Skill liest gestuft: Wurzelindex → passender Verzeichnisindex → Seiten. Der Antwortvertrag
muss diese Reihenfolge vorschreiben, sonst entsteht der Token-Gewinn nicht.

**2b — BM25.** `score_document` wird zerlegt in eine BM25-Basis (k1 = 1.2, b = 0.75, Standardwerte)
und die bestehenden Aufschläge für Konzepttreffer und Status. Ein Vergleichsmodus gibt beide Scores
nebeneinander aus, damit die Umstellung nachvollziehbar bleibt.

**Änderungen:**

| Datei | Änderung |
|---|---|
| `maintain-llm-wiki/scripts/build_graph.py` | Verzeichnis-Indizes miterzeugen |
| `maintain-llm-wiki/scripts/lint_wiki.py` | Verzeichnis-Indizes als generiert kennzeichnen und auf Aktualität prüfen |
| `maintain-llm-wiki/references/wiki-contract.md` | Abschnitt „Index und Änderungsprotokoll" um die Indexhierarchie erweitern |
| `query-llm-wiki/scripts/search_wiki.py` | BM25-Basis; Aufschläge erhalten; Vergleichsmodus |
| `query-llm-wiki/references/answer-contract.md` | Gestufte Leseordnung vorschreiben |
| beide `evals/evals.json` | Szenarien für Indexstufung und Rankingqualität |

**Abnahmekriterien.**

1. Jedes nicht leere Unterverzeichnis unter `wiki/` hat nach dem Graphbau ein `index.md`.
2. Verzeichnis-Indizes werden aus dem Frontmatter erzeugt; eine Handänderung darin wird beim
   nächsten Bau überschrieben und ist im Vertrag als generiert ausgewiesen.
3. Der Wurzelindex bleibt bei wachsendem Wiki annähernd konstant groß.
4. Auf einem Referenzwiki mit mindestens 50 Seiten liegt der gelesene Umfang bis zur ersten
   Seitenauswahl messbar unter dem heutigen Wert; der gemessene Wert wird dokumentiert — die
   80-Prozent-Angabe des Fremdprojekts wird nicht ungeprüft übernommen.
5. Der BM25-Score ist längennormalisiert: eine doppelt so lange Seite mit doppelt so vielen Treffern
   rankt nicht automatisch höher.
6. Seltene Begriffe wiegen schwerer als häufige.
7. Konzept- und Statusaufschläge wirken unverändert weiter.

### Stufe 3 — OKF-v0.2-Export

*Adressiert Befund 3. Nutzen: mittel. Risiko: niedrig, weil rein additiv.*

**3a — Bericht auf v0.2 heben.** `report_okf.py` prüft künftig `okf_version` im Wurzelindex,
`type`, die empfohlenen Felder ohne das nicht spezifikationskonforme `timestamp`, sowie die
v0.2-Felder `status`, `stale_after`, `generated`, `verified`, `sources`. Format-Kennung auf
`lmwiki-okf-compatibility/2`, Berichtsmodus bleibt nicht verändernd.

**3b — Echter Export.** Neues Skript `export_okf_bundle.py`: schreibt aus einem verifizierten
Release ein konformes OKF-v0.2-Bündel in ein separat gewähltes Ziel — analog zu
`export_wiki_skill.py`, mit derselben doppelten Manifestprüfung.

Abbildung nach Abschnitt 4, Befund 3. Das erzeugte Bündel enthält eine `README.md`, die ausdrücklich
festhält, was der Export **nicht** überträgt: Claim-Locatoren, Release-Manifest, Snapshots,
`SOUL.md`, kontrollierte Begriffswelten. Ein OKF-Bündel ist eine Interoperabilitätsansicht, kein
Ersatz.

**3c — Frontmatter-Weg B entscheiden.** Auf Grundlage der Erfahrung aus den Stufen 1 und 2:
Bleibt es bei flacher Speicherung, oder wird eine Verschachtelungsebene für eine geschlossene
Schlüsselliste zugelassen? Die Entscheidung wird im Vertrag begründet festgehalten. Bei Weg B:
Parseränderung, Migrationsplan im Plan/Apply-Muster, Minor-Version des Wiki-Schemas.

**Änderungen:**

| Datei | Änderung |
|---|---|
| `maintain-llm-wiki/scripts/report_okf.py` | Prüfumfang auf v0.2; `timestamp` entfernen |
| `maintain-llm-wiki/scripts/export_okf_bundle.py` | **neu** |
| `maintain-llm-wiki/scripts/run_locked.py` | Neues Skript in die Allowlist |
| `maintain-llm-wiki/scripts/describe_actions.py` | Aktion `export-okf-bundle` eintragen |
| `maintain-llm-wiki/references/frontmatter-operations.md` | Abschnitt „Self-description and OKF" aktualisieren |
| `maintain-llm-wiki/references/wiki-contract.md` | Abschnitt „Optional OKF compatibility" auf v0.2 heben; Verlustliste aufnehmen |
| `maintain-llm-wiki/SKILL.md` | Exportaktion aufnehmen |
| `README.md` | §4.17 neu fassen |

**Abnahmekriterien.**

1. Der Bericht prüft alle v0.2-Felder und nennt `timestamp` nicht mehr.
2. Das exportierte Bündel besteht die Konformitätsregeln von OKF v0.2.
3. Der Wurzelindex des Bündels trägt `okf_version: "0.2"` und sonst kein Frontmatter.
4. Der Export erfindet keine Titel, Beschreibungen oder Ressourcen; fehlende Werte bleiben leer und
   werden im Bericht ausgewiesen.
5. Die `README.md` des Bündels benennt jede nicht übertragene Eigenschaft.
6. Der Export verändert das Quellwiki nicht und schreibt ausschließlich in das gewählte Ziel.
7. Bei ungültigem oder nicht verifizierbarem Release wird kein Bündel erzeugt.

### Stufe 4 — Reichweite

*Adressiert Befunde 5, 7 und 8. Nutzen: mittel. Risiko: mittel bis hoch. Erst nach Stufe 1 bis 3.*

**4a — Quellentyp „Beobachtung".** Ein Ereignis statt eines Dokuments als registrierte Quelle, mit
Akteur, Zeitpunkt und Anlass. Nicht ohne Stufe 1 umsetzen: Ohne sichtbare Vertrauensstufe entstünde
unmarkiertes unbelegtes Wissen — genau das, was der Vertrag verhindern soll.

**4b — Read-Before-Write-Regel.** Im Pflegevertrag verankern: Nach umfangreicher Arbeit die
Reflexionsfragen stellen, bevor der Lock freigegeben wird. Reine Vertragsergänzung, kein Code.

**4c — Read-only-MCP-Server.** Über einen verifizierten Release. Werkzeuge: `verify`, `search`,
`show`, `inventory`, `quality`. Keine Schreiboperation. Damit wird das Wiki für jeden MCP-fähigen
Agenten nutzbar, nicht nur für Skill-Hosts. Das Sicherheitsmodell bleibt unverändert, weil der
Server nur lesen kann.

**4d — Adoptionsbericht.** Bestehendes Markdown-Verzeichnis analysieren und im Plan/Apply-Muster
zeigen, was übernommen werden könnte. Übernahme bleibt bestätigt und hash-gebunden.

**Bewusst zurückgestellt.** Attested Computation (Befund 6) — sinnvoll für Wikis mit Rechenlogik,
für die aktuelle Ausbaustufe kein vorrangiger Nutzen.

### Reihenfolge und Abhängigkeiten

```text
Stufe 1  Vertrauensstufe pro Seite          eigenständig
   |
   +--> Stufe 2  Indizes + BM25             Indizes zeigen Vertrauensstufen
   |
   +--> Stufe 3  OKF v0.2 Export            verified-Abbildung braucht Stufe 1
   |
   `--> Stufe 4  Reichweite                 4a braucht Stufe 1 zwingend
```

Stufe 2 und Stufe 3 sind untereinander unabhängig und können parallel laufen.

---

## 7. Offene Entscheidungen

Diese Punkte sind nicht aus dem Code ableitbar und gehören dir:

1. **Frontmatter-Weg A oder B** (Abschnitt 5.1). Empfehlung: A für Stufe 1, B bewusst in Stufe 3
   entscheiden.
2. **Ist der OKF-Export ein Produktziel oder eine Fußnote?** Bei „Produktziel" rückt Stufe 3 vor
   Stufe 2. Bei „Fußnote" genügt 3a, und 3b entfällt.
3. **Soll `stale_after` pro Seite eingeführt werden?** OKF kennt es; SkillSafeWerkstatt regelt
   Aktualität heute global über `QUALITY_POLICY.md`. Seitengenaue Verfallsdaten sind mächtiger,
   aber pflegeintensiver. Nicht in den Stufen enthalten — bewusst offen gelassen.
4. **Wie streng wird Stufe 4a?** Ein Wiki, das Beobachtungen aufnimmt, ist nützlicher, aber weniger
   streng belegt als eines, das nur Dokumente kuratiert. Das ist eine Produktentscheidung, keine
   technische.
5. **Ist MCP die richtige Reichweitenwette?** Alternative wäre, die Skill-Hosts als Zielgruppe zu
   akzeptieren und die Tiefe weiter auszubauen statt die Breite.
