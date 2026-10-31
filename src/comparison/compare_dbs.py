from collections.abc import Mapping
from typing import Any

import pandas as pd

from src.comparison.comparison_config import (
    CROSS_SYSTEM_IGNORED_COLUMNS,
    DIFF_FIELD_COLUMN,
    DIFF_FIRST_NAME_COLUMN,
    DIFF_ID_COLUMN,
    DIFF_IDENTITY_COLUMNS,
    DIFF_SURNAME_COLUMN,
    FAIRGATE_IGNORED_COLUMNS,
    INSTITUTES_FIELD,
    MAP_GENDER_TO_SALUTATION,
    MAP_MYSTV_TO_FAIRGATE_COLUMN,
    MAP_WEBSITE_TO_INTERNAL_CAT,
    MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE,
    MYSTV_IGNORED_COLUMNS,
)
from src.comparison.comparison_models import (
    MEMBER_SUMMARY_COLUMNS,
    ComparisonResult,
    DBSnapshot,
    DBSnapshotType,
)
from src.fairgate.fairgate_config import FairgateColumns
from src.mySTV.institute_functions import build_member_institute_functions
from src.mySTV.mystv_config import (
    MAPPER_FUNCTION_CODE_TO_NAME,
    MAPPER_INSTITUTE_CODE_TO_NAME,
    MembersColumns,
)
from src.mySTV.mystv_snapshot import MySTVSnapshot


def _values_equal(val_a: Any, val_b: Any) -> bool:
    """Compare scalars and simple containers, treating blank scalar values alike."""
    if isinstance(val_a, dict) or isinstance(val_b, dict):
        return (
            isinstance(val_a, dict)
            and isinstance(val_b, dict)
            and val_a.keys() == val_b.keys()
            and all(_values_equal(val_a[key], val_b[key]) for key in val_a)
        )
    if isinstance(val_a, (list, tuple)) or isinstance(val_b, (list, tuple)):
        return (
            isinstance(val_a, (list, tuple))
            and isinstance(val_b, (list, tuple))
            and len(val_a) == len(val_b)
            and all(_values_equal(a, b) for a, b in zip(val_a, val_b, strict=True))
        )
    if not pd.api.types.is_scalar(val_a) or not pd.api.types.is_scalar(val_b):
        raise TypeError(
            "Comparison supports scalar values and simple lists/dictionaries."
        )
    a_empty = bool(pd.isna(val_a)) or val_a == ""
    b_empty = bool(pd.isna(val_b)) or val_b == ""
    if a_empty or b_empty:
        return bool(a_empty and b_empty)
    return bool(val_a == val_b)


def _normalise_fairgate_value(column: str, value: Any) -> Any:
    mapping: Mapping[str, str]
    if column == FairgateColumns.WEBSITE:
        mapping = MAP_WEBSITE_TO_INTERNAL_CAT
    elif column == FairgateColumns.GENDER:
        mapping = MAP_GENDER_TO_SALUTATION
    else:
        return value
    if _values_equal(value, None):
        return value
    if not isinstance(value, str) or value not in mapping:
        raise ValueError(f"Unmapped Fairgate value in {column}.")
    return mapping[value]


def _institute_functions_by_member(
    snapshot: DBSnapshot,
) -> dict[str, set[tuple[str, str]]]:
    if snapshot.type == DBSnapshotType.FAIRGATE:
        return {}
    if not isinstance(snapshot, MySTVSnapshot):
        raise TypeError("MySTV comparisons require a MySTVSnapshot with institutes.")
    return build_member_institute_functions(snapshot.institutes)


def _format_institute_functions(institute_functions: set[tuple[str, str]]) -> str:
    return ", ".join(
        f"{MAPPER_INSTITUTE_CODE_TO_NAME.get(institute, institute)} ({institute}): "
        f"{MAPPER_FUNCTION_CODE_TO_NAME.get(function, function)} ({function})"
        for institute, function in sorted(institute_functions)
    )


def _validate_columns(snapshot: DBSnapshot, columns: list[str]) -> None:
    required = set(columns) | set(MEMBER_SUMMARY_COLUMNS[snapshot.type])
    missing = required.difference(snapshot.members.columns)
    if missing:
        raise ValueError(
            f"{snapshot.type} snapshot is missing columns: {', '.join(sorted(missing))}."
        )


def _field_differences(
    left_row: pd.Series[Any],
    right_row: pd.Series[Any],
    column_pairs: list[tuple[str, str]],
    *,
    normalise_right_for_fairgate: bool = False,
) -> list[tuple[str, Any, Any]]:
    differences: list[tuple[str, Any, Any]] = []
    for left_column, right_column in column_pairs:
        left_value, right_value = left_row[left_column], right_row[right_column]
        if normalise_right_for_fairgate:
            right_value = _normalise_fairgate_value(right_column, right_value)
        if not _values_equal(left_value, right_value):
            field_name = (
                left_column
                if left_column == right_column
                else f"{left_column} / {right_column}"
            )
            # Display original values so whitespace/Unicode differences stay visible.
            differences.append((field_name, left_value, right_row[right_column]))
    return differences


def _build_comparison_result(
    left: DBSnapshot,
    right: DBSnapshot,
    differences: dict[str, list[tuple[str, Any, Any]]],
    *,
    left_label: str,
    right_label: str,
) -> ComparisonResult:
    rows = []
    _, first_name_col, surname_col, _ = MEMBER_SUMMARY_COLUMNS[left.type]
    for member_id, member_differences in differences.items():
        if not member_differences:
            continue
        member = left.get_member(member_id)
        for field_name, left_value, right_value in member_differences:
            rows.append(
                {
                    DIFF_ID_COLUMN: member_id,
                    DIFF_FIRST_NAME_COLUMN: member[first_name_col],
                    DIFF_SURNAME_COLUMN: member[surname_col],
                    DIFF_FIELD_COLUMN: field_name,
                    left_label: str(left_value),
                    right_label: str(right_value),
                }
            )
    return ComparisonResult(
        left_label=left_label,
        right_label=right_label,
        differences=pd.DataFrame(
            rows,
            columns=[
                *DIFF_IDENTITY_COLUMNS,
                DIFF_FIELD_COLUMN,
                left_label,
                right_label,
            ],
        ),
        missing_in_left=right.members.loc[
            ~right.members.index.isin(left.members.index),
            MEMBER_SUMMARY_COLUMNS[right.type],
        ].copy(),
        missing_in_right=left.members.loc[
            ~left.members.index.isin(right.members.index),
            MEMBER_SUMMARY_COLUMNS[left.type],
        ].copy(),
    )


def compare_current_to_snapshot(
    *, current: DBSnapshot, snapshot: DBSnapshot
) -> ComparisonResult:
    if current.type != snapshot.type:
        raise ValueError(
            "Current data and snapshot must come from the same source. "
            "Use compare_mystv_to_fairgate for cross-system comparisons."
        )
    current_institutes = _institute_functions_by_member(current)
    snapshot_institutes = _institute_functions_by_member(snapshot)
    if current.type == DBSnapshotType.MYSTV:
        columns: list[str] = [
            col for col in MembersColumns if col not in MYSTV_IGNORED_COLUMNS
        ]
    else:
        columns = [
            col for col in FairgateColumns if col not in FAIRGATE_IGNORED_COLUMNS
        ]
    # Optional columns absent from both snapshots need no comparison.
    columns = [
        col for col in columns if col in current.members or col in snapshot.members
    ]
    _validate_columns(current, columns)
    _validate_columns(snapshot, columns)
    column_pairs = [(col, col) for col in columns]
    differences = {}
    for member_id in current.members.index.intersection(
        snapshot.members.index, sort=False
    ):
        member_differences = _field_differences(
            current.get_member(member_id), snapshot.get_member(member_id), column_pairs
        )
        current_institute_functions = current_institutes.get(member_id, set())
        snapshot_institute_functions = snapshot_institutes.get(member_id, set())
        if current_institute_functions != snapshot_institute_functions:
            member_differences.append(
                (
                    INSTITUTES_FIELD,
                    _format_institute_functions(current_institute_functions),
                    _format_institute_functions(snapshot_institute_functions),
                )
            )
        differences[member_id] = member_differences
    return _build_comparison_result(
        current, snapshot, differences, left_label="Aktuell", right_label="Snapshot"
    )


def compare_mystv_to_fairgate(
    *, mystv: MySTVSnapshot, fairgate: DBSnapshot
) -> ComparisonResult:
    if not isinstance(mystv, MySTVSnapshot):
        raise TypeError("mystv must be a MySTVSnapshot with institutes.")
    if fairgate.type != DBSnapshotType.FAIRGATE:
        raise ValueError("fairgate must be a Fairgate snapshot.")
    column_pairs: list[tuple[str, str]] = [
        (mystv_col, fg_col)
        for mystv_col, fg_col in MAP_MYSTV_TO_FAIRGATE_COLUMN.items()
        if mystv_col not in CROSS_SYSTEM_IGNORED_COLUMNS
    ]
    _validate_columns(mystv, [mystv_col for mystv_col, _ in column_pairs])
    _validate_columns(fairgate, [fg_col for _, fg_col in column_pairs])
    institutes = build_member_institute_functions(mystv.institutes)
    known_functions = set(MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE.values())
    differences = {}
    for member_id in mystv.members.index.intersection(
        fairgate.members.index, sort=False
    ):
        fg_member = fairgate.get_member(member_id)
        member_differences = _field_differences(
            mystv.get_member(member_id),
            fg_member,
            column_pairs,
            normalise_right_for_fairgate=True,
        )
        website = fg_member[FairgateColumns.WEBSITE]
        fg_code = MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE.get(website)
        fg_functions = {fg_code} if fg_code is not None else set()
        institute_functions = institutes.get(member_id, set())
        # Fairgate's website represents only these youth functions, not every institute.
        mystv_functions = {
            function for _, function in institute_functions
        } & known_functions
        if mystv_functions != fg_functions:
            member_differences.append(
                (
                    f"{INSTITUTES_FIELD} / {FairgateColumns.WEBSITE}",
                    _format_institute_functions(institute_functions),
                    website,
                )
            )
        differences[member_id] = member_differences
    return _build_comparison_result(
        mystv,
        fairgate,
        differences,
        left_label=DBSnapshotType.MYSTV.value,
        right_label=DBSnapshotType.FAIRGATE.value,
    )
