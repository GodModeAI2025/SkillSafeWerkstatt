#!/usr/bin/env python3
"""Deterministic word-form layer of the shared search core, using the standard library only.

The layer never changes a document token. At query time it answers one
question per query term: which tokens that really occur in the searched files
are a form of this term, by which rule, and how much weaker than the literal
token is that relation? The answer is a group of members, each tagged with its
rule and weight. `bm25.group_base_score` turns a group into one BM25F term.

Rules, from strongest to weakest:

- exact: the literal token. Weight 1.0; every other rule weighs less.
- fold: the same word in another spelling: ae/oe/ue for ä/ö/ü (ß and ss are
  already equal after case folding), or a hyphenated word written joined.
- stem: the same word with another inflection ending (German noun and
  adjective endings, English plural). Derivational suffixes are never removed,
  and nouns keep their -er: "Zähler" is not a form of "zahlen", and
  "Hersteller", "Herstellers" and "Herstellern" share one key that is not
  "herstellen".
- verb: a verb form (-t, -et, ge-...-t), a weaker secondary key. -et counts
  only where German writes the extra e (meldet, rechnet), so "Planet",
  "Market" or "Internet" are no verb forms.
- irregular: for a query word, a form of the same word from a closed table,
  where no ending rule can see it: strong and mixed verbs ("umgezogene",
  "umziehen", "umzog"; "vergilt", "vergalt", "vergolten") and comparison that
  changes the word ("höchste" and "höher" find "hoch"). A disclosed
  heuristic: a table form can also be another word with the same letters.
- derived: for a query word, a noun of the same closed table and a form of its
  verb ("Umzug" and "umgezogene", "Abschluss" and "abgeschlossen"). Another
  word, so a disclosed heuristic with the weight of `irregular`.
- compound_head, compound_modifier: a corpus word in which the term is the last
  part (head) or an earlier part (modifier), accepted only when every other
  part is itself a word of the searched files.
- compound_link: for a query word with no word form, a corpus word made of the
  same parts with another linking element between two of them
  ("Abschlagzahlung" and "Abschlagszahlung", "Kirchenturm" and "Kirchturm").
- query_part: the head of a query word that occurs nowhere, when the query word
  splits into words of the searched files.
- typo: a corpus word one edit away from a long query word that matches nothing
  by any other rule.

The first four are word forms: they are the same word. Irregular forms,
derived nouns, compound parts, link variants and typo corrections are
disclosed heuristics. They never set a term's rarity while a word form of it
occurs anywhere (the search core then counts the rarity from the word forms),
and their weight is applied after BM25 saturation (see bm25).
Compound rules consider no token longer than MAX_COMPOUND letters, so an
endless run of letters cannot make a search slow or deep.

Before tokens exist, `repair_text` joins words that the layout or the markup
split: HTML character references (decoded, so "K&uuml;ndigung" is
"Kündigung" and "&shy;" a soft hyphen), soft hyphens, zero-width characters,
a subscript or emphasis inside a word ("CO~2~", "CO<sub>2</sub>",
"**Kündigungs**frist") and hyphens at a line break. A superscript is kept as
pandoc writes it ("m^2^"); `join_superscripts` gives the joined spelling the
search core indexes as well.

Closed-class words (articles, pronouns, prepositions, conjunctions, auxiliary
and modal verbs, question words, negation) match only literally. They are never
stemmed, split, corrected, or taken as a form of a content word.

Nothing here reads or writes a file. All results are sorted, so they do not
depend on set or dict order or on PYTHONHASHSEED.
"""

from __future__ import annotations

import re
from html import unescape as _unescape
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


#: Every rule that can make a token count for a term, with its weight and its
#: class. The literal token is 1.0 and every other rule is strictly below it,
#: so on otherwise equal pages the literal match ranks first. The classes:
#:
#: - word_form: the same word. Only these set a term's rarity.
#: - heuristic: a disclosed guess of the ranking. It never sets a term's rarity
#:   while a word form exists; on a page it adds below the word forms (see
#:   bm25.group_base_score).
#: - scan: a guess only the exhaustive scan of the search core makes (see the
#:   rule names there), so a hit through it is checked in the text; its weight
#:   only orders the forms a report lists.
RULES: Dict[str, Tuple[float, str]] = {
    "exact": (1.0, "word_form"),
    "fold": (0.9, "word_form"),
    "stem": (0.6, "word_form"),
    "verb": (0.5, "word_form"),
    "irregular": (0.45, "heuristic"),
    "derived": (0.45, "heuristic"),
    "compound_head": (0.45, "heuristic"),
    "compound_link": (0.45, "heuristic"),
    "compound_modifier": (0.35, "heuristic"),
    "query_part": (0.35, "heuristic"),
    "typo": (0.3, "heuristic"),
    # The same quantity in another notation (see search_core.QUANTITY_RULE).
    # Heuristic, because recognising a number and its unit in a text can still
    # go wrong (a label, "Bauteil 1 l" read as a litre; a calendar week written
    # "12 kw", where only "12 KW" is refused; an English thousands comma; an
    # amount per another unit, "0,10 € pro Tag" read as "0,10 €"), so a hit is
    # checked in the text. The weight is that of a fold: once recognised, the
    # value and the dimension are the same, only the notation differs.
    "quantity": (0.9, "heuristic"),
    "hyphen_part": (0.35, "scan"),
    "ending": (0.35, "scan"),
    "verb_ending": (0.35, "scan"),
    "split_verb": (0.35, "scan"),
    "footnote_mark": (0.35, "scan"),
    "suspended_compound": (0.35, "scan"),
    "short_part": (0.35, "scan"),
}

#: Weight of each rule, from RULES.
WEIGHTS: Dict[str, float] = {rule: weight for rule, (weight, _) in RULES.items()}

#: Rules that find the same word, from RULES. Only these set a term's rarity.
WORD_FORM_RULES = frozenset(rule for rule, (_, kind) in RULES.items() if kind == "word_form")

#: Shortest stem an inflection ending may leave.
MIN_STEM = 4
#: Shortest stem the verb rule may leave when it removes a final -t.
MIN_VERB_STEM = 5
#: Shortest compound part.
MIN_PART = 4
#: Shortest query word that may be corrected as a typo (one edit).
MIN_TYPO_LENGTH = 8
#: Longest token the compound rules consider, as a compound, as a part, or as a
#: query word split at its head. Real compounds stay far below; a run of
#: thousands of letters would otherwise cost quadratic time and deep recursion.
MAX_COMPOUND = 64

#: Linking elements between compound parts. "er" and "ens" are left out on
#: purpose: they produced only false splits (zahl+er+stand, weit+er+gegeben).
LINKS = ("", "s", "es", "n", "en", "e")

#: Endings after which -er or -em is adjective inflection, not an agent noun.
#: The -ell adjectives (aktuell, generell, formell, schnell) end in one of the
#: five forms below; a bare "ell" also caught Hersteller, Antragsteller, Keller.
ADJECTIVE_ENDINGS = (
    "ig", "lich", "isch", "bar", "sam", "haft", "los", "iell", "uell", "nell", "rell", "mell", "al", "iv",
)

#: Letters after which a final -s is an inflection ending.
S_ENDING = frozenset("bdfghklmnrt")

#: Characters that hide inside a word without being part of it.
_INVISIBLE = {ord(character): None for character in "­​‌‍⁠﻿"}
#: The same characters as one pattern: a single pass finds whether a text holds any of them.
_HAS_INVISIBLE = re.compile("[­​‌‍⁠﻿]")
#: Hyphen characters other than the ASCII hyphen-minus.
_HYPHENS = {ord("‐"): "-", ord("‑"): "-"}
#: A hyphen at a line end before a letter. It breaks a word when a letter
#: precedes it too (checked in `_join_line_break`; a pattern that starts with
#: the hyphen itself scans long texts much faster than one with a lookbehind).
_LINE_BREAK = re.compile(r"-[ \t]*\r?\n[ \t]*(?=[^\W\d_])")
#: Words after a line-end hyphen that show a suspended compound ("Netz- und Messentgelte").
_SUSPENDED = re.compile(r"(?:und|oder|bzw|sowie|bis|and|or)\b", re.IGNORECASE)
#: An HTML character reference with its semicolon, as CommonMark decodes it in text: named, decimal or hexadecimal.
_ENTITY = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
#: An HTML subscript tag, opening or closing: pandoc's GFM writes "CO<sub>2</sub>".
_SUB_TAG = re.compile(r"</?sub\b[^>]*>", re.IGNORECASE)
#: An HTML superscript, written as pandoc's Markdown writes it (^...^) so that one spelling is indexed.
_SUP_TAG = re.compile(r"<sup\b[^>]*>([^<]{0,64})</sup\s*>", re.IGNORECASE)
#: Pandoc's subscript right after a letter or digit ("CO~2~"); never strikethrough (~~).
_SUBSCRIPT = re.compile(r"(?<=[^\W_])~([^\s~]{1,16})~(?!~)")
#: Pandoc's superscript right after a letter or digit ("m^2^", "Kündigungsfrist^1^").
_SUPERSCRIPT = re.compile(r"(?<=[^\W_])\^([^\s^]{1,16})\^")
#: Emphasis around letters or digits only, with * (CommonMark allows no emphasis with _ inside a word).
_EMPHASIS = re.compile(r"(?<!\*)(\*{1,3})([^\W_]+)\1(?!\*)")

#: The stopwords, written as people write them: left out of a query's terms
#: unless nothing else is left, and never a compound part.
STOPWORDS = """
aber als am an auch auf aus bei das der die ein eine einer eines für hat im in ist mit oder
sich sind und von was wie zu zum zur
a an and are as at be by for from how in is of on or that the to what with
"""
#: Closed word classes, written as people write them.
CLOSED_CLASS_DE = """
der die das den dem des ein eine einer eines einem einen kein keine keinen keinem keiner
ich du er sie es wir ihr man mich mir dich dir ihn ihm uns euch sich
mein meine meinem meinen meiner dein deine sein seine seinem seinen seiner ihre ihrem ihren ihrer
unser unsere unserem unseren euer eure
dieser diese dieses diesen diesem jemand jemandem jemanden jeder jede jeden jedem jedes
an am auf aus bei beim bis durch für gegen in im ins mit nach ohne seit über um unter von vom vor zu zum zur
aber als auch dass denn doch oder sondern und weil wenn ob
ist sind war waren bin bist wird werden wurde wurden hat haben hatte hatten habe
kann können konnte muss müssen musste darf dürfen soll sollen will wollen
was wer wen wem wessen wie wo wann warum wieso weshalb welche welcher welches welchen welchem
nicht
"""
CLOSED_CLASS_EN = """
a an and are as at be by for from how in is of on or that the to what with
who whom whose when where why which do does did can could would should
if we you he she they them this these those there not was were been has have had
our your their my than
"""
#: Prepositions, contractions, conjunctions, question words and particles the
#: closed class lacks ("per", "pro", "je", "laut", "gemäß", "wofür",
#: "wieviel", "bzw", "noch", "eigentlich", "nur"), the degree words of a
#: question with "wie" or "how" ("Wie hoch ...?", "Wie viel ...?", "Wie lange
#: ...?", "Wie oft ...?", "How long ...?", "How much ...?"), the light verbs
#: of a question ("Gibt es ...?", "Wie geht ...?", "Was gilt ...?", "Was
#: passiert ...?"), which name no topic, and the feminine suffix "innen" that
#: a gender star, colon or underscore splits off ("Kund*innen", "Kund:innen").
#: A passage need not hold them; the scan only. The ranking and the precision
#: gate never use them.
SCAN_FUNCTION_WORDS = """
ab ans aufs außer binnen durchs fürs gegenüber hinter hinters innerhalb außerhalb neben samt statt
trotz übers ums unters vors während wegen zwischen
per pro je laut lt gemäß gem bezüglich bzgl hinsichtlich mittels anhand zwecks infolge aufgrund seitens
dank entlang anstatt nebst mitsamt oberhalb unterhalb jenseits
bzw beziehungsweise sowie sowohl weder
wofür womit worauf wozu woran worin worüber wovon wodurch wonach wogegen woraus wobei wovor
wieviel wieviele viel viele vielen weswegen inwiefern hoch lange oft häufig teuer schnell
noch schon bereits eigentlich überhaupt etwa eben mal ja bitte wohl nur sogar erst
about after before between into over under via within without per regarding concerning versus vs
gibt gibts geben gab gegeben geht gehen ging gegangen gilt gelten galt gegolten passiert passieren
funktioniert funktionieren steht stehen
get gets got happen happens happened exist exists existed
long much many often far high expensive fast frequently
innen
"""

#: The function-word tiers, from the narrowest to the widest: (tier, its own
#: words). A tier holds its own words and every word of the tiers before it.
#:
#: - stopword: STOPWORDS.
#: - closed: matches only literally. Closed-class words (articles, pronouns,
#:   prepositions, conjunctions, auxiliary and modal verbs, question words,
#:   negation) are never stemmed, split, corrected, or taken as a form of a
#:   content word.
#: - scan: a word a passage never has to hold for the exhaustive scan.
FUNCTION_WORD_TIERS: Tuple[Tuple[str, str], ...] = (
    ("stopword", STOPWORDS),
    ("closed", CLOSED_CLASS_DE + CLOSED_CLASS_EN),
    ("scan", SCAN_FUNCTION_WORDS),
)


def function_words(normalise) -> Dict[str, frozenset]:
    """Each tier of FUNCTION_WORD_TIERS with the words of the tiers before it, normalised by `normalise`."""
    tiers: Dict[str, frozenset] = {}
    words: frozenset = frozenset()
    for tier, own in FUNCTION_WORD_TIERS:
        words = words.union(normalise(word) for word in own.split())
        tiers[tier] = words
    return tiers


def _join_line_break(match: "re.Match[str]") -> str:
    start = match.start()
    if not start or not match.string[start - 1].isalpha():
        return match.group(0)
    following = match.string[match.end():match.end() + 6]
    if _SUSPENDED.match(following):
        return match.group(0)
    # A word broken inside: join. A hyphenated word broken at its own hyphen
    # (the next part starts with a capital) keeps the hyphen.
    return "-" if following[:1].isupper() else ""


def _join_emphasis(match: "re.Match[str]") -> str:
    # Only emphasis inside a word is removed ("**Kündigungs**frist"); "**Hinweis**" stays as written.
    start, end = match.span()
    text = match.string
    if (start and text[start - 1].isalnum()) or (end < len(text) and text[end].isalnum()):
        return match.group(2)
    return match.group(0)


def repair_markup(text: str) -> str:
    """Join a word that inline markup split: a subscript, an HTML superscript, emphasis inside the word (pure).

    "CO~2~" and "CO<sub>2</sub>" become "CO2", as normalisation already makes
    of "CO₂". "m<sup>2</sup>" becomes pandoc's "m^2^", whose joined spelling
    `join_superscripts` gives, while the word stays apart from a footnote
    mark. Emphasis inside a word ("**Kündigungs**frist", pandoc's output for
    a partly bold Word compound) is removed when only letters or digits
    stand between its delimiters; "Kund*innen und Kolleg*innen" stays.
    """
    if "<s" in text or "<S" in text or "</s" in text or "</S" in text:
        text = _SUB_TAG.sub("", text)
        text = _SUP_TAG.sub(lambda match: "^" + match.group(1) + "^", text)
    if "~" in text:
        text = _SUBSCRIPT.sub(r"\1", text)
    if "*" in text:
        text = _EMPHASIS.sub(_join_emphasis, text)
    return text


def join_superscripts(text: str) -> str:
    """The text with every superscript glued to the word before it: "m^2^" becomes "m2" (pure)."""
    return _SUPERSCRIPT.sub(r"\1", text) if "^" in text else text


def repair_text(text: str) -> str:
    """Undo layout and markup artefacts that split a word.

    In order: HTML character references are decoded (CommonMark decodes them
    in text, so "K&uuml;ndigung", "K&#252;ndigung" and "Kündigung" are one
    word, "&nbsp;" a space and "&shy;" a soft hyphen); soft hyphens and
    zero-width characters are removed; inline markup is joined
    (`repair_markup`); and a hyphen at a line break inside a word is joined.
    Never drops a letter of the text; text without such artefacts comes back
    unchanged.
    """
    if "&" in text:
        text = _ENTITY.sub(lambda match: _unescape(match.group(0)), text)
    if _HAS_INVISIBLE.search(text):
        text = text.translate(_INVISIBLE)
    if "‐" in text or "‑" in text:
        text = text.translate(_HYPHENS)
    if "<" in text or "~" in text or "*" in text:
        text = repair_markup(text)
    if "-" in text and "\n" in text:
        text = _LINE_BREAK.sub(_join_line_break, text)
    return text


def fold_umlaut(token: str) -> str:
    """One spelling for ä/ae, ö/oe and ü/ue in a normalised token.

    Tokens arrive without diacritics (ü is already u), so a digraph is reduced
    to its bare vowel: "kuendigung" and "kundigung" meet. "ue" after q, a or e
    is no umlaut spelling (Quelle, Bauer, neue, Steuer) and stays.
    """
    if "ae" not in token and "oe" not in token and "ue" not in token:
        return token
    if len(token) < 4 and token[:2] not in ("ae", "oe", "ue"):
        # Short words are left alone ("due", "toe"), except a leading digraph ("oel").
        return token
    out: List[str] = []
    index = 0
    length = len(token)
    while index < length:
        character = token[index]
        if index + 1 < length and token[index + 1] == "e" and character in "aou":
            if character == "u" and index and token[index - 1] in "qae":
                out.append(character)
                index += 1
                continue
            out.append(character)
            index += 2
            continue
        out.append(character)
        index += 1
    return "".join(out)


def units_of(token: str) -> List[str]:
    """The written parts of a hyphen- or underscore-joined token."""
    if "-" not in token and "_" not in token:
        return [token]
    return [unit for unit in re.split(r"[-_]", token) if unit]


def spelling_key(token: str) -> str:
    """The token with umlaut digraphs folded and hyphens removed: the fold rule's key.

    The parts of a hyphenated token are only ever joined, never matched one by
    one, so a link slug such as "tarif-lindenstrom-fix12" can never match "Tarif".
    """
    if "-" not in token and "_" not in token:
        return fold_umlaut(token) if token.isalpha() else token
    return "".join(fold_umlaut(unit) if unit.isalpha() else unit for unit in units_of(token))


def _adjective_base(base: str) -> bool:
    """True when `base` + -er/-em reads as an inflected adjective, not as an agent noun.

    "-eig" is a verb stem (Zeiger, Steiger), and "-isch" needs two letters in
    front (frischer, typischer, but Fischer, Mischer). "Gläubiger" still reads
    as "gläubig" + -er: a pure rule cannot tell that noun from the adjective.
    """
    if not base.endswith(ADJECTIVE_ENDINGS) or base.endswith("eig"):
        return False
    return not (base.endswith("isch") and len(base) < 6)


def _same_noun(stemmed: str) -> str:
    """Give -ers and -ern the key the bare -er form gets, so one noun keeps one key."""
    if stemmed.endswith("er") and len(stemmed) - 2 >= MIN_STEM and _adjective_base(stemmed[:-2]):
        return stemmed[:-2]
    return stemmed


def stem(token: str) -> str:
    """Strip at most one inflection ending from an alphabetic token.

    German noun and adjective endings and the English plural. Derivation (-ung,
    -heit, -lich ...) is never touched, and -er or -em only go after an
    adjective ending, so agent nouns (Zähler, Betreiber, Hersteller) keep their
    -er, also before -s and -n (Herstellers, Herstellern).
    """
    length = len(token)
    if length <= MIN_STEM or not token.isalpha():
        return token
    if token.endswith("ies") and length - 3 >= MIN_STEM - 1 and not token.endswith("eies"):
        return token[:-3] + "y"
    if token.endswith("ens") and length - 3 >= MIN_STEM:
        return token[:-3]
    if token.endswith("en") and length - 2 >= MIN_STEM:
        return token[:-2]
    if token.endswith("es") and length - 2 >= MIN_STEM:
        return token[:-2]
    if (token.endswith("er") or token.endswith("em")) and length - 2 >= MIN_STEM:
        base = token[:-2]
        if _adjective_base(base):
            return base
    if token.endswith("e") and length - 1 >= MIN_STEM:
        return token[:-1]
    if token.endswith(("eln", "ern")) and length - 1 >= MIN_STEM:
        return _same_noun(token[:-1])
    if token.endswith("s") and length - 1 >= MIN_STEM and token[-2] in S_ENDING:
        return _same_noun(token[:-1])
    return token


def stem_key(token: str) -> str:
    """The stem rule's key: the folded spelling, stemmed."""
    return stem(spelling_key(token))


def _takes_et(rest: str) -> bool:
    """True when German writes -et, not -t, after this verb stem.

    After d or t (meldet, arbeitet), and after m or n that follows another
    consonant (widmet, öffnet, rechnet), but not after l, r, a vowel or a vowel
    plus h (filmt, lernt, wohnt). So "Planet", "Market" and "Internet" give no
    verb key.
    """
    if rest.endswith(("d", "t")):
        return True
    if len(rest) < 3 or rest[-1] not in "mn":
        return False
    before = rest[-2]
    if before in "aeiouylr" or before == rest[-1]:
        return False
    return before != "h" or rest[-3] == "c"


def verb_keys(stemmed: str) -> List[str]:
    """Secondary keys for verb forms of a stem key: kündigt and gekündigt give kundig."""
    keys: List[str] = []
    if not stemmed.isalpha() or not stemmed.endswith("t"):
        return keys
    if stemmed.endswith("et") and len(stemmed) - 2 >= MIN_STEM:
        if _takes_et(stemmed[:-2]):
            keys.append(stemmed[:-2])
    elif len(stemmed) - 1 >= MIN_VERB_STEM:
        keys.append(stemmed[:-1])
    if stemmed.startswith("ge"):
        rest = stemmed[2:]
        rest = rest[:-2] if rest.endswith("et") else rest[:-1]
        if len(rest) >= MIN_STEM and rest not in keys:
            keys.append(rest)
    return keys


# -- irregular forms ---------------------------------------------------------
#
# A closed table, written as tokens arrive: lower case, ä ö ü as a o u, ß as ss.
# Every form of one entry gets the same key. Two tokens with a common key are
# forms of one word for the `irregular` rule (verb form with verb form, degree
# with degree), or a noun of IRREGULAR_NOUNS and a form of its verb for the
# `derived` rule. Nothing outside the table is ever paired, so a missing verb
# only stays unfound. A form in the table can still be another word with the
# same letters; that is why both rules are disclosed heuristics, checked in the
# page text, and why the table leaves out every form listed below.

#: Prefixes after which a participle has no ge- of its own ("bezogen",
#: "entschieden", "verloren"), with the two-part prefixes of IRREGULAR_VERBS
#: whose last part is one of them ("einbezogen", "anerkannt", "vorbehalten").
INSEPARABLE_PREFIXES = frozenset((
    "be", "emp", "ent", "er", "ge", "miss", "ver", "zer", "hinter", "wider", "aner", "beibe", "einbe", "vorbe",
))
#: Prefixes that are separable in one verb and inseparable in another ("umgezogen"
#: and "umgangen", "untergebracht" and "unterbrochen"): both participles are listed.
TWO_WAY_PREFIXES = ("durch", "uber", "um", "unter")
#: Endings of a present stem: infinitive, first, second and third person.
_PRESENT_ENDINGS = ("e", "en", "st", "t", "est", "et")
#: Endings of a participle used as an adjective, and of a comparative.
_ADJECTIVE_ENDINGS = ("", "e", "en", "er", "es", "em")
#: Endings of a superlative. Not -ens: "höchstens", "bestens", "meistens" are adverbs of their own.
_SUPERLATIVE_ENDINGS = ("e", "en", "er", "es", "em")
#: Endings of a derived noun: plural and genitive (the umlaut is already gone: "Umzüge" is "umzuge").
_NOUN_ENDINGS = ("", "e", "en", "n", "s", "es")

#: German strong and mixed verbs: (present stem, present forms with a changed
#: vowel, preterite forms, participle, prefixes). The prefixes name every
#: prefixed verb the entry covers; "0" is the verb without a prefix. The forms
#: themselves come from _verb_forms. A preterite form, a prefix or a whole verb
#: is left out where it is also a common noun or another common word, so the
#: table never takes it for the verb:
#:
#: - preterite "stand" and "standen" (Stand, Zustand, Bestand, Abstand,
#:   Zuständen), "gaben" (Angaben,
#:   Abgaben, Aufgaben), "lagen" (Anlagen, Unterlagen, Vorlagen, Umlagen),
#:   "nahmen" (Ausnahmen, Einnahmen), "sprachen" (Sprachen), "griff"
#:   (Begriff, Zugriff), "band" (Verband), "trug" with be- (Betrug), "boten",
#:   "schienen", "wiesen", "mass" (Maß), "half" (English "half"); no
#:   subjunctive in -e at all (Gabe, Lage, Sprache, Griffe, Stände);
#: - prefixes: tragen without be-, ver-, an-, auf- (Betrag, Vertrag, Antrag,
#:   Auftrag), schlagen only with vor- (Abschlag, Zuschlag, Anschlag),
#:   scheiden without unter- and ver- (Unterschied, verschieden), messen
#:   without an- (angemessen), lassen without an- (Anlässe), laufen without
#:   ver- (Verläufe), wenden only with an-, auf- and ein- (Wende, verwandte),
#:   gelten without ent- (Entgelt, Entgelte), kommen without ab- and ein-
#:   (Abkommen, Einkommen), weisen and gleichen not without a prefix (Weise,
#:   gleich);
#: - the light verbs geben, gelten, liegen, stehen, kommen, halten, lassen and
#:   sehen only with a prefix: "gibt", "gilt", "liegt", "steht", "kommt",
#:   "hält", "lässt" and "sieht" stand in almost any sentence of any page;
#: - gehen and fallen only with a prefix ("geht" stands in almost any
#:   sentence; Fall, Fälle), gehen not with ver- (vergangen) and not with an-
#:   (the idiom "was die Kosten angeht" names no topic); raten and
#:   schießen only with a prefix (Rate, Raten, the verb geraten; Geschossen,
#:   Schoß); schneiden without a preterite and without durch- (Abschnitt,
#:   Durchschnitt, Schnitten, Durchschnitten);
#: - prefixes whose participle or infinitive is another word: greifen without
#:   be- (Begriffen), hängen and klingen without an- (Anhängen, Anklang),
#:   liegen without be-, ver-, um-, über-, hinter- (belegen, verlegen, umlegen,
#:   überlegen, hinterlegen), kennen without be- (bekannt), scheiden without
#:   be- (Bescheide), stehen without um- (unter Umständen), tragen and wachsen
#:   without er- (Erträge, Erwachsene), denken without ver- (Verdacht), nehmen
#:   without unter- (Unternehmen), wiegen without ab- (abgewogen is abwägen),
#:   schaffen only with er- (bare schaffen mostly means "to manage": "das
#:   schafft keiner"; the other prefixed verbs are weak: angeschafft,
#:   beschafft);
#: - verbs: fahren ("führen" is "fuhren" once the umlaut is gone, Fahrt,
#:   Gefahren, Verfahren), bitten ("bitte"), heißen ("heiße" and "heißen" are
#:   also the adjective: "heiße Speicher"), preisen (Preise, Preisen), essen
#:   (Essen), befehlen (Befehle), betrügen ("betrugen" of betragen), lügen
#:   (Lüge), bergen without ver- (Berge), and the light verbs tun, sein, haben,
#:   werden, wissen. Rare verbs (backen, blasen, braten, pfeifen, schleifen,
#:   winden ...) are left out as well.
IRREGULAR_VERBS: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("zieh", "", "zog zogen", "gezogen", "0 ab an auf aus be ein einbe ent heran hinzu nach um ver vor zu zuruck durch er uber unter"),
    ("schliess", "", "schloss schlossen", "geschlossen", "0 ab an auf aus be ein ent er ver zu zusammen"),
    ("geb", "gibt", "gab", "gegeben", "ab an auf aus be bei ein er frei heraus nach uber um ver vor weiter wieder zu zuruck mit statt"),
    ("nehm", "nimmt", "nahm", "genommen", "0 ab an auf aus ein ent mit teil uber vor weg zu zuruck fest hin ver wahr"),
    ("gelt", "gilt", "galt galten", "gegolten", "ab ver"),
    ("lieg", "", "lag", "gelegen", "an bei unter vor"),
    ("steh", "", "", "gestanden", "auf aus be bei ent fest ver zu an ein uber unter wider entgegen gegenuber"),
    ("find", "", "fand fanden", "gefunden", "0 auf be emp heraus statt vor ab ein er wieder"),
    ("bring", "", "brachte brachten", "gebracht", "0 an auf bei ein er mit unter ver vor zuruck hervor uber um zusammen"),
    ("scheid", "", "schied schieden", "geschieden", "0 aus ent"),
    ("komm", "", "kam kamen", "gekommen", "an auf aus be bei hinzu mit nach vor zu zuruck zusammen durch ent heraus entgegen"),
    ("lauf", "", "lief liefen", "gelaufen", "0 ab an aus durch ein um weiter zu auf be hinaus unter"),
    ("halt", "halt haltst", "hielt hielten", "gehalten", "ab an auf aus be beibe bei ein ent er fest uber unter ver vor vorbe zuruck durch"),
    ("lass", "", "liess liessen", "gelassen", "ab auf aus durch ent er frei nach uber unter ver weg zu zuruck be ein hinter los nieder"),
    ("trag", "", "trug trugen", "getragen", "0 bei ein nach uber vor aus"),
    ("tret", "tritt", "trat traten", "getreten", "0 an auf aus bei ein ent uber ver zu zuruck ab be"),
    ("sprech", "spricht", "sprach", "gesprochen", "0 ab an aus be ent mit nach wider zu frei ver"),
    ("brech", "bricht", "brach", "gebrochen", "0 ab auf aus ein unter zusammen an durch ver zer"),
    ("biet", "", "bot", "geboten", "0 an ver"),
    ("schreib", "", "schrieb schrieben", "geschrieben", "0 ab an auf aus be ein gut nach um unter vor zu fest uber ver"),
    ("steig", "", "stieg stiegen", "gestiegen", "0 an auf aus ein um ab be uber"),
    ("sink", "", "sank sanken", "gesunken", "0 ab"),
    ("schieb", "", "schob schoben", "geschoben", "0 auf ver"),
    ("weis", "", "wies", "gewiesen", "ab an aus be hin nach uber zu auf ein er ver vor zuruck"),
    ("mess", "misst", "", "gemessen", "0 ab aus be er nach ver"),
    ("ruf", "", "rief riefen", "gerufen", "0 ab an auf aus ein zuruck wider be hervor"),
    ("schlag", "", "schlug schlugen", "geschlagen", "0 vor"),
    ("verlier", "", "verlor verloren", "verloren", "0"),
    ("beginn", "", "begann begannen", "begonnen", "0"),
    ("gewinn", "", "gewann gewannen", "gewonnen", "0"),
    ("empfehl", "empfiehlt", "empfahl", "empfohlen", "0"),
    ("bind", "", "", "gebunden", "0 an ein ver unter"),
    ("les", "liest", "las lasen", "gelesen", "0 ab aus ein nach vor durch"),
    ("seh", "sieht", "sah sahen", "gesehen", "ab an aus ein nach uber vor zu"),
    ("helf", "hilft", "", "geholfen", "0 weiter"),
    ("werf", "wirft", "warf", "geworfen", "0 ab ein ent vor unter ver"),
    ("treib", "", "trieb trieben", "getrieben", "0 an be ver uber voran"),
    ("schein", "", "schien", "geschienen", "0 er"),
    ("bleib", "", "blieb blieben", "geblieben", "0 uber ver aus zuruck"),
    ("kenn", "", "kannte kannten", "gekannt", "0 an aner er"),
    ("nenn", "", "nannte nannten", "genannt", "0 be er"),
    ("send", "", "sandte sandten", "gesandt", "0 ab ver zu ent"),
    ("wend", "", "wandte wandten", "gewandt", "an auf ein"),
    ("denk", "", "dachte dachten", "gedacht", "0 be nach"),
    ("fang", "", "fing fingen", "gefangen", "0 an emp auf ab ein"),
    ("gleich", "", "glich glichen", "geglichen", "aus ver an be"),
    ("greif", "", "", "gegriffen", "0 ein zu an auf er zuruck"),
    ("wachs", "", "wuchs", "gewachsen", "0 an zu auf"),
    ("meid", "", "mied mieden", "gemieden", "0 ver"),
    ("weich", "", "wich wichen", "gewichen", "ab aus"),
    ("streich", "", "", "gestrichen", "0 durch unter ver"),
    ("werb", "wirbt", "warb", "geworben", "0 be er"),
    ("treff", "trifft", "traf trafen", "getroffen", "0 be ein zu an uber"),
    ("fliess", "", "floss flossen", "geflossen", "0 ab ein zu"),
    ("heb", "", "hob hoben", "gehoben", "0 auf er ab an be hervor"),
    ("lad", "ladt ladst", "lud luden", "geladen", "0 auf ein ent hoch herunter"),
    ("geling", "", "gelang", "gelungen", "0"),
    ("vergess", "vergisst", "vergass", "vergessen", "0"),
    ("flieg", "", "flog flogen", "geflogen", "0 ab an auf aus ein uber ver zuruck"),
    ("flieh", "", "floh flohen", "geflohen", "0 ent"),
    ("frier", "", "fror froren", "gefroren", "0 ein er zu"),
    ("giess", "", "goss gossen", "gegossen", "0 be ver"),
    ("leid", "", "litt litten", "gelitten", "0 er"),
    ("leih", "", "lieh liehen", "geliehen", "0 aus ent ver"),
    ("rat", "rat ratst", "riet rieten", "geraten", "ab an be er ver"),
    ("reiss", "", "riss rissen", "gerissen", "0 ab auf aus ein ent hin mit um zer"),
    ("schaff", "", "schuf schufen", "geschaffen", "er"),
    ("schiess", "", "schoss schossen", "geschossen", "zu vor"),
    ("schlaf", "schlaft", "schlief schliefen", "geschlafen", "0 aus ein ver"),
    ("schmelz", "schmilzt", "schmolz schmolzen", "geschmolzen", "0 ein ver"),
    ("schneid", "", "", "geschnitten", "0 ab an auf aus be ein uber zer zu"),
    ("schrei", "", "schrie schrien", "geschrien", "0 an"),
    ("schweig", "", "schwieg schwiegen", "geschwiegen", "0 ver"),
    ("schwimm", "", "schwamm schwammen", "geschwommen", "0"),
    ("sing", "", "sang sangen", "gesungen", "0"),
    ("sitz", "", "sass sassen", "gesessen", "0 be"),
    ("stech", "sticht", "stach stachen", "gestochen", "0 be"),
    ("stehl", "stiehlt", "stahl stahlen", "gestohlen", "0"),
    ("sterb", "stirbt", "starb starben", "gestorben", "0 ab aus ver"),
    ("stoss", "", "stiess stiessen", "gestossen", "0 ab an auf aus ver vor zu zusammen"),
    ("streit", "", "stritt stritten", "gestritten", "0 ab be"),
    ("trink", "", "trank tranken", "getrunken", "0 aus be er"),
    ("wasch", "", "wusch wuschen", "gewaschen", "0 ab aus"),
    ("wieg", "", "wog wogen", "gewogen", "0 auf uber"),
    ("zwing", "", "zwang zwangen", "gezwungen", "0 auf be er"),
    ("brenn", "", "brannte brannten", "gebrannt", "0 ab an aus durch ver"),
    ("renn", "", "rannte rannten", "gerannt", "0"),
    ("schreit", "", "schritt schritten", "geschritten", "0 be ein fort uber unter voran"),
    ("schwind", "", "schwand schwanden", "geschwunden", "0 ver"),
    ("dring", "", "drang drangen", "gedrungen", "0 ein durch vor"),
    ("ring", "", "rang rangen", "gerungen", "0 er"),
    ("kling", "", "klang klangen", "geklungen", "0 ab aus"),
    ("grab", "grabt grabst", "grub gruben", "gegraben", "0 aus be ein unter ver"),
    ("hang", "", "hing hingen", "gehangen", "0 ab zusammen"),
    ("losch", "lischt", "losch", "geloschen", "er"),
    ("wag", "", "wog wogen", "gewogen", "ab er"),
    ("gescheh", "geschieht", "geschah geschahen", "geschehen", "0"),
    ("missling", "", "misslang", "misslungen", "0"),
    ("derb", "dirbt", "darb darben", "gedorben", "ver"),
    ("berg", "birgt", "barg bargen", "geborgen", "ver"),
    ("gleit", "", "glitt glitten", "geglitten", "0"),
    ("schleich", "", "schlich schlichen", "geschlichen", "0 ein"),
    ("kriech", "", "kroch krochen", "gekrochen", "0"),
    ("riech", "", "roch rochen", "gerochen", "0"),
    ("reib", "", "rieb rieben", "gerieben", "0"),
    ("reit", "", "ritt ritten", "geritten", "0"),
    ("beiss", "", "biss bissen", "gebissen", "0"),
    ("bieg", "", "bog bogen", "gebogen", "0 ab ver"),
    ("gedeih", "", "gedieh gediehen", "gediehen", "0"),
    ("schwor", "", "schwor schworen", "geschworen", "0"),
    ("schwing", "", "schwang schwangen", "geschwungen", "0"),
    ("geh", "", "ging gingen", "gegangen", "ab auf aus be durch ein einher ent er fort hervor hinaus los nach uber um unter vor voran voraus vorbei weg weiter zu zuruck"),
    ("fall", "fallt", "fiel fielen", "gefallen", "an auf aus durch ein ent ver weg zuruck"),
)

#: Nouns that belong to a verb of IRREGULAR_VERBS by a changed vowel or a short
#: stem, with the prefix and present stem of that verb: "Umzug" is a form of
#: "umziehen" for the rule. Pairs whose meanings parted are left out: Anzug,
#: Aufzug and Verzug (Zahlungsverzug) are no forms of anziehen, aufziehen and
#: verziehen, nor Abgabe, Aufgabe, Anspruch, Abschlag, Vertrag, Übersicht,
#: Vorsicht, Ablauf or Verlauf (a procedure, a history) forms of abgeben,
#: aufgeben, ansprechen, abschlagen, vertragen, übersehen, vorsehen, ablaufen
#: or verlaufen; nor Anflug, Ausflug, Einfluss, Überfluss, Überschuss,
#: Ausschuss, Begriff, Abschnitt, Durchschnitt, Vorgang, Ausgang, Zugang,
#: Eingang, Zufall, Einfall, Anfall, Abfall or Ausweis. Schnitt ("im Schnitt")
#: and Schuss (no bare schießen) have no line either, nor Hinweis: a
#: "Hinweis:" label or heading stands on many pages and is no form of
#: hinweisen. A preterite that is a noun as well needs no line here
#: ("Betrieb", "Anstieg", "Eintritt", "Erhalt", "Fortschritt", "Abriss",
#: "Zwang" are listed forms already).
IRREGULAR_NOUNS: Tuple[Tuple[str, str, str], ...] = (
    ("umzug", "um", "zieh"), ("auszug", "aus", "zieh"), ("einzug", "ein", "zieh"), ("abzug", "ab", "zieh"),
    ("bezug", "be", "zieh"), ("entzug", "ent", "zieh"), ("zuzug", "zu", "zieh"),
    ("abschluss", "ab", "schliess"), ("anschluss", "an", "schliess"), ("ausschluss", "aus", "schliess"),
    ("beschluss", "be", "schliess"), ("einschluss", "ein", "schliess"), ("entschluss", "ent", "schliess"),
    ("verschluss", "ver", "schliess"), ("zusammenschluss", "zusammen", "schliess"),
    ("angabe", "an", "geb"), ("ausgabe", "aus", "geb"), ("eingabe", "ein", "geb"), ("vergabe", "ver", "geb"),
    ("ubergabe", "uber", "geb"), ("weitergabe", "weiter", "geb"), ("ruckgabe", "zuruck", "geb"),
    ("freigabe", "frei", "geb"), ("vorgabe", "vor", "geb"),
    ("annahme", "an", "nehm"), ("abnahme", "ab", "nehm"), ("aufnahme", "auf", "nehm"), ("ausnahme", "aus", "nehm"),
    ("einnahme", "ein", "nehm"), ("entnahme", "ent", "nehm"), ("ubernahme", "uber", "nehm"),
    ("zunahme", "zu", "nehm"), ("teilnahme", "teil", "nehm"), ("rucknahme", "zuruck", "nehm"),
    ("angebot", "an", "biet"),
    ("vorschrift", "vor", "schreib"), ("unterschrift", "unter", "schreib"), ("abschrift", "ab", "schreib"),
    ("gutschrift", "gut", "schreib"),
    ("widerspruch", "wider", "sprech"), ("absprache", "ab", "sprech"),
    ("abbruch", "ab", "brech"), ("ausbruch", "aus", "brech"), ("einbruch", "ein", "brech"),
    ("rucktritt", "zuruck", "tret"),
    ("vergleich", "ver", "gleich"), ("ausgleich", "aus", "gleich"),
    ("anfang", "an", "fang"),
    ("anruf", "an", "ruf"), ("abruf", "ab", "ruf"), ("aufruf", "auf", "ruf"), ("widerruf", "wider", "ruf"),
    ("vorschlag", "vor", "schlag"), ("beitrag", "bei", "trag"), ("eintrag", "ein", "trag"),
    ("vortrag", "vor", "trag"), ("nachtrag", "nach", "trag"),
    ("erlass", "er", "lass"), ("nachlass", "nach", "lass"),
    ("beginn", "", "beginn"), ("gewinn", "", "gewinn"), ("verlust", "", "verlier"), ("hilfe", "", "helf"),
    ("entwurf", "ent", "werf"), ("vorwurf", "vor", "werf"), ("einsicht", "ein", "seh"),
    ("entscheid", "ent", "scheid"),
    ("flug", "", "flieg"), ("abflug", "ab", "flieg"), ("ruckflug", "zuruck", "flieg"), ("zuschuss", "zu", "schiess"),
    ("vorschuss", "vor", "schiess"), ("verstoss", "ver", "stoss"), ("ausstoss", "aus", "stoss"), ("anstoss", "an", "stoss"),
    ("zusammenstoss", "zusammen", "stoss"), ("vorstoss", "vor", "stoss"), ("zusammenhang", "zusammen", "hang"), ("umgang", "um", "geh"),
    ("ruckgang", "zuruck", "geh"), ("ubergang", "uber", "geh"), ("ausfall", "aus", "fall"), ("wegfall", "weg", "fall"),
    ("verfall", "ver", "fall"), ("nachweis", "nach", "weis"), ("beweis", "be", "weis"),
    ("verweis", "ver", "weis"), ("angriff", "an", "greif"), ("eingriff", "ein", "greif"), ("zugriff", "zu", "greif"),
    ("ruckgriff", "zuruck", "greif"), ("zusammenbruch", "zusammen", "brech"), ("durchbruch", "durch", "brech"), ("aufschub", "auf", "schieb"),
    ("abfluss", "ab", "fliess"), ("zufluss", "zu", "fliess"),
)

#: German comparison that is more than an ending: (positive forms, comparative
#: stem, superlative stem). The pairing runs one way: "höchste" and "höher"
#: find "hoch", but "hoch" finds neither, because a question asks "Wie hoch
#: ...?" about any amount ("hoch" names no topic, as SCAN_FUNCTION_WORDS says).
#: For the same reason "beste" and "besten" find nothing: "Wie kündige ich am
#: besten?" names no topic either, while "besser" finds "gut" and "beste".
#: English "good" is such a target too (IRREGULAR_TARGETS): "better" and
#: "best" find it, it finds neither. "hohe" and "hohen" are left out: they are
#: also "Höhe" and "Höhen"; so is "guter": it is also "Güter". "hoher" stays a
#: comparative stem ("höher"), although it is also the positive "ein hoher
#: Abschlag": either way it finds "hoch" and "höchste", which is right for both.
#: viel/mehr/meist, nah/näher/nächst and gern/lieber/liebst are left out:
#: "mehr" and "nächste" mostly mean something else ("nicht mehr", "nächstes
#: Jahr"). A comparative or superlative with a plain ending ("länger",
#: "größte") is no irregular form: after normalisation it is the positive with
#: an ending.
IRREGULAR_DEGREES: Tuple[Tuple[str, str, str], ...] = (
    ("hoch hohes hohem", "hoher", "hochst"),
    ("gut gute guten gutes gutem", "besser", "best"),
)

#: English irregular forms, one word per line, every form written out; the
#: first word of a line is its key. The -ing forms are left out (regular, and
#: often nouns: "meeting", "building"), and so is lose/lost: German "löst" and
#: "löse" are "lost" and "lose" once the umlaut is gone. "good better best"
#: pairs one way, like hoch and gut (see IRREGULAR_DEGREES).
IRREGULAR_ENGLISH = """
pay pays paid
make makes made
take takes took taken
give gives gave given
write writes wrote written
send sends sent
buy buys bought
sell sells sold
bring brings brought
choose chooses chose chosen
begin begins began begun
know knows knew known
keep keeps kept
spend spends spent
win wins won
find finds found
show shows showed shown
tell tells told
say says said
speak speaks spoke spoken
withdraw withdraws withdrew withdrawn
understand understands understood
forget forgets forgot forgotten
good better best
"""


#: Forms left out although an entry generates them, because they are common
#: nouns or other words of their own: Messe ("ich messe"), Scheine ("ich
#: scheine"), Werft ("ihr werft"), Schloss ("schloss"), and "geboten", which is
#: also the participle of gebieten ("Eile ist geboten"); "angeboten",
#: "verboten", "schlossen" and "abschloss" stay. Since Stufe 7 also Floh,
#: Stahl, Schritt and Schritten, Rang, Ringe, Sitze, Wäsche, Stöße, Wiege,
#: Wogen, Schwamm, Klinge, Schreie, Schmelze, Hänge, Bogen, Berufe, drängen
#: ("drangen"), Fliege, Gruben, the city of Gießen, GRUB (the boot loader,
#: "grub") and Drang ("drang"). These forms are never forms of the table, but
#: as the finite verb before a clause-final particle the scan still takes them
#: as a split verb, like "schloss ... ab" ("Im nächsten Schritt geben Sie ...
#: ein" gives "schritt ... ein"), a disclosed heuristic. Also left out are
#: "durchgangen" and "untergangen" with their endings: durchgehen and
#: untergehen are only separable, so their participle without ge- is no word,
#: only the folded dative plural "Durchgängen" or "Untergängen".
#:
#: Accepted homographs keep their key, like "Messen": each has the letters of
#: a verb form or a noun of the tables, and leaving it out would lose that
#: form as well. A hit through one is a disclosed heuristic at the weight of
#: its rule and lists the form under `matched` (see "Was offen bleibt"). They
#: are the nouns Fliegen, Schläfen, Hängen, Berufen, Klingen, Ringen, Wiegen
#: and Sitzen; Sass (saß once ß is ss); Singen (the town); besessen
#: (obsessed); eingestanden (of einstehen and of eingestehen); belief (of
#: belaufen, and English "belief"); Riss and gerissen (a crack; cunning);
#: ausgefallen in the sense "unusual" for Ausfall; Zugriff, a generic word in
#: IT texts, for zugreifen; and the idioms "eingehen auf" and "zurückgehen
#: auf" for eingehen and zurückgehen.
IRREGULAR_EXCLUDED = frozenset((
    "messe", "scheine", "werft", "schloss", "geboten", "gebotene", "gebotenen", "gebotener", "gebotenes", "gebotenem",
    "floh", "stahl", "schritt", "schritten", "rang", "ringe", "sitze", "wasche", "stosse", "wiege",
    "wogen", "schwamm", "klinge", "schreie", "schmelze", "hange", "bogen", "berufe", "drangen", "fliege",
    "gruben", "giessen", "grub", "drang",
    "durchgangen", "durchgangene", "durchgangenen", "durchgangener", "durchgangenes", "durchgangenem",
    "untergangen", "untergangene", "untergangenen", "untergangener", "untergangenes", "untergangenem",
))
#: The two parts of the composite prefixes, for their zu-infinitive
#: ("anzuerkennen", "beizubehalten", "einzubeziehen", "vorzubehalten").
_COMPOSITE_PREFIXES = {"aner": ("an", "er"), "beibe": ("bei", "be"), "einbe": ("ein", "be"), "vorbe": ("vor", "be")}


def _present_endings(present: str, separable: bool) -> List[str]:
    """The endings of _PRESENT_ENDINGS that German writes after `present`."""
    return [
        ending for ending in _PRESENT_ENDINGS
        if not (separable and ending == "e")
        and not (ending in ("t", "st") and present.endswith(("t", "d")))
        and not (ending == "st" and present.endswith(("s", "z", "x")))
    ]


def _verb_forms(present: str, changed: str, preterite: str, participle: str, prefix: str) -> List[str]:
    """Every form of one prefixed verb of IRREGULAR_VERBS ("" for the bare verb).

    A separable verb gets no first person in -e: written joined it is rare
    ("dass ich ablaufe") and mostly a plural noun (Abläufe, Beiträge, Anrufe).
    No -t or -st follows a stem in t or d, and no -st one in s, z or x: German
    writes "findet", "bietest", "schließt", "sitzt" ("haltt", "findst",
    "schliessst", "sitzst" are no words); a changed vowel that folds onto the stem ("hält", "hältst",
    "lädt") is listed with the changed forms. No form is shorter than MIN_PART
    letters ("lag", "kam", "bot" are also abbreviations and names).
    """
    separable = bool(prefix) and prefix not in INSEPARABLE_PREFIXES and prefix not in TWO_WAY_PREFIXES
    forms = [prefix + present + ending for ending in _present_endings(present, separable)]
    forms.extend(prefix + form for form in changed.split())
    forms.extend(prefix + form for form in preterite.split())
    inseparable = prefix in INSEPARABLE_PREFIXES
    participles: List[str] = []
    if not prefix or not inseparable:
        participles.append(prefix + participle)
    if prefix and (inseparable or prefix in TWO_WAY_PREFIXES) and participle.startswith("ge"):
        participles.append(prefix + participle[2:])
    if prefix and not inseparable:
        forms.append(prefix + "zu" + present + "en")
    if prefix in _COMPOSITE_PREFIXES:
        first, second = _COMPOSITE_PREFIXES[prefix]
        forms.append(first + "zu" + second + present + "en")
    forms.extend(form + ending for form in participles for ending in _ADJECTIVE_ENDINGS)
    return [form for form in forms if len(form) >= MIN_PART and form not in IRREGULAR_EXCLUDED]


def _all_verb_forms() -> Iterable[Tuple[str, str]]:
    """(form, key) for every form of every prefixed verb of IRREGULAR_VERBS."""
    for present, changed, preterite, participle, prefixes in IRREGULAR_VERBS:
        for prefix in prefixes.split():
            prefix = "" if prefix == "0" else prefix
            for form in _verb_forms(present, changed, preterite, participle, prefix):
                yield form, prefix + "|" + present


#: (form, key) for every form of every prefixed verb of IRREGULAR_VERBS, built once for the two tables below.
_VERB_FORMS: Tuple[Tuple[str, str], ...] = tuple(_all_verb_forms())


def _irregular_table() -> Dict[str, Tuple[str, ...]]:
    """Every form of the irregular tables with the keys of the words it is a form of."""
    keys: Dict[str, set] = {}

    def add(form: str, key: str) -> None:
        keys.setdefault(form, set()).add(key)

    for form, key in _VERB_FORMS:
        add(form, key)
    for noun, prefix, present in IRREGULAR_NOUNS:
        for ending in _NOUN_ENDINGS:
            add(noun + ending, prefix + "|" + present)
    for positive, comparative, superlative in IRREGULAR_DEGREES:
        key = "=" + positive.split()[0]
        for form in positive.split():
            add(form, key)
        for ending in _ADJECTIVE_ENDINGS:
            add(comparative + ending, key)
        for ending in _SUPERLATIVE_ENDINGS:
            add(superlative + ending, key)
    for line in IRREGULAR_ENGLISH.strip().splitlines():
        words = line.split()
        for form in words:
            add(form, "en:" + words[0])
    return {form: tuple(sorted(found)) for form, found in sorted(keys.items())}


#: Every form of the irregular tables (folded spelling) with the keys of its words.
IRREGULAR_FORMS: Dict[str, Tuple[str, ...]] = _irregular_table()
#: Every form of IRREGULAR_NOUNS that is no verb form as well ("Entscheiden" is the verb):
#: a noun and a verb form with a common key pair under the `derived` rule.
IRREGULAR_NOUN_FORMS = frozenset(
    noun + ending for noun, _, _ in IRREGULAR_NOUNS for ending in _NOUN_ENDINGS
) - frozenset(form for form, _ in _VERB_FORMS)
#: The positive forms of IRREGULAR_DEGREES and English "good": found by their comparative and superlative, finding
#: neither; and the superlative of "gut" ("am besten" names no topic), found by "besser" and finding nothing.
IRREGULAR_TARGETS = (
    frozenset(form for positive, _, _ in IRREGULAR_DEGREES for form in positive.split())
    | {"good"}
    | {"best" + ending for ending in _SUPERLATIVE_ENDINGS}
)


def irregular_keys(spelling: str) -> Tuple[str, ...]:
    """The keys of the words a folded spelling is a form of by the irregular tables; empty outside them."""
    return IRREGULAR_FORMS.get(spelling, ())


def _forms_by_key(forms: Mapping[str, Tuple[str, ...]]) -> Dict[str, Tuple[str, ...]]:
    by_key: Dict[str, List[str]] = {}
    for form, keys in forms.items():
        for key in keys:
            by_key.setdefault(key, []).append(form)
    return {key: tuple(found) for key, found in sorted(by_key.items())}


#: Every key of the irregular tables with its forms.
IRREGULAR_BY_KEY: Dict[str, Tuple[str, ...]] = _forms_by_key(IRREGULAR_FORMS)


def irregular_variants(spelling: str) -> frozenset:
    """Every form of the irregular tables that shares a key with a folded spelling, the spelling included (pure)."""
    return frozenset(form for key in irregular_keys(spelling) for form in IRREGULAR_BY_KEY[key])


def edit_distance(left: str, right: str, limit: int) -> int:
    """Optimal string alignment distance (insert, delete, substitute, swap neighbours), capped at limit + 1."""
    if left == right:
        return 0
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    before_previous: List[int] = []
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row] + [0] * len(right)
        best = row
        for column, right_character in enumerate(right, 1):
            cost = 0 if left_character == right_character else 1
            value = min(previous[column] + 1, current[column - 1] + 1, previous[column - 1] + cost)
            if row > 1 and column > 1 and left_character == right[column - 2] and left[row - 2] == right_character:
                value = min(value, before_previous[column - 2] + 1)
            current[column] = value
            best = min(best, value)
        if best > limit:
            return limit + 1
        before_previous, previous = previous, current
    return min(previous[-1], limit + 1)


#: One member of a term's group: (token, rule, weight).
Member = Tuple[str, str, float]


class Resolver:
    """Resolve query terms against the vocabulary of one search.

    `vocabulary` maps every token of the searched files to the number of files
    that hold it. `closed` holds the closed-class words; `not_parts` the words
    that may not serve as a compound part (the stopwords). With `heuristics`
    false the resolver only finds word forms and skips the compound and typo
    indexes. Nothing is cached on disk; a resolver lives for one search.
    """

    def __init__(
        self,
        vocabulary: Mapping[str, int],
        closed: Iterable[str] = (),
        not_parts: Iterable[str] = (),
        heuristics: bool = True,
    ) -> None:
        self.vocabulary = vocabulary
        self.closed = frozenset(closed)
        excluded = frozenset(not_parts)
        self.by_spelling: Dict[str, List[str]] = {}
        self.by_stem: Dict[str, List[str]] = {}
        self.by_verb: Dict[str, List[str]] = {}
        self.by_irregular: Dict[str, List[str]] = {}
        #: Valid compound parts (folded spelling and stem of every word) with their file count.
        self.words: Dict[str, int] = {}
        #: Alphabetic content words with their stem key, for the compound and typo rules.
        self.alpha: List[Tuple[str, str, str]] = []
        for token in sorted(vocabulary):
            spelling = spelling_key(token)
            key = stem(spelling)
            compound_rules = heuristics and token.isalpha() and len(token) <= MAX_COMPOUND
            if compound_rules and len(token) >= MIN_PART and token not in excluded:
                # A closed-class word may still glue a compound together
                # (Gegen|leistung); it is never a match of its own.
                frequency = vocabulary[token]
                for part in (spelling, key):
                    if len(part) >= MIN_PART and frequency > self.words.get(part, 0):
                        self.words[part] = frequency
            if token in self.closed:
                # "seit" is not a form of "Seite", "wer" is no part of "werden".
                continue
            self.by_spelling.setdefault(spelling, []).append(token)
            self.by_stem.setdefault(key, []).append(token)
            for verb_key in verb_keys(key):
                self.by_verb.setdefault(verb_key, []).append(token)
            for irregular_key in irregular_keys(spelling):
                self.by_irregular.setdefault(irregular_key, []).append(token)
            if compound_rules:
                self.alpha.append((token, key, spelling))

    # -- the same word -----------------------------------------------------

    def word_forms(self, term: str) -> Dict[str, Tuple[str, float]]:
        """Tokens of the vocabulary that are the same word as `term`: exact, fold, stem, verb.

        A -t form of the corpus is taken as a verb form of `term` only when the
        term itself can be a verb (infinitive in -n, or a bare stem): "ändert"
        is a form of "ändern", not of "andere" or "anders".
        """
        members: Dict[str, Tuple[str, float]] = {}
        if term in self.vocabulary:
            members[term] = ("exact", WEIGHTS["exact"])
        if term in self.closed:
            return members
        spelling = spelling_key(term)
        key = stem(spelling)
        for token in self.by_spelling.get(spelling, ()):
            _add(members, token, "fold")
        for token in self.by_stem.get(key, ()):
            _add(members, token, "stem")
        if key.isalpha():
            if spelling.endswith("n") or spelling == key:
                for token in self.by_verb.get(key, ()):
                    _add(members, token, "verb")
            for verb_key in verb_keys(key):
                for token in self.by_stem.get(verb_key, ()):
                    _add(members, token, "verb")
                for token in self.by_verb.get(verb_key, ()):
                    _add(members, token, "verb")
        return members

    def irregular(self, term: str) -> Dict[str, Tuple[str, float]]:
        """Tokens that share a key of the irregular tables with `term` on the same side: verb with verb, degree with degree."""
        members: Dict[str, Tuple[str, float]] = {}
        spelling = spelling_key(term)
        if spelling in IRREGULAR_TARGETS:
            return members
        noun = spelling in IRREGULAR_NOUN_FORMS
        for irregular_key in irregular_keys(spelling):
            for token in self.by_irregular.get(irregular_key, ()):
                if (spelling_key(token) in IRREGULAR_NOUN_FORMS) == noun:
                    _add(members, token, "irregular")
        return members

    def derived(self, term: str) -> Dict[str, Tuple[str, float]]:
        """Tokens that are a derived noun of the verb `term` is a form of, or a form of the verb of the noun `term`."""
        members: Dict[str, Tuple[str, float]] = {}
        spelling = spelling_key(term)
        noun = spelling in IRREGULAR_NOUN_FORMS
        for irregular_key in irregular_keys(spelling):
            for token in self.by_irregular.get(irregular_key, ()):
                if (spelling_key(token) in IRREGULAR_NOUN_FORMS) != noun:
                    _add(members, token, "derived")
        return members

    # -- compounds ---------------------------------------------------------

    def _is_word(self, segment: str) -> bool:
        return len(segment) >= MIN_PART and segment in self.words

    def _sequence(self, text: str, memo: Dict[str, bool]) -> bool:
        """True when `text` is one or more words of the vocabulary joined by linking elements."""
        known = memo.get(text)
        if known is not None:
            return known
        result = self._is_word(text)
        if not result:
            for cut in range(MIN_PART, len(text) - MIN_PART + 1):
                if not self._is_word(text[:cut]):
                    continue
                for link in LINKS:
                    if text.startswith(link, cut) and len(text) - cut - len(link) >= MIN_PART:
                        if self._sequence(text[cut + len(link):], memo):
                            result = True
                            break
                if result:
                    break
        memo[text] = result
        return result

    def _rest_before(self, before: str, memo: Dict[str, bool]) -> bool:
        return not before or any(
            before.endswith(link) and self._sequence(before[: len(before) - len(link)], memo) for link in LINKS
        )

    def _rest_after(self, after: str, memo: Dict[str, bool]) -> bool:
        return not after or any(after.startswith(link) and self._sequence(after[len(link):], memo) for link in LINKS)

    def part_position(self, compound: str, key: str) -> str:
        """Where `key` is a part of `compound` ("head", "modifier" or "").

        Every other part must itself be a word of the vocabulary, joined by a
        linking element. Head wins when the key is found in both positions.
        """
        if len(key) < MIN_PART or len(compound) < len(key) + MIN_PART:
            return ""
        memo: Dict[str, bool] = {}
        found = ""
        start = compound.find(key)
        while start != -1:
            before = compound[:start]
            after = compound[start + len(key):]
            if (before or after) and self._rest_before(before, memo) and self._rest_after(after, memo):
                if not after:
                    return "head"
                found = "modifier"
            start = compound.find(key, start + 1)
        return found

    def compounds(self, term: str, exclude: Optional[Mapping[str, object]] = None) -> Dict[str, Tuple[str, float]]:
        """Corpus words that hold `term` as their head or as a modifier (tokens in `exclude` skipped)."""
        members: Dict[str, Tuple[str, float]] = {}
        exclude = exclude or {}
        if not term.isalpha() or term in self.closed:
            return members
        key = stem(spelling_key(term))
        if len(key) < MIN_PART:
            return members
        for token, token_key, _spelling in self.alpha:
            if token in exclude or len(token_key) < len(key) + MIN_PART or key not in token_key:
                continue
            position = self.part_position(token_key, key)
            if position == "head":
                _add(members, token, "compound_head")
            elif position == "modifier":
                _add(members, token, "compound_modifier")
        return members

    def link_variants(self, term: str) -> Dict[str, Tuple[str, float]]:
        """Corpus words made of the parts of `term` with another linking element between two of them.

        The query word must split there into words of the vocabulary on both
        sides; only the linking element changes ("", s, es, n, en, e). The
        variant is looked up in its exact spelling, uninflected or with the
        query word's own ending, never by its stem (a stem cut would make
        "Hauptachse" into "Hauptsache"). So "Abschlagzahlung" finds
        "Abschlagszahlung", "Abschlagzahlungen" finds "Abschlagszahlungen",
        "Kirchenturm" finds "Kirchturm", but "Abschlagzahlung" never finds
        "Abschlagszahlungen", and a word is never cut where its parts are not
        words of the searched files.
        """
        members: Dict[str, Tuple[str, float]] = {}
        if not term.isalpha() or term in self.closed:
            return members
        spelling = spelling_key(term)
        key = stem(spelling)
        if len(key) > MAX_COMPOUND:
            return members
        endings = ("", spelling[len(key):]) if spelling != key and spelling.startswith(key) else ("",)
        memo: Dict[str, bool] = {}
        for cut in range(MIN_PART, len(key) - MIN_PART + 1):
            before = key[:cut]
            if not self._sequence(before, memo):
                continue
            for link in LINKS:
                after = key[cut + len(link):]
                if not key.startswith(link, cut) or len(after) < MIN_PART or not self._sequence(after, memo):
                    continue
                for other in LINKS:
                    if other == link:
                        continue
                    variant = before + other + after
                    for ending in endings:
                        for token in self.by_spelling.get(variant + ending, ()):
                            _add(members, token, "compound_link")
        return members

    def query_head(self, term: str) -> str:
        """The head of a query word that splits into words of the vocabulary, or "".

        Only the head is matched: a free split would let a modifier such as "gas"
        in "Gastarif" match on its own. The longest head whose remainder is a
        sequence of vocabulary words wins.
        """
        if not term.isalpha() or term in self.closed:
            return ""
        key = stem(spelling_key(term))
        if len(key) > MAX_COMPOUND:
            return ""
        memo: Dict[str, bool] = {}
        for cut in range(MIN_PART, len(key) - MIN_PART + 1):
            head = key[cut:]
            if head not in self.closed and self._is_word(head) and self._rest_before(key[:cut], memo):
                return head
        return ""

    # -- typos ---------------------------------------------------------------

    def typos(self, term: str) -> Dict[str, Tuple[str, float]]:
        """Content words one edit away from a long query word."""
        members: Dict[str, Tuple[str, float]] = {}
        if not term.isalpha() or term in self.closed:
            return members
        probe = spelling_key(term)
        if len(probe) < MIN_TYPO_LENGTH:
            return members
        for token, _key, spelling in self.alpha:
            if abs(len(spelling) - len(probe)) > 1:
                continue
            if edit_distance(probe, spelling, 1) <= 1:
                _add(members, token, "typo")
        return members

    # -- resolution ----------------------------------------------------------

    def resolve(self, term: str, heuristics: bool = True, typos: bool = True) -> List[Member]:
        """Every vocabulary token that counts for `term`, sorted by weight, then token.

        Word forms first. Only when `heuristics` is set (query words, not concept
        expansions) irregular forms, derived nouns and compound parts follow,
        and for a query word without a word form its link variants; a query
        word that still matches nothing, or only link variants, may then match
        the head of its split (beside the variants, so a wrong variant never
        hides the head); and a long query word that still matches nothing may
        match a word one edit away. Link variants and typo corrections are both
        skipped when `typos` is false (the search core clears it for a word
        that exists in a layer it did not search: a word that exists is no typo,
        and no other spelling of it either).
        """
        members = self.word_forms(term)
        if heuristics and term not in self.closed:
            forms = bool(members)
            for token, value in self.irregular(term).items():
                members.setdefault(token, value)
            for token, value in self.derived(term).items():
                members.setdefault(token, value)
            for token, value in self.compounds(term, members).items():
                members.setdefault(token, value)
            if not forms and typos:
                for token, value in self.link_variants(term).items():
                    members.setdefault(token, value)
            if all(rule == "compound_link" for rule, _ in members.values()):
                head = self.query_head(term)
                if head:
                    for token in self.word_forms(head):
                        _add(members, token, "query_part")
            if not members and typos:
                members.update(self.typos(term))
        return sorted(((token, rule, weight) for token, (rule, weight) in members.items()), key=_member_order)


def _add(members: Dict[str, Tuple[str, float]], token: str, rule: str) -> None:
    weight = WEIGHTS[rule]
    current = members.get(token)
    if current is None or weight > current[1]:
        members[token] = (rule, weight)


def _member_order(member: Member) -> Tuple[float, str]:
    return (-member[2], member[0])


def same_word(left: str, right: str, closed: Iterable[str]) -> bool:
    """True when two normalised tokens are the same word by spelling or inflection.

    Closed-class words (`closed`) are only the same word as themselves. Used
    to match confirmed concept terms against a query, where compound parts
    and typo corrections never apply.
    """
    if left == right:
        return True
    if left in closed or right in closed:
        return False
    left_spelling, right_spelling = spelling_key(left), spelling_key(right)
    return left_spelling == right_spelling or stem(left_spelling) == stem(right_spelling)
