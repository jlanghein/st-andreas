"""Tests for Sippe operations."""

import pytest

from st_andreas.sippe.operations import (
    MemberSippe,
    SippeAlreadyExistsError,
    SippeHasMembersError,
    SippeInfo,
    SippeNotFoundError,
    SippeState,
    compute_member_updates,
    is_sorted,
    plan_add,
    plan_delete,
    plan_sort,
)


def make_state(
    sippe_names: list[str],
    members: list[tuple[int, str]] | None = None,
) -> SippeState:
    """Helper to create a SippeState from simple inputs.

    Args:
        sippe_names: List of Sippe names in current order
        members: List of (user_id, sippe_name) tuples
    """
    name_to_position = {name: i + 1 for i, name in enumerate(sippe_names)}

    member_counts: dict[str, int] = {}
    member_list: list[MemberSippe] = []

    if members:
        for i, (user_id, sippe_name) in enumerate(members):
            member_counts[sippe_name] = member_counts.get(sippe_name, 0) + 1
            member_list.append(
                MemberSippe(
                    user_id=user_id,
                    usd_id=1000 + i,
                    position=name_to_position[sippe_name],
                    sippe_name=sippe_name,
                )
            )

    sippe_list = [
        SippeInfo(
            name=name,
            position=i + 1,
            member_count=member_counts.get(name, 0),
        )
        for i, name in enumerate(sippe_names)
    ]

    return SippeState(sippe_list=sippe_list, members=member_list)


class TestIsSorted:
    def test_empty_list_is_sorted(self) -> None:
        state = make_state([])
        assert is_sorted(state)

    def test_single_item_is_sorted(self) -> None:
        state = make_state(["Adler"])
        assert is_sorted(state)

    def test_alphabetically_sorted(self) -> None:
        state = make_state(["Adler", "Bär", "Wolf"])
        assert is_sorted(state)

    def test_not_sorted(self) -> None:
        state = make_state(["Wolf", "Adler", "Bär"])
        assert not is_sorted(state)

    def test_case_insensitive_sort(self) -> None:
        state = make_state(["Adler", "bär", "Wolf"])
        assert is_sorted(state)


class TestComputeMemberUpdates:
    def test_no_updates_when_positions_match(self) -> None:
        members = [
            MemberSippe(user_id=1, usd_id=101, position=1, sippe_name="Adler"),
            MemberSippe(user_id=2, usd_id=102, position=2, sippe_name="Wolf"),
        ]
        new_names = ["Adler", "Wolf"]

        updates = compute_member_updates(members, new_names)

        assert updates == []

    def test_detects_position_changes(self) -> None:
        members = [
            MemberSippe(user_id=1, usd_id=101, position=2, sippe_name="Adler"),
            MemberSippe(user_id=2, usd_id=102, position=1, sippe_name="Wolf"),
        ]
        new_names = ["Adler", "Wolf"]

        updates = compute_member_updates(members, new_names)

        update_dict = {m.sippe_name: new_pos for m, new_pos in updates}
        assert update_dict["Adler"] == 1
        assert update_dict["Wolf"] == 2

    def test_ignores_members_not_in_new_list(self) -> None:
        members = [
            MemberSippe(user_id=1, usd_id=101, position=1, sippe_name="Unknown"),
        ]
        new_names = ["Adler", "Wolf"]

        updates = compute_member_updates(members, new_names)

        assert updates == []


class TestPlanAdd:
    def test_adds_to_empty_list(self) -> None:
        state = make_state([])

        plan = plan_add(state, "Adler")

        assert plan.new_sippe_names == ["Adler"]
        assert plan.member_updates == []

    def test_adds_and_sorts(self) -> None:
        state = make_state(["Adler", "Wolf"])

        plan = plan_add(state, "Bär")

        assert plan.new_sippe_names == ["Adler", "Bär", "Wolf"]

    def test_updates_member_positions(self) -> None:
        state = make_state(["Adler", "Wolf"], members=[(1, "Wolf")])

        plan = plan_add(state, "Bär")

        assert len(plan.member_updates) == 1
        member, new_pos = plan.member_updates[0]
        assert member.sippe_name == "Wolf"
        assert new_pos == 3

    def test_raises_if_already_exists(self) -> None:
        state = make_state(["Adler", "Wolf"])

        with pytest.raises(SippeAlreadyExistsError) as exc_info:
            plan_add(state, "Adler")

        assert exc_info.value.name == "Adler"

    def test_description_mentions_add(self) -> None:
        state = make_state(["Adler"])

        plan = plan_add(state, "Bär")

        assert "Bär" in plan.description
        assert "Add" in plan.description


class TestPlanDelete:
    def test_deletes_sippe_without_members(self) -> None:
        state = make_state(["Adler", "Bär", "Wolf"])

        plan = plan_delete(state, "Bär", reassign_to=None)

        assert plan.new_sippe_names == ["Adler", "Wolf"]

    def test_updates_member_positions_after_delete(self) -> None:
        state = make_state(["Adler", "Bär", "Wolf"], members=[(1, "Wolf")])

        plan = plan_delete(state, "Bär", reassign_to=None)

        assert len(plan.member_updates) == 1
        member, new_pos = plan.member_updates[0]
        assert member.sippe_name == "Wolf"
        assert new_pos == 2

    def test_raises_if_not_found(self) -> None:
        state = make_state(["Adler", "Wolf"])

        with pytest.raises(SippeNotFoundError) as exc_info:
            plan_delete(state, "Bär", reassign_to=None)

        assert exc_info.value.name == "Bär"

    def test_raises_if_has_members_without_reassign(self) -> None:
        state = make_state(["Adler", "Wolf"], members=[(1, "Adler")])

        with pytest.raises(SippeHasMembersError) as exc_info:
            plan_delete(state, "Adler", reassign_to=None)

        assert exc_info.value.name == "Adler"
        assert exc_info.value.member_count == 1

    def test_reassigns_members_before_delete(self) -> None:
        state = make_state(
            ["Adler", "Bär", "Wolf"],
            members=[(1, "Adler"), (2, "Adler"), (3, "Wolf")],
        )

        plan = plan_delete(state, "Adler", reassign_to="Wolf")

        assert "Adler" not in plan.new_sippe_names
        assert plan.new_sippe_names == ["Bär", "Wolf"]

        reassigned_to_wolf = [
            (m, pos) for m, pos in plan.member_updates if m.user_id in (1, 2)
        ]
        assert len(reassigned_to_wolf) == 2
        for _, new_pos in reassigned_to_wolf:
            assert new_pos == 2

    def test_raises_if_reassign_target_not_found(self) -> None:
        state = make_state(["Adler", "Wolf"], members=[(1, "Adler")])

        with pytest.raises(SippeNotFoundError) as exc_info:
            plan_delete(state, "Adler", reassign_to="Unknown")

        assert exc_info.value.name == "Unknown"

    def test_raises_if_reassign_to_same(self) -> None:
        state = make_state(["Adler", "Wolf"], members=[(1, "Adler")])

        with pytest.raises(ValueError, match="same Sippe"):
            plan_delete(state, "Adler", reassign_to="Adler")

    def test_description_mentions_reassignment(self) -> None:
        state = make_state(["Adler", "Wolf"], members=[(1, "Adler")])

        plan = plan_delete(state, "Adler", reassign_to="Wolf")

        assert "Adler" in plan.description
        assert "Wolf" in plan.description
        assert "1 members" in plan.description


class TestPlanSort:
    def test_sorts_alphabetically(self) -> None:
        state = make_state(["Wolf", "Adler", "Bär"])

        plan = plan_sort(state)

        assert plan.new_sippe_names == ["Adler", "Bär", "Wolf"]

    def test_updates_member_positions(self) -> None:
        state = make_state(
            ["Wolf", "Adler", "Bär"],
            members=[(1, "Adler"), (2, "Wolf"), (3, "Bär")],
        )

        plan = plan_sort(state)

        update_dict = {m.sippe_name: new_pos for m, new_pos in plan.member_updates}
        assert update_dict["Adler"] == 1
        assert update_dict["Bär"] == 2
        assert update_dict["Wolf"] == 3

    def test_already_sorted_no_updates(self) -> None:
        state = make_state(
            ["Adler", "Bär", "Wolf"],
            members=[(1, "Adler"), (2, "Bär"), (3, "Wolf")],
        )

        plan = plan_sort(state)

        assert plan.member_updates == []

    def test_case_insensitive(self) -> None:
        state = make_state(["wolf", "Adler", "bär"])

        plan = plan_sort(state)

        assert plan.new_sippe_names == ["Adler", "bär", "wolf"]
