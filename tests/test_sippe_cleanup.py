"""Tests for SIPPE cleanup operations."""

from st_andreas.sippe.cleanup import (
    MemberSippe,
    build_cleanup_plan,
)


class TestBuildCleanupPlan:
    """Tests for build_cleanup_plan function."""

    def test_detects_already_sorted(self) -> None:
        sippe_names = ["Adler", "Bär", "Wolf"]
        members = [
            MemberSippe(user_id=1, usd_id=101, current_position=1, sippe_name="Adler"),
            MemberSippe(user_id=2, usd_id=102, current_position=3, sippe_name="Wolf"),
        ]

        plan = build_cleanup_plan(sippe_names, members)

        assert plan.is_already_sorted
        assert plan.members_to_update == []

    def test_detects_unsorted(self) -> None:
        sippe_names = ["Wolf", "Adler", "Bär"]
        members = [
            MemberSippe(user_id=1, usd_id=101, current_position=2, sippe_name="Adler"),
            MemberSippe(user_id=2, usd_id=102, current_position=1, sippe_name="Wolf"),
        ]

        plan = build_cleanup_plan(sippe_names, members)

        assert not plan.is_already_sorted

    def test_calculates_correct_new_positions(self) -> None:
        sippe_names = ["Wolf", "Adler", "Bär"]
        members = [
            MemberSippe(user_id=1, usd_id=101, current_position=2, sippe_name="Adler"),
            MemberSippe(user_id=2, usd_id=102, current_position=1, sippe_name="Wolf"),
            MemberSippe(user_id=3, usd_id=103, current_position=3, sippe_name="Bär"),
        ]

        plan = build_cleanup_plan(sippe_names, members)

        updates_by_name = {
            m.sippe_name: new_pos for m, new_pos in plan.members_to_update
        }

        assert updates_by_name["Adler"] == 1
        assert updates_by_name["Bär"] == 2
        assert updates_by_name["Wolf"] == 3

    def test_counts_members_per_sippe(self) -> None:
        sippe_names = ["Adler", "Wolf"]
        members = [
            MemberSippe(user_id=1, usd_id=101, current_position=1, sippe_name="Adler"),
            MemberSippe(user_id=2, usd_id=102, current_position=1, sippe_name="Adler"),
            MemberSippe(user_id=3, usd_id=103, current_position=2, sippe_name="Wolf"),
        ]

        plan = build_cleanup_plan(sippe_names, members)

        counts_by_name = {s.name: s.member_count for s in plan.current_sippe_list}

        assert counts_by_name["Adler"] == 2
        assert counts_by_name["Wolf"] == 1

    def test_sorted_list_has_correct_positions(self) -> None:
        sippe_names = ["Wolf", "Adler", "Bär"]
        members: list[MemberSippe] = []

        plan = build_cleanup_plan(sippe_names, members)

        sorted_names = [s.name for s in plan.sorted_sippe_list]
        sorted_positions = [s.current_position for s in plan.sorted_sippe_list]

        assert sorted_names == ["Adler", "Bär", "Wolf"]
        assert sorted_positions == [1, 2, 3]

    def test_case_insensitive_sort(self) -> None:
        sippe_names = ["wolf", "Adler", "Bär"]
        members: list[MemberSippe] = []

        plan = build_cleanup_plan(sippe_names, members)

        sorted_names = [s.name for s in plan.sorted_sippe_list]

        assert sorted_names == ["Adler", "Bär", "wolf"]

    def test_empty_sippe_list(self) -> None:
        plan = build_cleanup_plan([], [])

        assert plan.is_already_sorted
        assert plan.current_sippe_list == []
        assert plan.sorted_sippe_list == []
        assert plan.members_to_update == []
