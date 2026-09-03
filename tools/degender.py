"""Rewrite Admidio's German language files to the generic masculine.

Usage::

    python3 tools/degender.py adm_program/languages/de-DE.xml ...

Every file is rewritten in place. A gendered construct that no rule covers
aborts the run with a non-zero exit code and leaves all files untouched, so an
Admidio update that reworded a string cannot silently ship wording nobody
reviewed. ``ACCEPTED_STRINGS`` waives single strings for an urgent update; each
waiver is printed on every run.

The rule tables live in the sibling module ``degender_rules``; both files are
copied side by side into the image and run by path, so the import is a plain
sibling import rather than a package one.
"""

import re
import sys
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

from degender_rules import (
    ACCEPTED_STRINGS,
    CONTEXT_RULES,
    NAME_ATTRIBUTE_PATTERN,
    STRING_ELEMENT_PATTERN,
    TOKEN_PATTERN,
    TOKEN_REPLACEMENTS,
    UNNAMED_STRING,
    UNRESOLVED_CONSTRUCT_PATTERN,
)

FILE_ENCODING: Final[str] = "utf-8"

EXIT_SUCCESS: Final[int] = 0
EXIT_UNRESOLVED_CONSTRUCT: Final[int] = 1
EXIT_USAGE: Final[int] = 2


class RuleKey(NamedTuple):
    string_name: str
    phrase: str


@dataclass(frozen=True)
class UnresolvedConstruct:
    string_name: str
    construct: str
    line: int


@dataclass(frozen=True)
class StringSpan:
    name: str
    body_start: int
    body_end: int


@dataclass(frozen=True)
class TransformResult:
    text: str
    changed_string_names: tuple[str, ...]
    waived_string_names: tuple[str, ...]
    unresolved: tuple[UnresolvedConstruct, ...]
    applied_rules: frozenset[RuleKey]


def string_name_of(attributes: str) -> str:
    match = NAME_ATTRIBUTE_PATTERN.search(attributes)
    return match.group(1) if match else UNNAMED_STRING


def string_spans(text: str) -> list[StringSpan]:
    """Locate every `<string>` body in the document, whatever attributes it carries."""
    return [
        StringSpan(
            name=string_name_of(match.group("attributes")),
            body_start=match.start("body"),
            body_end=match.end("body"),
        )
        for match in STRING_ELEMENT_PATTERN.finditer(text)
    ]


def find_unresolved(text: str) -> tuple[UnresolvedConstruct, ...]:
    """Report every gendered construct left in the document, waivers excepted.

    Scans the whole file rather than the strings the rules recognise: an element
    the rule engine fails to parse must still be caught here.
    """
    spans = string_spans(text)
    starts = [span.body_start for span in spans]
    findings: list[UnresolvedConstruct] = []
    for match in UNRESOLVED_CONSTRUCT_PATTERN.finditer(text):
        index = bisect_right(starts, match.start()) - 1
        owner = spans[index] if index >= 0 else None
        inside = owner is not None and match.start() < owner.body_end
        name = owner.name if owner is not None and inside else UNNAMED_STRING
        if name in ACCEPTED_STRINGS:
            continue
        line = text.count("\n", 0, match.start()) + 1
        findings.append(UnresolvedConstruct(name, match.group(), line))
    return tuple(findings)


def waived_strings(text: str) -> tuple[str, ...]:
    spans = {span.name: span for span in string_spans(text)}
    return tuple(
        name
        for name in ACCEPTED_STRINGS
        if name in spans
        and UNRESOLVED_CONSTRUCT_PATTERN.search(
            text[spans[name].body_start : spans[name].body_end]
        )
    )


def apply_rules(string_name: str, body: str) -> tuple[str, frozenset[RuleKey]]:
    """Rewrite one string body and report which context rules matched."""
    applied: set[RuleKey] = set()
    for rule in CONTEXT_RULES.get(string_name, ()):
        if rule.before in body:
            body = body.replace(rule.before, rule.after)
            applied.add(RuleKey(string_name, rule.before))
    return TOKEN_PATTERN.sub(lambda m: TOKEN_REPLACEMENTS[m.group()], body), frozenset(
        applied
    )


def transform_text(text: str) -> TransformResult:
    """Rewrite every string of one Admidio language file to the generic masculine."""
    changed: list[str] = []
    applied: set[RuleKey] = set()

    def rewrite(match: re.Match[str]) -> str:
        string_name = string_name_of(match.group("attributes"))
        body = match.group("body")
        new_body, applied_here = apply_rules(string_name, body)
        applied.update(applied_here)
        if new_body != body:
            changed.append(string_name)
        return match.group("head") + new_body + match.group("tail")

    rewritten = STRING_ELEMENT_PATTERN.sub(rewrite, text)
    return TransformResult(
        text=rewritten,
        changed_string_names=tuple(changed),
        waived_string_names=waived_strings(rewritten),
        unresolved=find_unresolved(rewritten),
        applied_rules=frozenset(applied),
    )


def all_rule_keys() -> frozenset[RuleKey]:
    return frozenset(
        RuleKey(string_name, rule.before)
        for string_name, rules in CONTEXT_RULES.items()
        for rule in rules
    )


def _report_file(path: Path, result: TransformResult) -> None:
    print(f"{path}: {len(result.changed_string_names)} strings rewritten")
    for string_name in result.waived_string_names:
        print(f"  WAIVED {string_name}: {ACCEPTED_STRINGS[string_name]}")
    for finding in result.unresolved:
        print(f"  UNRESOLVED {finding.string_name}: {finding.construct!r}")


def _report_stale_rules(stale: Iterable[RuleKey]) -> None:
    # A rule nothing matched means upstream reworded that string. If the new
    # wording is still gendered the detector below fails the build anyway, so a
    # stale rule alone must not block an urgent Admidio update.
    for key in sorted(stale):
        print(f"  STALE RULE {key.string_name}: {key.phrase!r} no longer occurs")


def main(argv: Sequence[str]) -> int:
    """Transform the given language files in place; return a process exit code."""
    paths = [Path(argument) for argument in argv[1:]]
    if not paths:
        print(
            f"usage: {argv[0]} <language-file> [<language-file> ...]", file=sys.stderr
        )
        return EXIT_USAGE

    results = {
        path: transform_text(path.read_text(encoding=FILE_ENCODING)) for path in paths
    }
    for path, result in results.items():
        _report_file(path, result)

    _report_stale_rules(
        all_rule_keys()
        - frozenset().union(*(result.applied_rules for result in results.values()))
    )

    if any(result.unresolved for result in results.values()):
        print("degender: refusing to write, review the findings above", file=sys.stderr)
        return EXIT_UNRESOLVED_CONSTRUCT

    for path, result in results.items():
        path.write_text(result.text, encoding=FILE_ENCODING)
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
