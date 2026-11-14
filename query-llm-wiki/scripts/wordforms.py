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
- compound_head, compound_modifier: a corpus word in which the term is the last
  part (head) or an earlier part (modifier), accepted only when every other
  part is itself a word of the searched files.
- query_part: the head of a query word that occurs nowhere, when the query word
  splits into words of the searched files.
- typo: a corpus word one edit away from a long query word that matches nothing
  by any other rule.

The first four are word forms: they are the same word. Compound parts and typo
corrections are disclosed heuristics. They never set a term's rarity while a
word form of it occurs anywhere (the search core then counts the rarity from
the word forms), and their weight is applied after BM25 saturation (see bm25).
Compound rules consider no token longer than MAX_COMPOUND letters, so an
endless run of letters cannot make a search slow or deep.

Before tokens exist, `repair_text` joins words that the layout split: soft
hyphens, zero-width characters and hyphens at a line break.

Closed-class words (articles, pronouns, prepositions, conjunctions, auxiliary
and modal verbs, question words, negation) match only literally. They are never
stemmed, split, corrected, or taken as a form of a content word.

Nothing here reads or writes a file. All results are sorted, so they do not
depend on set or dict order or on PYTHONHASHSEED.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


#: Weight of each rule. The literal token is 1.0 and every other rule is
#: strictly below it, so on otherwise equal pages the literal match ranks first.
WEIGHTS: Dict[str, float] = {
    "exact": 1.0,
    "fold": 0.9,
    "stem": 0.6,
    "verb": 0.5,
    "compound_head": 0.45,
    "compound_modifier": 0.35,
    "query_part": 0.35,
    "typo": 0.3,
}

#: Rules that find the same word. Only these set a term's rarity.
WORD_FORM_RULES = frozenset({"exact", "fold", "stem", "verb"})

#: Rules that are heuristics. They never set a term's rarity while a word form
#: exists; on a page they add below the word forms (see bm25.group_base_score).
HEURISTIC_RULES = frozenset({"compound_head", "compound_modifier", "query_part", "typo"})

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
#: Hyphen characters other than the ASCII hyphen-minus.
_HYPHENS = {ord("‐"): "-", ord("‑"): "-"}
#: A hyphen at a line end before a letter. It breaks a word when a letter
#: precedes it too (checked in `_join_line_break`; a pattern that starts with
#: the hyphen itself scans long texts much faster than one with a lookbehind).
_LINE_BREAK = re.compile(r"-[ \t]*\r?\n[ \t]*(?=[^\W\d_])")
#: Words after a line-end hyphen that show a suspended compound ("Netz- und Messentgelte").
_SUSPENDED = re.compile(r"(?:und|oder|bzw|sowie|bis|and|or)\b", re.IGNORECASE)

#: Closed word classes, written as people write them; `closed_class` normalises them.
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


def closed_class(normalise) -> frozenset:
    """The closed-class words, normalised with the caller's token normaliser."""
    return frozenset(normalise(word) for word in (CLOSED_CLASS_DE + CLOSED_CLASS_EN).split())


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


def repair_text(text: str) -> str:
    """Undo layout artefacts that split a word: soft hyphens, zero-width characters, line-break hyphens.

    Never drops a letter. Text without such artefacts comes back unchanged.
    """
    if any(character in text for character in "­​‌‍⁠﻿"):
        text = text.translate(_INVISIBLE)
    if "‐" in text or "‑" in text:
        text = text.translate(_HYPHENS)
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
        expansions) compound parts follow; a query word that occurs nowhere may
        then match the head of its split; and a long query word that still
        matches nothing may match a word one edit away, unless `typos` is false
        (the search core clears it for a word that exists in a layer it did not
        search: a word that exists is no typo).
        """
        members = self.word_forms(term)
        if heuristics and term not in self.closed:
            for token, value in self.compounds(term, members).items():
                members.setdefault(token, value)
            if not members:
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


def same_word(left: str, right: str, closed: Optional[Iterable[str]] = None) -> bool:
    """True when two normalised tokens are the same word by spelling or inflection.

    Closed-class words are only the same word as themselves. Used to match
    confirmed concept terms against a query, where compound parts and typo
    corrections never apply.
    """
    if left == right:
        return True
    if closed is not None and (left in closed or right in closed):
        return False
    left_spelling, right_spelling = spelling_key(left), spelling_key(right)
    return left_spelling == right_spelling or stem(left_spelling) == stem(right_spelling)
