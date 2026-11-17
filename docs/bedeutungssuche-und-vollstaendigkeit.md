# Bedeutungssuche und Vollständigkeit im erzeugten Wissens-Skill

Analyse, Umsetzungsplan und Umsetzungsstand
Stand: 2026-11-16 (Analyse und Plan vom 2026-11-13; alle sechs Stufen sind umgesetzt, siehe
Abschnitt „Umsetzungsstand")
Ausgangsfrage: „Wie bekomme ich eine Bedeutungssuche in den Skill, den das Projekt erzeugt, und
wie stelle ich sicher, dass er nichts übersieht?"
Messgrundlage: ein synthetisches Test-Wiki und 114 Testfragen. Zur Analyse lagen beide außerhalb
des Repositorys; seit Stufe 1 liegen sie unter `tests/fixtures/search_quality/` (Anhang A).

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
   Komposita und Tippfehler, seit Stufe 6 auch unregelmäßige Formen aus einer geschlossenen
   Tabelle, Fugenvarianten und Mengenangaben in anderer Schreibweise. Jede
   Treffer-Begründung wird ausgewiesen.

**„Nichts übersehen" lässt sich für Bedeutung nicht garantieren, wohl aber in überprüfbare Teile
zerlegen:**

- *Durch Konstruktion garantiert:* Kein Verlust bleibt stumm. Jede Kürzung wird gezählt:
  Gesamttreffer, Abschneiden, zurückgehaltene Claims, Begriffe ohne Treffer, nicht durchsuchte
  Schichten.
- *Durch ein Werkzeug geprüft und durch eine feste Regel gebunden:* „Das Wiki enthält dazu
  nichts" darf nur gesagt werden, wenn ein gebündelter Helfer eine vollständige Prüfung bestätigt
  hat, und es gilt dann für die gesuchten Formulierungen. Sonst lautet die Aussage: „Mit diesen
  Wörtern in Release V nicht gefunden."
- *Pro Release gemessen:* Quellenabdeckung (welche Quelle trägt keinen Claim) und, optional,
  Auffindbarkeit mit Fragen, die echte Nutzer formuliert haben.
- *Pro Antwort offengelegt:* womit gesucht wurde und was nicht geprüft werden konnte.

**Ein kritischer Fehler wurde dabei gefunden und in diesem Branch behoben:** Die Suche des
exportierten Wissens-Skills stürzte seit Commit `553e974` bei *jedem* Aufruf ab. Der Export
meldete trotzdem Erfolg (Befund 0).

| # | Befund (Stand vor Stufe 1) | Wert | Aufwand | Stand |
|---|---|---|---|---|
| 0 | Exportierte Suche stürzt bei jedem Aufruf ab | kritisch | niedrig | erledigt (Stufe 0) |
| 1 | Verluste sind stumm | hoch | niedrig | erledigt (Stufe 1) |
| 2 | Wortformen werden nicht erkannt | hoch | mittel | erledigt (Stufe 2) |
| 3 | Synonyme, Umschreibungen und andere Sprachen erreichen die Suche nicht | hoch | niedrig bis mittel | erledigt (Stufe 3), soweit der Agent umformuliert |
| 4 | Eine Fehlanzeige ist nicht abgesichert | hoch | mittel | erledigt (Stufe 4) |
| 5 | Der exportierte Skill ist eine abgedriftete Kopie | mittel | mittel | erledigt (Suche Stufe 1, Qualitätsbewertung Stufe 6) |
| 6 | Der Release prüft weder Quellenabdeckung noch Auffindbarkeit | mittel | mittel | erledigt (Stufe 5) |
| 7 | Plattformlücken: Windows-Ausgabe, Release-Bindung der Suche | mittel | niedrig | erledigt (Stufe 1) |

Was die Bausteine auf dem Test-Wiki bringen. Gezählt sind 107 beantwortbare Fragen. „Gefunden"
heißt: alle Pflichtseiten der Frage stehen in der Liste. Die oberen Zeilen sind Messungen der
Prototypen aus der Analyse, die drei letzten Messungen des umgesetzten Produkts.

| Variante | unter den ersten 3 | unter den ersten 12 (Standard) | unter den ersten 100 |
|---|---|---|---|
| vor Stufe 1 | 47 | 57 | 62 |
| nur kuratierte Seiten-Aliase, kein Code (Prototyp) | 64 | 74 | 79 |
| nur Wortformen (empfohlener Regelsatz des Prototyps) | 67 | 81 | 88 |
| kuratierte Begriffe + Wortformen (Prototyp) | 83 | 93 | 97 |
| … zusätzlich mit Quellenschicht (Prototyp) | 89 | 99 | 105 |
| Wortformen + blind geschriebene Agent-Umformulierungen (Simulation) | – | 101 | – |
| **umgesetzt: Wortformen (Stufe 2), nur die Frage** | **64** | **74** | **84** |
| **umgesetzt: zusätzlich Tabellenformen, Fugenvarianten und Mengenangaben (Stufe 6), nur die Frage** | **66** | **76** | **85** |
| **umgesetzt: zusätzlich vier Umformulierungen (Stufe 3), Frage oder Block, Satz A / B** | **86 / 86** | **99 / 98** | **99 / 99** |

Die beiden Zeilen „kuratierte Begriffe + Wortformen" stammen aus einem zweiten Entwurf mit
lockereren Wortformregeln. Die Kombination mit dem empfohlenen Regelsatz wurde nicht gemessen.
Die letzte Zeile zählt eine Frage, wenn jede Pflichtseite unter den ersten N der Frage oder des
Blocks `reformulation_results` steht; sie sieht also bis zu 2N Seiten. Bei gleich vielen
Plätzen, abwechselnd aus beiden Listen, sind es 83 unter den ersten 3 und 89 unter den ersten 12,
in beiden Sätzen (nach Stufe 6: 83 und 90). Die Zeile „Simulation" (101) war eine Schätzung der Analyse; gemessen im
Produkt sind es 99 und 98. Dass die Aliase-Zeile und die umgesetzte Wortform-Zeile beide 64 und
74 zeigen, ist Zufall: Die eine ist ein Versuch mit zusätzlich kuratierten Seiten-Aliasen ohne
Code, die andere misst die Wortformen auf dem unveränderten Test-Wiki.

Der Preis ist Präzision. Für Themen, die das Wiki gar nicht enthält, stieg die Zahl der Treffer
von 16 auf 31 (sieben Testfragen, jeweils höchstens 12 Treffer), im Prototyp wie im umgesetzten
Produkt. Eine Score-Schwelle trennt „gefunden" nicht von „nicht vorhanden". Deshalb braucht es
Befund 1 und 4 genauso wie Befund 2 und 3.

---

## 2. Wie die Suche vor Stufe 1 arbeitete

Die Lese-Suche (`query-llm-wiki/scripts/search_wiki.py`, `bm25.py`) rankte mit BM25F über fünf
Felder: Titel 10, Aliase 7, Überschriften 5, Beschreibung 4, Text 1. Danach kamen
multiplikative Faktoren für Phrase (1,5), passende Begriffswelt (+0,5 je Begriff) und Status
(aktiv 1,15, Entwurf 0,95, abgelöst 0,75). Der Tokenizer faltete Groß- und Kleinschreibung und
entfernte Diakritika. Bindestrich-Wörter blieben ein Token. Mehrere Suchwörter waren
ODER-verknüpft. Standardmäßig kamen 12 Treffer mit je höchstens 8 Claims zurück. Quellen und
Historie wurden nur auf Schalter durchsucht. Eine Begriffswelt erweiterte die Anfrage nur über
ihren bestätigten Vorzugsbegriff und ihre Aliase. Definition, Oberbegriff und verwandte Begriffe
nutzte die Suche nicht.

Der **exportierte** Wissens-Skill hatte eine eigene, ältere Suche
(`maintain-llm-wiki/assets/knowledge-skill/search_knowledge.py`). Sie arbeitete additiv mit
handgewählten Gewichten, kannte kein BM25, keine Historie und keine Ablaufdaten und wies die
Vertrauensstufe eines Treffers nicht aus. Filtern ließ sie nur über `--filter-json` mit
`__trust_tier`.

Heute gilt: Felder, Gewichte, Faktoren, Limits und die Erweiterung über Begriffswelten sind
unverändert. Beide Skills und jeder neue Export suchen mit demselben Kern (`search_core.py` mit
`bm25.py` und `wordforms.py`); hinzu kamen Zählwerk, Wortformen, Umformulierungen und die
vollständige Prüfung (Abschnitt „Umsetzungsstand").

---

## 3. Warum keine Embedding-Suche

Untersucht und, wo möglich, gemessen wurden fünf Familien:

| Option | Ergebnis (3 / 12 / 100 von 107) | Urteil |
|---|---|---|
| A Neuronale Embeddings (Modell, Vektorindex) | nicht gemessen | bricht vier Regeln; `onnxruntime` braucht Python ≥ 3.11, das Modell muss heruntergeladen werden |
| B Statische Embedding-Tabelle im Skill | ohne Schwelle 68 / 81 / 99, mit Ähnlichkeitsschwelle hinter der Wortsuche 58 / 71 / 76; **+0** auf dem Stapel | ohne Schwelle 12 Treffer für *jede* Negativfrage; mit Schwelle Fehltreffer wie vor Stufe 1 (16), aber weniger gefunden als mit Aliasen (71 statt 74) und bei englischen Fragen 1 von 8 statt 7 von 8 |
| C1 Zeichen-n-Gramm-Kosinus (3–5) | 76 / 88 / 99, aber 12 Treffer für jede Negativfrage | nicht als Ranker; **übernehmen** nur als erklärbare Wortform-Schicht (67–71 / 81–83 / 88–91, Befund 2) |
| C2–C5 LSA, Random Indexing, Kookkurrenz, Pseudo-Relevanz-Feedback | – / 59–67 / – | schlechter als die Wortform-Schicht, nicht erklärbar |
| D Kuratierte Erweiterung (Aliase, eingefroren im Release) | 70 / 79 / 85 | **übernehmen**, wirkte teilweise schon vor Stufe 1 |
| E Host-Agent formuliert um | 16 von 16 Umschreibungs- und Fremdsprachfragen unter den ersten 12, je nach Fusionsverfahren 14–16 von 16 unter den ersten 3 (Original allein: 3 von 16 unter den ersten 12) | **übernehmen**, der einzige Hebel für andere Sprachen |

Die Regelkonflikte im Einzelnen:

- *Nur Skill, kein Dienst* (README: „Kein MCP-Server, kein Dienst, kein Hintergrundprozess —
  auch nicht optional, auch nicht später").
- *Nur Standardbibliothek.* `numpy` steht in `tests/test_packaging.py` auf der Sperrliste.
- *Der Leser schreibt nichts.* Lese-Skill und exportierter Skill dürfen keinen Index anlegen.
- *Nur bestätigte Begriffswelten erweitern.* `init_wiki.py` schrieb bis Stufe 2 in jede
  `CONCEPTS.md`: „Search may expand a query only through confirmed preferred terms and
  aliases." Seit E1 heißt es: „Search expands a query in meaning only through confirmed
  preferred terms and aliases." Eine Ähnlichkeitssuche wäre auch nach dem neuen Wortlaut eine
  unbestätigte Erweiterung.

Der Host-Agent ist bereits ein Sprachmodell. Ein zweites Modell im Skill wäre teurer und
schlechter prüfbar. Ohne Schwelle war es bei den Negativfragen gemessen schädlich, mit Schwelle
brachte es weniger als Aliase und auf dem Stapel nichts.

---

## 4. Die Befunde im Einzelnen

Die Befunde beschreiben den Stand vor Stufe 1 und stehen deshalb in der Vergangenheitsform. Die
Empfehlungen sind der Plan von damals. Was daraus wurde und wo die Umsetzung abwich, steht am
Ende jedes Befunds unter „Umgesetzt" und ausführlich im Abschnitt „Umsetzungsstand".

### Befund 0 — Die exportierte Suche stürzte bei jedem Aufruf ab *(behoben in Stufe 0)*

**Beobachtung.** `wiki_filters.py` importiert seit Commit `553e974` das Modul `trust_contract`.
Der Exporter kopierte seine Bibliotheken aber aus einer festen Liste
(`frontmatter_contract.py`, `wiki_filters.py`), in der `trust_contract.py` fehlte.

**Das Problem.** Jeder Aufruf von `scripts/search_knowledge.py` im exportierten Skill endete mit
`ModuleNotFoundError: No module named 'trust_contract'`. Reproduziert wurde das in 456 von 456
Aufrufen. Der Export meldete dennoch `exported`, weil sein Selbsttest nur
`verify_knowledge.py` ausführte, und das importiert nichts Lokales. Kein Test berührte den
Exporter, und die statischen Importprüfungen erfassten die Vorlagen unter `assets/` nicht. Ein
Endnutzer bemerkte den Fehler erst bei seiner ersten Frage. Für die Ausgangsfrage hieß das: Der
erzeugte Skill hatte bis dahin *alles* übersehen.

**Empfehlung, umgesetzt.** Der Exporter ermittelt die benötigten Bibliotheken jetzt selbst, als
transitive Hülle der Importe seiner Vorlagen. Jeder Import muss auf einer von zwei geprüften
Listen stehen: lesende Bibliotheken des Skills oder Standardbibliotheksmodule, die es ab Python
3.9 auf allen Plattformen gibt und die selbst nichts schreiben. Alles andere lehnt er mit Namen
ab, ebenso relative und dynamische Importe, bevor er irgendetwas schreibt. Pflegewerkzeuge und
schreibende Bibliotheken kommen so nie in einen Export, und ein neuer Import wird laut abgelehnt
statt still vergessen. Vor dem Paketbau führt er jedes mitgelieferte Werkzeug im erzeugten Ordner
aus, die Suche auch mit Metadatenfilter. Weder `PYTHONPATH` noch installierte Pakete können dabei
einen fehlenden Import ersetzen. Scheitert irgendetwas nach Beginn des Schreibens, auch durch
Abbruch, entfernt er Ordner und Paket wieder. Interpreter-Caches neben den Werkzeugen kommen nie
ins Paket. Tests in `tests/test_export.py` prüfen das, und `tests/test_packaging.py` prüft
auch die Vorlagen (Abschnitt „Umsetzungsstand").

### Befund 1 — Verluste waren stumm *(erledigt in Stufe 1)*

**Beobachtung.** Die Suchausgabe nannte weder die Gesamtzahl der Treffer noch, ob abgeschnitten
wurde. Claims waren auf 8 pro Seite gekappt, ohne Zählung. Suchwörter ohne jeden Treffer wurden
nicht gemeldet. Das Stoppwort „für" wurde nie entfernt: Der Tokenizer machte daraus „fur", die
Liste enthielt aber „für". Navigationsseiten belegten 90 von 781 Ergebnisplätzen (78-mal eine
Indexseite, 9-mal `meta/questions.md`, 3-mal `WIKI.md`). Dass eine nicht durchsuchte Quelle das
Suchwort enthielt, erfuhr der Agent nicht. Ein leeres Ergebnis sah gleich aus, ob das Thema
fehlte oder nur ein anderes Wort verwendet wurde.

**Das Problem.** Der Agent konnte nicht unterscheiden zwischen „nichts da", „nicht gezeigt" und
„anders formuliert". Drei Messungen machten das greifbar:

- 5 Fragen hatten ihre Pflichtseite auf Rang 15 bis 39. Ohne Hinweis auf das Abschneiden sucht
  niemand weiter.
- 7 von 8 Fakten, die nur in Quellen stehen, wären über einen Hinweis „Quellen enthalten das
  Suchwort" auffindbar gewesen. Der Hinweis fehlte.
- Bei einer Frage nach einer Ausnahme (Abschlag um mehr als 20 Prozent senken) kam Claim 9 von
  12 nie zurück, weil er die Suchwörter nicht enthält. Der benachbarte Claim 7 wirkte wie die
  ganze Antwort.

Am häufigsten war aber ein anderer Fehler: ein **nicht leeres, aber falsches** Ergebnis. Mit
Wortformen und Agent-Umformulierungen lieferten im Prototyp 22 von 107 Fragen eine Liste, deren
erster Treffer falsch ist, aber wie ein exakter Treffer aussieht. Bei „Gastarif Kündigungsfrist"
steht die Strom-Kündigungsfrist oben. Dass „Gastarif" im ganzen Wiki nicht vorkommt, sah niemand.

**Empfehlung.** Ein Zählwerk in der Suchausgabe, das nur Schlüssel ergänzt und das Ranking nicht
verändert. Der Prototyp lieferte in 114 von 114 Fragen identische Ranglisten, die Ausgabe wuchs
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

**Umgesetzt.** Stufe 1 brachte den Block `coverage` mit allen genannten Zählern und je Treffer
`matched_terms`, `claims_total`, `claims_returned` und `navigation`; das Ranking blieb in 114 von
114 Fragen gleich. Abweichung: Navigationsseiten stehen nicht in einer eigenen Liste, sondern
bleiben in der Rangliste und tragen `navigation: true`, damit sich das Ranking nicht ändert;
zitiert werden sie nie. „für" fällt seit Stufe 2 wieder weg. Die Regel für nicht leere, aber
falsche Ergebnisse steht seit Stufe 4 im Antwortvertrag („Results that do not answer"), die
Teil-Fehlanzeige hängt seither an `absent_terms` der vollständigen Prüfung statt an
`matched_terms`.

### Befund 2 — Wortformen wurden nicht erkannt *(erledigt in Stufe 2)*

**Beobachtung.** Eine Suche nach „Tarife" fand keine Seite, auf der nur „Tarif" steht. Ebenso
wenig fand „Kuendigung" das Wort „Kündigung", „Gebühr" das Wort „Durchleitungsgebühr" und der
Tippfehler „Netzentgeld" das Wort „Netzentgelt". Gemessen unter den ersten 12: Flexion 3 von 8,
Komposita 4 von 8, Tippfehler 1 von 8. Bei den ae/oe/ue-Schreibweisen traf in 0 von 6 Fällen der
eigene Text der Zielseite. Gefunden wurde sie nur über Link-Slugs.

**Das Problem.** Das sind keine Bedeutungsfragen, sondern dasselbe Wort in anderer Form.
Trotzdem gingen sie verloren, und ein Suchwort mit null Treffern sah aus wie ein fehlendes Thema.

**Empfehlung.** Jedes Suchwort wird zu einer gewichteten Gruppe von Tokens, die *im Korpus
tatsächlich vorkommen*. Das wörtliche Token zählt 1,0, Formen zählen fest weniger. `bm25.py`
wertet die Gruppe als einen Begriff. Gemessene Leiter des empfohlenen Regelsatzes im Prototyp
(unter den ersten 12 / unter den ersten 100; in Klammern die Treffer der sieben Negativfragen
unter den ersten 12):

| Schritt | Regel | Ergebnis |
|---|---|---|
| vor Stufe 1 | – | 57 / 62 (16) |
| a | Umlaut-Umschrift und Silbentrenn-Reparatur, normalisierte Stoppwörter, Funktionswörter nur wörtlich | 58 / 62 (20) |
| b | leichter Stemmer (Endungen, keine Ableitungen) plus Verbformen | 67 / 71 (28) |
| c | Kompositumteile, nur wenn der Rest aus echten Korpuswörtern besteht | 75 / 82 (31) |
| d | Tippfehler: eine Änderung, nur Wörter ab 7 Buchstaben ohne andere Übereinstimmung | 81 / 88 (31) |

Ergebnis je Kategorie unter den ersten 12: Flexion 3 → 7 von 8, Komposita 4 → 8 von 8,
Tippfehler 1 → 8 von 8, Umlaut-Umschrift 6 → 7 von 7. Ein zweiter, aggressiverer Regelsatz aus
einem anderen Entwurf kam allein auf 83 / 91. Dort lieferten aber alle 7 Negativfragen Treffer
statt 5, im Mittel 7,1 pro Frage statt 4,4 beim empfohlenen Regelsatz (vor Stufe 1: 2,3), vor
allem durch lockerere Kompositumregeln.

Die Gegenprüfung fand fünf Konstruktionsfehler, die ein naiver Einbau gehabt hätte. Jeder davon
hätte korrekte Antworten verschlechtert:

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
auf Begriffswelt-Aliase anwenden (sonst verliert die bestätigte Begriffsseite Rang 1, etwa
`grundversorgung.md` bei „Basisversorgung kündigen"); das Suchwort selbst nur in Kopfposition und
gegen echte Korpuswörter zerlegen (die freie Zerlegung von „Gastarif" in „gas" + „tarif" hob eine
Negativfrage von 5 auf 32 Treffer); kein Abschneiden von „-er" bei Substantiven (Zähler ≠
zahlen).

Was die Schicht nicht kann: Synonyme, Umschreibungen und andere Sprachen. Fremdsprachige Fragen
bleiben bei 1 von 8. Unregelmäßige Formen fehlen ebenfalls: „umgezogene" findet „Umzug" nicht;
diese Frage rutschte im Prototyp von Rang 5 auf 17, im Produkt von Rang 5 auf 10. Seit Stufe 6
findet eine geschlossene Tabelle die häufigen unregelmäßigen Formen (`irregular`, `derived`),
und die Seite steht auf Rang 2; Formen außerhalb der Tabelle bleiben unerkannt.

**Umgesetzt.** Stufe 2 brachte alle vier Schritte als `wordforms.py`, mit Tippfehlern erst ab 8
Buchstaben und mehreren gemessenen Abweichungen vom Prototyp (Abschnitt „Umsetzungsstand",
Stufe 2). Abschlussmessung: 74 statt 57 Fragen unter den ersten 12, 31 statt 16 Treffer der
Negativfragen; nach Stufe 6 sind es 76 Fragen bei gleich vielen Treffern der Negativfragen.

### Befund 3 — Bedeutung erreichte die Suche nicht *(erledigt in Stufe 3, soweit der Agent umformuliert)*

**Beobachtung.** Für unkontrollierte Synonyme wurden 2 von 8 Fragen gefunden, für
Umschreibungen 2 von 8, für Fragen in anderer Sprache 1 von 8 („Ökostrom" statt „Grünstrom",
„Beschwerde" statt „Reklamation", „grid fees" statt „Netzentgelt"). Der Lese-Skill gab die
Frage einmal an die Suche (damals `query-llm-wiki/SKILL.md`, Schritt 6).

**Das Problem.** Bedeutung kann nur der Agent beisteuern oder der Pfleger, der das Wiki kuratiert.

**Empfehlung, zweigleisig:**

*Agent-Umformulierungen in einem Aufruf.* `--also` nimmt bis zu vier Umformulierungen (mit der
Frage fünf Suchen) in der Wiki-Sprache an, Übersetzungen eingeschlossen, und fasst alles in
einem Prozess über einen verifizierten Release zusammen. Fünf getrennte Aufrufe kosteten bei
4.626 Seiten 33 Sekunden, ein zusammengefasster Aufruf rechnerisch etwa 13. Unter Windows und
PowerShell ist die Übergabe als JSON über stdin robuster (`--request -`). Zwei Regeln aus der
Gegenprüfung:

- *Rang statt Score zusammenführen.* BM25-Scores sind zwischen Formulierungen nicht
  vergleichbar. Bei Bestwert-Fusion füllte eine schlampige Formulierung bis zu 39 Prozent der
  Plätze. Reihum-Verschränkung nach bestem Rang erreichte 15 von 16 Pflichtseiten unter den
  ersten 3 und 16 von 16 unter den ersten 12.
- *Treffer nur aus Umformulierungen getrennt ausweisen* (`found_by`). Umformulierungen erzeugen
  bei Negativfragen viele Treffer: eine Frage stieg von 1 auf 28, eine andere von 0 auf 3. Ohne
  Trennung würde die Fehlanzeige nie mehr ausgelöst.

*Kuratierte Begriffe, sofort und ohne Code.* Beide Suchen gewichten Seiten-`aliases` mit 7.
Aliase in der Sprache der Nutzer (Alltagswörter, Abkürzungen, englische Begriffe) hoben das
Ergebnis im Prototyp von 57 auf 74 unter den ersten 12. Begriffswelt-Aliase wirken über die
bestätigte Erweiterung. Vorsicht bei Alltagswörtern als Alias: „Sperrung" löst die Begriffswelt
Versorgungsunterbrechung auch bei „Sperrung des Kundenportals" aus, und „Abschlag" (Rabatt)
landet bei der Abschlagszahlung. Eine Lint-Statistik soll häufige Wörter unter den Aliasen zur
Bestätigung vorlegen. Ein skalarer `aliases`-Wert (`aliases: Foo` statt Liste) bestand damals den
Lint und wurde von der Suche ignoriert. Er sollte künftig als ein Alias gelesen werden, mit
Warnung.

**Umgesetzt.** Stufe 3 brachte `--also` (bis zu vier) und `--request -`, Reihum-Fusion nach
Rang, `found_by` und den getrennten Block `reformulation_results` ohne Navigationsseiten, dazu
drei Alias-Regeln, die Lint-Statistik `stats.alias_review` und das skalare `aliases` als ein
Alias mit Warnung. Abschlussmessung mit zwei blind geschriebenen Sätzen: 99 und 98 Fragen unter
den ersten 12 von Frage oder Block (bis zu 24 Seiten), 89 bei gleich vielen Plätzen. Andere
Sprachen erreicht die Suche weiter nur über eine Übersetzung durch den Agenten.

### Befund 4 — Eine Fehlanzeige war nicht abgesichert *(erledigt in Stufe 4)*

**Beobachtung.** 5 von 7 Fragen zu Themen, die das Wiki nicht enthält, lieferten normal
aussehende Treffer (Top-Score 1,74 bis 2,49). Je nach Regelsatz hatten 20 bis 36 beantwortbare
Fragen einen Top-Score, der höchstens so hoch war wie der höchste Negativ-Score. Kein
Schwellenwert trennte beides.

**Das Problem.** Ob „nichts gefunden" hieß „nichts vorhanden", entschied allein das Urteil des
Agenten, und genau dort versagte es: Die Treffer sahen normal aus. Eine Regel, die nur als Prosa
in der `SKILL.md` steht, würde gerade in diesem Fall übersprungen.

Ein Katalog aller Seitenbeschreibungen als Vollständigkeitsnachweis wurde gemessen und taugt nur
eingeschränkt. Auf dem Test-Wiki fand eine blinde Auswahl aus 56 Katalogzeilen (10.472 Zeichen)
für 104 von 107 Fragen alle Pflichtseiten (121 von 124 Pflichtseiten). Suche unter den ersten 12
und Katalog zusammen deckten 107 von 107 Fragen ab. Aber der Katalog deckt *Seiten* ab, nicht
*Fakten*. „Kündigung" auf der Seite Grundversorgung steht nur in einem Claim, nicht in der
Beschreibung. Quellen haben gar keine Beschreibung. Und er wächst mit dem Wiki: 11.900 Zeichen
bei 50 Seiten, 121.000 bei 492 und 1,15 Millionen bei 4.628 Seiten. Das kann kein Agent pro Frage
lesen.

**Empfehlung.** Das Urteil über die Fehlanzeige liefert ein Werkzeug, und eine feste Regel in den
Anleitungstexten bindet die Aussage daran:

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

Selbst eine vollständige Prüfung beweist nur, dass keine geprüfte Passage alle geprüften Wörter
einer Formulierung zusammen enthält, selbst oder in ihrem Kontext. Eine Seite, die die Antwort
ganz anders formuliert, kann fehlen. Das gehört in die Antwort.

**Umgesetzt.** Stufe 4 brachte `--exhaustive`, `absence_check` (`lmwiki-absence-check/1`),
`search_record` (`lmwiki-search-record/1`) und das Budget von 100.000 gedruckten Zeichen.
Abweichungen: `complete` verlangt zusätzlich mindestens zwei Umformulierungen mit eigenen
Wörtern; die Historie wird nur mit `--include-history` durchsucht, weil sie außerhalb des
Release-Manifests liegt; der Scan kennt eigene, ausgewiesene Heuristiken, die das Ranking nicht
kennt. Der feste Satz steht heute in allen drei Anleitungstexten so (ein Test verlangt ihn dort
wörtlich):

> State that the wiki contains nothing on a question, or on part of it, only when a search for
> this answer reported `absence_check.complete: true` and no returned result or exhaustive hit
> answers it, and say that this holds for the formulations you searched; otherwise state that
> nothing was found with the searched words in this release version. In both cases list the
> searched formulations and quote `search_record.line`.

### Befund 5 — Der exportierte Skill war eine abgedriftete Kopie *(Suche erledigt in Stufe 1; Qualitätsbewertung in Stufe 6)*

**Beobachtung.** Der Export suchte mit einer eigenen additiven Heuristik, kannte weder BM25,
Historie noch Ablaufdaten und wies die Vertrauensstufe eines Treffers nicht aus. Seine
`assess_quality.py` war eine getrennte Kopie, der die Offenlegung von Vertrauensstufe und Ablauf
fehlte. Seine `SKILL.md` entstand aus einem Python-f-String: Ein JSON-Beispiel darin löste
`ValueError` aus. Seine Befehle hingen vom aktuellen Verzeichnis ab.

**Das Problem.** Jede Verbesserung der Suche hätte zweimal gebaut werden müssen, und die zweite
Kopie driftete nachweislich ab. Befund 0 war genau so entstanden.

**Empfehlung.** Ein Suchkern (`search_core.py` plus `bm25.py`) für Lese-Skill und Export,
byte-identisch geprüft wie die übrigen geteilten Module. Die Export-Suche wird ein dünner
Wrapper. Ebenso ein gemeinsamer Bewertungskern für `assess_quality`. Die exportierte `SKILL.md`
wird eine Vorlagendatei statt eines f-Strings, mit eigenem Antwortvertrag unter `references/`
und einem Test, der die Fehlanzeige-Regel in allen drei Anweisungstexten verlangt. Die
gemessenen 20 von 20 Pakettests bestanden mit einem geteilten Kern.

**Umgesetzt.** Suchkern, dünner Wrapper, Vorlagendatei `assets/knowledge-skill/SKILL.template.md`
mit Befehlen über den vollen Pfad des Skill-Ordners und der Test der Fehlanzeige-Regel. Die
Leseregeln stehen in der exportierten `SKILL.md` selbst statt in einem eigenen Antwortvertrag
unter `references/`. Stufe 6 brachte den gemeinsamen Bewertungskern `quality_core.py`,
byte-identisch in beiden Skills und im Export. Beide `assess_quality.py` sind dünne Wrapper, die
nur noch ihren Release prüfen. Der Export meldet jetzt wie der Lese-Skill die Verteilung der
Vertrauensstufen und die Zahl der Seiten, deren Ablaufdatum beim Release schon überschritten war;
je Treffer gilt `past_expiry`. Beibehalten sind die Unterschiede, die aus dem eingefrorenen Stand
folgen: kein `--target`, kein `--expect-manifest-sha256`, der Ersatzzustand `invalid_snapshot`
statt `invalid_wiki` und sieben Hinweise, die statt des Pflege-Skills das kanonische Wiki und
einen neuen Export nennen.

### Befund 6 — Der Release prüfte weder Quellenabdeckung noch Auffindbarkeit *(erledigt in Stufe 5)*

**Beobachtung.** Auf 2 der 11 Quellen des Test-Wikis verweist kein einziger Claim. 7 der 8
Fakten, die nur in Quellen stehen, liegen in unzitierten Abschnitten. Nicht auflösbare
`source_id@locator`-Verweise bestanden den Lint ohne Hinweis. `quality-status` hatte keine
Abdeckungskennzahl.

**Das Problem.** Was nie in einen Claim überführt wurde, findet die Wiki-Suche nie. Das ist die
leiseste Form des Übersehens.

**Empfehlung.** Ein Quellenabdeckungs-Bericht für den Pfleger: Quellen und Abschnitte ohne
Claim, nicht auflösbare Locator. Warnungen, keine Fehler, damit bestehende Wikis weiter
veröffentlichen können. Optional dazu Auffindbarkeitsfragen, mit zwei Lehren aus der
Gegenprüfung:

- *Fragen müssen von Nutzern stammen, nicht vom pflegenden Agenten.* Fragen, die der Agent mit
  offener Seite schreibt, bestanden 40 von 40, während 18 Alltagsfragen zu denselben Seiten
  scheiterten. Fragen mit Wortüberlapp zur Zielseite fanden 37 von 44, unabhängig formulierte 20
  von 63.
- *Ein Claim als Ziel ist Pflicht*, nicht nur eine Seite. Sonst bleibt eine Frage grün, nachdem
  der Fakt gelöscht wurde. Gemessen: Rang 5 statt Rang 1, aber weiterhin „gefunden".

Diese Kennzahlen bleiben Pflegerdaten und gehören nie in die Qualitätszeile für Leser. Dort würde
schon ein Hinweis jedes aktualisierte Wiki auf „Prüfung fällig" setzen (damals
`assess_quality.py:279-282`).

**Umgesetzt.** Stufe 5 brachte die Auflösung kanonischer Locator als Lint-Warnung, die
Statistik `stats.source_coverage` (`lmwiki-source-coverage/1`) und die Auffindbarkeitsfragen.
Abweichung: Unzitierte Quellen und Einheiten sind eine Statistik, keine Warnung, weil
Hintergrundmaterial zu Recht unzitiert bleibt und eine Warnung, die sich nie abstellen lässt,
abstumpft. `quality-status.json` trägt bewusst weiterhin keine Abdeckungskennzahl.

### Befund 7 — Plattformlücken *(erledigt in Stufe 1)*

**Beobachtung.** Unter Windows schreibt Python eine umgeleitete Ausgabe in der ANSI-Codepage.
Alle Helfer gaben JSON mit `ensure_ascii=False` aus. Ein einziges Zeichen außerhalb von cp1252
in einer Seite, etwa „≥", brach die Suche mit leerer Ausgabe ab (simuliert mit
`PYTHONIOENCODING=cp1252`). Die Suche nahm außerdem kein `--expect-manifest-sha256` an. Mehrere
Aufrufe einer Antwort konnten also unbemerkt zwei Releases mischen. Und alle Werkzeuge, die
Geschwistermodule importieren, scheiterten unter `python -I`, `-P` oder `PYTHONSAFEPATH=1`, weil
dann ihr eigenes Verzeichnis nicht auf dem Suchpfad liegt. Sicherheitsleitfäden empfehlen `-I`
ausgerechnet für Code aus entpackten Archiven.

**Empfehlung.** `sys.stdout.reconfigure(encoding="utf-8")` in jedem Einstieg beider Skills und
der Vorlagen, mit einem cp1252-Regressionstest. `--expect-manifest-sha256` an der Suche, mit
Ergebnis `snapshot_changed`. Jeder Einstieg setzt sein eigenes Verzeichnis selbst an den Anfang
des Suchpfads, damit `-I` funktioniert.

**Umgesetzt.** Alle drei Punkte, geprüft in `tests/test_entrypoints.py`. Die Tests der Suche,
des Exports und der Paketierung laufen zusätzlich unter Python 3.9.

---

## 5. Was bewusst nicht übernommen werden sollte

- **Neuronale Embeddings, Vektorindex, Suchdienst.** Gründe in Abschnitt 3.
- **Statische Embedding-Tabelle.** Gemessen +0 auf dem Stapel. Ohne Schwelle macht sie jede
  Negativfrage zu 12 Treffern. Mit Schwelle hält sie die Fehltreffer auf dem Stand vor Stufe 1,
  findet aber weniger als Aliase und bei englischen Fragen 1 von 8.
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

Der Plan ist vollständig umgesetzt. Die Stufen stehen hier im Wortlaut des Plans; was gebaut
wurde und wo die Umsetzung abwich, steht im Abschnitt „Umsetzungsstand".

### Stufe 0 — Export reparieren *(umgesetzt)*

Importhülle statt fester Liste, Verweigerung von Pflegewerkzeugen, Selbsttest aller
mitgelieferten Werkzeuge in sauberer Umgebung, Aufräumen bei Fehlschlag, keine Caches im Paket,
Exporttests, statische Prüfungen für die Vorlagen und Python-3.9-Grammatikprüfung.

### Stufe 1 — Ein Suchkern und ein Zählwerk *(umgesetzt)*

1. `search_core.py` plus `bm25.py` als geteilter Kern beider Skills, in der Paritätsliste von
   `tests/test_packaging.py`. Die Export-Suche wird ein dünner Wrapper. Damit rankt der Export
   wie der Lese-Skill. Das ist eine gewollte Verhaltensänderung des Exports und gehört in die
   Release-Notiz.
2. Das Zählwerk aus Befund 1, nur zusätzliche Schlüssel.
3. `--expect-manifest-sha256` an der Suche, UTF-8-Ausgabe und eigener Suchpfad (für `-I`) in allen
   Einstiegen.
4. Die Testfragen-Batterie als Messinstrument ins Repository, siehe Entscheidung E4. Dazu ein
   **Präzisionstor** als Test:
   - Eine Frage, deren erster Treffer bei der Aufzeichnung eine Pflichtseite ist, behält eine
     Pflichtseite auf Rang 1. (Nachgetragen nach der Prüfung von Stufe 1: Ohne diese Regel blieben Verluste von
     Rang 1 auf Rang 2 oder 3 unbemerkt, genau die Fehler, die Befund 2 für Stufe 2 nennt.)
   - Keine Pflichtseite, die bei der Aufzeichnung unter den ersten 3 steht, verlässt sie.
   - Keine Pflichtseite fällt aus dem Standardlimit.
   - Navigationsseiten gewinnen keine Top-3-Plätze.
   - Die Trefferzahl der Negativfragen bleibt gedeckelt.

   Die bestehenden fest verdrahteten Ranking-Tests bestanden auch unter einem Prototyp mit 14
   verschlechterten Pflichtseiten. Sie schützen also nicht.
5. Doku nach Repo-Konvention: `SKILL.md`, `references/`, README-Tabellen, `describe_actions`
   (dort fehlte damals schon `--limit`), Evals, neu gebaute Pakete.

### Stufe 2 — Wortformen *(umgesetzt)*

1. Gewichtete Begriffsgruppen in `bm25.py` mit rückwärtskompatibler Signatur. Ohne Gruppen ist
   der Weg byte-identisch zu vorher. Score 0 bleibt Score 0.
2. Zuerst der vorsichtige Teil (Schritte a und b: 57 → 67). Kompositumteile und Tippfehler
   (→ 81) erst, wenn das Präzisionstor aus Stufe 1 grün ist.
3. Die fünf Konstruktionsregeln aus Befund 2 als Unit-Tests festnageln.
4. `match_rules` je Treffer und `unmatched_terms` je Anfrage. Die Schicht ist eine ausgewiesene
   Heuristik, und so steht es in der Antwort.

### Stufe 3 — Bedeutung über Agent und Kuration *(umgesetzt)*

1. `--also` beziehungsweise `--request -`, Reihum-Fusion nach Rang, `found_by`, getrennter Block
   für Treffer nur aus Umformulierungen.
2. Lese-`SKILL.md` und exportierte `SKILL.md`: bis zu vier Umformulierungen (mit der Frage fünf
   Suchen) in der Wiki-Sprache, bei fremdsprachigen Fragen immer eine Übersetzung.
3. Pflege: Anleitung zu Seiten-Aliasen in Nutzersprache, Lint-Statistik für Allerweltswörter
   unter den Aliasen, skalarer `aliases`-Wert als ein Alias mit Warnung.

### Stufe 4 — Abgesicherte Fehlanzeige *(umgesetzt, Entscheidung E2)*

`--exhaustive` mit Budget, `absence_check`, `search_record`, Textscan über Claims und Quelltexte,
Regel für nicht leere, aber falsche Ergebnisse (Befund 1), die Fehlanzeige-Regel in allen drei
Anweisungstexten, neue Evals. Umgesetzt mit einer Abweichung: Die Snapshots unter
`meta/history/` durchsucht die Prüfung nur mit `--include-history`.

### Stufe 5 — Prüfungen beim Release *(umgesetzt, Entscheidung E3)*

Quellenabdeckungs-Bericht und Locator-Auflösung als Warnungen. Optional Auffindbarkeitsfragen
von Nutzern, mit Claim-Ziel, nur für Pfleger. Robusterer Begriffswelt-Parser: Eine Überschrift
außerhalb der ID-Grammatik beendet die laufende Begriffswelt, statt sie still zu verfälschen.
Umgesetzt mit einer Abweichung: Nicht auflösbare Locator sind Warnungen, unzitierte Quellen und
Einheiten aber nur eine Statistik.

### Stufe 6 — Offene Punkte *(umgesetzt)*

Nach der Abschlussmessung: der gemeinsame Bewertungskern für `assess_quality` (Befund 5),
Fugenvarianten, unregelmäßige Formen aus einer geschlossenen Tabelle und Mengenangaben in
anderer Schreibweise, jeweils mit Prototyp, zwei Gegenprüfungen und Messung. Die freie
Zerlegung des Suchworts für co-03 wurde gemessen und abgelehnt.

### Reihenfolge und Abhängigkeiten

Stufe 1 zuerst: Ohne gemeinsamen Kern wäre jede weitere Stufe doppelt zu bauen, und ohne
Präzisionstor lassen sich die Wortformen nicht sicher einführen. Stufe 3 hängt nicht von
Stufe 2 ab und kann parallel laufen. Stufe 4 braucht die Zähler aus Stufe 1 und die Wortformen
aus Stufe 2 für ihren Textscan. Stufe 5 ist unabhängig. Ihr Quellenabdeckungs-Teil lohnt früh,
weil er die leiseste Lücke schließt.

### Wie Erfolg gemessen wird

Nicht nur Trefferquote:

- Treffer unter den ersten 1, 3 und 12 sowie unter den ersten 100.
- Verschlechterungen pro Frage gegenüber dem Stand vor Stufe 1, nicht nur Kategoriesummen.
- Trefferzahl und Top-3-Plätze der Negativfragen.
- Anteil der Navigationsseiten unter den ersten 3.
- Claim-Trefferquote: Ist der antwortende Claim unter den zurückgegebenen?
- Negativfragen *mit* Agent-Umformulierungen.

---

## 7. Entscheidungen

Alle fünf Entscheidungen sind gefallen und umgesetzt. Die Fragen stehen im Wortlaut der Analyse,
darunter jeweils die Entscheidung.

**E1 — Wortlaut der Erweiterungsregel.** Jede `CONCEPTS.md` enthält „Search may expand a query
only through confirmed preferred terms and aliases", und dieselbe Regel steht an drei weiteren
Stellen. Wortformen desselben Wortes sind Abgleich, keine Erweiterung. Kompositumteile und
Tippfehler sind aber Heuristiken, die über das getippte Wort hinausgehen. Vorschlag: „Wortformen
desselben Wortes gelten als Abgleich; Teil- und Näherungstreffer sind ausgewiesene Heuristiken;
Agent-Umformulierungen werden aufgelistet." Dazu ein Lint-Hinweis für bestehende
`CONCEPTS.md`-Texte. Das entscheidet der Eigentümer.

*Entschieden (Ja) und umgesetzt.* Der neue Wortlaut in jeder neuen `CONCEPTS.md`: „Search expands
a query in meaning only through confirmed preferred terms and aliases. Forms of the same word
(inflection, umlaut spelling, hyphenation) count as matches of that word. Compound parts and
one-letter typo corrections are disclosed heuristics. Reformulations by the agent are listed in
the answer." Für eine bestehende `CONCEPTS.md` mit dem alten Satz meldet der Lint eine Warnung
mit dem neuen Text; sie blockiert keinen Release.

**E2 — Der vollständige Prüfpfad als Ausnahme vom gestuften Lesen.**
`answer-contract.md` sagt „Do not read every directory index by reflex", und Eval 11 prüft das.
Ein `--exhaustive`-Aufruf ist kein Lesen aller Indizes, braucht aber eine ausdrückliche Ausnahme
und eine Budgetgröße (Vorschlag: etwa 100.000 Zeichen).

*Entschieden und umgesetzt.* Das Budget beträgt 100.000 Zeichen der Treffer, so gezählt, wie die
Ausgabe sie druckt. Der Antwortvertrag nennt den Aufruf ausdrücklich als einzige Ausnahme vom
gestuften Lesen („The one exception is the exhaustive search"), nur für Fehlanzeigen. „Do not
read every directory index by reflex" und Eval 11 blieben unverändert.

**E3 — Auffindbarkeitsfragen.** Wer schreibt sie (Vorschlag: der Eigentümer oder echte Nutzer,
nie der Agent)? Liegen sie in `schema/` und reisen damit in jeden Export mit, oder bleiben sie
beim Pfleger?

*Entschieden und umgesetzt.* Nur der Eigentümer oder echte Nutzer liefern Fragen, wörtlich; der
Agent formuliert keine. Jede Frage zielt auf einen bestätigten Claim. Die Fragen liegen nicht in
`schema/`, sondern in `meta/findability-questions.jsonl` beim Pfleger: außerhalb der
Release-Grenze, nicht gehasht, nicht im Standard-Snapshot, nie exportiert, und der Lese-Skill
liest sie nicht.

**E4 — Messinstrument ins Repository.** Soll das synthetische Test-Wiki mit den 114 Fragen als
Fixture unter `tests/` eingecheckt werden? Ohne das bleibt jede Ranking-Änderung ungemessen.

*Entschieden (Ja) und umgesetzt.* Test-Wiki, Fragen, Umformulierungssätze und die Erwartungen
der drei Tore liegen unter `tests/fixtures/search_quality/`. Der Bauhelfer veröffentlicht das
Wiki mit den echten Helfern in ein temporäres Verzeichnis und schreibt nichts ins Repository.

**E5 — Wie weit die Wortform-Schicht standardmäßig geht.** Nur Schritte a und b (57 → 67 unter
den ersten 12; Treffer der Negativfragen 16 → 28) oder alle vier Schritte (57 → 81; 16 → 31
unter den ersten 12, 16 → 45 unter den ersten 100). Empfehlung: mit a und b beginnen, c und d
hinter dem Präzisionstor freischalten.

*Entschieden und umgesetzt:* a und b zuerst, c und d nur, wo das Präzisionstor grün bleibt. Alle
vier Schritte haben es bestanden und sind eingeschaltet (Umsetzungsstand, Stufe 2).

---

## Umsetzungsstand (2026-11-17)

Alle sieben Stufen (0 bis 6) sind umgesetzt, dazu eine verhaltensneutrale Aufräumrunde und fünf
gezielte Suchen nach falschen Fehlanzeigen. Die Produktregeln gelten weiter: Der Lese-Skill schreibt
nichts, auch keinen Index und keinen Cache; alle Helfer brauchen nur Python ab 3.9 und die
Standardbibliothek und laufen unter Windows, macOS und Linux; die geteilten Module liegen
byte-identisch in beiden Skills; ein Export enthält nur eine geprüfte, lesende Hülle von
Bibliotheken und sucht wie der Lese-Skill. Die volle Testsuite hat 672 Tests und besteht; die
Tests von Suche, Export und Paketierung laufen zusätzlich unter Python 3.9.

Dieser Abschnitt beschreibt je Stufe, was gebaut ist, dann die Abschlussmessung nach Stufe 5,
Stufe 6 mit ihrer eigenen Messung, die Entscheidungen und Abweichungen vom Plan, was offen bleibt
und wie man neu misst. Die
Einzelheiten der Ausgabefelder stehen im README (Abschnitte 4.16, 4.26 und 5.4) und in den
Anleitungstexten der Skills.

### Stufe 0 — Export repariert (2026-11-13)

- `maintain-llm-wiki/scripts/export_wiki_skill.py`:
  - `library_closure()` ermittelt die Bibliotheken aus den Importen der Vorlagen. Jeder Import
    muss auf `EXPORTABLE_LIBRARIES` oder `EXPORTED_STDLIB` stehen. Zu Stufe 0 waren das drei
    Bibliotheken (`frontmatter_contract.py`, `trust_contract.py`, `wiki_filters.py`), heute sind
    es sieben: dazu `bm25.py`, `freshness.py`, `search_core.py` und `wordforms.py`. Relative und
    dynamische Importe sowie Vorlagenmodule, die kein Einstieg sind, werden abgelehnt, bevor
    etwas geschrieben wird.
  - `run_self_check()` führt im erzeugten Ordner Verifikation, Identitätsstatus,
    Qualitätsbewertung und heute vier Suchaufrufe aus: mit Quellen, mit `__trust_tier`-Filter,
    mit einer JSON-Anfrage über die Standardeingabe und mit `--exhaustive` und zwei
    Umformulierungen. Der Aufruf erfolgt mit `-B -S -s` und `PYTHONSAFEPATH=1`, ohne
    `PYTHONPATH`; `PYTHONHOME` bleibt erhalten.
  - Der Exporter beansprucht den Ordnernamen atomar. Danach entfernt er bei jedem Fehlschlag
    Ordner, Paket und Prüfsumme: Ablehnung, Fehler oder Abbruch.
  - `packaged_files()` hält Caches unter `scripts/` aus dem Paket, lässt aber jede Datei unter
    `references/knowledge/` darin, weil das Manifest sie bindet.
- `tests/test_export.py` (zu Stufe 0 neu mit 21 Tests, heute 31): Export gelingt; jedes
  Werkzeug läuft im installierten Ordner allein und aus dem entpackten Paket; `graph/legacy.pyc`
  aus dem Release kommt mit; nur geprüfte Bibliotheken kommen mit, kein Pflegewerkzeug;
  Zeitstempel kommen aus dem Release, und zwei Exporte sind byte-identisch; abgelehnt werden
  unbekannte Module, ungeprüfte Standardmodule (`tomllib`, `os`, `shutil`, `importlib`),
  relative und dynamische Importe, Vorlagenmodule ohne Einstieg, ungeprüfte Bibliotheken sowie
  `release_wiki`, `navigation` und `portable_io`. Als zweite Verteidigungslinie fängt der
  Selbsttest ein fälschlich gelistetes, fehlendes Modul ab, auch wenn `PYTHONPATH` oder eine
  `.pth`-Datei es bereitstellen würde. Eine Ablehnung nach Beginn des Schreibens hinterlässt
  nichts.
- `tests/test_packaging.py`: Die Vorlagen werden auf auflösbare Importe geprüft, exportierter
  Code per Syntaxbaum auf Schreibaufrufe und ungeprüfte Importe; die Positivliste darf nicht
  größer sein als die tatsächliche Importhülle; alle Helfer und Vorlagen müssen mit der
  Grammatik von Python 3.9 parsen.
- Gegenproben: Gegen den Exporter vor Stufe 0 schlug der Kerntest fehl. Zwei Prüfrunden fanden
  4 und dann 8 weitere Code- und Testfehler sowie 10 Fehler in diesem Dokument; alle sind
  behoben. Sechs gezielte Mutationen werden von den Tests erkannt.

### Stufe 1 — Suchkern, Zählwerk, Präzisionstor (2026-11-14)

- `search_core.py` und `bm25.py` sind der gemeinsame Kern beider Skills und stehen in der
  Paritätsliste von `tests/test_packaging.py`. `search_wiki.py` und die Export-Suche
  `search_knowledge.py` sind dünne Hüllen, die den Release vor und nach der Suche prüfen. Ein
  neu exportierter Wissens-Skill rankt damit wie der Lese-Skill; das ist eine gewollte
  Verhaltensänderung und steht im README (4.16).
- Jede Suchausgabe trägt den Block `coverage` (damals `lmwiki-search-coverage/1`, heute `/3`),
  jeder Treffer `matched_terms`, `claims_total`, `claims_returned` und `navigation`. Die
  Rangliste des Lese-Skills blieb in 342 verglichenen Läufen gleich.
- `--expect-manifest-sha256` an beiden Suchen, mit `snapshot_changed` bei einem anderen
  Release; UTF-8-Ausgabe und eigener Suchpfad in jedem Einstieg; der Aktionskatalog nennt
  `--limit` und `--expect-manifest-sha256`.
- Test-Wiki und 114 Fragen liegen unter `tests/fixtures/search_quality/` (E4), das
  Präzisionstor ist `tests/test_search_quality.py`. Seine erste `expectations.json` wurde mit
  dem Ranking vor der Änderung aufgezeichnet.
- Die `SKILL.md` des Exports entsteht aus der Vorlage `assets/knowledge-skill/SKILL.template.md`.

### Stufe 2 — Wortformen (2026-11-14)

**Was gebaut ist.** Ein neues Modul `wordforms.py` liegt byte-identisch in beiden Skills und
reist über den Suchkern in jeden Export. Bei jeder Suche baut der Suchkern im Speicher den
Wortschatz der durchsuchten Dateien auf. Daraus wird jedes Suchwort zu einer gewichteten Gruppe
von Wörtern, die dort wirklich vorkommen. Jedes Mitglied trägt seine Regel:

| Regel | Gewicht | Beispiel |
|---|---|---|
| `exact` | 1,0 | „Tarif" findet „Tarif" |
| `fold` | 0,9 | „Kuendigung" findet „Kündigung", „E-Mail" findet „EMail" |
| `stem` | 0,6 | „Netzentgelten" findet „Netzentgelt" |
| `verb` | 0,5 | „widerruft" findet „Widerruf" |
| `irregular` (seit Stufe 6) | 0,45 | „umgezogene" findet „umziehen" und „umzog", „höchste" findet „hoch" (geschlossene Tabelle, nur Wörter der Frage) |
| `derived` (seit Stufe 6) | 0,45 | „umgezogene" findet „Umzug" (Substantiv derselben Tabelle) |
| `compound_head` | 0,45 | „Gebühr" findet „Durchleitungsgebühr" |
| `compound_link` (seit Stufe 6) | 0,45 | „Abschlagzahlung" findet „Abschlagszahlung" (andere Fuge, nur für ein Suchwort ohne Wortform) |
| `compound_modifier` | 0,35 | „Vertrag" findet „Vertragslaufzeit" |
| `query_part` | 0,35 | „Wärmepumpenstromtarif" findet „Stromtarif" (nur der Kopf: der längste hintere Teil, dessen Rest aus Wörtern des Wikis besteht) |
| `typo` | 0,3 | „Netzentgeld" findet „Netzentgelt" (eine Änderung, ab 8 Buchstaben) |
| `quantity` (seit Stufe 6) | 0,9 | „2500 kWh" findet „2,5 MWh", „vierzehn Tage" findet „14 Tagen" (Heuristik, Gewicht einer Schreibvariante) |

Zu Schritt a gehören außerdem die Reparatur weicher Trennzeichen, unsichtbarer Zeichen und
Trennstriche am Zeilenende, die normalisierte Stoppwortliste („für" fällt wieder weg) und
Funktionswörter, die nur wörtlich treffen. `bm25.py` wertet eine Gruppe als einen Begriff;
eine Gruppe nur aus dem wörtlichen Token rechnet wie vorher. Für Messung und Tests gab es bis
zur Aufräumrunde nach Stufe 4 einen wörtlichen Modus (`word_forms=False`); auf dem Test-Wiki war
seine Rangliste in 114 von 114 Fragen identisch mit dem Stand vor Stufe 2. Kein Helfer nutzte
ihn, deshalb ist er entfernt.

**Die fünf Konstruktionsregeln** sind je durch einen Test in `tests/test_wordforms.py`
festgenagelt:

1. Die Seltenheit (IDF) einer Gruppe zählt nur Seiten mit dem Wort selbst oder einer echten
   Wortform. Kompositumteile und Tippfehler zählen für die Seltenheit nur, wenn es gar keine
   Wortform gibt. Auf einer Seite kommen sie in Schichten unter den Wortformen hinzu.
2. Das Regelgewicht wirkt nach der BM25-Sättigung. Ein Kompositumteil im Titel erreicht genau
   sein Gewicht eines exakten Titeltreffers, nicht 86 Prozent.
3. Der Phrasenbonus gilt nur für die wörtlichen Suchwörter auf ganzen Wortgrenzen. Vorher war
   es ein Teilzeichenketten-Vergleich: „tarif" galt auch in „festpreistarif" als Phrase.
4. Link-Ziele und Slugs werden nie an Bindestrichen zerlegt. Eine Seite, die auf eine Tarifseite
   verlinkt, trifft „Tarif" nicht über den Slug.
5. Tippfehler: eine Änderung, ab 8 Buchstaben, nur wenn keine andere Regel trifft. Gemessen auf
   dem Test-Wiki: alle 8 echten Tippfehler korrigiert. Von 200 korrekten, im Wiki fehlenden
   Wörtern wurden ab 7 Buchstaben 4 von 151 falsch korrigiert, ab 8 Buchstaben 3 von 130
   („Abmeldung" zu „Anmeldung", „Ausgaben" zu „Aufgaben", „Ausnahme" zu „Aufnahme"), ab 9
   Buchstaben 1 von 108. „smart", „meter" und „ankündigen" bleiben unkorrigiert.

Begriffswelten werden über das Wort, seine Schreibung (`fold`) und seine Flexionsendung
(`stem`) ausgelöst, nie über Verbformen, Kompositumteile oder Tippfehler. „Basisversorgung
kündigen" behält `grundversorgung.md` auf Rang 1. Eine Seite ohne jedes Mitglied einer Gruppe hat weiter den Score 0.

**Ausgabe.** Das Zählwerk hieß damit `lmwiki-search-coverage/2` (seit Stufe 3 `/3`). Jedes Suchwort nennt unter
`forms` bis zu 10 gezählte Wörter mit Regel, Gewicht und Dateizahl, dazu `forms_total`. Die
Dateizahlen zählen Formen mit. `form_only_terms` nennt Suchwörter, die nur über eine andere Form,
einen Kompositumteil oder eine Tippfehlerkorrektur getroffen haben. Jeder Treffer nennt in
`match_rules`, welche Wörter der Seite für welches Suchwort gezählt haben. Der Grenzsatz sagt
jetzt: Formen desselben Wortes und die ausgewiesenen Kompositum- und Tippfehlertreffer werden
gezählt, wie unter `forms` aufgeführt; andere Wörter, unregelmäßige Formen und andere Sprachen
nicht. (Seit Stufe 6 nennt er auch die Tabellen- und Mengentreffer und schließt nur noch
unregelmäßige Formen außerhalb der geschlossenen Tabelle und Zahlen in einer Schreibweise aus,
die die Suche nicht umrechnet.)

**Gemessene Leiter** auf dem Test-Wiki, im Prozess über `search_core` (107 beantwortbare Fragen,
7 Negativfragen, 114 Fragen für Navigationsplätze):

| Stufe | Rang 1 | unter 3 | unter 12 | unter 100 | Negativtreffer unter 12 / 100 | Navigation Top 3 | Verluste gegenüber vorher |
|---|---|---|---|---|---|---|---|
| vorher | 41 | 47 | 57 | 62 | 16 / 16 | 20 | – |
| a | 42 | 47 | 56 | 60 | 20 / 20 | 15 | su-06 fällt aus den ersten 12, sh-04 verliert Rang 1 |
| a+b | 49 | 56 | 64 | 69 | 27 / 27 | 13 | keine |
| a+b+c | 52 | 59 | 69 | 78 | 31 / 41 | 13 | br-05: eine Pflichtseite von Rang 3 auf 4 |
| a+b+c+d (eingeschaltet) | 56 | 64 | 74 | 84 | 31 / 41 | 13 | br-05 wie oben |

Je Kategorie unter den ersten 12, vorher → nachher: Flexion 3 → 8 von 8, Komposita 4 → 6 von 8,
Tippfehler 1 → 6 von 8, Umlaut-Schreibung 6 → 7 von 7, Synonym unkontrolliert 2 → 4 von 8,
Umschreibung 2 → 3 von 8, breite Fragen 0 → 1 von 5. Exakt, kuratierte Synonyme,
claimlastig, Historie und Kennungen bleiben, wie sie waren. Andere Sprachen bleiben bei 1 von 8.

Die Bedingungen für das Einschalten waren: höchstens drei begründete Verluste, keiner aus den
ersten 3 bis hinter Platz 12; höchstens 28 Negativtreffer unter den ersten 12 mit a+b und 31 mit
c oder d; höchstens 20 Top-3-Plätze für Navigationsseiten. Alle vier Schritte erfüllen sie. Der
einzige Verlust, br-05 („Zähler"), steht mit Begründung und `accepted_rank: 4` in
`accepted_regressions`: `lindenau-netz.md` enthält „Zählerstand" mehrfach und zieht über die
Regel `compound_modifier` an `intelligentes-messsystem.md` vorbei, das „Zähler" nur einmal
nennt. Mit dieser Regel bei 0,2 oder ohne sie bliebe die Seite auf Rang 3, aber su-02 („Smart
Meter Pflicht") verlöre seine Pflichtseite auf Rang 1; bei 0,25 bis 0,3 gingen beide verloren.
`expectations.json` ist neu aufgezeichnet: Untergrenzen 56, 64, 74 und 84, Obergrenzen 31
Negativtreffer und 13 Navigationsplätze.

**Was die Gegenprüfung des Prototyps erklärt.** in-04 („Kunde widerruft am Telefon") verlor im
Prototyp mit dem Stemmer allein, weil „Kunde" dort alle Seiten mit „Kunden" mitnahm und
„widerruft" ohne Verbregel nichts traf. Mit Verbregel (Teil von b) findet „widerruft" das Wort
„Widerruf", die Seite steigt von Rang 9 auf 3. in-05 („umgezogene Kunden") hat ein unregelmäßiges
Hauptwort, das die Schicht nicht findet (seit Stufe 6 findet die Regel `derived` „Umzug", und die
Seite steht auf Rang 2). Die Seite rankt nur über „Kunden" und „Vertrag". Zählen
deren Formen mit, werden beide Wörter häufiger und damit schwächer, und Seiten mit Komposita wie
„Haushaltskunden" ziehen vorbei. Im Prototyp fiel die Seite so von Rang 5 auf 17. Mit Flexion
0,7 fiel sie auch hier aus den ersten 12 (Rang 13); mit 0,6 landet sie auf Rang 10.

**Abweichungen vom Plan, gemessen begründet.**

- *Navigationsseiten zählen nur das Wort selbst.* Ohne diese Regel belegten Indexseiten mit allen
  vier Schritten 24 Top-3-Plätze (Grenze 20), und sh-04 verlöre seine Pflichtseite auf Rang 1.
  Indexseiten listen Titel und Beschreibungen ganzer Zweige auf und enthalten damit viele Formen.
- *Bei einem Link mit Beschriftung zählt nur die Beschriftung.* Sonst zählte
  „[[wiki/concepts/kuendigungsfrist|Kündigungsfrist]]" das Wort doppelt, einmal als gefalteten
  Slug, einmal als Text. Ohne diese Regel: 18 statt 13 Navigationsplätze bei sonst gleichen
  Zahlen. Unbeschriftete Links bleiben, wie sie sind.
- *Formen addieren sich in Schichten statt als strikter Rückfall.* Eine Seite mit dem Wort und
  einem Kompositum davon bekommt etwas mehr als mit dem Wort allein; eine Seite nur mit dem
  Kompositum bekommt höchstens dessen Gewicht. Der strikte Rückfall (Komposita zählen nur auf
  Seiten ganz ohne das Wort) kostete su-02 seine Pflichtseite auf Rang 1 (gemessen mit Flexion
  0,7, zusammen mit in-05 auf Rang 14). Ein früher Entwurf mit einem gewichteten Mittel statt
  Schichten senkte sogar den Score, wenn eine Form hinzukam, und kostete br-05 Rang 1.
- *Kompositumteile des Suchworts nur im Kopf.* Ein unbekanntes Suchwort sucht nur seinen Kopf,
  den längsten hinteren Teil, dessen Rest aus Wörtern des Wikis besteht. Der Prototyp suchte alle Teile und fand so „Wärmepumpenstromtarif" (co-03); hier bleibt
  co-03 unauffindbar. Eine freie Zerlegung wurde in Stufe 6 erneut als Prototyp gemessen und
  abgelehnt (Abschnitt „Stufe 6").
- *Eine Selektion ändert nicht, was ein Wort trifft.* Der Wortschatz kommt aus allen durchsuchten
  Dateien vor dem Metadatenfilter, damit die Zählungen unabhängig vom Filter bleiben.
- *Nicht durchsuchte Quellen zählen nur das Wort und seine echten Wortformen*, keine
  Kompositumteile und Tippfehler. `terms_only_in_unsearched` wird seit der Nachbesserung auf
  derselben Grundlage entschieden (siehe unten).

**Laufzeit** (damals gemessen, Mittel über 114 Suchen im Prozess, vorher → nachher): Test-Wiki 34 → 47 ms,
500-Seiten-Kopie mit 0,5 MB Quellen 341 → 413 ms, dieselbe Kopie mit 7,7 MB Quellen 907 →
1.028 ms. Das ist das 1,4-, 1,2- und 1,1-Fache; die Grenze war das Doppelte. Die meiste Zeit
kostet das Aufbauen des Wortschatzes, auch für die nicht durchsuchten Quellen. Spätere Änderungen
haben diesen Preis ausgeglichen (Abschlussmessung).

**Nachbesserung nach der Gegenprüfung (2026-11-14).** Eine unabhängige Prüfung fand sechs
Fehler im Code und mehrere ungenaue Stellen in den Texten. Behoben ist:

- *Hinweis auf die Quellen ging verloren.* `terms_only_in_unsearched.sources` verglich die
  Quellen (nur Wort und Wortformen) mit dem Wiki samt Kompositumteilen und Tippfehlern. Ein
  Wort, das nur in den Quellen steht, verschwand deshalb aus der Liste, sobald im Wiki ein
  Kompositum oder ein Tippfehler-Nachbar davon vorkam, etwa „Dauer" über „Dauerlösung" (sc-02,
  ty-04). Jetzt zählt auf beiden Seiten nur das Wort selbst und seine Wortformen. Außerdem
  korrigiert die Suche ein Wort, das selbst oder in einer Wortform in den nicht durchsuchten
  Quellen steht, nie als Tippfehler: „verjähren" wurde vorher zu „Verfahren".
- *Zu lockere Verbregel.* „-et" galt nach jedem Stamm als Verbendung, und jede „-t"-Form des
  Wikis passte zu jedem Suchwort mit demselben Stamm. So fand „Internet" das Wort „internen",
  „Planet" das Wort „Plan" und „andere" das Wort „ändert". Jetzt zählt „-et" nur nach d oder t
  und nach m oder n, vor denen ein Konsonant außer l und r steht und kein h nach einem Vokal
  („meldet", „öffnet", „rechnet", aber „lernt", „wohnt"). Eine „-t"-Form gilt nur für ein Suchwort auf „-n" oder für den bloßen Stamm.
  Die Kehrseite: „kündige" findet „kündigt" nicht mehr, wohl aber „kündigen".
- *„-er" fiel bei manchen Substantiven doch weg.* Die Ausnahme für Adjektive („wichtiger",
  „aktueller") griff auch bei „Hersteller", „Antragsteller", „Keller", „Zeiger" und „Fischer".
  Außerdem bekamen „Herstellers" und „Herstellern" einen anderen Schlüssel als „Hersteller".
  Jetzt gilt die Ausnahme nur für die Adjektivendungen „-iell", „-uell", „-nell", „-rell",
  „-mell" statt jedes „-ell", nicht nach „-eig" und bei „-isch" nur mit mindestens zwei
  Buchstaben davor. „-ers" und „-ern" bekommen denselben Schlüssel wie „-er".
- *Keine Längengrenze für Komposita.* Ein Wort aus Tausenden Buchstaben ohne Leerzeichen ließ die
  Suche abstürzen (`RecursionError`) oder minutenlang rechnen. Jetzt zerlegen die
  Kompositumregeln kein Wort mit mehr als 64 Buchstaben.
- *Navigationsseiten in der Ausgabe.* `match_rules` zeigte auf Indexseiten die Regel `stem`, wenn
  ein Begriffswelt-Wort derselben Gruppe dort wörtlich stand, und die Dateizahlen unter `forms`
  zählten Indexseiten mit. Jetzt zeigt eine Navigationsseite nur das Wort selbst, und eine Form
  zählt nur in den Dateien, in denen sie für den Score zählt.
- *Grenzsatz.* Er nennt jetzt neben den Formen auch die ausgewiesenen Kompositum- und
  Tippfehlertreffer, denn auch sie stecken in den Zahlen.

Das Präzisionstor zeigt danach dieselben Zahlen (56, 64, 74, 84; 31 Negativtreffer; 13
Navigationsplätze). pa-03 steht wieder auf Rang 9 wie vor Stufe 2 (vorher 10, weil „internen"
über die falsche Verbform zählte), pa-07 auf Rang 21 statt 24. Gegenüber dem Stand vor Stufe 2
rückten damit 43 von 124 Pflichtseiten vor, 4 fielen zurück und 77 blieben (heute 44, 4 und 76,
weil pa-04 seit der Zahlenschreibweise in Stufe 4 einen Rang weiter vorn steht). Nur br-05 verließ
dabei ein Band (Rang 3 auf 4, angenommen). Drei Seiten fielen innerhalb ihrer Bänder: in-05 von
Rang 5 auf 10 (siehe oben), pa-07 von 15 auf 21 und sh-06 von 8 auf 10. Bei pa-07 trifft
„andere" jetzt „anderen" und auch „ändern", weil Umlaute vor jedem Vergleich entfallen; dazu
kommen Komposita von „Strom". Bei sh-06 zählen die Formen und Komposita von „Verträge" auf mehr
Seiten mit. `expectations.json` ist dafür neu aufgezeichnet; nur die Ränge von pa-03 und pa-07
haben sich geändert.

Bekannte Restfälle: „Konzert" findet „Konzern" über die Verbregel („Konzer-t" gegen
„Konzer-n"). „Gläubiger" wird wie ein gebeugtes „gläubig" gelesen, „Verteidiger" wie
„verteidigen"; eine reine Regel ohne Wörterbuch trennt das Substantiv nicht vom Adjektiv oder
Verb.

**Offen.** Die Gewichte sind auf einem einzigen synthetischen Wiki gewählt, ohne zurückgehaltene
Testmenge. ty-05 („Abschlagzahlung") bleibt im Ranking unauffindbar, weil der Kopfteil „Zahlung" vor dem
Tippfehler greift (seit Stufe 6 findet die Regel `compound_link` „Abschlagszahlung" auf Rang 1). ty-07 („Grundversorung") steht auf Rang 23, weil ein Tippfehler keine
Begriffswelt auslöst und „Grundversorgung" auf fast jeder Seite steht.

### Stufe 3 — Umformulierungen und Alias-Pflege (2026-11-14)

- Beide Suchen nehmen bis zu vier Umformulierungen an, je höchstens 200 Zeichen: als `--also`
  oder als ein JSON-Objekt `{"query", "also", "filter"}` über die Standardeingabe
  (`--request -`). Ein Aufruf liest den Release einmal und sucht Frage und Umformulierungen
  nacheinander über denselben Korpus.
- `results` bleibt genau die Rangliste der Frage, mit Zählwerk und Facetten. Neu ist `found_by`
  je Treffer. Seiten, die nur Umformulierungen innerhalb des Limits fanden, stehen getrennt in
  `reformulation_results`: reihum nach Rang gezogen, ohne Doppelte, ohne Navigationsseiten, mit
  eigenem Limit. Gleiche oder leere Umformulierungen stehen in `dropped_formulations`.
- Das Zählwerk heißt seither `lmwiki-search-coverage/3` und zählt je Suche (`formulations`)
  und den Block (`reformulation_results`).
- Die Hülle prüft die Anfrage über die Standardeingabe, bevor sie das Wiki anfasst: BOM,
  UTF-16, Nicht-UTF-8, ein „?" vor einem Buchstaben als Spur einer Umkodierung durch
  PowerShell, einzelne Surrogate, doppelte und unbekannte Schlüssel, Grenzen.
- Anleitungstexte: Regeln für Umformulierungen (Wiki-Sprache, Übersetzung, andere Wörter statt
  anderer Formen desselben Wortes), jede gesuchte Umformulierung steht in der Antwort, der Block
  hat geringeres Vertrauen und hebt eine Fehlanzeige allein nie auf.
- Pflege: drei Regeln für Seiten-Aliase, die Lint-Statistik `stats.alias_review` (häufige
  Alias-Wörter und mehrfach vergebene Aliase zur Bestätigung) und ein skalares `aliases` als ein
  Alias mit Warnung.
- Zweites Tor: `reformulations.json` mit zwei Sätzen, die Agenten blind geschrieben haben (sie
  kannten nur die Fragen, nie das Wiki), und `reformulation_expectations.json`.

### Stufe 4 — Abgesicherte Fehlanzeige (2026-11-14 und 2026-11-15)

**Was gebaut ist.** Jede Suchausgabe trägt `search_record` (`lmwiki-search-record/1`, mit der
Prüfzeile `line`) und `absence_check` (`lmwiki-absence-check/1`). `complete` ist nur wahr, wenn
derselbe Aufruf mit `--exhaustive` lief, mindestens zwei Umformulierungen mit eigenen Wörtern
zählten, mindestens eine Suche ein Inhaltswort hatte und alle Treffer ins Budget passten. Sonst
nennt `reasons` die fehlenden Bedingungen, und `next_steps` sagt aus einem festen Vokabular, was
vor einer Fehlanzeige zu tun ist. `--exhaustive` rankt zusätzlich die Quellen und durchsucht
jede Passage der Wiki-Seiten, von `meta/questions.md` und des Quell-Markdowns nach allen
Inhaltswörtern aller Formulierungen; die Snapshots unter `meta/history/` nur mit
`--include-history`. Die Treffer stehen seitenweise unter `exhaustive_hits`, höchstens 100.000
Zeichen, so gezählt, wie die Ausgabe sie druckt (E2). Über die Wortformen des Rankings hinaus
kennt nur der Scan die ausgewiesenen Heuristiken `hyphen_part`, `ending`, `verb_ending`,
`split_verb`, `short_part`, `suspended_compound` und `footnote_mark`. Das Ranking änderten die
Runden nur über die gemeinsame Textreparatur (Zahlenschreibweise in Runde 2, Markup und
Zeichenreferenzen in Runde 4); auf dem Test-Wiki rückte dadurch eine Pflichtseite einen Rang vor
(pa-04). Der feste Satz zur Fehlanzeige steht wörtlich in
`query-llm-wiki/SKILL.md`, `references/answer-contract.md` und der Export-Vorlage (Befund 4).
Neu sind die Evals 20 bis 24 und das dritte Tor (`absence_expectations.json`).

**Fünf Suchen nach falschen Fehlanzeigen.** Eine falsche Fehlanzeige ist der teuerste Fehler
dieser Stufe: `complete: true`, obwohl eine Passage die Frage beantwortet und weder unter den
Ergebnissen noch unter den Treffern steht. Nach dem Bau suchten fünf Prüfrunden gezielt nach
solchen Fällen, jede mit eigenen Wikis und Fragen außerhalb des Test-Wikis. Jeder bestätigte
Befund bekam einen Regressionstest in `tests/test_absence_check.py`.

*Runde 1 (mit Stufe 4).* Bindestrich-Wörter, Claim- und Quellen-IDs, verschachtelte Listen,
Setext-Überschriften, lange Tabellen und die Trennung am Zeilenende in Claims; ein Absturz bei
leeren Abschnitten; Umformulierungen, die nur Wörter hinzufügen, zählen nicht.

*Runde 2 (2026-11-14).* Ein Seiten- oder Folienmarker mitten im Satz beendet keine Passage mehr,
sondern setzt nur die Fundstelle; rohe HTML-Tabellen werden als Tabellen mit Kopfzeile gelesen;
lange Absätze werden nur am Satzende geteilt; eine Kennung schaltet den Bindestrich-Abgleich nur
noch in der Passage ab, in der das Token ausschließlich als Kennung steht. Zu Schritt a der
Wortformen gehört seither auch eine einheitliche Schreibweise für Zahlen, in Frage und Seite gleich: Tausendertrennzeichen
(Punkt, Leerzeichen, geschütztes oder schmales Leerzeichen, Apostroph) fallen weg, wenn jede
weitere Gruppe genau drei Ziffern hat, und eine direkt angehängte Einheit aus mindestens zwei
Buchstaben wird abgetrennt. „2.500 kWh", „2 500 kWh" und „2500kWh" ergeben so „2500 kWh";
vorher war „2.500" für die Suche „2" und „500", und eine Frage nach „2500" fand die Seite nicht.
Dezimalkomma, Datum und ein einzelner Buchstabe an der Zahl („§ 14a") bleiben unverändert. Auf
dem Test-Wiki rückte dadurch eine Pflichtseite einen Rang vor (pa-04, Rang 24 auf 23); sonst
blieben alle drei Tore unverändert. Ebenfalls festgehalten: Plurale auf „-er" („Häuser",
„Kinder") und die Formen von Stämmen unter vier Buchstaben („Tag", „Tage", „Tagen") sind für die
Wortformen keine Formen desselben Wortes, weil die Flexionsregel bei Substantiven „-er" nie
abschneidet und mindestens vier Buchstaben stehen lässt. Die Anweisungstexte sagten bis dahin
pauschal, Plurale würden gefunden. Nur die vollständige Prüfung findet diese Formen, als
ausgewiesene Heuristik `ending`; das Ranking bleibt dabei.

*Runde 3 (2026-11-15).* Die vollständige Prüfung liest
seither auch Pandocs Gitter-, Mehrzeilen- und einfache Tabellen als Tabellen, wie eine
Pipe-Tabelle: eine Tabellenzeile über mehrere Textzeilen oder zwischen Leerzeilen bleibt eine
Zeile, und die Kopfzeile steht vorn und wird bei einem Schnitt mitgegeben. Vorher wurde jede
Zeile einer Mehrzeilen-Tabelle, Pandocs Standard für eine Word-Tabelle, zu einem eigenen Absatz
ohne Kopfzeile; eine Frage nach Spalte und Zeilenschlüssel („Kündigungsfrist" und
„LindenWärme WP") traf die antwortende Zeile nie, und die Prüfung meldete trotzdem
`complete: true`. Drei weitere ausgewiesene Heuristiken gelten nur in der Prüfung, nicht im
Ranking: `verb_ending` für die Verbformen eines regelmäßigen Verbs mit vierbuchstabigem Stamm
(„senkt" und „senken", „zahlt" und „zahlen", „prüft" und „geprüft"; die Verbregel der Wortformen
lässt mindestens fünf Buchstaben stehen), `suspended_compound` für ein Kompositum mit
Ergänzungsstrich („Grund- und Leistungspreis" enthält „Grundpreis", „Vertragsbeginn und -ende"
enthält „Vertragsende") und `footnote_mark` für eine angeklebte Fußnotenziffer
(„Kündigungsfrist2", so schreibt MarkItDown ein `<sup>2</sup>`). Eine hochgestellte Ziffer
(„Kündigungsfrist²") trennt die Prüfung vom Wort; das zusammengeschriebene Token bleibt
daneben, damit „Fix12" sich weiter selbst findet. Umformulierungen zählen seither so, wie die
Prüfung Wörter abgleicht, und unabhängig von ihrer Reihenfolge: Eine Umformulierung zählt
nicht, wenn sie alle Inhaltswörter der Frage oder irgendeiner anderen Umformulierung enthält.
Schreibung, Beugung, Verbform, die Formen unter `ending` und `verb_ending`, die zusammen- oder
getrennt geschriebene Form eines Wortes mit Bindestrich und die Begriffe einer Begriffswelt, die
dieselben Wörter schon auslösen, gelten dabei als dasselbe Wort; von Umformulierungen, die
einander enthalten, zählt nur die erste. Vorher hing es an der Reihenfolge der `--also`, ob eine
engere Umformulierung zählte, und „Kinder" zu „Kind", „gekündigt" zu „kündigt" oder ein Alias
derselben Begriffswelt zählten als neue Suche, obwohl die Prüfung dieselben Passagen traf. Auf
dem Test-Wiki sank dadurch die Zahl der vollständigen Prüfungen von 112 und 113 auf je 110
(Satz A und B): ex-01 und ty-01 in beiden Sätzen und cl-06 in Satz B haben als Umformulierungen
vor allem Begriffe der Begriffswelt `netzentgelt` oder Erweiterungen einer anderen
Umformulierung. `absence_expectations.json` wurde nur in diesen beiden Untergrenzen bewusst neu
aufgezeichnet; die heuristischen Treffer der sieben Fragen zu fehlenden Themen, die Sichtbarkeit
der Pflichtseiten und die beiden anderen Tore blieben unverändert, und das Ranking ebenso.

*Runde 4 (2026-11-15).* Die Textreparatur vor den
Tokens gilt für Ranking und Prüfung gleich und kennt seither auch Markup und HTML-Zeichenreferenzen.
Zeichenreferenzen mit Semikolon werden zu ihren Zeichen, wie CommonMark sie im Text darstellt
(„K&uuml;ndigungsfrist" ist „Kündigungsfrist", „&shy;" ein weiches Trennzeichen); vorher zerfiel das
Wort in „k", „uuml" und „ndigungsfrist", und dieselbe Tabelle wurde als rohes HTML gefunden, als
Pipe-Tabelle nicht. Ein Tiefgestelltes wird an das Wort gezogen („CO~2~" und „CO<sub>2</sub>", so
schreibt Pandoc ein tiefgestelltes Zeichen aus Word, sind wie „CO₂" schon immer „CO2"), eine
Hervorhebung mitten im Wort fällt weg („**Kündigungs**frist"), und ein Hochgestelltes in Markdown
zählt getrennt und zusammengeschrieben („m^2^" gibt „m", „2" und „m2"). Vorher war „CO2-Preis" für
eine mit Pandoc umgewandelte Word-Datei unauffindbar, `absent_terms` nannte das Wort, und die
Prüfung meldete `complete: true`. Drei Heuristiken der Prüfung wurden erweitert, eine kam hinzu, alle
nur in der Prüfung: `ending` vergleicht seither einen gemeinsamen Stamm (das Wort selbst oder das
Wort ohne eine Endung, jetzt auch -em, -s, -se, -sen und -nen) und findet so die Kasusendungen „-er"
und „-em" eines Adjektivs ohne Adjektivsuffix („intelligentem" zu „intelligenten", „fester" zu
„festen") und Plurale wie „Autos", „Ergebnisse" und „Kundinnen"; dafür trifft es auch „Lager" zu
„Lage". `verb_ending` findet Partizip und zu-Infinitiv trennbarer Verben („abgeschaltet" und
„abzuschalten" zu „abschalten"), die die Wortformen nicht kennen, weil sie „ge-" nur am Wortanfang
erkennen. Die neue Heuristik `short_part` findet ein Wort aus zwei oder drei Buchstaben, für das die
Kompositumregeln (Teile ab vier Buchstaben) nicht gelten, als ersten Teil eines Wortes, dessen Rest
ein Wort der durchsuchten Dateien ist („Gas" in „Gaskunden"), und als letzten Teil nach mindestens
drei Buchstaben („Gas" in „Erdgas"). `hyphen_part` lässt einen Teil aus einem Buchstaben bei seinem
Nachbarn, sodass „E-Mail-Adresse" und „E-Mail Adresse" einander finden und „E-Mail" in
„E-Mail-Newsletter" steht, „E-Mobilität" aber nie für „Mobilität" allein. Vorher gab ein Wort mit
einem einbuchstabigen Teil gar keine getrennte Schreibweise. Schließlich muss eine Passage weitere
Funktionswörter nicht mehr enthalten: Präpositionen wie „per", „pro", „je", „laut" und „gemäß",
Fragewörter wie „wofür" und „wieviel", Partikeln wie „noch", „eigentlich" und „nur" und das
Gradwort einer Frage mit „wie" („hoch", „viel", „lange", „oft", „teuer", „schnell"). Vorher traf
„Rechnung per SMS" den Satz „Die SMS-Rechnung kommt jeden Monat" nie, und „Wie hoch ist der
CO2-Preis?" verlangte „hoch" in jeder Passage. Alle sieben Befunde dieser Suche endeten vorher mit
`complete: true` und ohne den antwortenden Satz unter den Ergebnissen oder Treffern; jeder hat einen
Regressionstest in `tests/test_absence_check.py` (Klasse `MarkupAndWordClasses`). Auf dem Test-Wiki
blieben beide Ranking-Tore unverändert, ebenso die Untergrenzen des dritten Tors (je 110
vollständige Prüfungen, je 8 gedruckte späte Claims). `absence_expectations.json` wurde bewusst
neu aufgezeichnet, weil ne-04 („Ladesäule öffentliches Laden Preise") in Satz B einen heuristischen
Treffer bekam: einen Absatz über den dynamischen Tarif Flex mit dem nächtlichen Laden eines
Elektroautos zu Hause, gefunden über „Elektroautos" (`ending`). Er beantwortet die Frage nicht, und
so steht es als Begründung in der Datei.

*Runde 5 (Abschlussprüfung, 2026-11-16).* Acht Befunde, alle bestätigt und behoben:

- Die Spalten von Pandocs einfachen und mehrzeiligen Tabellen schneidet der Scan nach
  Anzeigespalten, nicht nach Zeichen: Emoji wie „✅", „❌" oder „🟢" und chinesische, japanische
  oder koreanische Schriftzeichen belegen zwei Spalten, kombinierende Zeichen, das weiche
  Trennzeichen und das Leerzeichen ohne Breite keine. Vorher verschob schon ein „✅" die
  Zellgrenzen seiner Zeile, und die antwortende Zelle wurde nicht getroffen.
- Eine Zeile mit Aufzählungsmarke mitten in einem Absatz setzt ihn fort, wie ein harter
  Zeilenumbruch oder Pandocs Zeilenumbruch sie erzeugt („ab dem" und „15. Januar" auf zwei
  Zeilen, „Modul" und „2. Ein Heizstab"), außer der Absatz endet mit einem Doppelpunkt oder ist
  eine fett gesetzte Zwischenzeile. In einem Listenpunkt setzt eine tiefer eingerückte Zahl
  außer 1 den Punkt fort. Vorher begann dort ein neuer Listenpunkt, und die Wörter eines Satzes
  standen in zwei Passagen.
- Zitate: Die „>"-Marken fallen vor allen Strukturprüfungen weg, weil Pandoc einen eingerückten
  Word-Absatz als Zitat schreibt. Eine Zeile nur aus „>" wirkt wie eine Leerzeile, und
  Zwischenzeilen, Überschriften, Listen und Tabellen in einem Zitat zählen wie außerhalb. Vorher
  galt ein Zitat als ein einziger Absatz.
- Die neue Heuristik `split_verb` findet ein trennbares Verb, das im Hauptsatz getrennt steht
  („lehnt … ab" für „ablehnen", „passt … an" für „angepasst"). Die Partikel muss ihren Satzteil
  beenden (vor einem Satzzeichen, am Ende des Textes oder vor „und", „oder", „aber" und ähnlichen
  Bindewörtern). Als Verb gilt jedes Wort desselben Satzes, das eines sein kann (mindestens drei
  Buchstaben, Endung auf e, n oder t, kein Funktionswort), höchstens 500 Zeichen vor der
  Partikel. Trennt die Frage selbst ein Verb („Wann schaltet der Netzbetreiber ab?"), sucht der
  Scan auch die zusammengeschriebenen Formen. Eine Umformulierung in der zusammengeschriebenen
  Form zählt weiter als eigene Umformulierung. Eine pathologische Eingabe (300.000-mal „ab,")
  prüft die Erkennung in 0,28 Sekunden.
- `verb_ending` findet die regelmäßigen Formen englischer Verben („cancelled", „applied",
  „charging", „billed").
- `ending` findet Komparativ mit Endung und Superlativ („günstigeren", „günstigste", „am
  schnellsten", „spätestens", „cheapest"; der Stamm braucht mindestens vier Buchstaben, damit
  „Polster" kein Superlativ von „Pol" ist) und weibliche Formen („Kundin", „Kundinnen" und
  „KundInnen" zu „Kunde"). „höchste" zu „hoch" ist unregelmäßig und bleibt hier unerkannt; seit
  Stufe 6 findet es die Regel `irregular` über die geschlossene Tabelle.
- Nicht mehr verlangt werden die englischen Gradwörter einer Frage mit „how" („long", „much",
  „many", „often", „far", „high", „expensive", „fast", „frequently") und die Endung „innen",
  die ein Genderstern oder Doppelpunkt abtrennt („Kund\*innen", „Kund:innen").
- `findability_questions.py` liest eine Datei mit BOM und Windows-Zeilenenden, wie sie nach
  einem Zusammenführen von Hand entsteht; schreibt `add` oder `remove` sie neu, entsteht kein BOM.

Dazu nennt die Alias-Regel im Wiki-Vertrag jetzt genau, welche Formen das Ranking findet und
welche deshalb als Alias auf die Seite gehören, und der feste Satz zur Fehlanzeige verlangt,
die gesuchten Formulierungen zu nennen. Die Rangliste blieb byte-identisch; nur Ausgaben mit
`--exhaustive` änderten sich. Auf dem Test-Wiki kamen Treffer über `split_verb` hinzu, alle für
den Satz „passt das Abrechnungssystem den Abschlag automatisch an": bei ty-05 in beiden Sätzen
zwei, der Absatz einer Quelle mit diesem Satz und derselbe Satz als Claim auf
`wiki/concepts/abschlagszahlung.md`, der schon im Umformulierungsblock gedruckt ist und deshalb nur
über `shown_in` verwiesen wird; bei ch-05 in Satz B einer, derselbe Absatz der Quelle, der auch die
gefragte Bedingung nennt („Für eine größere Senkung verlangen wir einen aktuellen Zählerstand").
Alle drei Tore bestanden ohne Neuaufzeichnung. Der Aufruf mit `--exhaustive` wurde im paarweisen
Vergleich (im Prozess, Median über 114 Fragen) etwa 7 % langsamer auf dem Test-Wiki
(100 → 107 ms) und 14 % auf der 500-Seiten-Kopie (832 → 949 ms); die übrigen Aufrufe blieben
gleich schnell.

### Stufe 5 — Prüfungen beim Release (2026-11-15)

- Fundstellen: `source_coverage.py` (nur im Pflege-Skill) löst kanonische Locator gegen die
  registrierte Extraktion auf: `page=`, `slide=`, `section=`, `heading=`, `sheet=`,
  `timestamp=` und `document`. Ein nicht auflösbarer Locator ergibt eine Lint-Warnung mit Claim,
  Locator und Grund; fehlen einer Extraktion die Seitenmarken ganz, gibt es eine Warnung je
  Quelle. Eine unbekannte Quell-ID bleibt ein Fehler. Keine dieser Warnungen sperrt einen
  Release.
- Quellenabdeckung: `stats.source_coverage` (`lmwiki-source-coverage/1`) zählt Quellen und
  Einheiten (Seiten oder Folien, sonst Abschnitte, sonst das Dokument), die kein aktiver oder
  strittiger Claim zitiert, und unter `locators` jeden Beleg nach aufgelöst, nicht aufgelöst und
  ungeprüft. Ein Beleg der ganzen Quelle zählt als breit und deckt keine Einheit ab. Das ist eine
  Statistik in der Lint- und Release-Ausgabe, keine Warnung, und nie Teil von
  `quality-status.json`. Vor dem Release legt der Pflege-Skill neu unzitierte Quellen dem
  Anwender vor.
- Eine Regel für Seitenmarken und Codeblöcke gilt für Lint, Leseansichten, Vorprüfung und Scan;
  ein Beleg mit `page=N` springt in den HTML-Leseansichten zur Marke.
- Ein Parser für `CONCEPTS.md` und `CLUSTERS.md` (`search_core.schema_definitions`, geteilt):
  Jede andere Überschrift beendet eine Definition, und ein Feld darunter ist ein Lint-Fehler mit
  Zeilennummer. Auf dem Test-Wiki und allen Test-Wikis der Suite liest er wie bisher.
- Auffindbarkeitsfragen: `findability_questions.py add|remove|check` verwaltet höchstens 200
  wörtliche Fragen von Eigentümer oder Nutzern mit bestätigtem Ziel-Claim in
  `meta/findability-questions.jsonl`, außerhalb des Releases und nie im Export (E3). `check`
  stellt jede Frage mit dem Suchkern des Lese-Skills auf den Arbeitsdateien und meldet `found`,
  `found_page_only`, `not_found`, `target_missing` oder `target_inactive`; blockieren kann eine
  Frage den Release nicht.
- Die Suchausgaben blieben Byte für Byte gleich (1.341 Vergleichsfälle); nur die Lint-Ausgabe
  trägt die neue Statistik. Eine Prüfrunde behob einen Absturz bei hochgestellten Ziffern in
  Seitenmarken und Fehler bei Zeitstempeln in Überschriften, Codeblöcken mit Tilden,
  Zeilentrennern in JSONL und einem „?" vor Buchstaben in wörtlichen Fragen.

Auf dem Test-Wiki sind alle 11 Quellen bewertet. 2 sind ganz unzitiert („Notfallhandbuch
Versorgungsstörung und Krisenkommunikation" und „Leitfaden Mieterstrom und gemeinschaftliche
Gebäudeversorgung", je 3 Seiten), eine ist teilweise zitiert (Richtlinie RL-FM-03, Seite 3 ohne
Claim). Von 35 Seiten zitieren Claims 28 (80 %). Alle 277 Fundstellen lösen auf, keine Quelle
wird als Ganzes zitiert, und der Lint ist gültig, ohne Fehler und ohne Warnungen.

### Aufräumrunde (2026-11-15, verhaltensneutral)

Gemeinsamer Code beider Suchhüllen (Argumente, Anfrage, Selektor, Berichtsrumpf, JSON-Ausgabe)
liegt im Suchkern. Der wörtliche Suchmodus (`word_forms=False`) und ein zweiter BM25-Pfad, die nur
Tests nutzten, sind entfernt. `wordforms.RULES` ist eine Tabelle für Name, Gewicht und Klasse
aller Abgleichregeln. 1.343 Vergleichsfälle (alle 114 Fragen in zehn Modi, die 500-Seiten-Kopie,
Export, Lint, ungültige Anfragen und der Messcode des Präzisionstors) blieben Byte für Byte gleich,
und alle drei Tore bestanden ohne Neuaufzeichnung.

### Abschlussmessung (2026-11-16)

Das Test-Wiki wurde einmal mit `build_fixture.py` aus dem Stand nach Stufe 5 (Commit `3ad6e86`)
gebaut. Beide Stände durchsuchten denselben Release: der Stand vor Stufe 1 (`origin/main`) über
seine eigene `search_wiki.py`, der heutige über `quality.py` im Prozess. Zur Kontrolle lief der
heutige Stand auch über die Befehlszeile; die Ränge sind in 114 von 114 Fragen gleich. Gezählt
werden 107 beantwortbare Fragen und 7 Fragen zu Themen, die das Wiki nicht enthält. Alle drei
Tore bestehen, und die Messwerte gleichen ihren aufgezeichneten Grenzen genau.

Die Zahlen dieses Abschnitts sind der Stand nach Stufe 5; was Stufe 6 daran ändert, steht im
Abschnitt „Stufe 6" danach.

Die letzte Prüfrunde (Runde 5 oben) kam nach dieser Messung. Sie änderte das Ranking nicht; die
Zeilen der vollständigen Prüfung sind danach nachgemessen und gleich geblieben. Nur die
Trefferzahlen von ty-05 (3 → 5, beide Sätze) und ch-05 (0 → 1, Satz B) und damit die Zahl der
Fragen mit dem Schritt `read_exhaustive_hits` in Satz B (104 → 105) änderten sich. Die
Laufzeiten mit `--exhaustive` liegen seither etwa 7 % (Test-Wiki) und 14 % (500-Seiten-Kopie)
höher.

**Begriffe.**

- *Gefunden unter den ersten N:* Jede Pflichtseite der Frage steht in `results` auf einem Rang
  bis N, gemessen mit `--limit 100`.
- *Pflichtseite auf Rang 1:* eine Pflichtseite der Frage steht auf Rang 1.
- *Treffer der Negativfragen:* die Summe der Ergebnisse unter den ersten 12 (oder 100) über die
  7 Fragen zu fehlenden Themen.
- *Navigationsplätze:* Ergebnisse unter den ersten 3 (oder 12) über alle 114 Fragen, deren Pfad
  `WIKI.md`, `meta/questions.md` oder eine `index.md` ist; für den alten Stand nach Pfad gezählt.
- *Frage oder Block:* Eine Frage zählt, wenn jede Pflichtseite unter den ersten N der Frage oder
  unter den ersten N Einträgen von `reformulation_results` steht. Diese Sicht umfasst bis zu 2N
  Seiten.
- *Bei gleichem Budget (verschränkt):* Ergebnisse und Block (je Limit 12) werden abwechselnd
  gelesen, Treffer 1, Block 1, Treffer 2 und so weiter; eine Frage zählt, wenn jede Pflichtseite
  unter den ersten N Einträgen steht. Das sind N Plätze.
- *Zeichenbedarf:* die gedruckten JSON-Zeichen von `exhaustive_hits`; Median nach
  `statistics.median`, 90. Perzentil nach nächstem Rang.
- *Laufzeit:* Median über 114 Fragen, ein Aufruf je Frage und Modus, die Modi je Frage
  abwechselnd. „Mit 4 Umformulierungen" heißt: zuerst die Einträge von Satz B, dann die von Satz
  A, ohne Doppelte, die ersten vier.

**Einzelanfrage**

| Kennzahl | vor Stufe 1 | heute |
|---|---|---|
| Pflichtseite auf Rang 1 | 41 | 56 |
| gefunden unter den ersten 3 | 47 | 64 |
| gefunden unter den ersten 12 (Standard) | 57 | 74 |
| gefunden unter den ersten 100 | 62 | 84 |
| Pflichtseiten unter den ersten 12 (von 124) | 68 | 91 |
| Treffer der 7 Negativfragen unter den ersten 12 / 100 | 16 / 16 | 31 / 41 |
| Negativfragen ohne jeden Treffer | 2 | 2 |
| Navigationsseiten unter den ersten 3 (114 Fragen) | 20 | 13 |
| Navigationsseiten unter den ersten 12 | 90 von 781 Plätzen | 79 von 947 Plätzen |
| nur in Quellen: mit `--include-sources` auf Rang 1 | 8 von 8 | 8 von 8 |

Von den 124 Pflichtseiten rückten 44 vor, 4 fielen zurück und 76 blieben auf ihrem Rang. Nur
br-05 verließ ein Band (Rang 3 auf 4, mit `accepted_rank: 4` angenommen); in-05 (5 auf 10), pa-07
(15 auf 21) und sh-06 (8 auf 10) blieben in ihren Bändern. Keine Frage verlor ihre Pflichtseite
auf Rang 1.

**Mit Umformulierungen (zwei blind geschriebene Sätze)**

| Kennzahl | nur Frage | Satz A | Satz B |
|---|---|---|---|
| gefunden in Frage oder Block unter den ersten 3 / 12 / 100 | 64 / 74 / 84 | 86 / 99 / 99 | 86 / 98 / 99 |
| bei gleichem Budget (verschränkt) unter den ersten 3 / 12 | 64 / 74 | 83 / 89 | 83 / 89 |
| Blockeinträge der 7 Negativfragen unter den ersten 12 (unter 100) | – | 41 (73) | 45 (64) |
| Negativfragen mit Block | – | 6 von 7 | 7 von 7 |
| Navigationsseiten im Block | – | 0 | 0 |
| Trefferliste der Frage unverändert | – | 114 von 114 | 114 von 114 |

Nur rund 6 Prozent der Blockeinträge beantwortbarer Fragen (6,6 und 5,8 %) sind Seiten, die die
Testdaten als passend führen. Eine Seite aus dem Block gilt deshalb erst als gefunden, wenn der
Agent sie gelesen hat.

**Je Kategorie, gefunden unter den ersten 12**

In den Spalten „+ A" und „+ B" zählt eine Frage, wenn jede Pflichtseite unter den ersten 12 der
Frage oder des Blocks steht (bis zu 24 Seiten).

| Kategorie | Fragen | vor Stufe 1 | heute | heute + A | heute + B |
|---|---|---|---|---|---|
| exakt | 7 | 7 | 7 | 7 | 7 |
| Flexion | 8 | 3 | 8 | 8 | 8 |
| Umlaut-Schreibung | 7 | 6 | 7 | 7 | 7 |
| Komposita | 8 | 4 | 6 | 8 | 8 |
| Synonym, nicht kuratiert | 8 | 2 | 4 | 8 | 8 |
| Synonym, kuratiert | 7 | 7 | 7 | 7 | 7 |
| Umschreibung | 8 | 2 | 3 | 8 | 8 |
| andere Sprache | 8 | 1 | 1 | 8 | 8 |
| Tippfehler | 8 | 1 | 6 | 8 | 8 |
| breite Frage | 5 | 0 | 1 | 5 | 4 |
| claimlastig | 8 | 8 | 8 | 8 | 8 |
| nur in Quellen (ohne Schalter) | 8 | 0 | 0 | 0 | 0 |
| abgelöst/Historie | 6 | 6 | 6 | 6 | 6 |
| Kennung | 11 | 10 | 10 | 11 | 11 |
| **Summe** | **107** | **57** | **74** | **99** | **98** |

Bei gleichem Budget sind es je Satz 89: exakt 7, Flexion 7, Umlaut 7, Komposita 8, freie
Synonyme 6, kuratierte Synonyme 7, Umschreibung 6, andere Sprache 8, Tippfehler 8, breite Frage
1, claimlastig 8, nur in Quellen 0, Historie 5, Kennung 11.

**Vollständige Prüfung (`--exhaustive`)**

| Kennzahl | Satz A | Satz B |
|---|---|---|
| `complete: true` | 110 von 114 | 110 von 114 |
| unvollständig, alle wegen zu weniger eigenständiger Umformulierungen | ex-01, ty-01, id-04, id-06 | ex-01, cl-06, ty-01, id-06 |
| Negativfragen vollständig geprüft | 7 von 7 | 7 von 7 |
| Wortform-Treffer bei Negativfragen | 0 | 0 |
| heuristische Treffer bei Negativfragen (beurteilt, keiner beantwortet die Frage) | 1 (ne-01) | 2 (ne-01, ne-04) |
| Pflichtseiten sichtbar in Ergebnissen, Block oder Treffern | 124 von 124 | 124 von 124 |
| antwortender Claim erreichbar / gedruckt / zusätzlich als Treffer | 8 / 8 / 3 von 8 | 8 / 8 / 5 von 8 |
| Ausgabe gleich wie derselbe Aufruf mit Quellen ohne Prüfung | 114 von 114 | 114 von 114 |
| Navigationsdateien als Trefferseite | 0 | 0 |
| Zeichenbedarf der Treffer: Median / 90. Perzentil / Maximum | 5.575 / 20.309 / 66.280 | 5.546 / 23.950 / 67.670 |
| Fragen über dem Budget von 100.000 Zeichen | 0 | 0 |

Die heuristischen Treffer bei Negativfragen: bei ne-01 („Fernwärme Anschlusskosten") in beiden
Sätzen ein Absatz einer Quelle über das Wiederherstellen eines gesperrten Stromanschlusses,
gefunden über „Anschlusses" als Teil von „Fernwärmeanschluss"; bei ne-04 in Satz B ein Absatz
über das nächtliche Laden eines Elektroautos zu Hause, gefunden über „Elektroautos" (`ending`).
Beide sind in `absence_expectations.json` mit Begründung beurteilt. Der Scan umfasst auf dem
Test-Wiki 46 Wiki-Dateien (6 Navigationsdateien übersprungen) mit 532 Passagen und 119.233
Zeichen und 11 Quellen mit 212 Passagen und 39.355 Zeichen.

**Laufzeit**

Gemessen ist ein Aufruf über die Befehlszeile mit vorhandenem Bytecode-Cache, in Klammern
derselbe Aufruf im Prozess, ohne Interpreterstart.

| Wiki | Aufruf | vor Stufe 1 | heute |
|---|---|---|---|
| Test-Wiki (52 gerankte Dateien, 11 Quellen) | Standard | 99 ms (55) | 107 ms (53) |
| | mit 4 Umformulierungen | – | 115 ms (61) |
| | `--exhaustive` mit 4 Umformulierungen | – | 152 ms (101) |
| 500-Seiten-Kopie (485 Seiten, 121 Quellen, 0,44 MB Quell-Markdown) | Standard | 497 ms (474) | 439 ms (387) |
| | mit 4 Umformulierungen | – | 456 ms (403) |
| | `--exhaustive` mit 4 Umformulierungen | – | 822 ms (775) |

Die Zeilen mit `--exhaustive` gelten vor Runde 5; danach liegen sie etwa 7 und 14 % höher
(paarweise im Prozess gemessen: 100 → 107 ms und 832 → 949 ms). Interpreterstart und Import der
Suche brauchen heute 51 statt 43 ms, ohne Bytecode-Cache (`python -B`) 93 statt 53 ms. Auf dem
Test-Wiki ist der heutige Stand nur deshalb langsamer; im Prozess ist er gleich schnell, auf der
500-Seiten-Kopie schneller.

Auf der 500-Seiten-Kopie steht jede Seite elfmal; Trefferzahlen und Zeichenbedarf sind dort
überhöht, sie ist nur ein Belastungstest. Mit den Sätzen A und B passten dort 72 von 114 Fragen
ins Budget, vollständig waren 70 und 71; die übrigen 42 enden mit `budget_exhausted`, 32 davon mit
dem Schritt `narrow_formulations`. Die sieben Negativfragen sind auch dort vollständig geprüft
(ne-01 mit 11 heuristischen Treffern, in Satz B auch ne-04 mit 11).

**Quellenabdeckung** (Lint auf dem Test-Wiki): siehe Stufe 5.

**Was die Zahlen nicht zeigen.** Die Messung beruht auf einem einzigen synthetischen,
deutschsprachigen Wiki eines fiktiven Stadtwerks. Gewichte und Regeln wurden darauf gewählt,
ohne zurückgehaltene Testmenge. Die beiden Sätze von Umformulierungen haben Agenten blind
geschrieben, aber aus derselben Modellfamilie, mit der gemessen wird; die Zahlen mit
Umformulierungen sind daher eher zu günstig. Die Sicht „Frage oder Block" liest bis zu doppelt so
viele Seiten wie die Frage allein; deshalb steht die Zahl bei gleichem Budget daneben. Die
Zahlen sind Regressionstore und Richtwerte, keine Zusagen für beliebige Wikis.

### Stufe 6 — Offene Punkte (2026-11-17)

Stufe 6 nahm sich die Punkte vor, die nach der Abschlussmessung offen waren. Für jeden gab es
einen Prototyp, zwei unabhängige Gegenprüfungen (Präzision und Korrektheit) und eine Messung
aller Varianten auf einem gemeinsamen Bau des Test-Wikis mit den echten Funktionen von
`quality.py`. „Nach Stufe 5" heißt im Folgenden Commit `6754d0c`.

| Punkt | Entscheidung | Wirkung auf dem Test-Wiki |
|---|---|---|
| Gemeinsamer Bewertungskern (Befund 5) | umgesetzt, mit Änderungen | keine auf die Suche; der Export meldet Vertrauensstufen und abgelaufene Seiten |
| Fugenvarianten (`compound_link`) | umgesetzt, mit Änderungen | ty-05: nicht unter den ersten 100 → Rang 1 |
| Unregelmäßige Formen (`irregular`, `derived`) | umgesetzt, mit Änderungen | in-05 10 → 2, pa-03 9 → 4, pa-07 21 → 9 |
| Mengenangaben (`quantity`) | umgesetzt, mit Änderungen | id-08 2 → 1 |
| Freie Zerlegung des Suchworts für co-03 | abgelehnt | – |
| ty-07 („Grundversorung") | keine Änderung | bleibt auf Rang 23 |

**Gemeinsamer Bewertungskern.** `quality_core.py` liegt byte-identisch in beiden Skills und in
jedem neuen Export; beide `assess_quality.py` sind dünne Hüllen. Die Ausgabe von
`assess_quality.py` im Lese-Skill blieb in 12 von 12 Aufrufen der Befehlszeile und in über 19.000 Zufallsfällen gleich (beide
Gegenprüfungen). Eine Statusdatei, die kein UTF-8 ist, ergibt einen Hinweis statt eines
Absturzes. Über den Prototyp hinaus: Die Zahl abgelaufener Seiten heißt in den Texten
ausdrücklich Stand des Releases, je Treffer gilt `past_expiry`; die exportierte `SKILL.md` nennt
die Offenlegung abgelaufener Seiten in einem eigenen Satz; ein Test lädt die `assess_quality.py`
eines frischen Exports und prüft den eingefrorenen Wortlaut (vorher blieben alle Tests grün, wenn
`frozen=True` fehlte); der Hinweis, dass keine Seite eine menschliche Prüfung trägt, empfiehlt im
Export das kanonische Wiki und einen neuen Export statt des Pflege-Skills.

**Fugenvarianten.** Ein Suchwort ohne jede Wortform im Wiki findet ein Wort des Wikis aus
denselben Teilen mit einer anderen Fuge („Abschlagzahlung" findet „Abschlagszahlung",
„Kirchenturm" findet „Kirchturm"), als Heuristik mit dem Gewicht 0,45. Gesucht wird nur die
Schreibung der Variante, nicht ihr Stamm: Die Stammsuche des Prototyps fand „Hauptsache" für
„Hauptachse" und „Fahrerinnen" für „Fahrrinne". Steht das Suchwort in den nicht durchsuchten
Quellen, gibt es keine Variante, wie bei einem Tippfehler. Der Kopf des Suchworts (`query_part`)
zählt neben den Varianten weiter, sodass eine falsche Variante die richtige Seite nicht mehr
verdrängt. In einer Zählung über 100.000 deutsche Wörter sank die Zahl der Suchwörter mit einer
Variante dadurch von 197 auf 155. Bekannte Fehlpaarungen sind Namen und ähnliche Wörter:
„Landmann" findet „Landsmann" (im Test festgehalten), dazu „Bestseller" und „Besteller",
„Sonneberg" und „Sonnenberg", „schlicht" und „schleicht".

**Unregelmäßige Formen.** Eine geschlossene Tabelle kennt 58 starke und gemischte Verben in 321
Präfixverben (das Verb ohne Präfix mitgezählt), 67 Substantive dieser Verben, 2 Steigerungsreihen
(hoch, gut) und 24 englische Zeilen, zusammen 4924 Formen unter 347 Schlüsseln. Beide Regeln sind
Heuristiken mit 0,45 und gelten nur für die Wörter der Frage: keine Begriffswelt, keine
nicht durchsuchte Schicht, nie die Seltenheit eines Wortes. Aus dem Prototyp entfernt sind die
leichten Verben ohne Präfix (geben, gelten, liegen, stehen, kommen, halten, lassen, sehen),
heißen, „ent-" bei gelten (Entgelte) sowie „ab-" und „ein-" bei kommen (Abkommen, Einkommen),
jede Form unter vier Buchstaben („lag", „kam"), die erste Person auf „-e" eines trennbaren Verbs
(Abläufe, Ausweise), „Messe", „Scheine", „Werft" und „guter" (Güter); „good" findet wie „hoch"
nichts, wird aber von „better" und „best" gefunden. Dazu kommen die zu-Infinitive der
zusammengesetzten Präfixe („anzuerkennen", „beizubehalten") und keine Endung „-t" oder „-st" nach
einem Stamm auf t oder d, keine „-st" nach ss (127 Unsinnsformen weniger, ohne Wirkung auf die
Tore). Die Prüfung meldet ein getrenntes Verb nie auf einem Substantiv: „ziehe … um" ist kein
`split_verb` auf „Umzug". In den Proben der Gegenprüfungen fiel die Zahl der Wortform-Treffer der
Prüfung von 3, 7 und 7 im Prototyp auf 0, 1 und 0, wie vor Stufe 6; „heiße Speicher" bleibt wie
vorher ohne Treffer. pa-07 steht seither in den Sätzen A und B auf Rang 9 der Frage statt auf
Platz 1 des Blocks, weil der Block keine Seite wiederholt, die schon unter den Treffern steht; das
steht mit Begründung in `accepted_regressions` des zweiten Tors.

**Mengenangaben.** Frage und Seite tragen für jede erkannte Menge ein Zeichen `=<Wert><Einheit>`
(`=2500kwh` für „2,5 MWh", `=14tag` für „vierzehn Tage") in einem eigenen BM25F-Feld. Umgerechnet
wird exakt in Zehnerpotenzen innerhalb von Energie, Leistung, Geld und Prozent; Zahlwörter von
eins bis zwanzig und die Zehner gelten vor einer solchen Einheit und vor einem Zählwort einer
geschlossenen Liste (Tag, Werktag, Kalendertag, Woche, Monat, Quartal, Jahr, Stunde, Minute,
Person, Rate). Keine Menge ergibt eine Zahl nach einem Paragraphen, einer anderen Zahl, einem
Vorzeichen oder in einer Spanne, vor einem Größenwort und vor jedem anderen Wort („Typ 2
Stecker", „Kapitel 4 Abrechnung"). Im Ranking zählt das Zeichen nur, wo es eine Schreibweise
überbrückt: wenn mindestens eine durchsuchte Inhaltsseite es enthält, aber keine andere Form des
Suchworts. Die Prüfung nimmt die Zeichen jedes Wortes der Frage. Die Regel ist eine Heuristik mit
0,9: Das Erkennen kann danebenliegen, ein Treffer wird deshalb im Text geprüft; mit 0,45 blieb
id-08 auf Rang 2. Auf einem eigenen Proben-Wiki erreichte die Prüfung 15 von 15 Mengen in anderer
Schreibweise (vorher 1), und alle 15 standen auf Rang 1. Auf den Gegenproben blieben die
Wortform-Treffer auf falschen Seiten bei 2 und 4 wie vorher; die 6 und 6 heuristischen Treffer
gehören nur zu den bekannten Fehlerklassen unter „Was offen bleibt". Alle 8 Fälle mit falschem
Wert blieben ohne Treffer, und „Widerruf vierzehn Tage" erreicht jetzt „binnen 14 Tagen".

**Abgelehnt: die freie Zerlegung des Suchworts (co-03).** Gemessen von den Gegenprüfungen: Bei 41
von 600 fehlenden echten Wörtern änderte sich Rang 1 (etwa „Höhepunkt", „Vollzeit",
„Wechselstrom", „Tarifvertrag"); in 51 von 86 Fällen standen die Teile mehr als 15 Wörter
auseinander; eine Frage zu einem fehlenden Thema bekam einen Treffer mehr
(„Wasserpreiserhöhung" 1 → 2); su-03 rutschte von Rang 10 auf 12, an den Rand seines Bandes;
ne-01 mit `--include-sources` bekam zwei Quellen ohne Antwort dazu (Rang 7 und 12). Die Prüfung
hätte nicht mehr die Formen benutzt, die das Ranking zählt (README 5.4), und 8 gebaute Wörter aus
60 Buchstaben kosteten 0,6 statt 0,006 Sekunden. co-03 bleibt offen.

**Keine Änderung: ty-07.** Selbst die richtige Schreibung „Grundversorgung" steht nur auf Rang 9,
weil die Frage eine Verbindung sucht, keine Wortform. Tippfehlergewichte von 0,45, 0,6 und 0,9
ergaben die Ränge 17, 17 und 11, und 0,9 brach das zweite Tor. Mit Umformulierungen steht die
Seite schon auf Rang 1 der Frage oder des Blocks.

**Messung** (derselbe Bau des Test-Wikis, im Prozess):

| Kennzahl | vor Stufe 1 | nach Stufe 5 | nach Stufe 6 |
|---|---|---|---|
| Pflichtseite auf Rang 1 | 41 | 56 | 58 |
| gefunden unter den ersten 3 | 47 | 64 | 66 |
| gefunden unter den ersten 12 (Standard) | 57 | 74 | 76 |
| gefunden unter den ersten 100 | 62 | 84 | 85 |
| Pflichtseiten unter den ersten 12 (von 124) | 68 | 91 | 93 |
| Treffer der 7 Negativfragen unter den ersten 12 / 100 | 16 / 16 | 31 / 41 | 31 / 41 |
| Navigationsseiten unter den ersten 3 (114 Fragen) | 20 | 13 | 13 |
| Navigationsseiten unter den ersten 12 | 90 von 781 Plätzen | 79 von 947 Plätzen | 79 von 948 Plätzen |
| Pflichtseiten vorgerückt / zurückgefallen / gleich, gegenüber vor Stufe 1 | – | 44 / 4 / 76 | 48 / 2 / 74 |

Zurückgefallen sind nur noch br-05 (3 auf 4, angenommen) und sh-06 (8 auf 10). Je Kategorie
(Rang 1 / unter 3 / unter 12 / unter 100), nach Stufe 5 → nach Stufe 6: Kennungen 6/9/10/10 →
7/9/10/10, Flexion 3/6/8/8 → 3/7/8/8, Umschreibungen 1/1/3/7 → 1/1/4/7, Tippfehler 5/6/6/7 →
6/7/7/8; alle anderen Kategorien blieben gleich. Mit Umformulierungen blieben Frage oder Block bei
86 / 99 / 99 (Satz A) und 86 / 98 / 99 (Satz B), die Blockeinträge der Negativfragen bei 41 und
45, keine Navigationsseite im Block, die Trefferliste der Frage in 114 von 114 Fragen gleich wie
ohne Umformulierungen; die Frage allein steht in beiden Sätzen bei 66 / 76 / 85, bei gleichem
Budget (verschränkt) sind es 83 und 90 statt 83 und 89. Die vollständige Prüfung blieb in jeder
Kennzahl gleich: 110 von 114 Fragen vollständig je Satz, 8 von 8 antwortenden Claims erreichbar,
107 Fragen mit allen Pflichtseiten sichtbar, keine Navigationsdatei als Trefferseite, Zeichenbedarf
im Median und Maximum 5.914 und 66.280 (Satz A) und 5.689 und 67.670 (Satz B).

Laufzeit (4 Kerne, Last 0,1 bis 0,9, schwankend): Der Import des Suchkerns dauert im Median von 21
Läufen 63 statt 46 Millisekunden, die Tabelle der unregelmäßigen Formen allein rund 13. Das Laden
eines Releases auf der 500-Seiten-Kopie dauert 0,32 bis 0,33 statt 0,26 bis 0,27 Sekunden, mit
`--exhaustive` 0,88 bis 0,91 statt 0,71 bis 0,76 (das schnellste von 7 Ladevorgängen, drei
Runden), weil jeder Text auch nach Mengenangaben gelesen wird.

**Tore.** Nur `expectations.json` ist neu aufgezeichnet: Untergrenzen 58 / 66 / 76 / 85,
Obergrenzen 31 und 13 unverändert. Besser wurden in-05 (10 → 2), pa-03 (9 → 4), pa-07 (21 → 9),
ty-05 (nicht unter den ersten 100 → 1), id-08 (2 → 1) und pa-04 (24 → 23, schon nach Stufe 5 so,
aber nicht aufgezeichnet). Wie jede Neuaufzeichnung beginnt sie mit leeren
`accepted_regressions`; br-05 steht seither mit Rang 4 in den Erwartungen und bleibt so an die
ersten 12 gebunden wie vorher mit `accepted_rank: 4`. Das zweite Tor ist nicht neu aufgezeichnet
(Unter- und Obergrenzen gleich; die zwei Einträge zu pa-07 stehen mit Begründung in
`accepted_regressions`), das dritte auch nicht (ein Probelauf ergab dieselbe Datei).

**Byte-Identität.** Der Vergleichslauf aller 1.343 Fälle (alle 114 Fragen in zehn Modi, 30 Fragen auf der 500-Seiten-Kopie, Export, Lint, ungültige Anfragen und der Messcode der Tore) gegen den Stand nach Stufe 5: Kein Exit-Code änderte sich, die geteilten Module sind byte-identisch, und die Test-Wikis blieben unverändert. 1.293 Fälle unterscheiden sich, 1.183 davon nur in den beiden Grenzsätzen (`coverage.boundary`, `absence_check.boundary`). Die übrigen 110 sind die gewollten Änderungen: 94 Fälle auf dem Test-Wiki, 9 auf der 500-Seiten-Kopie, 4 im Export (sein Bau liefert zusätzlich `scripts/quality_core.py` und die neue `SKILL.md` aus, drei vollständige Prüfungen nennen neue Formen) und die 3 Messungen der Tore. In der Standardsuche ändern sich 6 Fragen: id-08, in-05, pa-03, pa-07, pa-08 und ty-05.

Die volle Suite hat 672 Tests und besteht; die Tests von Bewertungskern, Mengenangaben,
Wortformen, vollständiger Prüfung, Suche, Export und Paketierung laufen zusätzlich unter
Python 3.9.

### Entscheidungen und Abweichungen vom Plan

Die Entscheidungen (Abschnitt 7):

- **E1** — Erweiterungsregel. Jede neue `CONCEPTS.md` sagt: „Search expands a query in meaning
  only through confirmed preferred terms and aliases. Forms of the same word (inflection, umlaut
  spelling, hyphenation) count as matches of that word. Compound parts and one-letter typo
  corrections are disclosed heuristics. Reformulations by the agent are listed in the answer."
  Für den alten Satz meldet der Lint eine Warnung, die keinen Release blockiert.
- **E2** — Budget 100.000 gedruckte Zeichen; `--exhaustive` ist die einzige Ausnahme vom
  gestuften Lesen und nur für Fehlanzeigen gedacht.
- **E3** — Auffindbarkeitsfragen nur wörtlich von Eigentümer oder Nutzern, mit Ziel-Claim, in
  `meta/findability-questions.jsonl` außerhalb des Releases, nie exportiert, nie vom Lese-Skill
  gelesen.
- **E4** — Test-Wiki, Fragen, Umformulierungssätze und Erwartungen liegen unter
  `tests/fixtures/search_quality/`.
- **E5** — Alle vier Wortform-Schritte sind eingeschaltet, jeder erst nach bestandenem
  Präzisionstor.

Abweichungen vom Plan, jeweils mit Grund:

- *Unzitierte Quellen sind eine Statistik, keine Warnung.* Hintergrundmaterial bleibt zu Recht
  unzitiert, und eine Warnung, die sich nie abstellen lässt, stumpft ab. Nicht auflösbare
  Locator sind dagegen Warnungen.
- *Die Historie wird nicht standardmäßig geprüft.* Die Snapshots unter `meta/history/` liegen
  außerhalb des Release-Manifests; `--exhaustive` durchsucht sie nur mit `--include-history`,
  und `absence_check.scopes` weist das aus. Ein Export hat keine Historie; seine Prüfung kann
  trotzdem vollständig sein.
- *Navigationsseiten zählen nur das Wort selbst und bleiben in der Rangliste.* Mit Formen belegten
  Indexseiten 24 Top-3-Plätze (Grenze 20), und eine eigene Liste hätte das Ranking verändert.
  Sie tragen `navigation: true`, werden nie zitiert und nie als Trefferseite der Prüfung gezählt.
- *Manche Heuristiken gelten nur im Scan.* `hyphen_part`, `ending`, `verb_ending`, `split_verb`,
  `short_part`, `suspended_compound` und `footnote_mark` kennt nur die vollständige Prüfung. So
  änderten die Prüfrunden das Ranking nur dort, wo Ranking und Prüfung denselben Text lesen
  (Zahlenschreibweise, Markup, Zeichenreferenzen), auf dem Test-Wiki um einen Rang. Der Preis: Das Ranking
  findet diese Formen nicht, und wo Nutzer sie tippen, müssen Seiten-Aliase sie tragen. Die
  Alias-Regel im Wiki-Vertrag zählt sie deshalb auf.
- *`complete` verlangt zwei eigenständige Umformulierungen.* Eine Umformulierung, die nur Wörter
  hinzufügt oder dieselben Wörter in einer Form enthält, die der Scan ohnehin trifft, zählt nicht.
- *Tippfehler ab 8 statt 7 Buchstaben; ein unbekanntes Suchwort wird nur an seinem Kopf
  zerlegt.* Beides senkt Fehlkorrekturen und Fehltreffer; co-03 („Wärmepumpenstromtarif") bleibt
  dadurch unauffindbar. Eine freie Zerlegung wurde in Stufe 6 als Prototyp gemessen und
  abgelehnt (Abschnitt „Stufe 6").
- *Der Export trägt seine Leseregeln in der `SKILL.md`*, nicht in einem eigenen Antwortvertrag.
  Seine `assess_quality.py` teilt seit Stufe 6 den Bewertungskern `quality_core.py` mit dem
  Lese-Skill.

### Was offen bleibt

- *Synonyme und Umschreibungen ohne Umformulierungen.* Die Frage allein findet 4 von 8 freien
  Synonymen und 4 von 8 Umschreibungen unter den ersten 12. Mit Umformulierungen sind es 8 von 8,
  aber nur, wenn der Agent sie schreibt. Ohne ihn helfen nur kuratierte Seiten-Aliase und
  Begriffswelten.
- *Andere Sprachen ohne Übersetzung.* 1 von 8. Die Suche übersetzt nicht.
- *Breite Fragen* finden mit der Frage allein 1 von 5; *Fakten nur in Quellen* ohne
  `--include-sources` 0 von 8, mit dem Schalter 8 von 8 auf Rang 1.
- *Unregelmäßige Formen außerhalb der Tabelle.* Die geschlossene Tabelle aus Stufe 6 kennt 58
  starke und gemischte Verben, 67 Substantive, 2 Steigerungsreihen und 24 englische Zeilen. Eine
  Form außerhalb davon („geflogen" zu „fliegen") findet weder das Ranking noch die Prüfung; der
  Grenzsatz und die Anleitungstexte nennen das. Eine Tabellenform kann ein anderes Wort sein
  („geladen" findet auch das Geschäft „Laden", „nachgekommen" die „Nachkommen"), und die
  Prüfung paart die Tabelle in beide Richtungen („hoch" trifft dort „höchste"), das Ranking nur
  in eine.
- *Der lange Schwanz der deutschen Morphologie und der Konverterformate.* Jede der fünf
  Prüfrunden fand neue falsche Fehlanzeigen: Tabellenformen, Listen, Zitate, getrennte Verben,
  Markup im Wort. Weitere sind zu erwarten. Dazu kommen bekannte Fehlpaarungen der Regeln:
  „Konzert" zu „Konzern", „Gläubiger" als gebeugtes „gläubig", „Zähler" zu „Zahl", „Lager" zu
  „Lage", „Marken" zu „Markt", „Beweis" zu „Eis", seit Stufe 6 auch Fugenvarianten wie
  „Landmann" zu „Landsmann", „Bestseller" zu „Besteller", „Sonneberg" zu „Sonnenberg" und
  „schlicht" zu „schleicht". Der Agent prüft heuristische Treffer deshalb im Text.
- *Zahlen in einer Schreibweise, die die Suche nicht umrechnet.* Seit Stufe 6 findet `quantity`
  Energie, Leistung, Geld und Prozent in anderer Einheit und Zahlwörter bis zwanzig und die
  Zehner vor einer Einheit oder einem Zählwort der Liste. Offen sind: Spannen („1 - 3 Monate",
  „zwischen 10 und 20 Prozent") werden übersprungen, nicht umgerechnet; Größenwörter (Tausend,
  Mio., Mrd.) ergeben keine Menge; andere Einheiten (Liter, m², km) fehlen.
- *Fehlerklassen der Mengenangaben.* Der Text wird vor dem Lesen der Einheit kleingeschrieben:
  „in der 12 KW" (Kalenderwoche) gilt als 12 Kilowatt, „500 mW" als 500 Megawatt. Ein englisches
  Tausenderkomma liest die Suche als Dezimalkomma („1,000 EUR" ist 1 Euro); das zu trennen
  braucht die Sprache des Wikis. Von einer zusammengesetzten Einheit zählt nur die erste:
  „0,10 € pro Tag" trifft „10 Cent", und „ct/kWh" wird nur als Cent umgerechnet. Ein
  Einheitenwort am Anfang der nächsten Zeile verbindet sich mit der Zahl davor („Stand 2024" und
  darunter „Euro" ergibt 2024 Euro), ebenso ein Zählwort nach einer Seitenzahl („auf Seite 12
  Monate"). Alle diese Fälle sind Heuristik-Treffer mit `matched`, keine Wortformen.
- *Umformulierungen, die nur eine Zahl anders schreiben,* zählen für `complete` noch als
  eigenständig, obwohl die Prüfung dieselbe Menge ohnehin findet. Das zu ändern würde nach
  einer Schätzung des Entwurfs (nicht gemessen) Satz B von 110 auf 109 vollständige Prüfungen
  senken, also eine Untergrenze; es blieb deshalb außerhalb von Stufe 6.
- *Einzelfälle des Rankings.* co-03 („Wärmepumpenstromtarif") steht nicht unter den ersten 100,
  ty-07 („Grundversorung") auf Rang 23; ty-05 steht seit Stufe 6 auf Rang 1. Für co-03 bleibt
  ein neuer Prototyp der freien Zerlegung offen: alle Teile in einem Satz, gemerkte Zerlegungen,
  je Seite einmal gezählt und eine eigene Probe mit fehlenden Themen. Dass co-03 die
  Satzbedingung übersteht, ist geschätzt, nicht gemessen.
- *Abgelaufene Seiten zum Zeitpunkt der Bewertung.* `assess_quality` meldet in `freshness` die
  Zahl der Seiten, deren Ablaufdatum beim Release schon überschritten war. Eine Seite, die erst
  danach abläuft, zählt sie nicht; das zeigt nur `past_expiry` am Suchtreffer. Gemessen: Ein
  Export, 150 Tage nach dem Release bewertet, meldet weiter 0 abgelaufene Seiten, während sein
  erster Treffer `past_expiry: true` trägt. Offen ist, die Zahl bei der Bewertung neu zu
  berechnen.
- *Eingefrorener Wortlaut für Review-, Richtlinien- und Identitätshinweise.* Im Export empfehlen
  die Hinweise zu fälligen oder überfälligen Reviews, zur fehlenden oder ungültigen
  Qualitätsrichtlinie und zur Identität weiter den Pflege-Skill, den ein eingefrorener Skill
  nicht mitbringt. Umformuliert sind bisher nur die sieben Hinweise, die sagen, wie ein neuer
  Stand entsteht.
- *`--expect-manifest-sha256` für die Qualitätsbewertung des Exports.* Die Suche des Exports
  prüft den gemerkten Manifest-Hash, `assess_quality.py` des Exports nimmt ihn nicht an und
  prüft nur den mitgelieferten Abzug.
- *Exit-Code bei falschem Aufruf.* Ein Aufruffehler beendet `assess_quality.py` des Lese-Skills
  mit Code 2, demselben Code wie `wiki_busy`. Unterscheiden lassen sich beide nur an der
  Ausgabe.
- *Echte Nutzerfragen.* Gewichte und Regeln sind auf einem synthetischen Wiki gewählt. Ob die
  Wörter echter Nutzer die Fakten erreichen, misst erst ein Wiki mit Auffindbarkeitsfragen.
- *Windows* ist simuliert (cp1252-Umleitung, PowerShell-Umkodierung), nicht auf einem
  Windows-Rechner gemessen.
- *Bewusst nicht vorgesehen:* Embeddings, Vektorindex, Suchdienst (Abschnitte 3 und 5).

### Wie man neu misst

- Volle Suite: `PYTHONDONTWRITEBYTECODE=1 python3 tests/run_tests.py -q` (672 Tests, etwa
  acht Minuten). Nur die drei Tore: `python3 tests/run_tests.py search_quality`. Beide bauen das
  Test-Wiki in ein temporäres Verzeichnis außerhalb des Repositorys.
- Die drei Tore in `tests/test_search_quality.py`:
  - `expectations.json` (Präzisionstor): Rang 1 je Frage, die Bänder unter den ersten 3 und 12
    je Pflichtseite, Untergrenzen 58 / 66 / 76 / 85, Obergrenzen 31 Negativtreffer und 13
    Navigationsplätze; hingenommene Verschlechterungen stehen mit Begründung in
    `accepted_regressions`.
  - `reformulation_expectations.json` (`ReformulationGate`): Treffer und Zählwerk der Frage
    unverändert (hart), Untergrenzen 86 / 99 / 99 (Satz A) und 86 / 98 / 99 (Satz B), die
    Bänder je Pflichtseite, Obergrenzen 41 und 45 Blockeinträge, keine Navigationsseite im Block
    (hart).
  - `absence_expectations.json` (`AbsenceGate`): Negativfragen vollständig und ohne
    Wortform-Treffer (hart), jeder heuristische Treffer einer Negativfrage mit Begründung
    aufgezeichnet, jede Pflichtseite sichtbar (hart), jeder antwortende Claim erreichbar (hart),
    Untergrenzen 110 vollständige Prüfungen und 8 Claims je Satz, keine Navigationsdatei als
    Trefferseite (hart), gleiche Ausgabe wie mit `--include-sources` (hart).
- Neu aufzeichnen: `python3 tests/fixtures/search_quality/record_expectations.py` für das erste
  Tor, mit `--reformulations` für das zweite und mit `--absence` für das dritte; `--output`
  schreibt in eine andere Datei. Ein Neuaufzeichnen verschiebt die Messlatte für alle späteren
  Änderungen und gehört mit Begründung in die Commit-Nachricht. Ein neuer heuristischer Treffer
  bekommt die Markierung `unjudged`, und das Tor schlägt an, bis jemand die Passage gelesen und
  das Urteil eingetragen hat. `reformulations.json` wird nie geändert, damit ein Tor besteht;
  stattdessen kommt ein neuer Satz hinzu.
- Eigene Zahlen: `tests/fixtures/search_quality/quality.py` bietet `measure`,
  `measure_reformulations` und `measure_absence`; `build_fixture.py --out <Verzeichnis>` baut
  das Test-Wiki mit den echten Helfern außerhalb des Repositorys.

---

## Anhang A — Messmethode und Grenzen

**Test-Wiki.** Ein synthetisches deutschsprachiges Wiki eines fiktiven Stadtwerks: 45
Inhaltsseiten (50 Markdown-Dateien mit Indizes), 11 Quellen und 8 Begriffswelten, veröffentlicht
als Release 0.1.1 mit den echten Helfern. Dazu 114 Fragen in 15 Kategorien mit Pflichtseiten.
Davon sind 107 beantwortbar und 7 betreffen fehlende Themen. Seit Stufe 1 liegen Bauhelfer,
Seiten als Python-Datenmodule und Fragen unter `tests/fixtures/search_quality/`.

**Ausgangslage je Kategorie vor Stufe 1** (unter den ersten 3 / 12 / 100, nicht gefunden auch mit
Quellen; den Stand danach zeigt die Abschlussmessung im Abschnitt „Umsetzungsstand"):

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

**Grenzen.** Sie gelten für die Analyse und, wo nicht anders gesagt, auch für die
Abschlussmessung.

- Ein einziges, synthetisches, deutschsprachiges Wiki mit 52 durchsuchten Seiten. Gewichte und
  Schwellen wurden darauf gewählt, ohne zurückgehaltene Testmenge.
- Falsch-Paarungen von Stemmer und Komposita beurteilte ein einzelner Gutachter.
- Zur Analyse wurde Python 3.9 nicht ausgeführt, nur seine Grammatik geprüft. In der Umsetzung
  liefen die Tests von Suche, Export und Paketierung auch unter Python 3.9.
- Windows wurde simuliert (cp1252-Umleitung, die Umkodierung durch PowerShell), nicht auf einem
  Windows-Rechner geprüft.
- Zeiten und Größen bei 500 bis 5.000 Seiten stammen aus vervielfältigten Kopien. Der
  Wortschatz wächst dort nicht wie in einem echten Wiki.
- Die Agent-Umformulierungen wurden vor dem Öffnen der Seiten geschrieben, aber vom selben
  Modell, das auch auswertete. Das gilt auch für die beiden Sätze des zweiten und dritten Tors.

Die Zahlen sind deshalb Richtwerte für Entscheidungen, keine Zusagen für beliebige Wikis.
