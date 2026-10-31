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


def _column_pairs(left: DBSnapshot, right: DBSnapshot) -> list[tuple[str, str]]:
    if left.type != right.type:
        pairs: list[tuple[str, str]] = [
            (mystv_col, fg_col)
            for mystv_col, fg_col in MAP_MYSTV_TO_FAIRGATE_COLUMN.items()
            if mystv_col not in CROSS_SYSTEM_IGNORED_COLUMNS
        ]
        if left.type == DBSnapshotType.FAIRGATE:
            pairs = [(fg_col, mystv_col) for mystv_col, fg_col in pairs]
        return pairs
    # Optional columns absent from both exports need no comparison. A column
    # present on only one side is a schema mismatch.
    if left.type == DBSnapshotType.MYSTV:
        return [
            (col, col)
            for col in MembersColumns
            if col not in MYSTV_IGNORED_COLUMNS
            and (col in left.members or col in right.members)
        ]
    return [
        (col, col)
        for col in FairgateColumns
        if col not in FAIRGATE_IGNORED_COLUMNS
        and (col in left.members or col in right.members)
    ]


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


def _institute_functions_difference(
    left_type: DBSnapshotType,
    right_type: DBSnapshotType,
    left_row: pd.Series[Any],
    right_row: pd.Series[Any],
    left_institute_functions: set[tuple[str, str]],
    right_institute_functions: set[tuple[str, str]],
) -> tuple[str, str, str] | None:
    if left_type == right_type:
        if (
            left_type == DBSnapshotType.MYSTV
            and left_institute_functions != right_institute_functions
        ):
            return (
                INSTITUTES_FIELD,
                _format_institute_functions(left_institute_functions),
                _format_institute_functions(right_institute_functions),
            )
        return None  # Fairgate's website is already compared as a regular field.

    if left_type == DBSnapshotType.MYSTV:
        mystv_institute_functions, fg_row = left_institute_functions, right_row
    else:
        mystv_institute_functions, fg_row = right_institute_functions, left_row
    website = fg_row[FairgateColumns.WEBSITE]
    fg_code = MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE.get(website)
    fg_functions = {fg_code} if fg_code is not None else set()
    # Fairgate's website represents only these youth functions, not every group.
    known_functions = set(MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE.values())
    mystv_functions = {
        function for _, function in mystv_institute_functions
    } & known_functions
    if mystv_functions == fg_functions:
        return None
    mystv_value = _format_institute_functions(mystv_institute_functions)
    if left_type == DBSnapshotType.MYSTV:
        return (
            f"{INSTITUTES_FIELD} / {FairgateColumns.WEBSITE}",
            mystv_value,
            str(website),
        )
    return (
        f"{FairgateColumns.WEBSITE} / {INSTITUTES_FIELD}",
        str(website),
        mystv_value,
    )


def compare_db_snapshots(
    snapshot_a: DBSnapshot, snapshot_b: DBSnapshot
) -> ComparisonResult:
    """Compare without I/O; A is current/left, B is historic/right for one source."""
    pairs = _column_pairs(snapshot_a, snapshot_b)
    for snapshot, side in ((snapshot_a, 0), (snapshot_b, 1)):
        required = {pair[side] for pair in pairs} | set(
            MEMBER_SUMMARY_COLUMNS[snapshot.type]
        )
        missing = required.difference(snapshot.members.columns)
        if missing:
            raise ValueError(
                f"{snapshot.type} snapshot is missing columns: {', '.join(sorted(missing))}."
            )
    same_source = snapshot_a.type == snapshot_b.type
    left_label, right_label = (
        ("Aktuell", "Snapshot")
        if same_source
        else (snapshot_a.type.value, snapshot_b.type.value)
    )
    a_ids, b_ids = set(snapshot_a.members.index), set(snapshot_b.members.index)
    missing_in_left = [
        member_id for member_id in snapshot_b.members.index if member_id not in a_ids
    ]
    missing_in_right = [
        member_id for member_id in snapshot_a.members.index if member_id not in b_ids
    ]
    a_institute_functions = _institute_functions_by_member(snapshot_a)
    b_institute_functions = _institute_functions_by_member(snapshot_b)
    rows = []
    _, first_name_col, surname_col, _ = MEMBER_SUMMARY_COLUMNS[snapshot_a.type]
    for member_id in snapshot_a.members.index:
        if not isinstance(member_id, str):
            raise TypeError("Member IDs in the index must be strings.")
        if member_id not in b_ids:
            continue
        a_row = snapshot_a.get_member(member_id)
        b_row = snapshot_b.get_member(member_id)
        differences: list[tuple[str, Any, Any]] = []
        for a_col, b_col in pairs:
            a_value, b_value = a_row[a_col], b_row[b_col]
            if not same_source:
                if snapshot_a.type == DBSnapshotType.FAIRGATE:
                    a_value = _normalise_fairgate_value(a_col, a_value)
                else:
                    b_value = _normalise_fairgate_value(b_col, b_value)
            if not _values_equal(a_value, b_value):
                field_name = a_col if same_source else f"{a_col} / {b_col}"
                differences.append((field_name, a_row[a_col], b_row[b_col]))
        institute_functions_diff = _institute_functions_difference(
            snapshot_a.type,
            snapshot_b.type,
            a_row,
            b_row,
            a_institute_functions.get(member_id, set()),
            b_institute_functions.get(member_id, set()),
        )
        if institute_functions_diff is not None:
            differences.append(institute_functions_diff)
        for field_name, a_value, b_value in differences:
            rows.append(
                {
                    DIFF_ID_COLUMN: member_id,
                    DIFF_FIRST_NAME_COLUMN: a_row[first_name_col],
                    DIFF_SURNAME_COLUMN: a_row[surname_col],
                    DIFF_FIELD_COLUMN: field_name,
                    left_label: str(a_value),
                    right_label: str(b_value),
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
        missing_in_left=snapshot_b.members.loc[
            missing_in_left, MEMBER_SUMMARY_COLUMNS[snapshot_b.type]
        ].copy(),
        missing_in_right=snapshot_a.members.loc[
            missing_in_right, MEMBER_SUMMARY_COLUMNS[snapshot_a.type]
        ].copy(),
    )
