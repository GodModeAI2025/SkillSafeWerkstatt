# Bedeutungssuche und Vollständigkeit im erzeugten Wissens-Skill

Analyse und Umsetzungsplan
Stand: 2026-11-13
Ausgangsfrage: „Wie bekomme ich eine Bedeutungssuche in den Skill, den das Projekt erzeugt, und
wie stelle ich sicher, dass er nichts übersieht?"
Messgrundlage: ein synthetisches Test-Wiki und 114 Testfragen, beides außerhalb des Repositorys
(Anhang A)

---

## 1. Kurzfazit

**Eine echte Vektor- oder Embedding-Suche passt nicht in dieses Produkt.** Sie bräuchte ein Modell
oder einen Index. Das bricht vier verbindliche Regeln: nur Skill, kein Dienst; nur
Standardbibliothek; der Leser schreibt nichts; nur bestätigte Begriffswelten dürfen eine Anfrage
erweitern. Sie bringt außerdem gemessen nichts, was billigere Bausteine nicht auch leisten
(Abschnitt 3).

**Bedeutung kommt stattdessen aus drei Quellen, die ins Produkt passen:**

1. **Der Host-Agent selbst.** Er ist die einzige Komponente, die Bedeutung versteht. Er kann die
   Frage in die Sprache des Wikis übersetzen und umformulieren. Die Suche muss diese
   Umformulierungen nur sauber in einem Aufruf zusammenführen.
2. **Kuratierte Begriffe**, eingefroren im Release: Seiten-`aliases` und Aliase der
   Begriffswelten. Das wirkt schon heute ohne eine Zeile Code.
3. **Eine deterministische Wortform-Schicht**: Umlaut-Umschrift, Flexion, Bindestriche,
   Komposita und Tippfehler. Jede Treffer-Begründung wird ausgewiesen.

**„Nichts übersehen" lässt sich für Bedeutung nicht garantieren, wohl aber in überprüfbare Teile
zerlegen:**

- *Durch Konstruktion garantiert:* Kein Verlust bleibt stumm. Jede Kürzung wird gezählt:
  Gesamttreffer, Abschneiden, zurückgehaltene Claims, Begriffe ohne Treffer, nicht durchsuchte
  Schichten.
- *Durch ein Werkzeug erzwungen:* „Das Wiki enthält dazu nichts" darf nur gesagt werden, wenn
  ein gebündelter Helfer eine vollständige Prüfung bestätigt hat. Sonst lautet die Aussage: „Mit
  diesen Wörtern in Release V nicht gefunden."
- *Pro Release gemessen:* Quellenabdeckung (welche Quelle trägt keinen Claim) und, optional,
  Auffindbarkeit mit Fragen, die echte Nutzer formuliert haben.
- *Pro Antwort offengelegt:* womit gesucht wurde und was nicht geprüft werden konnte.

**Ein kritischer Fehler wurde dabei gefunden und in diesem Branch behoben:** Die Suche des
exportierten Wissens-Skills stürzte seit Commit `553e974` bei *jedem* Aufruf ab. Der Export
meldete trotzdem Erfolg (Befund 0).

| # | Befund | Wert | Aufwand |
|---|---|---|---|
| 0 | Exportierte Suche stürzt bei jedem Aufruf ab | kritisch | niedrig, **erledigt** |
| 1 | Verluste sind stumm | hoch | niedrig |
| 2 | Wortformen werden nicht erkannt | hoch | mittel |
| 3 | Synonyme, Umschreibungen und andere Sprachen erreichen die Suche nicht | hoch | niedrig bis mittel |
| 4 | Eine Fehlanzeige ist nicht abgesichert | hoch | mittel |
| 5 | Der exportierte Skill ist eine abgedriftete Kopie | mittel | mittel |
| 6 | Der Release prüft weder Quellenabdeckung noch Auffindbarkeit | mittel | mittel |
| 7 | Plattformlücken: Windows-Ausgabe, Release-Bindung der Suche | mittel | niedrig |

Was die Bausteine auf dem Test-Wiki bringen. Gezählt sind 107 beantwortbare Fragen. „Gefunden"
heißt: alle Pflichtseiten der Frage stehen in der Liste.

| Variante | unter den ersten 3 | unter den ersten 12 (Standard) | unter den ersten 100 |
|---|---|---|---|
| heute | 47 | 57 | 62 |
| nur kuratierte Seiten-Aliase, kein Code | 64 | 74 | 79 |
| nur Wortformen (empfohlener Regelsatz des Prototyps) | 67 | 81 | 88 |
| kuratierte Begriffe + Wortformen | 83 | 93 | 97 |
| … zusätzlich mit Quellenschicht | 89 | 99 | 105 |
| Wortformen + blind geschriebene Agent-Umformulierungen (Simulation) | – | 101 | – |

Die beiden Zeilen „kuratierte Begriffe + Wortformen" stammen aus einem zweiten Entwurf mit
lockereren Wortformregeln. Die Kombination mit dem empfohlenen Regelsatz wurde nicht gemessen.

Der Preis ist Präzision. Für Themen, die das Wiki gar nicht enthält, steigt die Zahl der Treffer
von 16 auf 31 (sieben Testfragen, jeweils höchstens 12 Treffer). Eine Score-Schwelle trennt
„gefunden" nicht von „nicht vorhanden". Deshalb braucht es Befund 1 und 4 genauso wie Befund 2
und 3.

---

## 2. Wie die Suche heute arbeitet

Die Lese-Suche (`query-llm-wiki/scripts/search_wiki.py`, `bm25.py`) rankt mit BM25F über fünf
Felder: Titel 10, Aliase 7, Überschriften 5, Beschreibung 4, Text 1. Danach kommen
multiplikative Faktoren für Phrase (1,5), passende Begriffswelt (+0,5 je Begriff) und Status
(aktiv 1,15, Entwurf 0,95, abgelöst 0,75). Der Tokenizer faltet Groß- und Kleinschreibung und
entfernt Diakritika. Bindestrich-Wörter bleiben ein Token. Mehrere Suchwörter sind
ODER-verknüpft. Standardmäßig kommen 12 Treffer mit je höchstens 8 Claims zurück. Quellen und
Historie werden nur auf Schalter durchsucht. Eine Begriffswelt erweitert die Anfrage nur über
ihren bestätigten Vorzugsbegriff und ihre Aliase. Definition, Oberbegriff und verwandte Begriffe
nutzt die Suche nicht.

Der **exportierte** Wissens-Skill hat eine eigene, ältere Suche
(`maintain-llm-wiki/assets/knowledge-skill/search_knowledge.py`). Sie arbeitet additiv mit
handgewählten Gewichten, kennt kein BM25, keine Historie, keine Vertrauensstufen und keine
Ablaufdaten.

---

## 3. Warum keine Embedding-Suche

Untersucht und, wo möglich, gemessen wurden fünf Familien:

| Option | Ergebnis (3 / 12 / 100 von 107) | Urteil |
|---|---|---|
| A Neuronale Embeddings (Modell, Vektorindex) | nicht gemessen | bricht vier Regeln; `onnxruntime` braucht Python ≥ 3.11, das Modell muss heruntergeladen werden |
| B Statische Embedding-Tabelle im Skill | 68 / 81 / 99 allein, **+0** auf dem empfohlenen Stapel | liefert für *jede* Negativfrage 12 Treffer und zerstört damit jedes Fehlanzeige-Signal |
| C1 Zeichen- und Wortform-Abgleich | 67–71 / 81–83 / 88–91 | **übernehmen** als erklärbare Wortform-Schicht (Befund 2) |
| C2–C5 LSA, Random Indexing, Kookkurrenz, Pseudo-Relevanz-Feedback | 59–67 / – / – | schlechter als C1, nicht erklärbar |
| D Kuratierte Erweiterung (Aliase, eingefroren im Release) | 70 / 79 / 85 | **übernehmen**, wirkt teilweise schon heute |
| E Host-Agent formuliert um | 14–16 von 16 Umschreibungs- und Fremdsprachfragen unter den ersten 12 (Original allein: 3 von 16) | **übernehmen**, der einzige Hebel für andere Sprachen |

Die Regelkonflikte im Einzelnen:

- *Nur Skill, kein Dienst* (README: „Kein MCP-Server, kein Dienst, kein Hintergrundprozess —
  auch nicht optional, auch nicht später").
- *Nur Standardbibliothek.* `numpy` steht in `tests/test_packaging.py` auf der Sperrliste.
- *Der Leser schreibt nichts.* Lese-Skill und exportierter Skill dürfen keinen Index anlegen.
- *Nur bestätigte Begriffswelten erweitern.* `init_wiki.py` schreibt in jede `CONCEPTS.md`:
  „Search may expand a query only through confirmed preferred terms and aliases." Eine
  Ähnlichkeitssuche wäre eine unbestätigte Erweiterung.

Der Host-Agent ist bereits ein Sprachmodell. Ein zweites Modell im Skill wäre teurer, schlechter
prüfbar und bei den Negativfragen gemessen schädlich.

---

## 4. Die Befunde im Einzelnen

### Befund 0 — Die exportierte Suche stürzt bei jedem Aufruf ab *(behoben)*

**Beobachtung.** `wiki_filters.py` importiert seit Commit `553e974` das Modul `trust_contract`.
Der Exporter kopierte seine Bibliotheken aber aus einer festen Liste
(`frontmatter_contract.py`, `wiki_filters.py`), in der `trust_contract.py` fehlte.

**Das Problem.** Jeder Aufruf von `scripts/search_knowledge.py` im exportierten Skill endete mit
`ModuleNotFoundError: No module named 'trust_contract'`. Reproduziert wurde das in 456 von 456
Aufrufen. Der Export meldete dennoch `exported`, weil sein Selbsttest nur
`verify_knowledge.py` ausführte, und das importiert nichts Lokales. Kein Test berührte den
Exporter, und die statischen Importprüfungen erfassten die Vorlagen unter `assets/` nicht. Ein
Endnutzer bemerkte den Fehler erst bei seiner ersten Frage. Für die Ausgangsfrage heißt das: Der
erzeugte Skill hat bisher *alles* übersehen.

**Empfehlung, umgesetzt.** Der Exporter ermittelt die benötigten Bibliotheken jetzt selbst, als
transitive Hülle der Importe seiner Vorlagen. Mitkommen darf nur, was auf seiner Liste geprüfter
lesender Bibliotheken steht. Jedes andere Modul lehnt er mit Namen ab, denn Pflegewerkzeuge und
schreibende Bibliotheken dürfen nie in einen Export. Ein neuer Import wird so laut abgelehnt
statt still vergessen. Vor dem Paketbau führt er jedes mitgelieferte Werkzeug einmal im
erzeugten Ordner aus, auch die Suche. Dabei steht nur die Standardbibliothek zur Verfügung: ohne
`PYTHONPATH`, ohne Site-Pakete, ohne Bytecode-Schreiben. Scheitert das, entfernt er den Ordner
und baut kein Paket. Interpreter-Caches neben den Werkzeugen kommen nie ins Paket. Neue Tests in
`tests/test_export.py` prüfen das, und `tests/test_packaging.py` prüft jetzt auch die Vorlagen
(Abschnitt „Umsetzungsstand").

### Befund 1 — Verluste sind stumm

**Beobachtung.** Die Suchausgabe nennt weder die Gesamtzahl der Treffer noch, ob abgeschnitten
wurde. Claims sind auf 8 pro Seite gekappt, ohne Zählung. Suchwörter ohne jeden Treffer werden
nicht gemeldet. Das Stoppwort „für" wird nie entfernt: Der Tokenizer macht daraus „fur", die
Liste enthält aber „für". Generierte Indexseiten belegen 90 von 781 Ergebnisplätzen. Dass eine
nicht durchsuchte Quelle das Suchwort enthält, erfährt der Agent nicht. Ein leeres Ergebnis
sieht gleich aus, ob das Thema fehlt oder nur ein anderes Wort verwendet wird.

**Das Problem.** Der Agent kann nicht unterscheiden zwischen „nichts da", „nicht gezeigt" und
„anders formuliert". Drei Messungen machen das greifbar:

- 5 Fragen haben ihre Pflichtseite auf Rang 15 bis 39. Ohne Hinweis auf das Abschneiden sucht
  niemand weiter.
- 7 von 8 Fakten, die nur in Quellen stehen, wären über einen Hinweis „Quellen enthalten das
  Suchwort" auffindbar. Heute fehlt der Hinweis.
- Bei einer Frage nach einer Ausnahme (Abschlag um mehr als 20 Prozent senken) kommt Claim 9 von
  12 nie zurück, weil er die Suchwörter nicht enthält. Der benachbarte Claim 7 wirkt wie die
  ganze Antwort.

Am häufigsten ist aber ein anderer Fehler: ein **nicht leeres, aber falsches** Ergebnis. Mit
Wortformen und Agent-Umformulierungen liefern 22 von 107 Fragen eine Liste, deren erster Treffer
falsch ist, aber wie ein exakter Treffer aussieht. Bei „Gastarif Kündigungsfrist" steht die
Strom-Kündigungsfrist oben. Dass „Gastarif" im ganzen Wiki nicht vorkommt, sieht niemand.

**Empfehlung.** Ein Zählwerk in der Suchausgabe, das nur Schlüssel ergänzt und das Ranking nicht
verändert. Der Prototyp liefert in 114 von 114 Fragen identische Ranglisten, die Ausgabe wächst
um etwa 36 Prozent:

- Gesamtzahl der Treffer, `truncated`, `omitted_count` und höchstens 20 weitere Pfade mit Score.
  Keine vollständige Restliste: Bei 4.628 Seiten wären das für eine breite Anfrage (90.
  Perzentil) etwa 308.000 Zeichen pro Aufruf.
- je Treffer `claims_total` und `claims_returned`. Dazu eine Leseregel: Vor einer Antwort aus
  einer Seite mit zurückgehaltenen Claims werden alle ihre Claims gelesen.
- je Suchwort die Zahl der Dateien pro Schicht (Wiki, Quellen, Historie), dazu `dropped_terms`
  (Stoppwort, Einzelzeichen), `unmatched_terms` und `terms_only_in_unsearched`.
- je Treffer `matched_terms`: welche inhaltstragenden Suchwörter *auf dieser Seite* vorkommen.
  Daraus folgt die Regel: Fehlt der spezifischste Begriff der Frage auf allen gezeigten Seiten,
  ist das eine Teil-Fehlanzeige („Das Wiki behandelt Kündigungsfristen, aber nichts zu
  Gastarifen").
- Navigationsseiten (`WIKI.md`, `*/index.md`, `meta/questions.md`) in einer eigenen Liste statt
  zwischen den Inhaltstreffern.
- ein fester Grenzsatz: Die Zahlen beschreiben Wortübereinstimmungen und beweisen nicht, dass
  das Thema fehlt.

### Befund 2 — Wortformen werden nicht erkannt

**Beobachtung.** Eine Suche nach „Tarife" findet heute keine Seite, auf der nur „Tarif" steht.
Ebenso wenig findet „Kuendigung" das Wort „Kündigung", „Gebühr" das Wort „Durchleitungsgebühr"
und der Tippfehler „Netzentgeld" das Wort „Netzentgelt". Gemessen unter den ersten 12: Flexion 3
von 8, Komposita 4 von 8, Tippfehler 1 von 8. Bei den ae/oe/ue-Schreibweisen traf in 0 von 6
Fällen der eigene Text der Zielseite. Gefunden wurde sie nur über Link-Slugs.

**Das Problem.** Das sind keine Bedeutungsfragen, sondern dasselbe Wort in anderer Form.
Trotzdem gehen sie heute verloren, und ein Suchwort mit null Treffern sieht aus wie ein
fehlendes Thema.

**Empfehlung.** Jedes Suchwort wird zu einer gewichteten Gruppe von Tokens, die *im Korpus
tatsächlich vorkommen*. Das wörtliche Token zählt 1,0, Formen zählen fest weniger. `bm25.py`
wertet die Gruppe als einen Begriff. Gemessene Leiter des empfohlenen Regelsatzes (unter den
ersten 12 / unter den ersten 100; in Klammern die Treffer der sieben Negativfragen unter den
ersten 12):

| Schritt | Regel | Ergebnis |
|---|---|---|
| heute | – | 57 / 62 (16) |
| a | Umlaut-Umschrift und Silbentrenn-Reparatur, normalisierte Stoppwörter, Funktionswörter nur wörtlich | 58 / 62 (20) |
| b | leichter Stemmer (Endungen, keine Ableitungen) plus Verbformen | 67 / 71 (28) |
| c | Kompositumteile, nur wenn der Rest aus echten Korpuswörtern besteht | 75 / 82 (31) |
| d | Tippfehler: eine Änderung, nur Wörter ab 7 Buchstaben ohne andere Übereinstimmung | 81 / 88 (31) |

Ergebnis je Kategorie unter den ersten 12: Flexion 3 → 7 von 8, Komposita 4 → 8 von 8,
Tippfehler 1 → 8 von 8, Umlaut-Umschrift 6 → 7 von 7. Ein zweiter, aggressiverer Regelsatz aus
einem anderen Entwurf kam allein auf 83 / 91. Dort lieferten aber alle 7 Negativfragen Treffer
statt 5, im Mittel 7,1 statt 2,3 pro Frage, vor allem durch lockerere Kompositumregeln.

Die Gegenprüfung fand fünf Konstruktionsfehler, die ein naiver Einbau hätte. Jeder davon
verschlechtert heute korrekte Antworten:

1. *Gemeinsame Dokumentfrequenz über alle Formen* nimmt seltenen Fachbegriffen ihr Gewicht. Die
   IDF von „sondervertragskunden" fiel von 3,56 auf 0,13. Bei „Zählerstand beim
   Lieferantenwechsel" verlor die richtige Seite Rang 1. Daher: IDF nur aus wörtlichem Token und
   echten Wortformen bilden, Teile und Tippfehler nur als Rückfall.
2. *Formgewicht vor der BM25-Sättigung* verpufft. Ein Kompositumteil im Titel behält 86 Prozent
   eines exakten Titeltreffers. Daher: das Gewicht nach der Sättigung anwenden.
3. *Der Phrasenbonus als Teilzeichenkette* belohnt Teiltreffer mit Faktor 1,5. Daher: nur auf
   Token-Grenzen und nur für wörtliche Treffer.
4. *Bindestrich-Teilung von Link-Slugs* lässt jede Seite, die auf eine Tarifseite verlinkt, für
   „Tarif" treffen. Daher: Pfade und Slugs nie zerlegen.
5. *Tippfehler mit zwei Änderungen oder bei kurzen Wörtern* korrigieren echte Wörter falsch
   („smart" → „start", „meter" → „alter", „ankündigen" → „kündigen"). Daher: eine Änderung, ab 7
   bis 8 Buchstaben. Gemessen: 8 von 8 echten Tippfehlern korrigiert, 0 bis 2 Fehlkorrekturen
   bei 75 bis 104 korrekten, im Wiki fehlenden Wörtern.

Dazu kommen: keine Teile von Funktionswörtern („werden" ≠ „wer" + „den"); Kompositumteile nicht
auf Begriffswelt-Aliase anwenden (sonst steigt eine Negativfrage von 5 auf 32 Treffer); kein
Abschneiden von „-er" bei Substantiven (Zähler ≠ zahlen).

Was die Schicht nicht kann: Synonyme, Umschreibungen und andere Sprachen. Fremdsprachige Fragen
bleiben bei 1 von 8. Unregelmäßige Formen fehlen ebenfalls: „umgezogene" findet „Umzug" nicht,
diese Frage rutscht von Rang 5 auf 17.

### Befund 3 — Bedeutung erreicht die Suche nicht

**Beobachtung.** Für unkontrollierte Synonyme werden 2 von 8 Fragen gefunden, für
Umschreibungen 2 von 8, für Fragen in anderer Sprache 1 von 8 („Ökostrom" statt „Grünstrom",
„Beschwerde" statt „Reklamation", „grid fees" statt „Netzentgelt"). Der Lese-Skill gibt die
Frage einmal an die Suche (`query-llm-wiki/SKILL.md`, Schritt 6).

**Das Problem.** Bedeutung kann nur der Agent beisteuern oder der Pfleger, der das Wiki kuratiert.

**Empfehlung, zweigleisig:**

*Agent-Umformulierungen in einem Aufruf.* `--also` nimmt bis zu fünf Umformulierungen in der
Wiki-Sprache an, Übersetzungen eingeschlossen, und fasst alles in einem Prozess über einen
verifizierten Release zusammen. Fünf getrennte Aufrufe kosten bei 4.626 Seiten 33 Sekunden, ein
zusammengefasster Aufruf rechnerisch etwa 13. Unter Windows und PowerShell ist die Übergabe als
JSON über stdin robuster (`--request -`). Zwei Regeln aus der Gegenprüfung:

- *Rang statt Score zusammenführen.* BM25-Scores sind zwischen Formulierungen nicht
  vergleichbar. Bei Bestwert-Fusion füllt eine schlampige Formulierung bis zu 39 Prozent der
  Plätze. Reihum-Verschränkung nach bestem Rang erreichte 15 von 16 Pflichtseiten unter den
  ersten 3 und 16 von 16 unter den ersten 12.
- *Treffer nur aus Umformulierungen getrennt ausweisen* (`found_by`). Umformulierungen erzeugen
  bei Negativfragen viele Treffer: eine Frage stieg von 1 auf 28, eine andere von 0 auf 3. Ohne
  Trennung würde die Fehlanzeige nie mehr ausgelöst.

*Kuratierte Begriffe, sofort und ohne Code.* Beide Suchen gewichten Seiten-`aliases` mit 7.
Aliase in der Sprache der Nutzer (Alltagswörter, Abkürzungen, englische Begriffe) heben das
Ergebnis von 57 auf 74 unter den ersten 12. Begriffswelt-Aliase wirken über die bestätigte
Erweiterung. Vorsicht bei Alltagswörtern als Alias: „Sperrung" löst die Begriffswelt
Versorgungsunterbrechung auch bei „Sperrung des Kundenportals" aus, und „Abschlag" (Rabatt)
landet bei der Abschlagszahlung. Eine Lint-Statistik soll häufige Wörter unter den Aliasen zur
Bestätigung vorlegen. Ein skalarer `aliases`-Wert (`aliases: Foo` statt Liste) besteht heute den
Lint und wird von der Suche ignoriert. Er soll künftig als ein Alias gelesen werden, mit
Warnung.

### Befund 4 — Eine Fehlanzeige ist nicht abgesichert

**Beobachtung.** 5 von 7 Fragen zu Themen, die das Wiki nicht enthält, liefern heute normal
aussehende Treffer (Top-Score 1,74 bis 2,49). Je nach Regelsatz haben 20 bis 36 beantwortbare
Fragen einen Top-Score, der höchstens so hoch ist wie der höchste Negativ-Score. Kein
Schwellenwert trennt beides.

**Das Problem.** Ob „nichts gefunden" heißt „nichts vorhanden", entscheidet heute allein das
Urteil des Agenten, und genau dort versagt es: Die Treffer sehen normal aus. Eine Regel, die nur
als Prosa in der `SKILL.md` steht, würde gerade in diesem Fall übersprungen.

Ein Katalog aller Seitenbeschreibungen als Vollständigkeitsnachweis wurde gemessen und taugt nur
eingeschränkt. Auf dem Test-Wiki fand eine blinde Auswahl aus 56 Katalogzeilen (10.472 Zeichen)
104 von 107 Pflichtseiten, Suche und Katalog zusammen 107 von 107. Aber der Katalog deckt
*Seiten* ab, nicht *Fakten*. „Kündigung" auf der Seite Grundversorgung steht nur in einem Claim,
nicht in der Beschreibung. Quellen haben gar keine Beschreibung. Und er wächst mit dem Wiki:
11.900 Zeichen bei 50 Seiten, 121.000 bei 492 und 1,15 Millionen bei 4.628 Seiten. Das kann
kein Agent pro Frage lesen.

**Empfehlung.** Die Fehlanzeige setzt ein Werkzeug durch, nicht die Prosa:

- Jede Suchausgabe trägt `absence_check.complete = false` und die fehlenden Bedingungen.
- Nur ein Aufruf `--exhaustive` kann `complete = true` setzen. Er umfasst Formulierungen, Wiki,
  Quellen, Historie und einen Textscan über *alle* Claims und Quelltexte mit den Wortformen, in
  einem Prozess und mit festem Ausgabebudget von etwa 100.000 Zeichen.
- Passt die vollständige Prüfung nicht ins Budget, nennt die Ausgabe den geprüften Anteil, und
  die Antwort sagt, wie viele Seiten nicht einzeln beurteilt wurden.
- `search_record` ist eine Zeile aus Zählern und Release-Version, die die Antwort zitiert.
- Ein Satz in Lese-`SKILL.md`, `answer-contract.md` und der exportierten `SKILL.md`: „Sage nur
  dann, dass das Wiki nichts zu X enthält, wenn eine Suchausgabe dieser Antwort
  `absence_check.complete = true` meldet; sonst sage ‚mit diesen Wörtern in Release V nicht
  gefunden' und zitiere `search_record`."

Selbst eine vollständige Prüfung beweist nur, dass keines der geprüften Wörter vorkommt. Eine
Seite, die die Antwort ganz anders formuliert, kann fehlen. Das gehört in die Antwort.

### Befund 5 — Der exportierte Skill ist eine abgedriftete Kopie

**Beobachtung.** Der Export sucht mit einer eigenen additiven Heuristik und kennt weder BM25,
Historie, Vertrauensstufen noch Ablaufdaten. Seine `assess_quality.py` ist eine getrennte Kopie,
der die Offenlegung von Vertrauensstufe und Ablauf fehlt. Seine `SKILL.md` entsteht aus einem
Python-f-String: Ein JSON-Beispiel darin löst `ValueError` aus. Seine Befehle hängen vom
aktuellen Verzeichnis ab.

**Das Problem.** Jede Verbesserung der Suche müsste zweimal gebaut werden, und die zweite Kopie
driftet nachweislich ab. Befund 0 war genau so entstanden.

**Empfehlung.** Ein Suchkern (`search_core.py` plus `bm25.py`) für Lese-Skill und Export,
byte-identisch geprüft wie die übrigen geteilten Module. Die Export-Suche wird ein dünner
Wrapper. Ebenso ein gemeinsamer Bewertungskern für `assess_quality`. Die exportierte `SKILL.md`
wird eine Vorlagendatei statt eines f-Strings, mit eigenem Antwortvertrag unter `references/`
und einem Test, der die Fehlanzeige-Regel in allen drei Anweisungstexten verlangt. Die
gemessenen 20 von 20 Pakettests bestehen mit einem geteilten Kern.

### Befund 6 — Der Release prüft weder Quellenabdeckung noch Auffindbarkeit

**Beobachtung.** Auf 2 der 11 Quellen des Test-Wikis verweist kein einziger Claim. 7 der 8
Fakten, die nur in Quellen stehen, liegen in unzitierten Abschnitten. Nicht auflösbare
`source_id@locator`-Verweise bestehen den Lint. `quality-status` hat keine Abdeckungskennzahl.

**Das Problem.** Was nie in einen Claim überführt wurde, findet die Wiki-Suche nie. Das ist die
leiseste Form des Übersehens.

**Empfehlung.** Ein Quellenabdeckungs-Bericht für den Pfleger: Quellen und Abschnitte ohne
Claim, nicht auflösbare Locator. Warnungen, keine Fehler, damit bestehende Wikis weiter
veröffentlichen können. Optional dazu Auffindbarkeitsfragen, mit zwei Lehren aus der
Gegenprüfung:

- *Fragen müssen von Nutzern stammen, nicht vom pflegenden Agenten.* Fragen, die der Agent mit
  offener Seite schreibt, bestehen 40 von 40, während 18 Alltagsfragen zu denselben Seiten
  scheitern. Fragen mit Wortüberlapp zur Zielseite finden 37 von 44, unabhängig formulierte 20
  von 63.
- *Ein Claim als Ziel ist Pflicht*, nicht nur eine Seite. Sonst bleibt eine Frage grün, nachdem
  der Fakt gelöscht wurde. Gemessen: Rang 5 statt Rang 1, aber weiterhin „gefunden".

Diese Kennzahlen bleiben Pflegerdaten und gehören nie in die Qualitätszeile für Leser. Dort würde
schon ein Hinweis jedes aktualisierte Wiki auf „Prüfung fällig" setzen
(`assess_quality.py:279-282`).

### Befund 7 — Plattformlücken

**Beobachtung.** Unter Windows schreibt Python eine umgeleitete Ausgabe in der ANSI-Codepage.
Alle Helfer geben JSON mit `ensure_ascii=False` aus. Ein einziges Zeichen außerhalb von cp1252
in einer Seite, etwa „≥", bricht die Suche mit leerer Ausgabe ab (simuliert mit
`PYTHONIOENCODING=cp1252`). Die Suche nimmt außerdem kein `--expect-manifest-sha256` an. Mehrere
Aufrufe einer Antwort können also unbemerkt zwei Releases mischen.

**Empfehlung.** `sys.stdout.reconfigure(encoding="utf-8")` in jedem Einstieg beider Skills und
der Vorlagen, mit einem cp1252-Regressionstest. `--expect-manifest-sha256` an der Suche, mit
Ergebnis `snapshot_changed`. Die Prüfung der Python-3.9-Grammatik ist in diesem Branch umgesetzt.

---

## 5. Was bewusst nicht übernommen werden sollte

- **Neuronale Embeddings, Vektorindex, Suchdienst.** Gründe in Abschnitt 3.
- **Statische Embedding-Tabelle.** Gemessen +0 auf dem Stapel, und sie macht jede Negativfrage
  zu 12 Treffern.
- **LSA, Kookkurrenz, Pseudo-Relevanz-Feedback.** Schlechter als die Wortform-Schicht und nicht
  erklärbar.
- **Ein Score-Schwellenwert als Fehlanzeige.** Scores sind ungeeicht (Befund 4).
- **Der vollständige Katalog als Pflicht vor jeder Fehlanzeige.** Unlesbar ab einigen hundert
  Seiten. Stattdessen ein budgetierter `--exhaustive`-Aufruf.
- **Blättern mit `--offset` und ein seitenweiser Katalog in der ersten Ausbaustufe.** Jede Seite
  ist ein neuer Prozess mit zwei Hash-Durchläufen (etwa 5 Sekunden bei 4.626 Seiten) und öffnet
  eine Lücke für gemischte Releases. Zählwerk, Limit bis 100 und `--exhaustive` decken den
  Bedarf.
- **Hinweise über „Related" oder Unterbegriffe.** 11 solche Hinweise auf dem Test-Wiki, 0
  relevant.
- **Tippfehlerkorrektur mit zwei Änderungen, Kompositumteile an Nicht-Kopf-Position ohne
  Korpusprüfung, Bindestrich-Teilung von Slugs, „-er"-Abschneiden bei Substantiven.**
- **Vom pflegenden Agenten geschriebene Suchproben als Auffindbarkeitsmaß.** Sie bestätigen sich
  selbst (Befund 6).
- **Bestwert-Fusion über Umformulierungen.** Siehe Befund 3.

---

## 6. Umsetzungsplan

### Stufe 0 — Export reparieren *(erledigt)*

Importhülle statt fester Liste, Verweigerung von Pflegewerkzeugen, Selbsttest aller
mitgelieferten Werkzeuge in sauberer Umgebung, Aufräumen bei Fehlschlag, keine Caches im Paket,
Exporttests, statische Prüfungen für die Vorlagen und Python-3.9-Grammatikprüfung.

### Stufe 1 — Ein Suchkern und ein Zählwerk *(bis auf E4 keine Produktentscheidung nötig)*

1. `search_core.py` plus `bm25.py` als geteilter Kern beider Skills, in der Paritätsliste von
   `tests/test_packaging.py`. Die Export-Suche wird ein dünner Wrapper. Damit rankt der Export
   wie der Lese-Skill. Das ist eine gewollte Verhaltensänderung des Exports und gehört in die
   Release-Notiz.
2. Das Zählwerk aus Befund 1, nur zusätzliche Schlüssel.
3. `--expect-manifest-sha256` an der Suche, UTF-8-Ausgabe in allen Einstiegen.
4. Die Testfragen-Batterie als Messinstrument ins Repository, siehe Entscheidung E4. Dazu ein
   **Präzisionstor** als Test:
   - Keine Pflichtseite, die heute unter den ersten 3 steht, verlässt sie.
   - Keine Pflichtseite fällt aus dem Standardlimit.
   - Navigationsseiten gewinnen keine Top-3-Plätze.
   - Die Trefferzahl der Negativfragen bleibt gedeckelt.

   Die bestehenden fest verdrahteten Ranking-Tests bestanden auch unter einem Prototyp mit 14
   verschlechterten Pflichtseiten. Sie schützen also nicht.
5. Doku nach Repo-Konvention: `SKILL.md`, `references/`, README-Tabellen, `describe_actions`
   (dort fehlt heute schon `--limit`), Evals, neu gebaute Pakete.

### Stufe 2 — Wortformen *(braucht Entscheidung E1)*

1. Gewichtete Begriffsgruppen in `bm25.py` mit rückwärtskompatibler Signatur. Ohne Gruppen ist
   der Weg byte-identisch zu heute. Score 0 bleibt Score 0.
2. Zuerst der vorsichtige Teil (Schritte a und b: 57 → 67). Kompositumteile und Tippfehler
   (→ 81) erst, wenn das Präzisionstor aus Stufe 1 grün ist.
3. Die fünf Konstruktionsregeln aus Befund 2 als Unit-Tests festnageln.
4. `match_rules` je Treffer und `unmatched_terms` je Anfrage. Die Schicht ist eine ausgewiesene
   Heuristik, und so steht es in der Antwort.

### Stufe 3 — Bedeutung über Agent und Kuration

1. `--also` beziehungsweise `--request -`, Reihum-Fusion nach Rang, `found_by`, getrennter Block
   für Treffer nur aus Umformulierungen.
2. Lese-`SKILL.md` und exportierte `SKILL.md`: bis zu fünf Umformulierungen in der Wiki-Sprache,
   bei fremdsprachigen Fragen immer eine Übersetzung.
3. Pflege: Anleitung zu Seiten-Aliasen in Nutzersprache, Lint-Statistik für Allerweltswörter
   unter den Aliasen, skalarer `aliases`-Wert als ein Alias mit Warnung.

### Stufe 4 — Abgesicherte Fehlanzeige *(braucht Entscheidung E2)*

`--exhaustive` mit Budget, `absence_check`, `search_record`, Textscan über Claims und Quelltexte,
Regel für nicht leere, aber falsche Ergebnisse (Befund 1), die Fehlanzeige-Regel in allen drei
Anweisungstexten, neue Evals.

### Stufe 5 — Prüfungen beim Release *(braucht Entscheidung E3)*

Quellenabdeckungs-Bericht und Locator-Auflösung als Warnungen. Optional Auffindbarkeitsfragen
von Nutzern, mit Claim-Ziel, nur für Pfleger. Robusterer Begriffswelt-Parser: Eine Überschrift
außerhalb der ID-Grammatik beendet die laufende Begriffswelt, statt sie still zu verfälschen.

### Reihenfolge und Abhängigkeiten

Stufe 1 zuerst: Ohne gemeinsamen Kern wäre jede weitere Stufe doppelt zu bauen, und ohne
Präzisionstor lassen sich die Wortformen nicht sicher einführen. Stufe 3 hängt nicht von
Stufe 2 ab und kann parallel laufen. Stufe 4 braucht die Zähler aus Stufe 1 und die Wortformen
aus Stufe 2 für ihren Textscan. Stufe 5 ist unabhängig. Ihr Quellenabdeckungs-Teil lohnt früh,
weil er die leiseste Lücke schließt.

### Wie Erfolg gemessen wird

Nicht nur Trefferquote:

- Treffer unter den ersten 1, 3 und 12 sowie unter den ersten 100.
- Verschlechterungen pro Frage gegenüber heute, nicht nur Kategoriesummen.
- Trefferzahl und Top-3-Plätze der Negativfragen.
- Anteil der Navigationsseiten unter den ersten 3.
- Claim-Trefferquote: Ist der antwortende Claim unter den zurückgegebenen?
- Negativfragen *mit* Agent-Umformulierungen.

---

## 7. Offene Entscheidungen

**E1 — Wortlaut der Erweiterungsregel.** Jede `CONCEPTS.md` enthält „Search may expand a query
only through confirmed preferred terms and aliases", und dieselbe Regel steht an drei weiteren
Stellen. Wortformen desselben Wortes sind Abgleich, keine Erweiterung. Kompositumteile und
Tippfehler sind aber Heuristiken, die über das getippte Wort hinausgehen. Vorschlag: „Wortformen
desselben Wortes gelten als Abgleich; Teil- und Näherungstreffer sind ausgewiesene Heuristiken;
Agent-Umformulierungen werden aufgelistet." Dazu ein Lint-Hinweis für bestehende
`CONCEPTS.md`-Texte. Das entscheidet der Eigentümer.

**E2 — Der vollständige Prüfpfad als Ausnahme vom gestuften Lesen.**
`answer-contract.md` sagt „Do not read every directory index by reflex", und Eval 11 prüft das.
Ein `--exhaustive`-Aufruf ist kein Lesen aller Indizes, braucht aber eine ausdrückliche Ausnahme
und eine Budgetgröße (Vorschlag: etwa 100.000 Zeichen).

**E3 — Auffindbarkeitsfragen.** Wer schreibt sie (Vorschlag: der Eigentümer oder echte Nutzer,
nie der Agent)? Liegen sie in `schema/` und reisen damit in jeden Export mit, oder bleiben sie
beim Pfleger?

**E4 — Messinstrument ins Repository.** Soll das synthetische Test-Wiki mit den 114 Fragen als
Fixture unter `tests/` eingecheckt werden? Ohne das bleibt jede Ranking-Änderung ungemessen.

**E5 — Wie weit die Wortform-Schicht standardmäßig geht.** Nur Schritte a und b (57 → 67 unter
den ersten 12; Treffer der Negativfragen 16 → 28) oder alle vier Schritte (57 → 81; 16 → 31
unter den ersten 12, 16 → 45 unter den ersten 100). Empfehlung: mit a und b beginnen, c und d
hinter dem Präzisionstor freischalten.

---

## Umsetzungsstand (2026-11-13)

Stufe 0 ist in diesem Branch umgesetzt:

- `maintain-llm-wiki/scripts/export_wiki_skill.py`: `library_closure()` ermittelt die
  Bibliotheken aus den Importen der Vorlagen und lässt nur Module der Positivliste
  `EXPORTABLE_LIBRARIES` zu (heute `frontmatter_contract.py`, `trust_contract.py`,
  `wiki_filters.py`). `run_self_check()` führt Verifikation, Identitätsstatus,
  Qualitätsbewertung und Suche im erzeugten Ordner aus, mit `-B -S -s` und ohne `PYTHONPATH`.
  Bei Fehlschlag wird der Ordner entfernt. `packaged_files()` hält Caches unter `scripts/` aus
  dem Paket, lässt aber jede Datei unter `references/knowledge/` darin, weil das Manifest sie
  bindet.
- `tests/test_export.py` (neu, 13 Tests): Export gelingt; jedes Werkzeug läuft im installierten
  Ordner allein und aus dem entpackten `.skill`-Paket; eine veröffentlichte Datei namens
  `graph/legacy.pyc` kommt mit ins Paket; nur geprüfte Bibliotheken, darunter
  `trust_contract.py`, und kein Pflegewerkzeug; kein Cache neben den Werkzeugen; zwei Exporte
  eines Release sind byte-identisch; der Paketfilter wirkt nur unter `scripts/`. Abgelehnt
  werden: ein unerfüllbarer Import, auch wenn `PYTHONPATH` oder eine `.pth`-Datei in den
  Site-Paketen ihn bereitstellen würde; eine ungeprüfte neue Bibliothek; `release_wiki`,
  `navigation` und `portable_io` als Importe. Nach einer Ablehnung bleibt kein Ordner zurück.
- `tests/test_packaging.py`: Die Vorlagen unter `assets/knowledge-skill` werden auf auflösbare
  Importe geprüft. Jede Bibliothek der Positivliste muss frei von Schreibaufrufen bleiben. Alle
  Helfer und Vorlagen müssen mit der Grammatik von Python 3.9 parsen.
- Gegenproben: Gegen den Exporter vor diesem Branch schlug der Kerntest fehl. Eine unabhängige
  Prüfung meiner ersten Korrektur fand vier weitere Fehler: Bytecode-benannte Release-Dateien
  fehlten im Paket; schreibende Bibliotheken ohne Einstieg wären mitgekommen; ein umgedrehter
  `__main__`-Vergleich blieb unerkannt; über `.pth`-Dateien bestand der Selbsttest fälschlich.
  Die Tests oben schlagen gegen diese erste Korrektur 11-mal an.
- `maintain-llm-wiki/SKILL.md`, `references/wiki-contract.md` und README Abschnitt 4.16
  beschreiben Importhülle und Selbsttest. Beide Pakete sind neu gebaut.

Stufen 1 bis 5 sind offen.

---

## Anhang A — Messmethode und Grenzen

**Test-Wiki.** Ein synthetisches deutschsprachiges Wiki eines fiktiven Stadtwerks: 45
Inhaltsseiten (50 Markdown-Dateien mit Indizes), 11 Quellen und 8 Begriffswelten, veröffentlicht
als Release 0.1.1 mit den echten Helfern. Dazu 114 Fragen in 15 Kategorien mit Pflichtseiten.
Davon sind 107 beantwortbar und 7 betreffen fehlende Themen.

**Ausgangslage je Kategorie** (unter den ersten 3 / 12 / 100, nicht gefunden auch mit Quellen):

| Kategorie | Fragen | 3 | 12 | 100 | nicht gefunden |
|---|---|---|---|---|---|
| exakt | 7 | 7 | 7 | 7 | 0 |
| Flexion | 8 | 0 | 3 | 4 | 4 |
| Umlaut-Umschrift | 7 | 6 | 6 | 6 | 1 |
| Komposita | 8 | 4 | 4 | 4 | 4 |
| Synonym, nicht kuratiert | 8 | 1 | 2 | 2 | 6 |
| Synonym, kuratiert | 7 | 7 | 7 | 7 | 0 |
| Umschreibung | 8 | 0 | 2 | 6 | 2 |
| andere Sprache | 8 | 1 | 1 | 1 | 7 |
| Tippfehler | 8 | 1 | 1 | 1 | 7 |
| breite Frage | 5 | 0 | 0 | 0 | 5 |
| claimlastig | 8 | 8 | 8 | 8 | 0 |
| nur in Quellen | 8 | 0 | 0 | 0 | 0 (alle 8 auf Rang 1 mit Quellen) |
| abgelöst/Historie | 6 | 3 | 6 | 6 | 0 |
| Kennung | 11 | 9 | 10 | 10 | 1 |
| **Summe** | **107** | **47** | **57** | **62** | **37** |

**Vorgehen.** Drei unabhängige Entwürfe (Absicherung zuerst, echte Semantik-Optionen,
Wortform-Prototyp) und vier gezielte Gegenprüfungen: Produktregeln und Tests, Recall-Lücken,
Präzision und Ranking, Praxistauglichkeit. Prototypen liefen gegen den echten Code. Im
abgeschalteten Zustand waren sie byte-identisch zur Repo-Suche (342 von 342 Läufen).

**Grenzen.**

- Ein einziges, synthetisches, deutschsprachiges Wiki mit 52 durchsuchten Seiten. Gewichte und
  Schwellen wurden darauf gewählt, ohne zurückgehaltene Testmenge.
- Falsch-Paarungen von Stemmer und Komposita beurteilte ein einzelner Gutachter.
- Python 3.9 wurde nicht ausgeführt, nur seine Grammatik geprüft.
- Windows wurde simuliert, PowerShell-Quoting nicht geprüft.
- Zeiten und Größen bei 500 bis 5.000 Seiten stammen aus vervielfältigten Kopien. Der
  Wortschatz wächst dort nicht wie in einem echten Wiki.
- Die Agent-Umformulierungen wurden vor dem Öffnen der Seiten geschrieben, aber vom selben
  Modell, das auch auswertete.

Die Zahlen sind deshalb Richtwerte für Entscheidungen, keine Zusagen für beliebige Wikis.
