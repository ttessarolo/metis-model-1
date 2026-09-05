"""Deterministic natural-language surface for Brain output cardinality.

The same parsed object is used first by semantic retrieval (to remove only
validated output-language residue) and then by orchestration (to authorize the
exact Metis ``take`` surface).  This prevents two independent parsers from
silently disagreeing about total count and pagination.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

_EXPLICIT_COUNT_RE = re.compile(
    r"(?<!\w)([1-9][0-9]{0,3})\s+(?:risultat[io]|contenut[io]|element[io]|film|video)(?!\w)",
    re.IGNORECASE,
)
_PAGE_COUNT_RE = re.compile(
    r"(?:(?<!\w)([1-9][0-9]{0,3})\s+"
    r"(?:risultat[io]|element[io]|contenut[io]|film|video)?\s*per\s+pagina(?!\w)|"
    r"(?<!\w)pagina\s+(?:da|di|con)\s+([1-9][0-9]{0,3})(?!\w))",
    re.IGNORECASE,
)
_COUNT_COMMAND_RE = re.compile(
    r"(?<!\w)(?:porta|imposta|fissa)\s+(?:il\s+)?(?:numero|totale)\s+"
    r"(?:di|dei|degli|delle)?\s*(?:risultat[io]|contenut[io]|element[io]|film|video)\s+"
    r"(?:a|su)\s+([1-9][0-9]{0,3})(?!\w)",
    re.IGNORECASE,
)
_DSL_COUNT_RE = re.compile(
    r"(?<!\w)take\s+([1-9][0-9]{0,3})\s+from(?!\w)",
    re.IGNORECASE,
)
_AMBIGUOUS_COUNT_RE = re.compile(
    r"(?<!\w)(?:alcuni|alcune|qualche|pochi|poche|molti|molte|tanti|tante)\s+"
    r"(?:risultat[io]|contenut[io]|element[io]|film|video)(?!\w)",
    re.IGNORECASE,
)
_PAGINATION_RE = re.compile(
    r"(?<!\w)(?:paginat[aoei]|paginazione|per\s+pagina)(?!\w)",
    re.IGNORECASE,
)
_SEMANTIC_COUNT_NOUN_RE = re.compile(r"(?<!\w)(film|video)(?!\w)", re.IGNORECASE)
_NON_EXACT_PREFIX_RE = re.compile(
    r"(?:^|[^\w])(?:"
    r"non\s+(?:voglio|avere|restituire|usare|usa|mettere|inserire|impostare|"
    r"oltre|esattamente|pi[uù](?:\s+di)?|"
    r"superiore\s+a|inferiore\s+a)|"
    r"non|senza|al\s+massimo|massimo|minimo|fino\s+a|almeno|circa|"
    r"all['’]incirca|approssimativamente|indicativamente|orientativamente|"
    r"pi[uù]\s+o\s+meno|intorno\s+(?:a|ai|alle)|oltre|entro|"
    r"(?:sopra|sotto)(?:\s+(?:a|i|le|gli))?|a\s+partire\s+da|"
    r"pi[uù]\s+di|meno\s+di|"
    r"(?:porta|imposta|fissa)\s+(?:il\s+)?limite(?:\s+massimo)?(?:\s+(?:di|a))?"
    r")\s*$",
    re.IGNORECASE,
)
_NON_EXACT_SUFFIX_RE = re.compile(
    r"^\s*(?:al\s+massimo|massimo|minimo|o\s+meno|o\s+pi[uù]|circa|"
    r"almeno|non\s+oltre|non\s+pi[uù](?:\s+di)?|pi[uù]\s+o\s+meno)(?!\w)",
    re.IGNORECASE,
)
_RANGE_QUALIFIER = (
    r"(?:(?:circa|almeno|massimo|minimo|oltre|entro|approssimativamente|"
    r"indicativamente|pi[uù]\s+o\s+meno)\s+)?"
)
_RANGE_HAS_QUALIFIER_RE = re.compile(
    r"(?<!\w)(?:circa|almeno|massimo|minimo|oltre|entro|approssimativamente|"
    r"indicativamente|pi[uù]\s+o\s+meno)(?!\w)",
    re.IGNORECASE,
)
_RANGE_NOUN = r"(?:risultat[io]|contenut[io]|element[io]|film|video)"
_RANGE_OR_ALTERNATIVE_RE = re.compile(
    rf"(?<!\w)(?:"
    rf"(?:tra|fra)\s+{_RANGE_QUALIFIER}([1-9][0-9]{{0,3}})\s+e\s+"
    rf"{_RANGE_QUALIFIER}([1-9][0-9]{{0,3}})|"
    rf"da\s+{_RANGE_QUALIFIER}([1-9][0-9]{{0,3}})\s+a\s+"
    rf"{_RANGE_QUALIFIER}([1-9][0-9]{{0,3}})|"
    rf"{_RANGE_QUALIFIER}([1-9][0-9]{{0,3}})\s*"
    rf"(?:o|oppure|/|[-\u2010-\u2015])\s*{_RANGE_QUALIFIER}"
    rf"([1-9][0-9]{{0,3}})"
    rf")(?:(?P<page>(?:\s+{_RANGE_NOUN})?\s+per\s+pagina)|\s+{_RANGE_NOUN})(?!\w)",
    re.IGNORECASE,
)
_NUMERIC_PAGINATION_CANDIDATE_RE = re.compile(
    r"(?:(?<!\w)[0-9]+\s+(?:risultat[io]|element[io]|contenut[io]|film|video)?\s*"
    r"per\s+pagina(?!\w)|(?<!\w)pagina\s+(?:(?:da|di|con)\s+)?[0-9]+(?!\w))",
    re.IGNORECASE,
)
# Treat typographic signs like their ASCII equivalents.  They must never be
# allowed to fall through to the bare ``pagina`` path, which would silently
# replace an invalid requested size with the tenant default.
_INVALID_NUMERIC_TOKEN = (
    r"(?:[+\-\u2010\u2011\u2012\u2013\u2014\u2015\u207b\u208b\ufe63\uff0d\u2212\uff0b]\s*[0-9]+|"
    r"[.,][0-9]+|[0-9]+[.,][0-9]+)"
)
_INVALID_NUMERIC_OUTPUT_RE = re.compile(
    rf"(?:(?<!\w){_INVALID_NUMERIC_TOKEN}\s+"
    r"(?:risultat[io]|contenut[io]|element[io]|film|video)(?:\s+per\s+pagina)?(?!\w)|"
    rf"(?<!\w){_INVALID_NUMERIC_TOKEN}\s+per\s+pagina(?!\w)|"
    rf"(?<!\w)pagina\s+(?:(?:da|di|con)\s+)?{_INVALID_NUMERIC_TOKEN}(?!\w)|"
    r"(?<!\w)(?:porta|imposta|fissa)\s+(?:il\s+)?(?:numero|totale|limite)\s+"
    r"(?:di|dei|degli|delle)?\s*(?:risultat[io]|contenut[io]|element[io]|film|video)\s+"
    rf"(?:a|su)\s+{_INVALID_NUMERIC_TOKEN}(?!\w))",
    re.IGNORECASE,
)
_INVALID_DSL_COUNT_RE = re.compile(
    rf"(?<!\w)take\s+(?:0[0-9]*|[1-9][0-9]{{4,}}|{_INVALID_NUMERIC_TOKEN})\s+from(?!\w)",
    re.IGNORECASE,
)
_OUTPUT_AFTER_NUMBER_RE = re.compile(
    r"(?:\s+(?:risultat[io]|contenut[io]|element[io]|film|video)"
    r"(?:\s+per\s+pagina)?(?!\w)|\s+per\s+pagina(?!\w))",
    re.IGNORECASE,
)
_PAGE_BEFORE_SIGN_RE = re.compile(
    r"(?<!\w)pagina\s+(?:(?:da|di|con)\s+)?$",
    re.IGNORECASE,
)
_COUNT_COMMAND_BEFORE_SIGN_RE = re.compile(
    r"(?<!\w)(?:porta|imposta|fissa)\s+(?:il\s+)?(?:numero|totale)\s+"
    r"(?:di|dei|degli|delle)?\s*(?:risultat[io]|contenut[io]|element[io]|film|video)\s+"
    r"(?:a|su)\s+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OutputMention:
    """One exact total or page-size contract present in operator prose."""

    mode: str
    value: int
    start: int
    end: int


@dataclass(frozen=True)
class OutputRequestSurface:
    """Shared retrieval/orchestration interpretation of one instruction."""

    instruction: str
    semantic_instruction: str
    mentions: tuple[OutputMention, ...]
    generic_pagination: bool
    ambiguous_count: bool
    invalid_numeric_pagination: bool
    invalid_numeric_output: bool

    @property
    def contracts(self) -> tuple[tuple[str, int], ...]:
        result: list[tuple[str, int]] = []
        for mention in self.mentions:
            contract = (mention.mode, mention.value)
            if contract not in result:
                result.append(contract)
        return tuple(result)


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < other_end and other_start < end for other_start, other_end in spans)


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    """Return straight/smart quoted regions; an unterminated quote owns the tail."""

    pairs = {'"': '"', "“": "”", "«": "»", "‘": "’", "‹": "›"}
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] == "`":
            run_end = index + 1
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            marker = text[index:run_end]
            closing_index = text.find(marker, run_end)
            end = len(text) if closing_index < 0 else closing_index + len(marker)
            spans.append((index, end))
            index = end
            continue
        if text[index] == "'":
            previous_is_word = index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_")
            next_is_word = index + 1 < len(text) and (
                text[index + 1].isalnum() or text[index + 1] == "_"
            )
            if previous_is_word and next_is_word:
                index += 1
                continue
            closing_index = index + 1
            while closing_index < len(text):
                if text[closing_index] == "\\":
                    closing_index = min(len(text), closing_index + 2)
                    continue
                if text[closing_index] == "'":
                    before_is_word = closing_index > 0 and (
                        text[closing_index - 1].isalnum() or text[closing_index - 1] == "_"
                    )
                    after_is_word = closing_index + 1 < len(text) and (
                        text[closing_index + 1].isalnum() or text[closing_index + 1] == "_"
                    )
                    if not (before_is_word and after_is_word):
                        spans.append((index, closing_index + 1))
                        index = closing_index + 1
                        break
                closing_index += 1
            else:
                index += 1
            continue
        closing = pairs.get(text[index])
        if closing is None:
            index += 1
            continue
        start = index
        index += 1
        while index < len(text):
            if text[index] == "\\" and closing == '"':
                index = min(len(text), index + 2)
                continue
            if text[index] == closing:
                index += 1
                break
            index += 1
        spans.append((start, index))
    return spans


def _semantic_noun(text: str) -> str | None:
    match = _SEMANTIC_COUNT_NOUN_RE.search(text)
    return match.group(1) if match is not None else None


def _is_non_exact(text: str, start: int, end: int | None = None) -> bool:
    if _NON_EXACT_PREFIX_RE.search(text[max(0, start - 96) : start]) is not None:
        return True
    return end is not None and _NON_EXACT_SUFFIX_RE.search(text[end : end + 64]) is not None


def _is_numeric_sign(character: str) -> bool:
    name = unicodedata.name(character, "")
    return unicodedata.category(character) == "Pd" or any(
        marker in name for marker in ("PLUS", "MINUS", "HYPHEN")
    )


def _numeric_sign_start(text: str, start: int) -> int | None:
    index = start
    while index > 0 and text[index - 1].isspace():
        index -= 1
    if index > 0 and _is_numeric_sign(text[index - 1]):
        return index - 1
    return None


def _has_non_integer_prefix(text: str, start: int) -> bool:
    return (
        _numeric_sign_start(text, start) is not None
        or re.search(r"[.,]$", text[max(0, start - 16) : start]) is not None
    )


def _has_signed_output_number(text: str, quoted_spans: list[tuple[int, int]]) -> bool:
    for number in re.finditer(r"[0-9]+", text):
        sign_start = _numeric_sign_start(text, number.start())
        if sign_start is None or _overlaps(sign_start, number.end(), quoted_spans):
            continue
        before = text[max(0, sign_start - 192) : sign_start]
        after = text[number.end() : number.end() + 96]
        if (
            _OUTPUT_AFTER_NUMBER_RE.match(after) is not None
            or _PAGE_BEFORE_SIGN_RE.search(before) is not None
            or _COUNT_COMMAND_BEFORE_SIGN_RE.search(before) is not None
        ):
            return True
    return False


def parse_output_request(instruction: str) -> OutputRequestSurface:
    """Parse and mask exact output-language spans without losing ``Film``.

    ``24 film`` is simultaneously a cardinality request and often a reviewed
    catalog value.  The numeric/output surface is removed for semantic
    grounding while the word ``film`` is retained.  Comments or DSL source are
    not accepted here; this parser receives bounded natural-language turns.
    """

    if not isinstance(instruction, str):
        raise TypeError("instruction must be a string")
    quoted_spans = _quoted_spans(instruction)
    range_matches = [
        match
        for match in _RANGE_OR_ALTERNATIVE_RE.finditer(instruction)
        if not _overlaps(*match.span(), quoted_spans)
        and not _is_non_exact(instruction, *match.span())
    ]
    range_spans = [match.span() for match in range_matches]
    qualified_range_matches = [
        match
        for match in range_matches
        if _RANGE_HAS_QUALIFIER_RE.search(match.group(0)) is not None
    ]
    choice_range_matches = [
        match for match in range_matches if match not in qualified_range_matches
    ]
    all_page_matches = [
        match
        for match in _PAGE_COUNT_RE.finditer(instruction)
        if not _overlaps(*match.span(), quoted_spans)
        and not _overlaps(*match.span(), range_spans)
        and not _has_non_integer_prefix(instruction, match.start())
    ]
    blocked_page_spans = [
        match.span() for match in all_page_matches if _is_non_exact(instruction, *match.span())
    ]
    page_matches = [
        match for match in all_page_matches if not _is_non_exact(instruction, *match.span())
    ]
    command_matches = [
        match
        for match in _COUNT_COMMAND_RE.finditer(instruction)
        if not _overlaps(*match.span(), quoted_spans)
        and not _is_non_exact(instruction, *match.span())
    ]
    dsl_count_matches = [
        match
        for match in _DSL_COUNT_RE.finditer(instruction)
        if not _overlaps(*match.span(), quoted_spans)
        and not _is_non_exact(instruction, *match.span())
        and not _has_non_integer_prefix(instruction, match.start(1))
    ]
    authoritative_spans = range_spans + [
        match.span() for match in page_matches + command_matches + dsl_count_matches
    ]
    mentions: list[OutputMention] = []
    for match in choice_range_matches:
        values = [int(value) for value in re.findall(r"[0-9]+", match.group(0))[:2]]
        if len(values) != 2:
            raise AssertionError("range output roster is invalid")
        mode = "page" if match.group("page") is not None else "count"
        mentions.extend(OutputMention(mode, value, *match.span()) for value in values)
    mentions.extend(
        OutputMention("page", int(match.group(1) or match.group(2)), *match.span())
        for match in page_matches
    )
    mentions.extend(
        OutputMention("count", int(match.group(1)), *match.span()) for match in command_matches
    )
    mentions.extend(
        OutputMention("count", int(match.group(1)), *match.span()) for match in dsl_count_matches
    )
    count_matches = [
        match
        for match in _EXPLICIT_COUNT_RE.finditer(instruction)
        if not _overlaps(*match.span(), authoritative_spans + quoted_spans)
        and not _is_non_exact(instruction, *match.span())
        and not _has_non_integer_prefix(instruction, match.start())
    ]
    mentions.extend(
        OutputMention("count", int(match.group(1)), *match.span()) for match in count_matches
    )
    mentions.sort(key=lambda item: (item.start, item.end, item.mode))

    explicit_page_spans = [match.span() for match in page_matches]
    generic_matches = [
        match
        for match in _PAGINATION_RE.finditer(instruction)
        if not _overlaps(
            *match.span(),
            explicit_page_spans + range_spans + blocked_page_spans + quoted_spans,
        )
        and not _is_non_exact(instruction, *match.span())
    ]
    ambiguous_matches = [
        match
        for match in _AMBIGUOUS_COUNT_RE.finditer(instruction)
        if not _overlaps(*match.span(), quoted_spans)
        and not _is_non_exact(instruction, *match.span())
    ]
    numeric_pagination_candidates = [
        match
        for match in _NUMERIC_PAGINATION_CANDIDATE_RE.finditer(instruction)
        if not _overlaps(*match.span(), quoted_spans)
        and not _overlaps(*match.span(), range_spans)
        and not _is_non_exact(instruction, *match.span())
    ]
    valid_page_spans = {match.span() for match in page_matches}
    invalid_numeric_pagination = any(
        match.span() not in valid_page_spans for match in numeric_pagination_candidates
    )
    protected_numeric_spans = quoted_spans + range_spans
    invalid_numeric_output = (
        bool(qualified_range_matches)
        or _has_signed_output_number(instruction, protected_numeric_spans)
        or any(
            not _overlaps(*match.span(), protected_numeric_spans)
            for match in _INVALID_NUMERIC_OUTPUT_RE.finditer(instruction)
        )
        or any(
            not _overlaps(*match.span(), quoted_spans)
            and not _is_non_exact(instruction, *match.span())
            for match in _INVALID_DSL_COUNT_RE.finditer(instruction)
        )
    )

    masked = list(instruction)
    replacements: list[tuple[int, str]] = []
    for mention in mentions:
        source = instruction[mention.start : mention.end]
        noun = _semantic_noun(source)
        if noun is not None:
            replacements.append((mention.start, noun))
        for index in range(mention.start, mention.end):
            masked[index] = " "
    for match in generic_matches + ambiguous_matches:
        for index in range(*match.span()):
            masked[index] = " "
    for match in ambiguous_matches:
        noun = _semantic_noun(match.group(0))
        if noun is not None:
            replacements.append((match.start(), noun))
    for start, noun in replacements:
        masked[start : start + len(noun)] = noun
    semantic_instruction = " ".join("".join(masked).split())
    return OutputRequestSurface(
        instruction=instruction,
        semantic_instruction=semantic_instruction,
        mentions=tuple(mentions),
        generic_pagination=bool(
            page_matches
            or generic_matches
            or any(match.group("page") is not None for match in choice_range_matches)
        ),
        ambiguous_count=bool(ambiguous_matches),
        invalid_numeric_pagination=invalid_numeric_pagination,
        invalid_numeric_output=invalid_numeric_output,
    )


# CREATE uses a richer quantity surface than the legacy output parser above.
# Keep the two parsers separate: existing retrieval/orchestration callers retain
# their exact legacy behavior while CREATE can bind each operator-owned fact to
# a typed, host-issued requirement grant.
CreateQuantityStatus = Literal["absent", "resolved", "ambiguous", "conflict", "invalid"]
CreateQuantityKind = Literal[
    "result_count",
    "row_count",
    "fetch_occurrences",
    "block_count",
    "instance_count",
    "branch_count",
    "pool_count",
    "role_count",
    "over_fetch",
]
CreateQuantityScope = Literal[
    "total",
    "page",
    "row",
    "pool",
    "fetch",
    "final_output",
    "block",
    "instance",
    "branch",
    "variant",
    "path",
    "role",
]
CreateQuantityMode = Literal[
    "total",
    "page",
    "page_default",
    "exact",
    "deferred",
    "multiplier",
]
CreateQuantityQualifier = Literal["first", "second", "final", "each"]
CreateQuantityContract = tuple[
    CreateQuantityKind,
    CreateQuantityScope,
    CreateQuantityMode,
    CreateQuantityQualifier | None,
    int | None,
    int | None,
]

_CREATE_MAX_QUANTITY = 10_000
_CREATE_MIN_MULTIPLIER = 2
_CREATE_MAX_MULTIPLIER = 16
_CREATE_NUMBER_WORD_VALUES = {
    "un": 1,
    "uno": 1,
    "una": 1,
    "due": 2,
    "tre": 3,
    "quattro": 4,
    "cinque": 5,
    "sei": 6,
    "sette": 7,
    "otto": 8,
    "nove": 9,
    "dieci": 10,
    "undici": 11,
    "dodici": 12,
    "tredici": 13,
    "quattordici": 14,
    "quindici": 15,
    "sedici": 16,
    "diciassette": 17,
    "diciotto": 18,
    "diciannove": 19,
    "venti": 20,
    "ventuno": 21,
    "ventidue": 22,
    "ventitre": 23,
    "ventiquattro": 24,
    "venticinque": 25,
    "ventisei": 26,
    "ventisette": 27,
    "ventotto": 28,
    "ventinove": 29,
    "trenta": 30,
    "quaranta": 40,
    "cinquanta": 50,
    "sessanta": 60,
    "settanta": 70,
    "ottanta": 80,
    "novanta": 90,
    "cento": 100,
}
_CREATE_NUMBER_WORD_PATTERN = "|".join(
    sorted(
        (re.escape(word) for word in (*_CREATE_NUMBER_WORD_VALUES, "ventitré")),
        key=len,
        reverse=True,
    )
)
_CREATE_NUMBER = rf"(?:[0-9]+|{_CREATE_NUMBER_WORD_PATTERN})"
_CREATE_RESULT_NOUN = r"(?:risultat[io]|contenut[io]|element[io]|titol[io]|film|video)"
_CREATE_STRUCTURAL_NOUN = (
    r"(?:rig(?:a|he)|blocch[io]|istanz[ae]|ram[io]|variant[aei]|percors[io]|pool|ruol[io])"
)
_CREATE_COUNTED_NOUN = rf"(?:{_CREATE_RESULT_NOUN}|{_CREATE_STRUCTURAL_NOUN}|take)"
_CREATE_LABEL_WORD = r"[A-Za-zÀ-ÖØ-öø-ÿ0-9_/-]+"

_CREATE_MULTIPLIER_RE = re.compile(
    rf"(?<!\w)(?P<subject>sequenza|riga|take)\s+"
    rf"(?P<value>{_CREATE_NUMBER})\s*(?:per|\*)\s*(?P<factor>{_CREATE_NUMBER})(?!\w)",
    re.IGNORECASE,
)
_CREATE_PAGE_DEFAULT_RE = re.compile(
    rf"(?:(?<!\w)(?P<value>{_CREATE_NUMBER})\s+"
    rf"(?:{_CREATE_RESULT_NOUN}\s*)?(?:total[ie]\s*)?per\s+pagina(?!\w)|"
    rf"(?<!\w)pagina\s+(?:da|di|con)\s+(?P<after>{_CREATE_NUMBER})(?!\w)|"
    rf"(?<!\w)(?:take\s+)?page\s+default\s+(?P<dsl>{_CREATE_NUMBER})(?!\w))",
    re.IGNORECASE,
)
_CREATE_PAGE_MODE_RE = re.compile(
    r"(?<!\w)(?:paginazione(?:\s+snapshot)?|pagina\s+snapshot)(?!\w)",
    re.IGNORECASE,
)
_CREATE_PER_ROW_RE = re.compile(
    rf"(?<!\w)(?P<value>{_CREATE_NUMBER})\s+{_CREATE_RESULT_NOUN}"
    r"(?:\s+total[ie])?\s+per\s+(?:ogni\s+|ciascun[ao]\s+)?riga(?!\w)",
    re.IGNORECASE,
)
_CREATE_ROW_RESULT_RE = re.compile(
    rf"(?<!\w)(?:(?P<determiner>ciascun[ao]|ogni|una?|la)\s+)?riga"
    rf"(?P<label>(?:\s+(?!(?:da|di|con)\b){_CREATE_LABEL_WORD}){{0,4}})"
    rf"\s+(?:da|di|con)\s+(?P<value>{_CREATE_NUMBER})(?!\w)"
    rf"(?:\s+{_CREATE_RESULT_NOUN})?(?:\s+total[ie])?",
    re.IGNORECASE,
)
_CREATE_POOL_RESULT_RE = re.compile(
    rf"(?:(?<!\w)pool"
    rf"(?P<label>(?:\s+(?!(?:da|di|con)\b){_CREATE_LABEL_WORD}){{0,4}})"
    rf"\s+(?:da|di|con)\s+(?P<after>{_CREATE_NUMBER})(?!\w)"
    rf"(?:\s+{_CREATE_RESULT_NOUN})?(?:\s+ciascun[oi]?)?|"
    rf"(?<!\w)(?P<before>{_CREATE_NUMBER})\s+{_CREATE_RESULT_NOUN}"
    r"\s+per\s+(?:ogni\s+|ciascun[oa]\s+)?pool(?!\w))",
    re.IGNORECASE,
)
_CREATE_FETCH_RESULT_RE = re.compile(
    rf"(?<!\w)(?:(?P<qualifier>primo|secondo|finale|ultimo)\s+)?take"
    rf"(?:\s+(?!(?:da|a|con)\b){_CREATE_LABEL_WORD}){{0,4}}"
    rf"\s+(?:da|a|con)\s+(?P<value>{_CREATE_NUMBER})(?!\w)",
    re.IGNORECASE,
)
_CREATE_FETCH_CONTINUATION_RE = re.compile(
    rf"(?<!\w)(?:un|uno)\s+(?P<qualifier>secondo|finale|ultimo)\s+"
    rf"da\s+(?P<value>{_CREATE_NUMBER})(?!\w)",
    re.IGNORECASE,
)
_CREATE_FETCH_OCCURRENCES_RE = re.compile(
    rf"(?<!\w)(?P<value>{_CREATE_NUMBER})\s+take"
    r"(?:\s+di\s+endpoint)?(?:\s+(?:complessiv[ioe]|total[ie]))?(?!\w)",
    re.IGNORECASE,
)
_CREATE_FINAL_OUTPUT_RE = re.compile(
    rf"(?:(?<!\w)(?:limita|limito|fissa|imposta)\s+"
    rf"(?:il\s+)?(?:risultat[io]|limite)\s+finale\s+(?:a|su)\s+"
    rf"(?P<explicit>{_CREATE_NUMBER})(?!\w)|"
    rf"(?<!\w)limita\s+(?:il\s+)?(?:tutto\s+)?a\s+"
    rf"(?P<implicit>{_CREATE_NUMBER})(?!\w))",
    re.IGNORECASE,
)
_CREATE_DEFERRED_TOTAL_RE = re.compile(
    r"(?<!\w)(?:"
    r"non\s+(?:applicare|applica|impostare|imposta|usare|usa|mettere|metti)"
    r"(?:\s+ancora)?\s+(?:un\s+)?limite\s+globale|"
    r"senza\s+(?:un\s+)?limite\s+globale"
    r")(?!\w)",
    re.IGNORECASE,
)
_CREATE_STRUCTURAL_COUNT_RE = re.compile(
    rf"(?<!\w)(?P<value>{_CREATE_NUMBER})\s+"
    rf"(?P<noun>{_CREATE_STRUCTURAL_NOUN})(?!\w)",
    re.IGNORECASE,
)
_CREATE_TOTAL_RE = re.compile(
    rf"(?<!\w)(?P<value>{_CREATE_NUMBER})\s+{_CREATE_RESULT_NOUN}"
    r"(?:\s+(?:total[ie]|complessiv[ioe]))?(?!\w)",
    re.IGNORECASE,
)

_CREATE_VAGUE_QUANTITY_RE = re.compile(
    rf"(?<!\w)(?:alcuni|alcune|qualche|pochi|poche|molti|molte|tanti|tante)\s+"
    rf"{_CREATE_COUNTED_NOUN}(?!\w)",
    re.IGNORECASE,
)
_CREATE_APPROXIMATE_QUANTITY_RE = re.compile(
    rf"(?<!\w)(?:circa|almeno|al\s+massimo|massimo|minimo|oltre|entro|"
    rf"approssimativamente|indicativamente|pi[uù]\s+o\s+meno)\s+"
    rf"{_CREATE_NUMBER}\s+{_CREATE_COUNTED_NOUN}(?!\w)",
    re.IGNORECASE,
)
_CREATE_APPROXIMATE_SCOPED_RE = re.compile(
    rf"(?<!\w)(?:riga|pool|take|pagina)(?:\s+{_CREATE_LABEL_WORD}){{0,4}}\s+"
    rf"(?:da|a|con)\s+(?:circa|almeno|massimo|minimo|oltre|entro)\s+"
    rf"{_CREATE_NUMBER}(?!\w)",
    re.IGNORECASE,
)
_CREATE_RANGE_OR_CHOICE_RE = re.compile(
    rf"(?<!\w)(?:(?:tra|fra)\s+(?P<first>{_CREATE_NUMBER})\s+e\s+"
    rf"(?P<second>{_CREATE_NUMBER})|da\s+(?P<from>{_CREATE_NUMBER})\s+a\s+"
    rf"(?P<to>{_CREATE_NUMBER})|(?P<left>{_CREATE_NUMBER})\s*"
    rf"(?:o|oppure|/|[-\u2010-\u2015])\s*(?P<right>{_CREATE_NUMBER}))\s+"
    rf"{_CREATE_COUNTED_NOUN}(?!\w)",
    re.IGNORECASE,
)
_CREATE_MISSING_LIMIT_RE = re.compile(
    r"(?<!\w)limite\s+(?:globale|finale)"
    r"(?:\s+(?:distinto|diverso|specifico))?(?:\s+per\s+ciascun[oa])?(?!\w)",
    re.IGNORECASE,
)
_CREATE_SIGNED_OR_DECIMAL = (
    r"(?:[+\-\u2010\u2011\u2012\u2013\u2014\u2015\u207b\u208b\ufe63\uff0d\u2212\uff0b]"
    r"\s*[0-9]+|[.,][0-9]+|[0-9]+[.,][0-9]+)"
)
_CREATE_INVALID_NUMBER_BEFORE_RE = re.compile(
    rf"(?<!\w){_CREATE_SIGNED_OR_DECIMAL}\s+{_CREATE_COUNTED_NOUN}(?!\w)",
    re.IGNORECASE,
)
_CREATE_INVALID_NUMBER_AFTER_RE = re.compile(
    rf"(?<!\w)(?:riga|pool|take|pagina|risultato\s+finale|limite\s+finale)"
    rf"(?:\s+{_CREATE_LABEL_WORD}){{0,4}}\s+(?:da|a|con|su)\s+"
    rf"{_CREATE_SIGNED_OR_DECIMAL}(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CreateQuantityMention:
    """One exact, source-spanned CREATE quantity fact owned by the operator."""

    kind: CreateQuantityKind
    scope: CreateQuantityScope
    mode: CreateQuantityMode
    value: int | None
    factor: int | None
    qualifier: CreateQuantityQualifier | None
    start: int
    end: int

    @property
    def contract(self) -> CreateQuantityContract:
        return (
            self.kind,
            self.scope,
            self.mode,
            self.qualifier,
            self.value,
            self.factor,
        )


@dataclass(frozen=True, slots=True)
class CreateQuantitySurface:
    """Fail-closed CREATE interpretation; unresolved surfaces grant no facts."""

    instruction: str
    semantic_instruction: str
    status: CreateQuantityStatus
    mentions: tuple[CreateQuantityMention, ...]
    issues: tuple[str, ...]

    @property
    def contracts(self) -> tuple[CreateQuantityContract, ...]:
        result: list[CreateQuantityContract] = []
        for mention in self.mentions:
            if mention.contract not in result:
                result.append(mention.contract)
        return tuple(result)

    @property
    def requires_clarification(self) -> bool:
        return self.status in {"ambiguous", "conflict", "invalid"}


def _create_plain_number(token: str) -> int | None:
    if token.isascii() and token.isdecimal():
        value = int(token)
        return value if 1 <= value <= _CREATE_MAX_QUANTITY else None
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", token.casefold())
        if not unicodedata.combining(character)
    )
    return _CREATE_NUMBER_WORD_VALUES.get(normalized)


def _create_qualifier(token: str | None) -> CreateQuantityQualifier | None:
    if token is None:
        return None
    normalized = token.casefold()
    if normalized == "primo":
        return "first"
    if normalized == "secondo":
        return "second"
    if normalized in {"finale", "ultimo"}:
        return "final"
    if normalized.startswith("ciascun") or normalized == "ogni":
        return "each"
    if normalized in {"un", "una", "la"}:
        return None
    raise AssertionError("unknown CREATE quantity qualifier")


def _create_structural_contract(
    noun: str,
) -> tuple[CreateQuantityKind, CreateQuantityScope]:
    normalized = noun.casefold()
    if normalized.startswith("rig"):
        return "row_count", "page"
    if normalized.startswith("blocc"):
        return "block_count", "block"
    if normalized.startswith("istanz"):
        return "instance_count", "instance"
    if normalized.startswith("ram"):
        return "branch_count", "branch"
    if normalized.startswith("variant"):
        return "branch_count", "variant"
    if normalized.startswith("percors"):
        return "branch_count", "path"
    if normalized == "pool":
        return "pool_count", "pool"
    if normalized.startswith("ruol"):
        return "role_count", "role"
    raise AssertionError("unknown CREATE structural quantity noun")


def _create_unquoted_matches(
    pattern: re.Pattern[str],
    instruction: str,
    quoted_spans: list[tuple[int, int]],
) -> list[re.Match[str]]:
    return [
        match
        for match in pattern.finditer(instruction)
        if not _overlaps(*match.span(), quoted_spans)
    ]


def _create_masked_instruction(
    instruction: str,
    mentions: list[CreateQuantityMention],
) -> str:
    masked = list(instruction)
    replacements: list[tuple[int, str]] = []
    for mention in mentions:
        noun = _semantic_noun(instruction[mention.start : mention.end])
        if noun is not None:
            replacements.append((mention.start, noun))
        for index in range(mention.start, mention.end):
            masked[index] = " "
    for start, noun in replacements:
        masked[start : start + len(noun)] = noun
    return " ".join("".join(masked).split())


def _create_has_conflict(mentions: list[CreateQuantityMention]) -> bool:
    """Detect contracts that cannot safely identify distinct local targets."""

    strict_groups: dict[
        tuple[CreateQuantityKind, CreateQuantityScope, CreateQuantityQualifier | None],
        set[tuple[CreateQuantityMode, int | None, int | None]],
    ] = {}
    for mention in mentions:
        strict = (
            mention.scope in {"total", "page", "final_output"}
            or mention.kind
            in {
                "row_count",
                "fetch_occurrences",
                "block_count",
                "instance_count",
                "branch_count",
                "pool_count",
                "role_count",
            }
            or mention.qualifier in {"first", "second", "final", "each"}
        )
        if not strict:
            continue
        key = (mention.kind, mention.scope, mention.qualifier)
        strict_groups.setdefault(key, set()).add((mention.mode, mention.value, mention.factor))
    if any(len(values) > 1 for values in strict_groups.values()):
        return True

    deferred = any(
        mention.kind == "result_count" and mention.scope == "total" and mention.mode == "deferred"
        for mention in mentions
    )
    explicit_global = any(
        mention.kind == "result_count"
        and mention.scope in {"total", "final_output"}
        and mention.mode != "deferred"
        for mention in mentions
    )
    return deferred and explicit_global


def parse_create_quantity_surface(instruction: str) -> CreateQuantitySurface:
    """Parse operator-owned CREATE quantities without guessing missing values.

    Ambiguous, conflicting or invalid prose returns no mentions at all.  This is
    intentional: downstream authority code may issue value/slot grants only
    when the entire turn's quantity surface is resolved.
    """

    if not isinstance(instruction, str):
        raise TypeError("instruction must be a string")

    quoted_spans = _quoted_spans(instruction)
    mentions: list[CreateQuantityMention] = []
    issues: list[str] = []

    def issue(value: str) -> None:
        if value not in issues:
            issues.append(value)

    def add(
        match: re.Match[str],
        *,
        kind: CreateQuantityKind,
        scope: CreateQuantityScope,
        mode: CreateQuantityMode,
        token: str | None,
        factor_token: str | None = None,
        qualifier: CreateQuantityQualifier | None = None,
    ) -> None:
        value = _create_plain_number(token) if token is not None else None
        factor = _create_plain_number(factor_token) if factor_token is not None else None
        if token is not None and value is None:
            issue("invalid_quantity")
            return
        if factor_token is not None and (
            factor is None or not _CREATE_MIN_MULTIPLIER <= factor <= _CREATE_MAX_MULTIPLIER
        ):
            issue("invalid_multiplier")
            return
        mentions.append(
            CreateQuantityMention(
                kind=kind,
                scope=scope,
                mode=mode,
                value=value,
                factor=factor,
                qualifier=qualifier,
                start=match.start(),
                end=match.end(),
            )
        )

    ambiguous_spans: list[tuple[int, int]] = []
    for pattern in (
        _CREATE_VAGUE_QUANTITY_RE,
        _CREATE_APPROXIMATE_QUANTITY_RE,
        _CREATE_APPROXIMATE_SCOPED_RE,
        _CREATE_RANGE_OR_CHOICE_RE,
    ):
        for match in _create_unquoted_matches(pattern, instruction, quoted_spans):
            ambiguous_spans.append(match.span())
            issue("ambiguous_quantity")

    invalid_spans: list[tuple[int, int]] = []
    for pattern in (_CREATE_INVALID_NUMBER_BEFORE_RE, _CREATE_INVALID_NUMBER_AFTER_RE):
        for match in _create_unquoted_matches(pattern, instruction, quoted_spans):
            invalid_spans.append(match.span())
            issue("invalid_quantity")

    blocked_spans = quoted_spans + ambiguous_spans + invalid_spans
    owned_spans: list[tuple[int, int]] = []

    for match in _CREATE_MULTIPLIER_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans):
            continue
        subject = match.group("subject").casefold()
        add(
            match,
            kind="over_fetch",
            scope="row" if subject == "riga" else "fetch",
            mode="multiplier",
            token=match.group("value"),
            factor_token=match.group("factor"),
        )
        owned_spans.append(match.span())

    for match in _CREATE_PAGE_DEFAULT_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="result_count",
            scope="page",
            mode="page_default",
            token=match.group("value") or match.group("after") or match.group("dsl"),
        )
        owned_spans.append(match.span())

    for match in _CREATE_PER_ROW_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="result_count",
            scope="row",
            mode="total",
            token=match.group("value"),
            qualifier="each",
        )
        owned_spans.append(match.span())

    for match in _CREATE_ROW_RESULT_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        qualifier = _create_qualifier(match.group("determiner"))
        add(
            match,
            kind="result_count",
            scope="row",
            mode="total",
            token=match.group("value"),
            qualifier=qualifier,
        )
        owned_spans.append(match.span())

    for match in _CREATE_POOL_RESULT_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="result_count",
            scope="pool",
            mode="total",
            token=match.group("after") or match.group("before"),
            qualifier="each",
        )
        owned_spans.append(match.span())

    for match in _CREATE_FETCH_RESULT_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="result_count",
            scope="fetch",
            mode="total",
            token=match.group("value"),
            qualifier=_create_qualifier(match.group("qualifier")),
        )
        owned_spans.append(match.span())

    for match in _CREATE_FETCH_CONTINUATION_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        preceding = instruction[max(0, match.start() - 96) : match.start()]
        if re.search(r"(?<!\w)take(?!\w)", preceding, re.IGNORECASE) is None:
            continue
        add(
            match,
            kind="result_count",
            scope="fetch",
            mode="total",
            token=match.group("value"),
            qualifier=_create_qualifier(match.group("qualifier")),
        )
        owned_spans.append(match.span())

    for match in _CREATE_FETCH_OCCURRENCES_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="fetch_occurrences",
            scope="fetch",
            mode="exact",
            token=match.group("value"),
        )
        owned_spans.append(match.span())

    for match in _CREATE_FINAL_OUTPUT_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="result_count",
            scope="final_output",
            mode="total",
            token=match.group("explicit") or match.group("implicit"),
            qualifier="final",
        )
        owned_spans.append(match.span())

    for match in _CREATE_DEFERRED_TOTAL_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="result_count",
            scope="total",
            mode="deferred",
            token=None,
        )
        owned_spans.append(match.span())

    # Structural counts are independent of nested row/pool result counts, so
    # this pass deliberately permits those overlaps.
    for match in _CREATE_STRUCTURAL_COUNT_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans):
            continue
        kind, scope = _create_structural_contract(match.group("noun"))
        add(
            match,
            kind=kind,
            scope=scope,
            mode="exact",
            token=match.group("value"),
        )

    for match in _CREATE_TOTAL_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="result_count",
            scope="total",
            mode="total",
            token=match.group("value"),
        )
        owned_spans.append(match.span())

    for match in _CREATE_PAGE_MODE_RE.finditer(instruction):
        if _overlaps(*match.span(), blocked_spans + owned_spans):
            continue
        add(
            match,
            kind="result_count",
            scope="page",
            mode="page",
            token=None,
        )
        owned_spans.append(match.span())

    # A positive request for a global/final cap without a number is unresolved.
    # Exact/deferred matches own their span and are therefore exempt.
    for match in _create_unquoted_matches(_CREATE_MISSING_LIMIT_RE, instruction, quoted_spans):
        if not _overlaps(*match.span(), owned_spans):
            issue("missing_quantity")

    mentions.sort(
        key=lambda mention: (
            mention.start,
            mention.end,
            mention.kind,
            mention.scope,
            mention.mode,
        )
    )
    if _create_has_conflict(mentions):
        issue("conflicting_quantity")

    if any(value in issues for value in ("invalid_quantity", "invalid_multiplier")):
        status: CreateQuantityStatus = "invalid"
    elif "conflicting_quantity" in issues:
        status = "conflict"
    elif issues:
        status = "ambiguous"
    elif mentions:
        status = "resolved"
    else:
        status = "absent"

    if status != "resolved":
        return CreateQuantitySurface(
            instruction=instruction,
            semantic_instruction=instruction,
            status=status,
            mentions=(),
            issues=tuple(issues),
        )
    return CreateQuantitySurface(
        instruction=instruction,
        semantic_instruction=_create_masked_instruction(instruction, mentions),
        status=status,
        mentions=tuple(mentions),
        issues=(),
    )
