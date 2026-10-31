from functools import cached_property
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from src.comparison.comparison_config import (
    MAP_MYSTV_TO_FAIRGATE_COLUMN,
    MAP_WEBSITE_TO_INTERNAL_CAT,
)
from src.config.constants import FAIRGATE_CLUB_SLUG
from src.fairgate.fairgate_client import FairgateClient
from src.fairgate.fairgate_config import (
    FAIRGATE_DATE_COLS,
    FORMER_MEMBER_WEBSITE,
    FairgateColumns,
    FairgateConfigurationError,
)
from src.mySTV.mystv_config import (
    EMPTY_DATE_STR,
)
from src.utils.utils import index_members


class FairgateProcessor:
    def __init__(
        self,
        *,
        filename: str | Path | BinaryIO | None = None,
        club_slug: str | None = None,
    ) -> None:
        if filename is not None and club_slug is not None:
            raise ValueError("Choose filename or club_slug, not both.")
        if club_slug is not None and not club_slug:
            raise ValueError("club_slug must not be empty.")
        self.filename = filename
        self.club_slug = club_slug if club_slug is not None else FAIRGATE_CLUB_SLUG

    @cached_property
    def fg_data(self) -> pd.DataFrame:
        """Load and preprocess the selected source once, on first access."""
        if self.filename is not None:
            fg_data = self._read_excel(self.filename)
        else:
            with FairgateClient(club_slug=self.club_slug) as fg_client:
                fg_client.login()
                fg_data = self._read_excel(BytesIO(fg_client.export_contacts()))
        return self._preprocess_data(fg_data)

    def _preprocess_data(self, fg_data: pd.DataFrame) -> pd.DataFrame:
        expected_date_formats = ["%d.%m.%Y", "%Y-%m-%d %H:%M:%S"]
        for date_col in FAIRGATE_DATE_COLS:
            dates = fg_data[date_col].replace(["", EMPTY_DATE_STR], None)
            parsed_dates = pd.Series(pd.NaT, index=dates.index, dtype="datetime64[ns]")
            for expected_format in expected_date_formats:
                remaining = dates.notna() & parsed_dates.isna()
                if not remaining.any():
                    break
                parsed_dates.loc[remaining] = pd.to_datetime(
                    dates.loc[remaining], format=expected_format, errors="coerce"
                )
            if (dates.notna() & parsed_dates.isna()).any():
                raise FairgateConfigurationError(
                    f"Invalid date in {date_col}; expected one of {expected_date_formats}."
                )
            fg_data[date_col] = parsed_dates
        return fg_data

    @classmethod
    def from_excel(cls, filename: str | Path | BinaryIO) -> FairgateProcessor:
        """Select a manual export; reading is deferred until data is accessed."""
        return cls(filename=filename)

    @staticmethod
    def _read_excel(filename: str | Path | BinaryIO) -> pd.DataFrame:
        if not isinstance(filename, (str, Path)):
            filename.seek(0)
        # Keep identifiers as strings to preserve leading zeros.
        fg_data = pd.read_excel(filename, dtype=str)
        required_columns = set(FAIRGATE_DATE_COLS) | set(
            MAP_MYSTV_TO_FAIRGATE_COLUMN.values()
        )
        missing_columns = required_columns.difference(fg_data.columns)
        if missing_columns:
            raise FairgateConfigurationError(
                f"Fairgate export is missing required columns: {', '.join(sorted(missing_columns))}."
            )
        return fg_data

    @cached_property
    def _members_cached(self) -> pd.DataFrame:
        excluded = self.former_members.index.union(self.other_members.index)
        members = self.fg_data.drop(index=excluded).copy()

        if not members[FairgateColumns.WEBSITE].isin(MAP_WEBSITE_TO_INTERNAL_CAT).all():
            raise FairgateConfigurationError("Not all Websites are mapped.")

        return index_members(members, FairgateColumns.STV_NUMBER)

    @property
    def members(self) -> pd.DataFrame:
        return self._members_cached.copy()

    def clear_cached_data(self) -> None:
        """Reload the selected Excel or online source on the next data access."""
        self.__dict__.pop("_members_cached", None)
        self.__dict__.pop("fg_data", None)

    @property
    def former_members(self) -> pd.DataFrame:
        return self.fg_data.loc[
            self.fg_data[FairgateColumns.WEBSITE] == FORMER_MEMBER_WEBSITE
        ]

    @property
    def other_members(self) -> pd.DataFrame:
        return self.fg_data.loc[pd.isna(self.fg_data[FairgateColumns.WEBSITE])]

    def get_member(self, member_id: str) -> pd.Series[Any]:
        members = self._members_cached
        if member_id not in members.index:
            raise ValueError(f"Could not find member with id {member_id}")
        member = members.loc[member_id]
        if isinstance(member, pd.DataFrame):
            raise TypeError(
                f"Expected one member for ID {member_id}, got multiple rows."
            )
        return member.copy()
