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
    r"non\s+(?:voglio|avere|restituire|oltre|esattamente|pi[uù](?:\s+di)?|"
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
    authoritative_spans = range_spans + [match.span() for match in page_matches + command_matches]
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
