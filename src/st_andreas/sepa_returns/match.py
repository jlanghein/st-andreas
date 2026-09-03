"""Resolution of a SEPA mandate reference back to Admidio members.

Pure: the caller supplies the directory, so this module never touches a
database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@dataclass(frozen=True)
class MemberIdentity:
    """The identifying fields of one Admidio user.

    Membership status is deliberately absent: a return frequently concerns
    someone who has since left the Stamm.
    """

    user_id: int
    mitglieds_nr: str
    familien_nr: str | None
    first_name: str
    last_name: str

    @property
    def display_name(self) -> str:
        """Name as it should appear in a report line."""
        return f"{self.first_name} {self.last_name}".strip()


class MatchOutcome(StrEnum):
    """Result of resolving one mandate reference."""

    RESOLVED = "resolved"
    AMBIGUOUS_DUPLICATE_MITGLIEDSNR = "ambiguous_duplicate_mitgliedsnr"
    AMBIGUOUS_MEMBER_AND_FAMILY = "ambiguous_member_and_family"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class MandateMatch:
    """A mandate reference together with the members it resolves to."""

    mandate_reference: str
    outcome: MatchOutcome
    members: tuple[MemberIdentity, ...]
    detail: str

    @property
    def is_writable(self) -> bool:
        """Whether this match may be written to Admidio."""
        return self.outcome is MatchOutcome.RESOLVED and bool(self.members)


@dataclass(frozen=True)
class MemberDirectory:
    """Members indexed by the two identifiers a mandate reference can carry."""

    by_mitglieds_nr: Mapping[str, tuple[MemberIdentity, ...]]
    by_familien_nr: Mapping[str, tuple[MemberIdentity, ...]]


def build_directory(members: Iterable[MemberIdentity]) -> MemberDirectory:
    """Index members by MitgliedsNr and FamilienNr."""
    by_mitglieds_nr: dict[str, list[MemberIdentity]] = {}
    by_familien_nr: dict[str, list[MemberIdentity]] = {}

    for member in members:
        if member.mitglieds_nr:
            by_mitglieds_nr.setdefault(member.mitglieds_nr, []).append(member)
        if member.familien_nr:
            by_familien_nr.setdefault(member.familien_nr, []).append(member)

    return MemberDirectory(
        by_mitglieds_nr={key: tuple(value) for key, value in by_mitglieds_nr.items()},
        by_familien_nr={key: tuple(value) for key, value in by_familien_nr.items()},
    )


def match_mandate(directory: MemberDirectory, mandate_reference: str) -> MandateMatch:
    """Resolve a mandate reference to the member or family it belongs to."""
    reference = mandate_reference.strip()
    members = directory.by_mitglieds_nr.get(reference, ())
    family = directory.by_familien_nr.get(reference, ())

    if members and family:
        return MandateMatch(
            mandate_reference=reference,
            outcome=MatchOutcome.AMBIGUOUS_MEMBER_AND_FAMILY,
            members=(),
            detail=(
                f"{reference} is a MitgliedsNr of "
                f"{_names(members)} and a FamilienNr of {_names(family)}"
            ),
        )

    if len(members) > 1:
        return MandateMatch(
            mandate_reference=reference,
            outcome=MatchOutcome.AMBIGUOUS_DUPLICATE_MITGLIEDSNR,
            members=(),
            detail=f"MitgliedsNr {reference} is held by {_names(members)}",
        )

    resolved = members or family
    if not resolved:
        return MandateMatch(
            mandate_reference=reference,
            outcome=MatchOutcome.UNRESOLVED,
            members=(),
            detail=f"No member carries {reference!r}",
        )

    return MandateMatch(
        mandate_reference=reference,
        outcome=MatchOutcome.RESOLVED,
        members=resolved,
        detail=_names(resolved),
    )


def _names(members: Iterable[MemberIdentity]) -> str:
    return ", ".join(f"{member.display_name} (#{member.user_id})" for member in members)
