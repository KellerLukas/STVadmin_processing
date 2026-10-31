from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pandas as pd

from src.fairgate.fairgate_config import FairgateColumns
from src.mySTV.mystv_config import MembersColumns
from src.utils.utils import index_members


class DBSnapshotType(StrEnum):
    MYSTV = "mySTV"
    FAIRGATE = "Fairgate"


MEMBER_SUMMARY_COLUMNS: dict[DBSnapshotType, list[str]] = {
    DBSnapshotType.MYSTV: [
        MembersColumns.MEMBER_ID,
        MembersColumns.FIRST_NAME,
        MembersColumns.SURNAME,
        MembersColumns.MEMBERSHIP_ENTRY_DATES,
    ],
    DBSnapshotType.FAIRGATE: [
        FairgateColumns.STV_NUMBER,
        FairgateColumns.FIRST_NAME,
        FairgateColumns.SURNAME,
        FairgateColumns.ASSOCIATION_ENTRY_DATE,
    ],
}


@dataclass(eq=False)
class DBSnapshot:
    type: DBSnapshotType
    members: pd.DataFrame

    def __post_init__(self) -> None:
        id_column = MEMBER_SUMMARY_COLUMNS[self.type][0]
        self.members = index_members(self.members, id_column)

    def get_member(self, member_id: str) -> pd.Series[Any]:
        """Read a single row; comparison callers must not modify it."""
        member = self.members.loc[member_id]
        if isinstance(member, pd.DataFrame):
            raise TypeError(
                f"Expected one member for ID {member_id}, got multiple rows."
            )
        return member


@dataclass(eq=False)
class ComparisonResult:
    differences: pd.DataFrame
    missing_in_left: pd.DataFrame
    missing_in_right: pd.DataFrame
    left_label: str
    right_label: str
