from typing import Any

import pandas as pd

from src.comparison.comparison_config import (
    MAP_FAIRGATE_TO_MYSTV_COLUMN,
    MAP_GENDER_TO_SALUTATION,
    MAP_MYSTV_TO_FAIRGATE_COLUMN,
    MAP_WEBSITE_TO_INTERNAL_CAT,
    MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE,
    DBSnapshot,
    DBSnapshotType,
)
from src.fairgate.fairgate_config import FairgateColumns
from src.mySTV.mystv_config import (
    MAPPER_FUNCTION_CODE_TO_NAME,
    MembersColumns,
)
from src.mySTV.mystv_processor import (
    MySTVProcessor,
)
from src.mySTV.mystv_snapshot import MySTVSnapshot


def _values_equal(val_a: Any, val_b: Any) -> bool:
    def _val_empty(val):
        return pd.isna(val) or val == "" or val is None

    a_empty = _val_empty(val_a)
    b_empty = _val_empty(val_b)
    if a_empty or b_empty:
        return bool(a_empty and b_empty)
    return bool(val_a == val_b)


def _convert_fg_to_mystv_row(fg_row: pd.Series[Any]) -> pd.Series[Any]:
    fg_row = fg_row[MAP_FAIRGATE_TO_MYSTV_COLUMN.keys()]
    converted = fg_row.rename(MAP_FAIRGATE_TO_MYSTV_COLUMN, inplace=False)
    for fg_col, mystv_col in MAP_FAIRGATE_TO_MYSTV_COLUMN.items():
        if fg_col not in fg_row:
            continue
        if fg_col == FairgateColumns.WEBSITE:
            converted[mystv_col] = MAP_WEBSITE_TO_INTERNAL_CAT[fg_row[fg_col]]
        if fg_col == FairgateColumns.GENDER:
            converted[mystv_col] = MAP_GENDER_TO_SALUTATION[fg_row[fg_col]]
    return converted


def find_db_row_diffs_mystv_fg(
    mystv_row: pd.Series[Any], fg_row: pd.Series[Any]
) -> list[MembersColumns]:
    diffs: list[MembersColumns] = []
    ignore = [
        MembersColumns.REGIONAL_ABO,
        MembersColumns.GYM_LIVE_ABO,
        MembersColumns.LANGUAGE,
        MembersColumns.ADDRESS_RELEASE,
        MembersColumns.MY_STV_COMMENT,
        MembersColumns.MEMBERSHIP_ENTRY_DATES,
    ]
    ignore += [
        col for col in MembersColumns if col not in MAP_MYSTV_TO_FAIRGATE_COLUMN.keys()
    ]
    fg_row_converted = _convert_fg_to_mystv_row(fg_row=fg_row)
    return find_db_row_diffs_mystv_mystv(mystv_row, fg_row_converted, ignore=ignore)


def find_db_row_diffs_fg_fg(
    row_a: pd.Series[Any],
    row_b: pd.Series[Any],
    ignore: list[FairgateColumns] | None = None,
) -> list[FairgateColumns]:
    diffs: list[FairgateColumns] = []
    ignore = ignore or []
    for col in FairgateColumns:
        if col in ignore:
            continue
        if not _values_equal(row_a[col], row_b[col]):
            diffs.append(col)
    return diffs


def find_db_row_diffs_mystv_mystv(
    row_a: pd.Series[Any],
    row_b: pd.Series[Any],
    ignore: list[MembersColumns] | None = None,
) -> list[MembersColumns]:
    diffs: list[MembersColumns] = []
    ignore = ignore or None
    for col in MembersColumns:
        if col in ignore:
            continue
        if not _values_equal(row_a[col], row_b[col]):
            diffs.append(col)
    return diffs


def find_db_snapshot_row_diffs(
    member_id: str, snapshot_a: DBSnapshot, snapshot_b: DBSnapshot
) -> list[MembersColumns] | list[FairgateColumns]:
    if not isinstance(member_id, str):
        raise TypeError("Member IDs in the index must be strings.")
    a_row = snapshot_a.members.loc[member_id]
    if isinstance(a_row, pd.DataFrame):
        raise TypeError(
            f"Expected one member for ID {member_id}, got multiple rows in snapshot a."
        )
    b_row = snapshot_b.members.loc[member_id]
    if isinstance(b_row, pd.DataFrame):
        raise TypeError(
            f"Expected one member for ID {member_id}, got multiple rows in snapshot b."
        )
    if all(
        s_type == DBSnapshotType.MYSTV for s_type in [snapshot_a.type, snapshot_b.type]
    ):
        return find_db_row_diffs_mystv_mystv(a_row, b_row)
    if all(
        s_type == DBSnapshotType.FAIRGATE
        for s_type in [snapshot_a.type, snapshot_b.type]
    ):
        return find_db_row_diffs_fg_fg(a_row, b_row)
    if snapshot_a.type == DBSnapshotType.MYSTV:
        return find_db_row_diffs_mystv_fg(mystv_row=a_row, fg_row=b_row)
    return find_db_row_diffs_mystv_fg(mystv_row=b_row, fg_row=a_row)


def get_functions_for_member_from_fg_snapshot(
    member_id: str, snapshot: DBSnapshot
) -> list[str]:
    if not snapshot.type == DBSnapshotType.FAIRGATE:
        raise ValueError("Expected Fairgate snapshot")
    website = snapshot.members.loc[member_id][FairgateColumns.WEBSITE]
    return [MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE.get(website)]


def get_functions_for_member_from_mystv_snapshot(
    member_id: str, snapshot: DBSnapshot
) -> list[str]:
    if not snapshot.type == DBSnapshotType.MYSTV:
        raise ValueError("Expected mySTV snapshot")
    return MySTVProcessor.get_functions_for_member_unguarded(
        member_id=member_id, institutes=snapshot.institutes
    )


def are_there_db_snapshot_function_diffs(
    member_id: str, snapshot_a=DBSnapshot, snapshot_b=DBSnapshot
) -> bool:
    function_sets = []
    for snapshot in [snapshot_a, snapshot_b]:
        if snapshot.type == DBSnapshotType.MYSTV:
            function_sets.append(
                set(
                    get_functions_for_member_from_mystv_snapshot(
                        member_id=member_id, snapshot=snapshot
                    )
                )
            )
        else:
            function_sets.append(
                set(
                    get_functions_for_member_from_fg_snapshot(
                        member_id=member_id, snapshot=snapshot
                    )
                )
            )
    return function_sets[0] == function_sets[1]


def compare_db_snapshots(
    snapshot_a: DBSnapshot, snapshot_b: DBSnapshot
) -> tuple[
    dict[str, list[MembersColumns] | list[FairgateColumns]],
    list[str],
    list[str],
    list[str],
]:
    a_ids = set(snapshot_a.members.index)
    b_ids = set(snapshot_b.members.index)
    b_ids_missing_in_a = [
        member_id for member_id in snapshot_b.members.index if member_id not in a_ids
    ]
    a_ids_missing_in_b = [
        member_id for member_id in snapshot_a.members.index if member_id not in b_ids
    ]
    diff_columns = {}
    diff_functions = []
    for member_id, a_row in snapshot_a.members.iterrows():
        if not isinstance(member_id, str):
            raise TypeError("Member IDs in the index must be strings.")
        if member_id not in b_ids:
            continue
        member_diffs = find_db_snapshot_row_diffs(
            member_id=member_id, snapshot_a=snapshot_a, snapshot_b=snapshot_b
        )
        if member_diffs:
            diff_columns[member_id] = member_diffs
        if are_there_db_snapshot_function_diffs(
            member_id, snapshot_a=snapshot_a, snapshot_b=snapshot_b
        ):
            diff_functions[member_id]
    return diff_columns, diff_functions, a_ids_missing_in_b, b_ids_missing_in_a


def get_diff_summary_mystv_fg(
    diff_columns: dict[str, list[MembersColumns]],
    diff_functions: list[str],
    mystv_snapshot: MySTVSnapshot,
    fg_snapshot: DBSnapshot,
) -> pd.DataFrame:
    """Return one row per differing field, keeping both source values visible."""
    columns = ["STV-Nummer", "Vorname", "Nachname", "Feld", "mySTV", "Fairgate"]
    rows = []
    for member_id, cols in diff_columns.items():
        mystv_row = mystv_snapshot.members.loc[member_id]
        fg_row = fg_snapshot.members.loc[member_id]
        for col in cols:
            fg_col = MAP_MYSTV_TO_FAIRGATE_COLUMN[col]
            rows.append(
                {
                    "STV-Nummer": member_id,
                    "Vorname": mystv_row[MembersColumns.FIRST_NAME],
                    "Nachname": mystv_row[MembersColumns.SURNAME],
                    "Feld": f"{col} / {fg_col}",
                    "mySTV": str(mystv_row[col]),
                    "Fairgate": str(fg_row[fg_col]),
                }
            )
    for member_id in diff_functions:
        mystv_row = mystv_snapshot.members.loc[member_id]
        fg_row = fg_snapshot.members.loc[member_id]
        member_function_codes = get_functions_for_member_from_mystv_snapshot(
            member_id=member_id, snapshot=mystv_snapshot
        )
        functions = [
            MAPPER_FUNCTION_CODE_TO_NAME[code] for code in member_function_codes
        ]
        rows.append(
            {
                "STV-Nummer": member_id,
                "Vorname": mystv_row[MembersColumns.FIRST_NAME],
                "Nachname": mystv_row[MembersColumns.SURNAME],
                "Feld": f"Riegen / {FairgateColumns.WEBSITE}",
                "mySTV": ", ".join(functions),
                "Fairgate": str(fg_row[FairgateColumns.WEBSITE]),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def get_diff_summary_mystv_current_historic(
    diff_columns: dict[str, list[MembersColumns]],
    diff_functions: list[str],
    current: MySTVSnapshot,
    historic: MySTVSnapshot,
) -> pd.DataFrame:
    """Return one row per differing field, keeping both source values visible."""
    columns = ["STV-Nummer", "Vorname", "Nachname", "Feld", "Aktuell", "Snapshot"]
    rows = []
    for member_id, cols in diff_columns.items():
        current_row = current.members.loc[member_id]
        historic_row = historic.members.loc[member_id]
        for col in cols:
            rows.append(
                {
                    "STV-Nummer": member_id,
                    "Vorname": current_row[MembersColumns.FIRST_NAME],
                    "Nachname": current_row[MembersColumns.SURNAME],
                    "Feld": col,
                    "Aktuell": str(current_row[col]),
                    "Snapshot": str(historic_row[col]),
                }
            )
    for member_id in diff_functions:
        current_row = current.members.loc[member_id]
        historic_row = historic.members.loc[member_id]
        current_function_codes = get_functions_for_member_from_mystv_snapshot(
            member_id=member_id, snapshot=current
        )
        current_functions = [
            MAPPER_FUNCTION_CODE_TO_NAME[code] for code in historic_function_codes
        ]
        historic_function_codes = get_functions_for_member_from_mystv_snapshot(
            member_id=member_id, snapshot=historic
        )
        historic_functions = [
            MAPPER_FUNCTION_CODE_TO_NAME[code] for code in current_function_codes
        ]
        rows.append(
            {
                "STV-Nummer": member_id,
                "Vorname": current[MembersColumns.FIRST_NAME],
                "Nachname": current[MembersColumns.SURNAME],
                "Feld": "Riegen",
                "Aktuell": ", ".join(current_functions),
                "Snapshot": ", ".join(historic_functions),
            }
        )
    return pd.DataFrame(rows, columns=columns)
