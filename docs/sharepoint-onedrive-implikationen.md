# SharePoint und OneDrive als Ablage: was der Skill wissen und beherrschen muss

Prüfbericht und Umsetzungsplan
Stand: 2026-09-06
Geprüfter Stand: `maintain-llm-wiki`, `query-llm-wiki` (Branch `claude/okf-agent-memory-learnings-iyamt1`)

---

## 1. Kurzfazit

`maintain-llm-wiki/SKILL.md:8` erklärt: „Treat that directory as the only canonical output; SharePoint,
OneDrive, Git, or another later storage location is **outside this skill's concern**."

Das ist als Architekturaussage richtig — das Dateiformat ist ablageunabhängig. Als
Betriebsannahme ist es falsch: Ein Synchronisationsclient **erzeugt eigenständig Dateien** im
Wiki-Verzeichnis und **verzögert Schreibvorgänge unbestimmt**. Beides verletzt Invarianten, die der
Skill selbst zusichert. Die Ablage ist damit nicht außerhalb seiner Zuständigkeit, sondern eine
Umgebung, deren Eigenschaften er kennen muss.

Heute deckt der Vertrag genau **einen** Punkt ab (`wiki-contract.md:59`: der kooperative Lock ist
kein verteilter Lock-Dienst). Das ist ehrlich und richtig, aber es ist der einzige Punkt.

Neun weitere Wirkungen sind ungedeckt. Zwei davon sind kritisch:

| # | Befund | Schwere | Wirkung |
|---|---|---|---|
| B1 | Eine Konfliktkopie macht den gesamten Release unlesbar | **kritisch** | Lese-Skill verweigert jede Antwort |
| B2 | Der Lock schützt bei Sync-Konflikten nicht, meldet den Verlust aber zu spät | **kritisch** | Teilgeschriebener Zustand trotz Lock |
| B3 | Files On-Demand: jede Frage lädt das komplette Wiki herunter | hoch | Leistung, Kosten, Offline-Ausfall |
| B4 | „Release veröffentlicht" ohne Bestätigung des Uploads | hoch | Falsche Persistenzaussage |
| B5 | Sync-Reihenfolge erzeugt transientes `invalid_wiki` mit falscher Diagnose | mittel | Wiki gilt als beschädigt, ist es aber nicht |
| B6 | `.DS_Store` bricht den Lint, wird von Verify aber ignoriert | mittel | Widersprüchliches Verhalten, blockiert Release |
| B7 | Pfadlängengrenzen (400 / 260 Zeichen) werden nie geprüft | mittel | Dateien synchronisieren nicht |
| B8 | Verbotene Namen und Zeichen in erzeugten Slugs | mittel | Datei erreicht die Ablage nie |
| B9 | Groß-/Kleinschreibung: SharePoint unterscheidet nicht, der Skill schon | niedrig | Kollision, fehlschlagende Umbenennung |
| B10 | Selective Sync kann `meta/history/` unsichtbar machen | niedrig | Scheinbar fehlende Wiederherstellungspunkte |

Alle Codebefunde sind am tatsächlichen Stand verifiziert und mit Zeilenangabe belegt. Alle
SharePoint-Eigenschaften sind mit Microsoft-Quelle belegt. Vier Punkte sind ausdrücklich als
**empirisch zu verifizieren** markiert — sie werden nicht als gesichert dargestellt.

---

## 2. Was SharePoint und OneDrive tatsächlich tun

### 2.1 Konfliktbehandlung

Der Sync-Client **merged nicht** und **fragt nicht**. Für alle Nicht-Office-Dateien — und Markdown,
JSON und HTML sind Nicht-Office-Dateien — gilt: Bei einem Konflikt bleiben **beide Fassungen
erhalten**, eine davon wird umbenannt. Der Zusatz ist der Gerätename, üblicherweise in der Form
`name-DESKTOP-A1B2C3.md` oder `name (Computername conflict).md`. Die Konfliktkopie landet **im
selben Verzeichnis**.

Für das Wiki heißt das: Der Sync-Client kann jederzeit eine zusätzliche `.md`-Datei in `wiki/`,
`sources/` oder `schema/` erzeugen, ohne dass ein Pflegeprozess läuft.

### 2.2 Verbotene Namen und Zeichen

Nicht erlaubt sind die Zeichen `" * : < > ? / \ |`, führende und schließende Leerzeichen sowie ein
schließender Punkt. Nicht erlaubt sind außerdem die Namen `.lock`, `CON`, `PRN`, `AUX`, `NUL`,
`COM0`–`COM9`, `LPT0`–`LPT9`, `desktop.ini`, jeder Name, der mit `~$` beginnt, sowie `_vti_` an
beliebiger Stelle im Namen.

`.lock` ist damit ein **gesperrter Name**. Die Lock-Datei des Skills heißt `.llmwiki.lock`
(`wiki_lock.py:19`) — die Sperre gilt dem exakten Namen, nicht der Endung, also ist der aktuelle
Name zulässig. Das ist eine Beinahe-Kollision, die dokumentiert gehört: Ein künftiger Wechsel auf
`.lock` würde die Ablage unbenutzbar machen.

`desktop.ini` und `.DS_Store` werden vom Sync-Client bewusst **nicht** hochgeladen; existiert eine
Cloud-Kopie, löscht der Client sie und behält die lokale. Sie sind also lokal vorhanden und in der
Cloud abwesend — für ein hashbasiertes Manifest ein relevanter Unterschied.

### 2.3 Pfadlängen

Der vollständige dekodierte Pfad einschließlich Dateiname darf **400 Zeichen** nicht überschreiten;
die Grenze gilt für die Kombination aus Ordnerpfad und Dateiname. Unabhängig davon greift unter
Windows ohne aktivierte Langpfadunterstützung die Grenze von **260 Zeichen**.

### 2.4 Files On-Demand

Dateien existieren in drei Zuständen: Platzhalter (etwa 1 KB, Inhalt nur in der Cloud), vollständige
Datei, angeheftete vollständige Datei. Ein Platzhalter **hydriert beim Zugriff automatisch** — „the
file will hydrate without additional code changes". Genau das ist das Problem: Ein gewöhnliches
`read_bytes()` löst einen Download aus, blockiert bis zum Abschluss und schlägt offline fehl. Die
Reparse-Points, über die das umgesetzt ist, werden normalen Anwendungen **verborgen**, sodass eine
Erkennung über Symlink- oder Reparse-Prüfung nicht funktioniert.

### 2.5 Der Lock ist nicht synchronisationssicher

Zwei zeitweise getrennte Geräte erzeugen jeweils lokal `.llmwiki.lock`. `os.open` mit `O_EXCL`
(`wiki_lock.py:66`) schützt zuverlässig gegen einen zweiten Prozess **auf demselben Dateisystem** —
gegen zwei Dateisysteme, die erst später abgeglichen werden, schützt es nicht. Beim Abgleich
entsteht auch hier eine Konfliktkopie oder eine Fassung überschreibt die andere.

---

## 3. Die Befunde im Einzelnen

### B1 — Eine Konfliktkopie macht den gesamten Release unlesbar (kritisch)

**Code.** `verify_release.py:34–49` sammelt in `controlled_paths()` rekursiv alle Dateien unter
`schema/`, `sources/`, `wiki/`, `graph/`. Übersprungen werden nur Namen, die mit `.` beginnen oder
auf `.tmp` enden. `verify_release.py:118` prüft anschließend:

```python
unexpected = sorted(controlled_paths(target) - seen)
if unexpected:
    errors.append(f"Controlled files exist outside the release manifest: {unexpected}")
```

**Ablauf.** Nach dem Release erzeugt der Sync-Client `wiki/concepts/governance-DESKTOP-A1B2C3.md`.
Der Name beginnt nicht mit einem Punkt und endet nicht auf `.tmp`, wird also erfasst. Er steht nicht
im Manifest. Ergebnis: `invalid_wiki`.

**Wirkung.** Der Lese-Skill erzeugt aus `invalid_wiki` grundsätzlich **keine Sachantwort**. Eine
einzige vom Synchronisationsclient angelegte Datei setzt damit das gesamte Wiki außer Betrieb — bei
inhaltlich völlig intaktem Wissensstand. Die Meldung nennt zudem nicht die Ursache, sondern nur eine
unerwartete Datei.

Zusätzlich wird die Konfliktkopie von `lint_wiki.py:543` (`(target / "wiki").rglob("*.md")`) als
**echte Wiki-Seite geparst**. Da sie das Frontmatter des Originals trägt, kollidiert ihre `id` — der
Linter meldet eine doppelte ID statt einer Konfliktkopie.

### B2 — Der Lock schützt nicht und meldet den Verlust zu spät (kritisch)

**Code.** `wiki_lock.py:50–63`: `require_lock()` vergleicht den übergebenen Token gegen
`token_sha256` in der Lock-Datei und bricht bei Abweichung mit `SystemExit` ab. `run_locked.py`
ruft diese Prüfung **zu Beginn jedes Helferaufrufs** auf.

**Ablauf.** Gerät A und Gerät B beginnen getrennt eine Pflege, jedes erzeugt lokal seine Lock-Datei
mit eigenem Token. Beide arbeiten. Der Sync-Abgleich ersetzt auf einem der Geräte die Lock-Datei
durch die des anderen. Der nächste Helferaufruf dort findet einen fremden Token-Hash und bricht ab —
**nachdem** bereits Dateien geschrieben wurden.

**Wirkung.** Genau der Zustand, den der Vertrag ausschließt: ein teilgeschriebener Pflegestand. Der
Vertrag erkennt das Risiko in `wiki-contract.md:59` grundsätzlich an, zieht aber keine Konsequenz —
weder eine Prüfung beim Erwerb, noch eine Kennzeichnung des Wikis als synchronisiert, noch eine
Warnung an den Anwender.

Verschärfend: Die Freigabe des Locks synchronisiert ebenfalls verzögert. Gerät B sieht nach
abgeschlossener Pflege auf Gerät A minutenlang eine **Phantomsperre** und meldet `wiki_busy`
(`verify_release.py:53`), obwohl niemand mehr arbeitet.

*Empirisch zu verifizieren:* ob der OneDrive-Client `.llmwiki.lock` überhaupt synchronisiert oder
als Punktdatei behandelt. Beide Ausgänge sind problematisch — wird sie nicht synchronisiert, ist der
Lock geräteübergreifend vollständig wirkungslos, ohne dass es jemand bemerkt.

### B3 — Files On-Demand: jede Frage lädt das ganze Wiki (hoch)

**Code.** `verify_release.py:105`:

```python
for entry in files:
    ...
    content = path.read_bytes()
```

Die Schleife läuft über **alle** Manifest-Einträge, also über `schema/`, `sources/`, `wiki/`,
`graph/` einschließlich sämtlicher erzeugter HTML-Leseansichten. Der Lese-Skill führt diese
Verifikation **vor jeder Antwort** aus.

**Wirkung.** Auf einer Ablage mit Files On-Demand hydriert jede einzelne Frage das komplette Wiki.
Bei einem Wiki aus mehreren hundert Quellen und der zugehörigen `graph/pages/`-Ansicht sind das
leicht Hunderte Megabyte — pro Frage, gegebenenfalls über eine getaktete Verbindung, und offline
schlägt es fehl.

**Die Spannung.** Die vollständige Hash-Prüfung **ist** die Sicherheitszusage; sie darf nicht
einfach entfallen. Machbar ist aber: den Zustand vor dem Lesen erkennen und den Anwender
entscheiden lassen.

**Erkennung mit Standardbibliothek.** Unter Windows über `os.stat().st_file_attributes`:
`stat.FILE_ATTRIBUTE_OFFLINE` (0x1000) ist in Pythons `stat`-Modul vorhanden;
`FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (0x400000) ist es **nicht** und muss als Literal geführt
werden — geprüft auf dem aktuellen Interpreter. Unter macOS und Linux dient
`st_blocks == 0 and st_size > 0` als Heuristik für eine datenlose Datei. Beide Prüfungen lesen nur
Metadaten und lösen **keine** Hydrierung aus.

### B4 — „Release veröffentlicht" ohne Bestätigung des Uploads (hoch)

**Code.** Alle Schreibpfade enden auf `handle.flush()`, `os.fsync()`, `os.replace()` — etwa
`wiki_lock.py:69–71` und `frontmatter_actions.py:55–57`. Das ist lokal korrekt und garantiert
Dauerhaftigkeit **auf dieser Platte**.

**Wirkung.** Ist die Synchronisation pausiert, das Gerät offline, das Kontingent erschöpft oder der
Pfad zu lang, meldet der Skill dennoch einen erfolgreichen Release. Für den Anwender, der das Wiki
mit anderen teilt, ist das eine falsche Aussage: Veröffentlicht ist es nur für ihn selbst.

Die zehnte Agentengarantie aus `okf-agent-memory` — „Persistenz nie behaupten, ohne sie bestätigt zu
haben" — ist hier direkt anwendbar und heute nicht erfüllt.

### B5 — Sync-Reihenfolge erzeugt falsche Diagnose (mittel)

**Code.** `release_wiki.py` ersetzt `meta/manifest.json` atomar als letzten Schritt. Das ist die
richtige lokale Reihenfolge.

**Wirkung.** Der Sync-Client überträgt in **eigener** Reihenfolge. Ein zweites Gerät kann das neue
Manifest vor den zugehörigen Inhalten erhalten. `verify_release.py:113` meldet dann
`Released file hash differs` → `invalid_wiki`.

Das Verhalten ist sicher — es scheitert geschlossen und liest keinen Mischstand. Falsch ist die
**Diagnose**: Gemeldet wird ein nicht verifizierbarer Release, tatsächlich ist die Übertragung nur
noch nicht abgeschlossen. Der Anwender kann aus der Meldung nicht ableiten, dass Warten hilft.

### B6 — `.DS_Store` bricht den Lint, Verify ignoriert sie (mittel)

**Code.** `lint_wiki.py:485–497` beanstandet in `sources/` jeden Eintrag, dessen Endung nicht `.md`
ist. Für `.DS_Store` liefert `Path.suffix` den leeren String — geprüft —, die Bedingung
`suffix.casefold() != ".md"` trifft also zu:

```
sources/.DS_Store: sources/ permits registered Markdown files only;
original or binary files must remain outside the wiki
```

`verify_release.py:44` und `release_wiki.py:110` überspringen dieselbe Datei dagegen, weil ihr Name
mit einem Punkt beginnt.

**Wirkung.** Ein macOS-Anwender, der `sources/` im Finder öffnet, blockiert damit jeden weiteren
Release — mit einer Meldung, die auf eine unzulässige Originaldatei hindeutet, obwohl es ein
Betriebssystemartefakt ist. Gleichzeitig behandeln die drei Skripte dieselbe Datei
unterschiedlich.

`Thumbs.db` und `desktop.ini` verhalten sich umgekehrt: Sie beginnen nicht mit einem Punkt, werden
also von `controlled_files()` erfasst und wandern bei einem Release **in das Manifest** — oder
lösen, wenn sie danach entstehen, denselben harten Fehlschlag wie B1 aus.

### B7 — Pfadlängen werden nie geprüft (mittel)

Der Skill erzeugt Pfade der Form `sources/src-<hash>-<slug>.md` und
`graph/pages/wiki/concepts/<slug>.html`. Der Slug stammt aus dem Dokumenttitel und ist in der Länge
unbegrenzt. Dazu kommt der Präfix der Ablage, etwa
`/sites/<Team>/Freigegebene Dokumente/<Projekt>/<Wiki>/`.

Keine Stelle im Code prüft eine Längengrenze. Betroffene Dateien synchronisieren schlicht nicht —
lokal ist alles konsistent, in der Cloud fehlen sie. Der Effekt ähnelt B4: Der Skill meldet Erfolg,
die Ablage hat den Inhalt nicht.

### B8 — Verbotene Namen und Zeichen in erzeugten Slugs (mittel)

Slugs entstehen aus Titeln. Ein Titel kann `:`, `?`, `*`, `|`, `"`, `<`, `>` enthalten, mit einem
Leerzeichen oder Punkt enden oder auf einen gesperrten Namen führen.

*Empirisch zu verifizieren:* ob die Sperre für `AUX`, `CON`, `NUL` und die `COM`/`LPT`-Namen auch
greift, wenn eine Endung angehängt ist (`aux.md`). Die Microsoft-Dokumentation nennt die Namen ohne
Endung; das tatsächliche Verhalten des Clients sollte gemessen und nicht angenommen werden.

Ebenfalls zu klären: ob der Sync-Client Punktdateien generell überträgt. Davon hängt B2 unmittelbar
ab.

### B9 — Groß-/Kleinschreibung (niedrig)

SharePoint bewahrt Groß- und Kleinschreibung, unterscheidet aber nicht danach. `Governance.md` und
`governance.md` können dort nicht nebeneinander existieren; lokal auf macOS im Normalfall ebenfalls
nicht, unter Linux schon. Eine reine Schreibweisenänderung über `move_wiki_page.py` ist auf einem
nicht unterscheidenden Dateisystem kein gewöhnlicher Umbenennungsvorgang und kann fehlschlagen oder
wirkungslos bleiben.

### B10 — Selective Sync kann Snapshots verbergen (niedrig)

Wählt ein Anwender `meta/history/` von der Synchronisation ab oder gibt den Speicherplatz frei, sind
Snapshots lokal nicht vorhanden. `restore_wiki.py` listet dann weniger Wiederherstellungspunkte, ohne
zwischen „existiert nicht" und „nicht synchronisiert" zu unterscheiden. Der Anwender kann daraus den
falschen Schluss ziehen, ein Wiederherstellungspunkt sei verloren.

### Nebenbefund — kein Wiederholungsversuch bei Sperrverletzungen

Unter Windows halten Sync-Client und Virenschutz zeitweise Handles auf Dateien. `os.replace` kann
dann mit `PermissionError` fehlschlagen. Eine Prüfung des Codes zeigt: Es gibt **keinen einzigen
Wiederholungsversuch**; die vorhandenen `except OSError`-Stellen behandeln andere Fälle. Ein
Fehlschlag beim abschließenden Ersetzen des Manifests hinterlässt neue Inhalte mit altem Manifest —
wiederherstellbar, aber unnötig.

### Nebenbefund — SharePoint führt eine zweite Historie

Die Ablage hält eigene Versionsstände und einen Papierkorb. Das ist kein Fehler, aber der Skill
sollte es kennen: Es ist ein realer Wiederherstellungsweg, wenn `meta/history/` fehlt, und es
bedeutet zugleich, dass ein Löschen im Wiki den Inhalt in der Ablage nicht beseitigt — relevant für
jede Erwartung an die Inhaltsrichtlinie.

---

## 4. Was der Skill wissen muss

Faktenwissen, das heute an keiner Stelle im Vertrag steht:

1. Der Sync-Client ist ein **Schreiber auf dem Wiki-Verzeichnis**, nicht nur ein Transportweg.
2. Konflikte werden **nie gemergt**; es entstehen zusätzliche Dateien im selben Verzeichnis, benannt
   nach dem Gerät.
3. `.lock`, `CON`, `PRN`, `AUX`, `NUL`, `COM0`–`COM9`, `LPT0`–`LPT9`, `desktop.ini`, Namen mit `~$`
   am Anfang und `_vti_` an beliebiger Stelle sind gesperrt; ebenso `" * : < > ? / \ |`, führende
   und schließende Leerzeichen sowie ein schließender Punkt.
4. Der vollständige dekodierte Pfad ist auf **400 Zeichen** begrenzt; unter Windows greift zusätzlich
   **260 Zeichen** ohne aktivierte Langpfadunterstützung.
5. Files On-Demand hydriert **transparent beim Lesen**; die zugrundeliegenden Reparse-Points sind
   normalen Anwendungen verborgen.
6. `desktop.ini` und `.DS_Store` werden nicht in die Cloud übertragen — lokal vorhanden, entfernt
   abwesend.
7. Ein erfolgreiches `fsync` bedeutet **lokale** Dauerhaftigkeit, nicht Ankunft in der Ablage.
8. Die Übertragungsreihenfolge ist nicht die lokale Schreibreihenfolge.
9. SharePoint unterscheidet keine Groß- und Kleinschreibung, bewahrt sie aber.
10. Die Ablage führt eigene Versionsstände und einen Papierkorb.
11. Eine Bibliothek mit erzwungenem Auschecken macht Dateien schreibgeschützt.

## 5. Was der Skill beherrschen muss

Fähigkeiten, geordnet nach Dringlichkeit:

1. **Synchronisierte Ablagen erkennen** und das Wiki entsprechend kennzeichnen.
2. **Sync-Artefakte als solche erkennen** — Konfliktkopien, `desktop.ini`, `Thumbs.db`, `.DS_Store` —
   und sie mit klarer Diagnose vom Befund „beschädigter Release" trennen.
3. **Konfliktkopien behandeln**: erkennen, dem Anwender Original und Kopie gegenüberstellen, nach
   Bestätigung übernehmen oder verwerfen. Niemals automatisch löschen.
4. **Vor dem Lesen den Hydrierungszustand prüfen** und bei überwiegend datenlosen Dateien warnen,
   bevor ein Download ausgelöst wird.
5. **Persistenz ehrlich melden**: zwischen „lokal geschrieben" und „in der Ablage angekommen"
   unterscheiden und Letzteres nicht behaupten, solange es nicht belegt ist.
6. **Namen und Pfade vorab prüfen**, bevor eine Datei entsteht, die die Ablage nicht annehmen kann.
7. **Transiente Zustände von echten Fehlern unterscheiden** — Sync in Arbeit, Phantomsperre,
   Sperrverletzung — und in diesen Fällen Warten oder Wiederholen empfehlen statt Beschädigung zu
   melden.
8. **Bei synchronisierten Ablagen den Lock-Vorbehalt aktiv aussprechen**, statt ihn nur im Vertrag
   stehen zu haben.

## 6. Was der Skill nicht kann und sagen muss

Diese Grenzen bleiben bestehen und gehören ausdrücklich in die Grenzenliste:

- Kein Dateilock über zwei Geräte hinweg. Wer strikte gleichzeitige Pflege auf mehreren Rechnern
  braucht, braucht eine zentrale Koordination — das kann eine Datei nicht leisten.
- Keine Zusage, dass eine lokal geschriebene Datei die Ablage erreicht. Der Skill kann prüfen und
  warnen, aber nicht erzwingen.
- Kein Zugriff auf den Zustand des Sync-Clients selbst. Alle Erkennung erfolgt über Dateisystem­
  merkmale und ist damit heuristisch.
- Keine Reparatur von Berechtigungen, Kontingenten, erzwungenem Auschecken oder Drosselung.
- Keine Wiederherstellung aus der SharePoint-Versionshistorie. Der Skill kann darauf hinweisen; die
  Ablage bedient das über ihre eigene Oberfläche.

---

## 7. Umsetzungsplan

Drei Stufen. Stufe S1 behebt die beiden kritischen Befunde und ist unabhängig von allem anderen
lieferbar.

### Stufe S1 — Sync-Artefakte und Lock-Ehrlichkeit

*Behebt B1, B2, B6 und den Sperrverletzungs-Nebenbefund. Risiko: niedrig, weil überwiegend
Diagnose statt Verhaltensänderung.*

**S1a — Gemeinsame Artefakterkennung.** Neues Modul `sync_artifacts.py`, von Lint, Release und
Verify gemeinsam genutzt, damit die drei Skripte dieselbe Datei nicht länger unterschiedlich
behandeln. Erkannt werden:

- Konfliktkopien nach Namensmuster (Gerätenamen-Suffix, `(… conflict)`, `(1)`);
- Betriebssystemartefakte: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `~$…`;
- gesperrte Namen und Zeichen nach Abschnitt 2.2.

Die Erkennung **löscht nichts**. Sie klassifiziert und liefert eine eigene Fehlerkategorie.

**S1b — Getrennte Diagnose statt `invalid_wiki`.** `verify_release.py` unterscheidet künftig:

| Zustand | Bedeutung | Antwort möglich |
|---|---|---|
| `invalid_wiki` | Release inhaltlich nicht verifizierbar | nein |
| `sync_artifacts_present` | **neu** — nur Sync-Artefakte weichen ab | nein, aber mit klarer Handlungsanweisung |
| `sync_in_progress` | **neu** — Manifest neuer als Inhalte, Übertragung plausibel offen | nein, Warten empfohlen |
| `stale_lock_suspected` | **neu** — Lock vorhanden, aber Ursprungsgerät ist nicht dieses | nein, Prüfung empfohlen |

Damit meldet der Lese-Skill nicht länger „Wiki beschädigt", wenn OneDrive lediglich eine Datei
angelegt hat oder noch überträgt.

**S1c — Konfliktkopien im Pflege-Skill behandeln.** Neue Aktion im Plan/Apply-Muster: Original und
Konfliktkopie mit Hash, Größe und Änderungszeit gegenüberstellen; nach Bestätigung die Kopie in einen
Snapshot übernehmen und aus dem Arbeitsstand entfernen, oder sie als neue Quelle registrieren.
Niemals ohne Bestätigung.

**S1d — Lock-Vorbehalt aktiv aussprechen.** Beim Erwerb erkennt der Skill Anzeichen einer
synchronisierten Ablage und weist einmalig darauf hin, dass der Lock geräteübergreifend nicht
schützt. Die Lock-Datei erhält Gerätekennung und Ablagehinweis, damit eine Phantomsperre als solche
erkennbar wird.

**S1e — Wiederholungsversuch bei Sperrverletzungen.** `os.replace` und die Schreibpfade erhalten
einen begrenzten Wiederholungsversuch mit wachsender Wartezeit für `PermissionError` und
`OSError` mit Windows-Fehlercode 32 und 5. Drei Versuche, danach klarer Fehler mit Nennung des
wahrscheinlichen Verursachers.

| Datei | Änderung |
|---|---|
| `maintain-llm-wiki/scripts/sync_artifacts.py` | **neu** |
| `maintain-llm-wiki/scripts/lint_wiki.py` | Artefakte über das gemeinsame Modul klassifizieren; `.DS_Store` nicht mehr als Originaldatei melden |
| `maintain-llm-wiki/scripts/release_wiki.py` | Artefakte aus `controlled_files()` ausschließen; Release bei erkannten Konfliktkopien verweigern |
| `maintain-llm-wiki/scripts/verify_release.py` | Neue Zustände; Artefakte getrennt melden |
| `maintain-llm-wiki/scripts/wiki_lock.py` | Gerätekennung; Hinweis bei synchronisierter Ablage; Wiederholungsversuch |
| `maintain-llm-wiki/scripts/resolve_conflict_copy.py` | **neu**, Plan/Apply |
| `maintain-llm-wiki/scripts/run_locked.py` | Neues Skript in die Allowlist |
| `maintain-llm-wiki/scripts/describe_actions.py` | Neue Aktion eintragen |
| `query-llm-wiki/scripts/verify_release.py` | Neue Zustände spiegeln |
| `query-llm-wiki/references/answer-contract.md` | Verhalten je Zustand festlegen |
| `maintain-llm-wiki/references/wiki-contract.md` | Neuer Abschnitt „Synchronisierte Ablagen" |

**Abnahmekriterien.**

1. Eine Konfliktkopie in `wiki/` führt zu `sync_artifacts_present`, nicht zu `invalid_wiki`, und die
   Meldung nennt Datei, vermutete Ursache und Handlungsempfehlung.
2. `.DS_Store` in `sources/` wird von Lint, Release und Verify **identisch** behandelt und nicht
   mehr als unzulässige Originaldatei gemeldet.
3. `desktop.ini` und `Thumbs.db` gelangen unter keinen Umständen in ein Release-Manifest.
4. Keine Aktion löscht ein Sync-Artefakt ohne ausdrückliche Bestätigung.
5. Die Konfliktkopie wird beim Lint nicht mehr als Wiki-Seite mit doppelter ID gemeldet, sondern als
   Konfliktkopie.
6. Beim Lock-Erwerb auf einer erkannten synchronisierten Ablage erscheint der Vorbehalt genau einmal.
7. Ein simulierter `PermissionError` beim Ersetzen des Manifests wird bis zu dreimal wiederholt und
   danach mit verständlicher Ursache gemeldet.
8. Auf einer nicht synchronisierten Ablage ändert sich kein bestehendes Verhalten.

### Stufe S2 — Hydrierung und ehrliche Persistenz

*Behebt B3, B4, B5, B10. Risiko: mittel, weil der Lesepfad berührt wird.*

**S2a — Hydrierungsprüfung vor der Verifikation.** Vor dem Hashen ermittelt der Lese-Skill über
reine Metadaten, wie viele Dateien datenlos sind (Windows: `st_file_attributes` gegen
`FILE_ATTRIBUTE_OFFLINE` und das Literal `0x400000`; sonst `st_blocks == 0 and st_size > 0`).
Überschreitet der Anteil eine Schwelle, meldet er das geschätzte Downloadvolumen und fragt, bevor er
liest.

**S2b — Benannter Teilverifikationsmodus.** Ergänzend, ausdrücklich benannt und im Antwortvertrag
offengelegt: Manifest vollständig verifizieren, Inhaltsdateien nur für die tatsächlich gelesenen
Seiten. Schwächer als die vollständige Prüfung — deshalb muss die Antwort diesen Modus nennen. Kein
Vorgabewert; nur nach Anwenderentscheidung.

**S2c — Persistenz ehrlich melden.** Nach dem Release prüft der Skill, ob die Ablage synchronisiert
ist, und formuliert das Ergebnis entsprechend: „lokal veröffentlicht; Übertragung in die Ablage
nicht bestätigt". Er behauptet nicht, dass andere den Stand sehen können.

**S2d — `sync_in_progress` erkennen.** Weichen ausschließlich Hashes ab, während das Manifest jünger
ist als die abweichenden Dateien, ist eine laufende Übertragung wahrscheinlicher als eine
Beschädigung. Der Zustand aus S1b wird hier mit Leben gefüllt.

**S2e — Snapshots: fehlend oder nicht synchronisiert.** `restore_wiki.py` unterscheidet zwischen
einem tatsächlich fehlenden und einem datenlosen oder abgewählten Snapshot-Verzeichnis.

**Abnahmekriterien.**

1. Auf einer Ablage mit überwiegend datenlosen Dateien wird vor dem ersten Lesen gewarnt und kein
   Download ohne Entscheidung ausgelöst.
2. Die Erkennung selbst löst nachweislich keine Hydrierung aus.
3. Der Teilverifikationsmodus ist nie Vorgabe und wird in jeder damit erzeugten Antwort genannt.
4. Nach einem Release auf synchronisierter Ablage behauptet keine Ausgabe eine bestätigte
   Übertragung.
5. Ein Zustand mit neuem Manifest und noch alten Inhalten wird als `sync_in_progress` gemeldet, nicht
   als `invalid_wiki`.
6. Ein nicht synchronisiertes `meta/history/` wird als solches gemeldet und nicht als leer.

### Stufe S3 — Namens- und Pfadverträglichkeit

*Behebt B7, B8, B9. Risiko: niedrig, rein präventiv.*

**S3a — Ablageprofil.** Bei der Einrichtung kann der Anwender die Zielablage angeben — lokal,
OneDrive, SharePoint — und optional den URL-Präfix der Bibliothek. Gespeichert in
`schema/WIKI_PROFILE.md`. Ohne Angabe gilt der lokale, unbeschränkte Fall.

**S3b — Namensprüfung vor der Erzeugung.** Jeder erzeugte Slug wird gegen die Regeln aus
Abschnitt 2.2 geprüft, bevor eine Datei entsteht. Bei Kollision schlägt der Skill einen zulässigen
Namen vor und lässt ihn bestätigen.

**S3c — Pfadbudget.** Aus dem Präfix ergibt sich der verbleibende Spielraum bis 400 Zeichen. Der
Skill warnt bei Überschreitung und beim Erreichen von 260 Zeichen im lokalen Pfad. Ein Lint-Hinweis
listet gefährdete Dateien.

**S3d — Schreibweisenkollisionen.** Der Linter meldet Pfade, die sich nur in der Groß- und
Kleinschreibung unterscheiden. `move_wiki_page.py` behandelt eine reine Schreibweisenänderung als
eigenen Fall über einen Zwischennamen.

**Abnahmekriterien.**

1. Ein Titel mit `:` oder `?` erzeugt niemals einen unzulässigen Dateinamen.
2. Kein erzeugter Name lautet `.lock`, `CON`, `PRN`, `AUX`, `NUL`, `COM0`–`COM9`, `LPT0`–`LPT9` oder
   `desktop.ini`, beginnt mit `~$` oder enthält `_vti_`.
3. Bei gesetztem Präfix meldet der Skill jede Datei, die 400 Zeichen überschreiten würde, **bevor**
   sie entsteht.
4. Zwei Seiten, die sich nur in der Schreibweise unterscheiden, werden beanstandet.
5. Eine reine Schreibweisenänderung gelingt auch auf einem nicht unterscheidenden Dateisystem.
6. Ohne Ablageprofil verhält sich der Skill wie bisher.

### Reihenfolge

```text
S1  Artefakte + Lock-Ehrlichkeit     unabhängig, zuerst
 |
 +--> S2  Hydrierung + Persistenz    nutzt die Zustände aus S1b
 |
 `--> S3  Namen + Pfade              unabhängig, parallel möglich
```

---

## 8. Empirisch zu klären

Vier Punkte sind aus Dokumentation allein nicht sicher zu beantworten und sollten auf einer echten
Ablage gemessen werden, bevor die betroffenen Teile umgesetzt werden:

1. Überträgt der OneDrive-Client `.llmwiki.lock`? Falls nein, ist der Lock geräteübergreifend
   vollständig wirkungslos — das ändert die Formulierung in S1d von „schützt nicht zuverlässig" zu
   „schützt nicht".
2. Welches Namensmuster verwendet der aktuelle Client für Konfliktkopien von `.md`-Dateien? Davon
   hängt die Mustererkennung in S1a ab.
3. Greift die Namenssperre auch mit Endung, also bei `aux.md` und `con.md`?
4. Werden Punktdateien und Punktverzeichnisse generell übertragen? Davon hängt ab, ob `meta/history/`
   und die erzeugten Artefakte überhaupt geräteübergreifend verfügbar sind.

---

## 9. Quellen

- [SharePoint limits — 400-Zeichen-Pfadgrenze](https://learn.microsoft.com/office365/servicedescriptions/sharepoint-online-service-description/sharepoint-online-limits#service-limits-for-all-plans)
- [Migration Assessment Scan: Long OneDrive URLs](https://learn.microsoft.com/sharepointmigration/migration-assessment-scan-long-onedrive-urls)
- [Build a Cloud Sync Engine that Supports Placeholder Files — Hydrierung und verborgene Reparse-Points](https://learn.microsoft.com/windows/win32/cfapi/build-a-cloud-file-sync-engine)
- [CfGetPlaceholderStateFromAttributeTag — Platzhalterzustände](https://learn.microsoft.com/windows/win32/api/cfapi/nf-cfapi-cfgetplaceholderstatefromattributetag)
- [Resolve sync issues in OneDrive for work or school](https://learn.microsoft.com/troubleshoot/sharepoint/sync/troubleshoot-sync-issues)
- [Guide to migrating file shares to OneDrive, Teams, and SharePoint — ungültige Zeichen und Namen](https://learn.microsoft.com/sharepointmigration/fileshare-to-odsp-migration-guide#assess-and-remediate-your-content)
- [Restrictions and limitations in OneDrive and SharePoint](https://support.microsoft.com/en-us/onedrive/restrictions-and-limitations-in-onedrive-and-sharepoint) (Liste der gesperrten Namen; über den Proxy dieser Sitzung nicht direkt abrufbar, Inhalt über Sekundärquellen und die Microsoft-Learn-Migrationsleitfäden abgeglichen)
- [How OneDrive Sync resolves sync conflicts](https://sharepointmaven.com/how-onedrive-sync-resolves-sync-conflicts/) (Konfliktkopien-Benennung, Sekundärquelle)
