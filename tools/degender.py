"""Rewrite Admidio's German language files to the generic masculine.

Usage::

    python3 tools/degender.py adm_program/languages/de-DE.xml ...

Every file is rewritten in place. A gendered construct that no rule covers
aborts the run with a non-zero exit code and leaves all files untouched, so an
Admidio update that reworded a string cannot silently ship wording nobody
reviewed. ``ACCEPTED_STRINGS`` waives single strings for an urgent update; each
waiver is printed on every run.
"""

import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

FILE_ENCODING: Final[str] = "utf-8"

EXIT_SUCCESS: Final[int] = 0
EXIT_UNRESOLVED_CONSTRUCT: Final[int] = 1
EXIT_USAGE: Final[int] = 2

STRING_ELEMENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?P<head><string name="(?P<name>[^"]+)">)(?P<body>.*?)(?P<tail></string>)',
    re.DOTALL,
)


class PhraseRule(NamedTuple):
    """A literal phrase rewrite applied to the body of one named string."""

    before: str
    after: str


USER_PAIR_NOMINATIVE: Final = PhraseRule(
    "die Benutzerin oder der Benutzer", "der Benutzer"
)
USER_PAIR_NOMINATIVE_INITIAL: Final = PhraseRule(
    "Die Benutzerin oder der Benutzer", "Der Benutzer"
)
USER_PAIR_NOMINATIVE_ALT: Final = PhraseRule(
    "die Benutzerin bzw. der Benutzer", "der Benutzer"
)
USER_PAIR_NOMINATIVE_ALT_INITIAL: Final = PhraseRule(
    "Die Benutzerin bzw. der Benutzer", "Der Benutzer"
)
USER_PAIR_NOMINATIVE_REVERSED: Final = PhraseRule(
    "Der Benutzer bzw. die Benutzerin", "Der Benutzer"
)
USER_PAIR_GENITIVE: Final = PhraseRule(
    "der Benutzerin oder des Benutzers", "des Benutzers"
)
USER_PAIR_GENITIVE_ALT: Final = PhraseRule(
    "der Benutzerin bzw. des Benutzers", "des Benutzers"
)
USER_PAIR_DATIVE_BY: Final = PhraseRule(
    "von der Benutzerin oder dem Benutzer", "vom Benutzer"
)
USER_PAIR_ACCUSATIVE_THROUGH: Final = PhraseRule(
    "durch die Benutzerin oder den Benutzer", "durch den Benutzer"
)
NEW_USER_PAIR_NOMINATIVE: Final = PhraseRule(
    "eine neue Benutzerin oder ein neuer Benutzer", "ein neuer Benutzer"
)
ADMIN_PAIR_GENITIVE: Final = PhraseRule(
    "einer Administratorin oder eines Administrators", "eines Administrators"
)
ADMIN_PAIR_GENITIVE_TYPO: Final = PhraseRule(
    "einer Administatorin oder eines Administrators", "eines Administrators"
)
SENDER_PAIR_GENITIVE: Final = PhraseRule(
    "der Absenderin bzw. des Absenders", "des Absenders"
)
PARTICIPANTS_GENITIVE_COUNT: Final = PhraseRule(
    "Anzahl der Teilnehmenden", "Anzahl der Teilnehmer"
)
PARTICIPANTS_GENITIVE_ALL: Final = PhraseRule("aller Teilnehmenden", "aller Teilnehmer")
PARTICIPANTS_GENITIVE_LIST: Final = PhraseRule(
    "Liste der Teilnehmenden", "Liste der Teilnehmer"
)
MODULE_ADMINS_NOMINATIVE: Final = PhraseRule(
    "sind Administrierende des", "sind Administratoren des"
)

CONTEXT_RULES: Final[Mapping[str, tuple[PhraseRule, ...]]] = {
    "GBO_CAPTCHA_DESC": (USER_PAIR_NOMINATIVE,),
    "GBO_ENTRY_QUEUED": (
        PhraseRule("von einer Moderatorin oder einem Moderator", "von einem Moderator"),
    ),
    "GBO_GUESTBOOK_MODERATION_DESC": (
        ADMIN_PAIR_GENITIVE,
        PhraseRule("bei angemeldeten Benutzer:innen", "bei angemeldeten Benutzern"),
    ),
    "GBO_INITIAL_COMMENTS_LOADING_DESC": (USER_PAIR_NOMINATIVE,),
    "INS_ADMINISTRATOR_LOGIN_DESC": (
        PhraseRule(
            "von einer Administratorin oder einem Administrator",
            "von einem Administrator",
        ),
        ADMIN_PAIR_GENITIVE,
    ),
    "INS_COHABITANT": (PhraseRule("Partner/-in", "Partner"),),
    "INS_DATA_OF_ADMINISTRATOR": (
        PhraseRule(
            "einer Administratorin / eines Administrators", "eines Administrators"
        ),
    ),
    "INS_DATA_OF_ADMINISTRATOR_DESC": (ADMIN_PAIR_GENITIVE,),
    "INS_DESCRIPTION_ADMINISTRATOR": (
        PhraseRule(
            "aller Administratorinnen und Administratoren", "aller Administratoren"
        ),
    ),
    "INS_INSTALLATION_SUCCESSFUL": (ADMIN_PAIR_GENITIVE_TYPO, ADMIN_PAIR_GENITIVE),
    "INS_SPOUSE": (PhraseRule("Ehepartner/-in", "Ehepartner"),),
    "ORG_ADD_ORGANIZATION_DESC": (
        PhraseRule("Die/Der aktuelle Benutzer:in", "Der aktuelle Benutzer"),
        PhraseRule("zur/zum Administrator:in", "zum Administrator"),
    ),
    "ORG_AUTOMATIC_LOGOUT_AFTER_DESC": (
        PhraseRule(
            "eine inaktive Benutzerin oder ein inaktiver Benutzer",
            "ein inaktiver Benutzer",
        ),
        PhraseRule("solange sie oder er", "solange er"),
        USER_PAIR_NOMINATIVE,
    ),
    "ORG_BROWSER_UPDATE_CHECK_DESC": (
        PhraseRule("wird Benutzerinnen und Benutzern", "wird Benutzern"),
    ),
    "ORG_CAPTCHA_REGISTRATION": (USER_PAIR_NOMINATIVE,),
    "ORG_EMAIL_ALERTS_DESC": (NEW_USER_PAIR_NOMINATIVE,),
    "ORG_FIELD_URL_DESC": (USER_PAIR_NOMINATIVE,),
    "ORG_HOMEPAGE_REGISTERED_USERS": (
        USER_PAIR_NOMINATIVE,
        PhraseRule("sobald er/sie sich", "sobald er sich"),
    ),
    "ORG_JAVASCRIPT_EDITOR_ENABLE_DESC": (USER_PAIR_NOMINATIVE,),
    "ORG_SEARCH_SIMILAR_NAMES_DESC": (
        PhraseRule(
            "existierenden Benutzerinnen und Benutzern", "existierenden Benutzern"
        ),
        PhraseRule(
            "existierenden Benutzern und Benutzerinnen", "existierenden Benutzern"
        ),
    ),
    "ORG_SHOW_CREATE_EDIT_DESC": (
        PhraseRule("die Erstellerin bzw. der Ersteller", "der Ersteller"),
        PhraseRule("mit der Benutzerin bzw. der Benutzer", "mit dem Benutzer"),
        USER_PAIR_NOMINATIVE,
        PhraseRule("mit ihrem Vor- und Nachnamen", "mit seinem Vor- und Nachnamen"),
    ),
    "ORG_SHOW_ORGANIZATION_SELECT_DESC": (
        USER_PAIR_NOMINATIVE_INITIAL,
        USER_PAIR_NOMINATIVE,
    ),
    "ORG_VALUE_LIST_DESC": (
        PhraseRule("bei den Benutzerinnen bzw. Benutzern", "bei den Benutzern"),
    ),
    "ORG_VARIABLE_EMAIL": (USER_PAIR_GENITIVE_ALT, USER_PAIR_GENITIVE),
    "ORG_VARIABLE_FIRST_NAME": (USER_PAIR_GENITIVE,),
    "ORG_VARIABLE_LAST_NAME": (USER_PAIR_GENITIVE,),
    "ORG_VARIABLE_NEW_PASSWORD": (USER_PAIR_GENITIVE,),
    "ORG_VARIABLE_USERNAME": (USER_PAIR_GENITIVE,),
    "SYS_ADMINISTRATORS": (PhraseRule("Administrierende", "Administratoren"),),
    "SYS_ADMINISTRATORS_DESC": (MODULE_ADMINS_NOMINATIVE,),
    "SYS_ALBUM_FOLDER_NOT_FOUND": (
        PhraseRule("Besucher:innen der Webseite", "Besuchern der Webseite"),
    ),
    "SYS_ALLOW_ADDITIONAL_GUESTS_DESC": (
        PARTICIPANTS_GENITIVE_COUNT,
        PhraseRule("Anzahl an Teilnehmenden", "Anzahl an Teilnehmern"),
    ),
    "SYS_ALLOW_USER_COMMENTS_DESC": (PARTICIPANTS_GENITIVE_LIST,),
    "SYS_ASSIGN_LOGIN_EMAIL": (USER_PAIR_NOMINATIVE_ALT,),
    "SYS_CATEGORIES_ADMINISTRATORS_DESC": (MODULE_ADMINS_NOMINATIVE,),
    "SYS_CATEGORIES_ALL_MODULE_ADMINISTRATORS_MOTHER_ORGA": (
        PhraseRule("Alle Administrierende des", "Alle Administratoren des"),
    ),
    "SYS_COMPANION": (PhraseRule("Freund/-in", "Freund"),),
    "SYS_CONFIGURATION_ALL_USERS": (
        PhraseRule("allen Benutzer:innen", "allen Benutzern"),
    ),
    "SYS_COOKIE_NOTE_DESC": (
        USER_PAIR_DATIVE_BY,
        PhraseRule("erhält er/sie", "erhält er"),
    ),
    "SYS_DAYS_FIELD_HISTORY_DESC": (USER_PAIR_ACCUSATIVE_THROUGH,),
    "SYS_DEFAULT_ASSIGNMENT_REGISTRATION_DESC": (
        PhraseRule(
            "Wird eine neue Benutzerin oder ein neuer Benutzer angelegt",
            "Wird ein neuer Benutzer angelegt",
        ),
        PhraseRule(
            "der neuen Benutzerin oder dem neuen Benutzer", "dem neuen Benutzer"
        ),
    ),
    "SYS_DEFAULT_COUNTRY_DESC": (USER_PAIR_DATIVE_BY,),
    "SYS_DEFAULT_LIST_CONFIGURATION_PARTICIPATION": (PARTICIPANTS_GENITIVE_ALL,),
    "SYS_DEFAULT_LIST_CONFIGURATION_PARTICIPATION_DESC": (PARTICIPANTS_GENITIVE_ALL,),
    "SYS_DELIVERY_CONFIRMATION_DESC": (
        PhraseRule("des Empfangenden", "des Empfängers"),
        PhraseRule("Der Empfangende", "Der Empfänger"),
    ),
    "SYS_EMAIL_ADMINISTRATOR_DESC": (
        PhraseRule("eines Administrierenden", "eines Administrators"),
    ),
    "SYS_ENABLE_EVENT_REGISTRATION": (
        PARTICIPANTS_GENITIVE_COUNT,
        PARTICIPANTS_GENITIVE_ALL,
    ),
    "SYS_ENABLE_GREETING_CARDS_DESC": (
        PhraseRule("angemeldete Benutzerinnen und Benutzern", "angemeldete Benutzer"),
    ),
    "SYS_ENABLE_GROUPS_ROLES_DESC": (
        PhraseRule("angemeldete Benutzerinnen und Benutzern", "angemeldete Benutzer"),
    ),
    "SYS_EVENT_CATEGORIES_ROLES_DIFFERENT": (
        PhraseRule("bei den Teilnehmenden", "bei den Teilnehmern"),
    ),
    "SYS_EVENT_MAX_MEMBERS": (PARTICIPANTS_GENITIVE_COUNT,),
    "SYS_EXPORT_LISTS_DESC": (
        PhraseRule("von Benutzerinnen und Benutzern", "von Benutzern"),
        PhraseRule("von Benutzerinnnen und Benutzern", "von Benutzern"),
    ),
    "SYS_IMPORT_LOGIN_DATA_DESC": (
        PhraseRule(
            "von einer Administatorin oder einem Administrator",
            "von einem Administrator",
        ),
    ),
    "SYS_INSTALLATION_SUCCESSFUL_DESC": (
        PhraseRule("eines Administrienden", "eines Administrators"),
    ),
    "SYS_INTO_TO_DESC": (
        PhraseRule("jeder Empfangende", "jeder Empfänger"),
        PhraseRule("der anderen Empfangenden", "der anderen Empfänger"),
    ),
    "SYS_LEADER_RIGHTS_DESC": (
        PhraseRule("zu Leiterinnen oder Leitern", "zu Leitern"),
    ),
    "SYS_LOG_ALL_CHANGES_DESC": (USER_PAIR_NOMINATIVE, USER_PAIR_NOMINATIVE_ALT),
    "SYS_LOGIN_USER_NO_ADMINISTRATOR": (
        PhraseRule("für Administriende der", "für Administratoren der"),
        PhraseRule("für Administrierende der", "für Administratoren der"),
    ),
    "SYS_LOSTPW_SEVERAL_EMAIL": (
        PhraseRule(
            "keine eindeutige Benutzerin bzw. kein eindeutiger Benutzer",
            "kein eindeutiger Benutzer",
        ),
    ),
    "SYS_MAP_LINK_ROUTE_DESC": (
        PhraseRule("dieser Benutzerin bzw. dieses Benutzers", "dieses Benutzers"),
    ),
    "SYS_MAX_PARTICIPANTS_OF_ROLE": (
        PhraseRule("von max. #VAR2# Teilnehmenden", "von max. #VAR2# Teilnehmern"),
    ),
    "SYS_MENU_MODULE_RIGHTS_DESC": (USER_PAIR_NOMINATIVE,),
    "SYS_NUMBER_RECIPIENTS_DESC": (
        PhraseRule("an Empfängerinnen oder Empfängern", "an Empfängern"),
    ),
    "SYS_PARTICIPANTS_LIMIT": (
        PhraseRule("Begrenzung der Teilnehmenden", "Begrenzung der Teilnehmer"),
    ),
    "SYS_PARTICIPATION_INFORMATION": (
        PhraseRule("Informationen der Teilnehmenden", "Informationen der Teilnehmer"),
    ),
    "SYS_PASSWORD_FORGOTTEN_PREF_DESC": (
        USER_PAIR_NOMINATIVE,
        PhraseRule(
            "an die Administratorinnen und Administratoren", "an die Administratoren"
        ),
    ),
    "SYS_REGISTRATION_ADOPT_ALL_DATA_DESC": (
        PhraseRule(
            "eine neu registrierte Benutzerin oder ein neu registrierter Benutzer",
            "ein neu registrierter Benutzer",
        ),
        PhraseRule("Bei Benutzerinnen und Benutzern", "Bei Benutzern"),
    ),
    "SYS_RELATIONSHIP_TYPE_EDIT_USER_DESC": (
        PhraseRule(
            "einer anderen Benutzerin oder eines anderen Benutzers",
            "eines anderen Benutzers",
        ),
        PhraseRule("nur die Benutzer bzw. der Benutzer", "nur der Benutzer"),
    ),
    "SYS_RIGHT_ASSIGN_ROLES_DESC": (
        PhraseRule("anderen Benutzerinnen oder Benutzern", "anderen Benutzern"),
    ),
    "SYS_REMOVE_EVENT_REGISTRATION": (
        PhraseRule("bisherigen Teilnehmenden", "bisherigen Teilnehmer"),
    ),
    "SYS_RIGHT_MAIL_PARTICIPANTS": (
        PhraseRule("an alle Teilnehmenden", "an alle Teilnehmer"),
    ),
    "SYS_RIGHT_VIEW_PARTICIPANTS": (
        PARTICIPANTS_GENITIVE_ALL,
        PARTICIPANTS_GENITIVE_LIST,
    ),
    "SYS_ROLE_ACCESS_PERMISSIONS_DESC": (
        PhraseRule("Administrierende besitzen", "Administratoren besitzen"),
    ),
    "SYS_ROLES_MODULE_ADMINISTRATORS_DESC": (MODULE_ADMINS_NOMINATIVE,),
    "SYS_SAVE_ALL_CANCELLATIONS_DESC": (
        PhraseRule("von Teilnehmenden", "von Teilnehmern"),
        PARTICIPANTS_GENITIVE_ALL,
        PARTICIPANTS_GENITIVE_LIST,
    ),
    "SYS_SEND_EMAIL_TO_ALL_ADDRESSES": (USER_PAIR_GENITIVE_ALT,),
    "SYS_SEND_EMAIL_TO_ALL_ADDRESSES_DESC": (
        USER_PAIR_GENITIVE,
        USER_PAIR_GENITIVE_ALT,
    ),
    "SYS_SEND_MAIL_TO_ROLE": (
        PhraseRule("eingeloggte Benutzerinnen und Benutzer", "eingeloggte Benutzer"),
    ),
    "SYS_SEND_PRIVATE_MESSAGE_DESC": (
        PhraseRule(
            "die ausgewählte Empfängerin bzw. den ausgewählten Empfänger",
            "den ausgewählten Empfänger",
        ),
    ),
    "SYS_SENDER_EMAIL_ADDRESS_DESC": (SENDER_PAIR_GENITIVE,),
    "SYS_SENDER_NAME_DESC": (
        SENDER_PAIR_GENITIVE,
        PhraseRule("eine Absender:in E-Mail-Adresse", "eine Absender-E-Mail-Adresse"),
    ),
    "SYS_SHOW_CAPTCHA_DESC": (USER_PAIR_NOMINATIVE,),
    "SYS_SHOW_FORMER_MEMBERS_DESC": (USER_PAIR_NOMINATIVE_ALT_INITIAL,),
    "SYS_SHOW_FORMER_ROLE_MEMBERSHIP_DESC": (USER_PAIR_NOMINATIVE,),
    "SYS_SHOW_MAP_LINK_PROFILE_DESC": (
        PhraseRule(
            "der angezeigten Benutzerin oder des angezeigten Benutzers",
            "des angezeigten Benutzers",
        ),
        PhraseRule(
            "der angezeigten Benutzerin bzw. des angezeigten Benutzers",
            "des angezeigten Benutzers",
        ),
        USER_PAIR_GENITIVE,
    ),
    "SYS_SHOW_ROLE_MEMBERSHIP_DESC": (USER_PAIR_NOMINATIVE,),
    "SYS_SHOW_ROLES_OTHER_ORGANIZATIONS_DESC": (USER_PAIR_NOMINATIVE,),
    "SYS_SYSMAIL_REGISTRATION_ADMINISTRATOR": (NEW_USER_PAIR_NOMINATIVE,),
    "SYS_TEST_MAIL_DESC": (
        PhraseRule(
            "der angemeldeten Benutzerin bzw. des angemeldeten Benutzers",
            "des angemeldeten Benutzers",
        ),
    ),
    "SYS_USER_DELETE_DESC": (USER_PAIR_NOMINATIVE_ALT_INITIAL,),
    "SYS_USER_VALID_LOGIN": (
        PhraseRule("Diese Benutzerin bzw. dieser Benutzer", "Dieser Benutzer"),
    ),
    "SYS_VIEW_PROFILES_OF_ROLE_MEMBERS_DESC": (USER_PAIR_NOMINATIVE_REVERSED,),
    "SYS_VIEW_ROLE_MEMBERSHIPS_DESC": (USER_PAIR_NOMINATIVE_REVERSED,),
}

TOKEN_REPLACEMENTS: Final[Mapping[str, str]] = {
    "Absender:in": "Absender",
    "Administrator:in": "Administrator",
    "Administrator:innen": "Administratoren",
    "Benutzer:in": "Benutzer",
    "Benutzer:innen": "Benutzer",
    "Besucher:innen": "Besucher",
    "Diese:r": "Dieser",
    "Empfänger:in": "Empfänger",
    "Empfänger:innen": "Empfänger",
    "Leiter:in": "Leiter",
    "Leiter:innen": "Leiter",
    "Teilnehmende": "Teilnehmer",
    "ein:e": "ein",
    "eine:n": "einen",
    "inaktive:r": "inaktiver",
    "jede:n": "jeden",
    "kein:e": "kein",
    "neue:r": "neuer",
}

GERMAN_LETTER: Final[str] = "A-Za-zÄÖÜäöüß"

TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    "(?:"
    + "|".join(
        re.escape(token) for token in sorted(TOKEN_REPLACEMENTS, key=len, reverse=True)
    )
    + f")(?![{GERMAN_LETTER}])"
)

UNRESOLVED_CONSTRUCT_PATTERN: Final[re.Pattern[str]] = re.compile(
    "|".join(
        (
            rf"[{GERMAN_LETTER}]{{2,}}:(?:innen|in|e[nr]?|n|r)(?![{GERMAN_LETTER}])",
            rf"[{GERMAN_LETTER}]{{3,}}/-?in(?:nen)?(?![{GERMAN_LETTER}])",
            # Upstream misspells the plural as "Benutzerinnnen" in one string,
            # so the repeated n has to be part of the detector.
            r"\b[A-ZÄÖÜ][a-zäöüß]*(?:er|or|är|eur|ist|ant|ent|at)in(?:n*en)?\b",
            r"\b(?:Teilnehmend|Administrierend|Administriend|Empfangend)e[mnrs]?\b",
            r"\b(?:sie oder er|er oder sie|er/sie|sie/er)\b",
        )
    )
)

ACCEPTED_STRINGS: Final[Mapping[str, str]] = {
    "INS_COHABITANT_FEMALE": (
        "Relationship type deliberately naming the female partner; the male "
        "counterpart is the separate string INS_COHABITANT_MALE."
    ),
}


class RuleKey(NamedTuple):
    string_name: str
    phrase: str


@dataclass(frozen=True)
class UnresolvedConstruct:
    string_name: str
    construct: str


@dataclass(frozen=True)
class TransformResult:
    text: str
    changed_string_names: tuple[str, ...]
    waived_string_names: tuple[str, ...]
    unresolved: tuple[UnresolvedConstruct, ...]
    applied_rules: frozenset[RuleKey]


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
    waived: list[str] = []
    unresolved: list[UnresolvedConstruct] = []
    applied: set[RuleKey] = set()

    def rewrite(match: re.Match[str]) -> str:
        string_name = match.group("name")
        body = match.group("body")
        new_body, applied_here = apply_rules(string_name, body)
        applied.update(applied_here)
        if new_body != body:
            changed.append(string_name)
        for construct in UNRESOLVED_CONSTRUCT_PATTERN.findall(new_body):
            if string_name in ACCEPTED_STRINGS:
                waived.append(string_name)
            else:
                unresolved.append(UnresolvedConstruct(string_name, construct))
        return match.group("head") + new_body + match.group("tail")

    return TransformResult(
        text=STRING_ELEMENT_PATTERN.sub(rewrite, text),
        changed_string_names=tuple(changed),
        waived_string_names=tuple(dict.fromkeys(waived)),
        unresolved=tuple(unresolved),
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
