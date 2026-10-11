# Was SkillSafeWerkstatt von CROW lernen kann

Analyse und Umsetzungsplan
Stand: 2026-10-11
Untersuchtes Fremdprojekt: Cesarini & Sassarini, „CROW: Classifier-Routed Organization of LLM Wikis" (2026), [doi:10.5281/zenodo.23260209](https://doi.org/10.5281/zenodo.23260209)

---

## 1. Kurzfazit

CROW und SkillSafeWerkstatt lösen dasselbe Problem auf verschiedenen Seiten: **Wissenskuration mit LLMs ist teuer, weil der generative Model die atomaren Entscheidungen fällen muss** — wo eine neue Note hingehört, ob sie eine Seite ersetzt, welche Seiten zusammengehören. CROW zeigt, dass man genau diese Entscheidungen einem typisierten, kostengünstigen Entscheidungsdienst („Decision Provider") übergeben kann, der Wahrscheinlichkeiten zurückgibt, während das generative Model nur noch schreibt.

SkillSafeWerkstatt hat die Hälfte der CROW-Lernernte schon immer besessen: die zweite Hälfte fehlte. Konkret:

| CROW-Komponente | Vorher in SkillSafeWerkstatt | Jetzt |
|---|---|---|
| Generative Schicht (Entitäten-, Konzept-, Synthese-Seiten) | Der Agent selbst | Unverändert |
| Decision Provider | Nicht vorhanden; der Agent entschied alles selbst | `decision_provider.py` in beiden Skills (byte-identisch), herstellerneutrales Wire-Format `lmwiki-decision/1` |
| Routing-Entscheidung | Agent-Handarbeit gegen `CLUSTERS.md` | `route_source.py` mit Schwelle `tau_route` und Beam-Eskalation |
| Konsolidierungs-Entscheidung | Agent-Handarbeit | `plan_consolidation.py` mit Schwelle `tau_cons`; unterhalb: immer neue Seite |
| Link-Entscheidung | Agent-Handarbeit im Seiten-Batch | `score_related.py` mit Schwelle `tau_link` und `max_links`-Cap |
| Clustering externer Sammlungen | Agent-Handarbeit im Übernahme-Workflow | `propose_clusters.py`, Zero-Shot, mit „Keiner davon"-Ausstieg und `uncertain`-Flag |
| Retrieval-Selektion | Deterministisches BM25 | Optional: `score_notes.py`; default und Fallback bleibt BM25 |
| Konsens- und Konfigurationsvertrag | Nicht vorhanden | `schema/DECISION_LAYER.md`: aus, draft, consent_required, misconfigured, active; Linter blockiert Release bei Fehlkonfiguration |
| Einwilligung (Datentransfer) | Nicht vorhanden | `consent_by`/`consent_at` als Vertragsfelder; ohne Einwilligung kein Aufruf |

Die wesentliche Designentscheidung der Distribution: **CROW wird als Vertrag portiert, nicht als Dienst.** Es gibt keinen Server, keinen Daemon, keinen Endpunkt in diesem Repo — nur einen ausgehenden HTTP-Aufruf eines Hilfswerkzeugs nach aktivierter Einwilligung. Skill-only bleibt damit unangetastet, und das Wiki ist ohne die Schicht vollständig funktionsfähig.

## 2. Was die Entscheidungsschicht ist — und was nicht

**Ist:**

- ein typisierter Wire-Format-Vertrag: Request = kompakter Zustand + Fragen (Wahl mit Optionen, Ja/Nein), Response = Wahrscheinlichkeitsverteilungen pro Frage, strikt validiert (alle Fragen genau einmal, Wahrscheinlichkeiten in [0,1], Summe ≈ 1, max. 255 Optionen);
- ein Konfigurationsvertrag mit fünf Zuständen (`inactive`, `consent_required`, `misconfigured`, `active`), dessen `active`-Zustand eine nachweisbare Einwilligung erfordert;
- vier Pflege-Helfer und ein Lese-Helfer, die **nur Vorschläge** erzeugen; jede Veränderung verläuft weiter über Plan/Apply mit Vorschau, Bestätigung und Snapshot;
- eine Kalibrierung als Vertragswert: die Schwellen `tau_*` sind im Vertrag editierbar und werden an einem gelabelten Auszug des eigenen Wikis gesetzt.

**Ist nicht:**

- kein Ersatz für die Kompilierung von Wissensseiten, das Qualitäts- oder Cleaning-Review, den Linter oder die Release-Mechanik;
- keine Schreibkomponente: kein Helfer erzeugt Ordner, Links, Cluster oder Seiten;
- keine Berechtigung: Provider-Antworten sind Daten, keine Anweisungen — die Vertrauensregeln für unvertrauenswürdige Quellen gelten unverändert;
- keine Garantie: ein selbstsicher falscher Provider passiert jede Schwelle still; die Sicherheit liegt in den expliziten Auswegen (`new`, „Keiner davon", Beam, Fallback auf den Agenten).

## 3. Schwellenwerte und ihre Semantik

Konfidenz ist hier **Konzentration der Verteilung**, nicht Richtigkeit: das Maximum der Wahrscheinlichkeiten (Wahl) bzw. `max(p, 1-p)` (Ja/Nein).

| Schwellenwert | Standard | Rolle |
|---|---|---|
| `tau_route` | 0.6 | darunter: Routing gibt den Beam (top `beam`) an den Agenten zurück |
| `tau_cons` | 0.6 | darunter: Konsolidierung antwortet „neue Seite" |
| `tau_link` | 0.6 | Minimum für eine See-also-Verknüpfung |
| `tau_ret` | 0.1 | Minimum, damit eine Note bei der Auswahl gelesen wird; bewusst niedrig — die Selektion macht die Rangfolge, nicht der Cut |
| `tau_path`, `tau_fold`, `tau_ing` | 0.5 / 0.08 / 0.5 | reserviert für hierarchisches Routing und Kandidatenzulassung |
| `beam` | 3 | Größe des Rückgabebens bei Unsicherheit |
| `k` / `max_notes_per_cluster` / `max_links` | 8 / 40 / 5 | Auswahlgrößen und Linter-Reservegrenzen |
| `state_chars` / `request_chars` | 6000 / 90000 | Charakter-Budgets pro Zustand bzw. Request |

Die niedrige Retrieval-Schwelle mit breiter Kandidatenmenge folgt dem gemessenen Retrieval-Verhalten der Referenzpublikation; eine hohe Schwelle, die die richtige Note vor der Rangfolge aussortiert, wäre kontraproduktiv.

## 4. Datenschutz und Einwilligung

Jeder aktive Aufruf sendet Fragen- und Zustands-Text (Titel, Beschreibung, begrenzter Auszug) an das konfigurierte Endpoint. Das ist ein **Datentransfer**, kein lokales Rechenwerk. Deshalb:

- die Einwilligung ist ein **bestätigter Vertragswechsel**: Vor dem Setzen von `consent_by`/`consent_at` muss der Agent dem Nutzer erklären, welche Inhalte wohin gehen;
- ohne Einwilligung verweigern alle Helfer den Aufruf (Zustand `consent_required`), der Linter warnt;
- der API-Key kommt zur Laufzeit aus der benannten Umgebungsvariable und wird nie im Wiki, in Plänen oder Berichten abgelegt;
- eine Fehlkonfiguration blockiert das Release: eine halb aktivierte Schicht kann nicht veröffentlicht werden.

## 5. Ehrliche Grenzen

1. **Selbstsicher falsch.** Verteilungskontrast ist keine Richtigkeitsaussage. Die Schicht reduziert Kosten und Ermüdung, nicht den Fehlerbestand.
2. **Komposition von Fehlern.** Routing, Selektion und Konsolidierung laufen in Folge; ein Fehler in der ersten Stufe verfehlt die folgenden.
3. **Beschreibung als Score-Fläche.** Seiten mit vager oder fehlender `summary` werden systematisch schlechter geroutet und gefunden. Bessere Beschreibungen sind Kurationsarbeit, kein Schwellenwert-Tuning.
4. **Zahlen und Daten.** Die aktuelle Provider-Generation ist bei Versionen und Enddaten schwach; entsprechende Entscheidungen bleiben beim Agenten.
5. **Ein Korpus, eine Ordnung, ein Modellpaar.** Die Referenzpublikation misst an 525 kurzen persönlichen Dokumenten. Kosten- und Trefferzahlen sind eine Größenordnung, keine Generalisierung.
6. **Prompt-injection bleibt.** Notiz- und Quellentext kann die Entscheidung des Providers beeinflussen — daher gelten die Vertrauensregeln unverändert, und ein Provider kann nicht mehr ändern als eine Quelle.

## 6. Was bewusst nicht umgesetzt wurde

- **Kein Embedding-/Vektorpfad.** CROW nutzt keine Embeddings; die Distribution hält sich daran und bleibt bei BM25 + typisiertem Provider.
- **Kein eigener Dienst oder Modell.** Die Distribution definiert den Vertrag, nicht die Inferenz. Ein beliebiger kompatibler HTTP-Provider mit Bearer-Auth tut; wird nicht mitgeliefert.
- **Kein Auto-Modus.** Kein Helfer schreibt direkt in das kanonische Wiki. Ein „Auto-Accept" über die Bestätigungsprozesse hinweg wäre ein Vertrauensbruch des bestehenden Kontrakts und wird daher nicht implementiert.
- **Kein MCP-Endpunkt.** Der Wire-Format-Vertrag ist transportneutral; die Distribution bleibt ein reines Skill-Bündel.

## 7. Umsetzungsumfang (Branch `feature/crow-decision-layer`)

| Datei | Änderung |
|---|---|
| `*/scripts/decision_provider.py` | Neu, shared, byte-identisch; Konfig-, Request-, Response-, Konfidenz- und Transportvertrag |
| `maintain-llm-wiki/scripts/route_source.py` | Neu; Routing-Helfer |
| `maintain-llm-wiki/scripts/plan_consolidation.py` | Neu; Konsolidierungs-Helfer |
| `maintain-llm-wiki/scripts/score_related.py` | Neu; Link-Helfer |
| `maintain-llm-wiki/scripts/propose_clusters.py` | Neu; Zero-Shot-Clustering-Helfer |
| `query-llm-wiki/scripts/score_notes.py` | Neu; Lese-Helfer mit BM25-Fallback |
| `maintain-llm-wiki/scripts/run_locked.py` | Hilfe-Index um vier neue Helfer ergänzt |
| `maintain-llm-wiki/scripts/init_wiki.py` | Legt `schema/DECISION_LAYER.md` (deaktiviert) an und verlinkt es in `WIKI.md` |
| `maintain-llm-wiki/scripts/lint_wiki.py` | Validiert den Vertrag; Fehlkonfiguration blockiert Release; Cluster-Reservegrenzen |
| `*/scripts/describe_actions.py` | Katalog um Entscheidungsschicht-Aktionen ergänzt |
| `*/SKILL.md`, `*/references/decision-layer.md` | Vertrag und Arbeitsregeln in beide Skills aufgenommen |
| `tests/test_decision_layer.py` | 25 Tests über alle Helfer und Zustände |
| `tests/test_packaging.py` | `decision_provider.py` in der Byte-Identitätsprüfung |
| `README.md` | Abschnitt 4.26, Zuständigkeits- und Funktionskatalog, Grenzen |
| `index.html` | Landingpage-Sektion mit Vorteilen der Überarbeitung |
