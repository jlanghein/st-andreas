"""Sippe management utilities for Admidio.

This package provides safe Sippe management with full member reassignment.
"""

from st_andreas.sippe.operations import (
    MemberSippe,
    MutationPlan,
    SippeAlreadyExistsError,
    SippeHasMembersError,
    SippeInfo,
    SippeNotFoundError,
    SippeState,
    compute_member_updates,
    execute_mutation,
    fetch_member_assignments,
    fetch_sippe_names,
    fetch_sippe_state,
    is_sorted,
    plan_add,
    plan_delete,
    plan_sort,
)

__all__ = [
    "MemberSippe",
    "MutationPlan",
    "SippeAlreadyExistsError",
    "SippeHasMembersError",
    "SippeInfo",
    "SippeNotFoundError",
    "SippeState",
    "compute_member_updates",
    "execute_mutation",
    "fetch_member_assignments",
    "fetch_sippe_names",
    "fetch_sippe_state",
    "is_sorted",
    "plan_add",
    "plan_delete",
    "plan_sort",
]
