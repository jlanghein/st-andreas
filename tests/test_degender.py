"""Tests for the Admidio language transform in tools/degender.py."""

import importlib.util
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from types import ModuleType
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
TRANSFORM_PATH: Final[Path] = REPO_ROOT / "tools" / "degender.py"
FIXTURE_DIR: Final[Path] = Path(__file__).parent / "fixtures" / "languages"
SAMPLE_FIXTURE: Final[Path] = FIXTURE_DIR / "sample-de-DE.xml"
DRIFT_FIXTURE: Final[Path] = FIXTURE_DIR / "sample-drift-de-DE.xml"
FILE_ENCODING: Final[str] = "utf-8"
STRING_ELEMENT_TAG: Final[str] = "string"
STRING_NAME_ATTRIBUTE: Final[str] = "name"


def _load_transform() -> ModuleType:
    spec = importlib.util.spec_from_file_location(TRANSFORM_PATH.stem, TRANSFORM_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {TRANSFORM_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


degender = _load_transform()


def transform_fixture(path: Path = SAMPLE_FIXTURE) -> dict[str, str]:
    result = degender.transform_text(path.read_text(encoding=FILE_ENCODING))
    root = ElementTree.fromstring(result.text)
    return {
        element.attrib[STRING_NAME_ATTRIBUTE]: element.text or ""
        for element in root.iter(STRING_ELEMENT_TAG)
    }


def test_colon_plural_of_or_stem_becomes_administratoren() -> None:
    # Arrange / Act
    strings = transform_fixture()

    # Assert
    assert "Administratoren-Adresse" in strings["SYS_MULTIPLE_RECIPIENTS_DESC"]


def test_colon_plural_of_er_stem_keeps_the_singular_form() -> None:
    strings = transform_fixture()

    assert strings["SYS_USER"] == "Benutzer"
    assert strings["SYS_MULTIPLE_RECIPIENTS_DESC"].endswith(
        "(Voreinstellung: Absender)"
    )


def test_dative_plural_keeps_its_ending() -> None:
    strings = transform_fixture()

    assert strings["SYS_CONFIGURATION_ALL_USERS"] == (
        "Konfiguration allen Benutzern zur Verfügung stellen"
    )


def test_colon_article_and_pronoun_forms_become_masculine() -> None:
    strings = transform_fixture()

    assert "an einen Administrator" in strings["SYS_DEFAULT_LIST_NOT_SET_UP"]
    assert "für jeden Benutzer und jedes Feld" in strings["SYS_LOG_ALL_CHANGES_DESC"]


def test_paired_form_is_collapsed_to_the_masculine() -> None:
    strings = transform_fixture()

    assert strings["ORG_VARIABLE_FIRST_NAME"] == (
        "Vorname des Benutzers aus dem jeweiligen E-Mailkontext"
    )
    assert "sowie der Benutzer, der die Änderung" in strings["SYS_LOG_ALL_CHANGES_DESC"]


def test_article_changes_together_with_the_noun() -> None:
    strings = transform_fixture()

    assert strings["ORG_ADD_ORGANIZATION_DESC"] == (
        "Der aktuelle Benutzer wird dort automatisch zum Administrator ernannt."
    )


def test_neutral_participle_takes_the_dative_plural() -> None:
    strings = transform_fixture()

    assert strings["SYS_EVENT_CATEGORIES_ROLES_DIFFERENT"].startswith(
        "Sie haben bei den Teilnehmern Rollen zugeordnet"
    )


def test_neutral_participle_takes_the_genitive_plural() -> None:
    strings = transform_fixture()

    assert strings["SYS_PARTICIPANTS_LIMIT"] == "Begrenzung der Teilnehmer"
    assert strings["SYS_SHOW_PARTICIPANTS"] == "Teilnehmer anzeigen"


def test_time_format_and_neutral_vocabulary_stay_untouched() -> None:
    strings = transform_fixture()

    assert strings["SYS_DATE_FORMAT_HOUR"] == "H:i"
    assert strings["SYS_MEMBERS"] == "Mitglieder"


def test_sample_fixture_leaves_no_unresolved_construct() -> None:
    result = degender.transform_text(SAMPLE_FIXTURE.read_text(encoding=FILE_ENCODING))

    assert result.unresolved == ()


def test_accepted_string_is_waived_instead_of_failing() -> None:
    result = degender.transform_text(SAMPLE_FIXTURE.read_text(encoding=FILE_ENCODING))

    assert result.waived_string_names == ("INS_COHABITANT_FEMALE",)
    assert transform_fixture()["INS_COHABITANT_FEMALE"] == "Partnerin"


def test_unknown_construct_is_reported_as_unresolved() -> None:
    result = degender.transform_text(DRIFT_FIXTURE.read_text(encoding=FILE_ENCODING))

    unresolved = {finding.string_name for finding in result.unresolved}
    assert unresolved == {"SYS_NEW_EDITOR", "SYS_NEW_SPEAKER"}


def test_unknown_construct_fails_the_run_without_writing(tmp_path: Path) -> None:
    # Arrange
    target = tmp_path / DRIFT_FIXTURE.name
    original = DRIFT_FIXTURE.read_text(encoding=FILE_ENCODING)
    target.write_text(original, encoding=FILE_ENCODING)

    # Act
    exit_code = degender.main([TRANSFORM_PATH.name, str(target)])

    # Assert
    assert exit_code == degender.EXIT_UNRESOLVED_CONSTRUCT
    assert target.read_text(encoding=FILE_ENCODING) == original


def test_transform_rewrites_the_file_in_place(tmp_path: Path) -> None:
    target = tmp_path / SAMPLE_FIXTURE.name
    target.write_text(
        SAMPLE_FIXTURE.read_text(encoding=FILE_ENCODING), encoding=FILE_ENCODING
    )

    exit_code = degender.main([TRANSFORM_PATH.name, str(target)])

    assert exit_code == degender.EXIT_SUCCESS
    assert "Benutzer:in" not in target.read_text(encoding=FILE_ENCODING)


def test_transform_is_idempotent() -> None:
    once = degender.transform_text(
        SAMPLE_FIXTURE.read_text(encoding=FILE_ENCODING)
    ).text

    twice = degender.transform_text(once)

    assert twice.text == once
    assert twice.changed_string_names == ()


def test_transform_preserves_the_document_structure() -> None:
    original = SAMPLE_FIXTURE.read_text(encoding=FILE_ENCODING)

    result = degender.transform_text(original)

    original_names = [
        element.attrib[STRING_NAME_ATTRIBUTE]
        for element in ElementTree.fromstring(original).iter(STRING_ELEMENT_TAG)
    ]
    assert list(transform_fixture()) == original_names
    assert result.text.count(f"<{STRING_ELEMENT_TAG} ") == original.count(
        f"<{STRING_ELEMENT_TAG} "
    )


def test_every_context_rule_belongs_to_a_named_string() -> None:
    keys = degender.all_rule_keys()

    assert keys
    assert all(key.string_name in degender.CONTEXT_RULES for key in keys)
