"""Tests for resolving mandate references to members."""

from __future__ import annotations

import pytest

from st_andreas.sepa_returns.match import (
    MatchOutcome,
    MemberDirectory,
    MemberIdentity,
    build_directory,
    match_mandate,
)

SINGLE_MEMBER = MemberIdentity(
    user_id=1,
    mitglieds_nr="XY123456",
    familien_nr=None,
    first_name="Erika",
    last_name="Müller",
)
FAMILY = (
    MemberIdentity(
        user_id=2,
        mitglieds_nr="FB000001",
        familien_nr="FA0042F",
        first_name="Max",
        last_name="Beispiel",
    ),
    MemberIdentity(
        user_id=3,
        mitglieds_nr="FB000002",
        familien_nr="FA0042F",
        first_name="Mia",
        last_name="Beispiel",
    ),
    MemberIdentity(
        user_id=4,
        mitglieds_nr="FB000003",
        familien_nr="FA0042F",
        first_name="Moritz",
        last_name="Beispiel",
    ),
)
COLLIDING_MEMBER = MemberIdentity(
    user_id=5,
    mitglieds_nr="AB010203",
    familien_nr=None,
    first_name="Dora",
    last_name="Doppelt",
)
COLLIDING_FAMILY_MEMBER = MemberIdentity(
    user_id=6,
    mitglieds_nr="CD040506",
    familien_nr="AB010203",
    first_name="Nils",
    last_name="Namensvetter",
)
DUPLICATE_MEMBERS = (
    MemberIdentity(
        user_id=7,
        mitglieds_nr="DUP00001",
        familien_nr=None,
        first_name="Anna",
        last_name="Eins",
    ),
    MemberIdentity(
        user_id=8,
        mitglieds_nr="DUP00001",
        familien_nr=None,
        first_name="Bert",
        last_name="Zwei",
    ),
)
FORMER_MEMBER = MemberIdentity(
    user_id=9,
    mitglieds_nr="EX000001",
    familien_nr=None,
    first_name="Willi",
    last_name="Weggezogen",
)


@pytest.fixture
def directory() -> MemberDirectory:
    return build_directory(
        [
            SINGLE_MEMBER,
            *FAMILY,
            COLLIDING_MEMBER,
            COLLIDING_FAMILY_MEMBER,
            *DUPLICATE_MEMBERS,
            FORMER_MEMBER,
        ]
    )


class TestBuildDirectory:
    def test_indexes_by_mitglieds_nr(self, directory: MemberDirectory) -> None:
        assert directory.by_mitglieds_nr["XY123456"] == (SINGLE_MEMBER,)

    def test_indexes_every_member_of_a_family(
        self, directory: MemberDirectory
    ) -> None:
        assert directory.by_familien_nr["FA0042F"] == FAMILY

    def test_ignores_an_empty_mitglieds_nr(self) -> None:
        nameless = MemberIdentity(
            user_id=10,
            mitglieds_nr="",
            familien_nr=None,
            first_name="Ohne",
            last_name="Nummer",
        )

        assert build_directory([nameless]).by_mitglieds_nr == {}


class TestMatchMandate:
    def test_resolves_a_single_member(self, directory: MemberDirectory) -> None:
        match = match_mandate(directory, "XY123456")

        assert match.outcome is MatchOutcome.RESOLVED
        assert match.members == (SINGLE_MEMBER,)
        assert match.is_writable

    def test_resolves_a_family_to_every_member(
        self, directory: MemberDirectory
    ) -> None:
        match = match_mandate(directory, "FA0042F")

        assert match.outcome is MatchOutcome.RESOLVED
        assert match.members == FAMILY

    def test_still_matches_a_member_who_has_left(
        self, directory: MemberDirectory
    ) -> None:
        match = match_mandate(directory, "EX000001")

        assert match.members == (FORMER_MEMBER,)

    def test_ignores_surrounding_whitespace(self, directory: MemberDirectory) -> None:
        assert match_mandate(directory, " XY123456 ").members == (SINGLE_MEMBER,)

    def test_duplicate_mitglieds_nr_is_ambiguous(
        self, directory: MemberDirectory
    ) -> None:
        match = match_mandate(directory, "DUP00001")

        assert match.outcome is MatchOutcome.AMBIGUOUS_DUPLICATE_MITGLIEDSNR
        assert match.members == ()
        assert not match.is_writable

    def test_member_and_family_collision_is_ambiguous(
        self, directory: MemberDirectory
    ) -> None:
        match = match_mandate(directory, "AB010203")

        assert match.outcome is MatchOutcome.AMBIGUOUS_MEMBER_AND_FAMILY
        assert match.members == ()

    def test_collision_detail_names_both_sides(
        self, directory: MemberDirectory
    ) -> None:
        match = match_mandate(directory, "AB010203")

        assert "Dora Doppelt" in match.detail
        assert "Nils Namensvetter" in match.detail

    def test_unknown_reference_is_unresolved(
        self, directory: MemberDirectory
    ) -> None:
        match = match_mandate(directory, "ZZ999999")

        assert match.outcome is MatchOutcome.UNRESOLVED
        assert not match.is_writable

    def test_empty_reference_is_unresolved(self, directory: MemberDirectory) -> None:
        assert match_mandate(directory, "").outcome is MatchOutcome.UNRESOLVED
