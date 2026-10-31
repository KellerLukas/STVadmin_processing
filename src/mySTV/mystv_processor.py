import copy
import logging
from functools import cached_property
from typing import Any

import pandas as pd

from src.config.paths import (
    FILENAME_NEWSLETTER_BLACKLIST,
    WORKING_DIR_PATH,
)
from src.mySTV.institute_functions import build_member_institute_functions
from src.mySTV.mystv_client_v2 import MySTVClientV2
from src.mySTV.mystv_config import (
    EMPTY_DATE_STR,
    EXPECTED_DATE_FORMAT_PER_COL,
    INSTITUTES_TYPE,
    MAP_CATEGORY_TO_INTERNAL,
    MAPPER_FUNCTION_CODE_TO_NAME,
    MAPPER_INSTITUTE_CODE_TO_NAME,
    InternalCategory,
    MembersColumns,
    MembershipCategory,
    MySTVConfigurationError,
)
from src.utils.utils import calculate_age_at_ts, index_members

logger = logging.getLogger(__name__)


class MySTVProcessor:
    def __init__(self, club_id: str):
        self.club_id = club_id

    @cached_property
    def mystv_client(self) -> MySTVClientV2:
        client = MySTVClientV2(club_id=self.club_id)
        try:
            client.login()
        except BaseException:
            try:
                client.close()
            except BaseException:  # noqa: BLE001
                # Preserve the original login error if secondary cleanup fails.
                logger.warning(
                    "Could not fully clean up a MySTV client after initialization failed."
                )
            raise
        return client

    def close(self) -> None:
        """Close the cached client; call before replacing this processor in a notebook."""
        client = self.__dict__.get("mystv_client")
        if client is not None:
            client.close()

    def clear_cached_data(self) -> None:
        """Discard local member and institute data; keep the authenticated client."""
        self.__dict__.pop("_members_cached", None)
        self.__dict__.pop("_institutes_cached", None)
        logger.info("Cleared cached MySTV member and institute data")

    # Cache on this processor instance; public properties return defensive copies.
    @cached_property
    def _members_cached(self) -> pd.DataFrame:
        """Return a DataFrame of all members in the club."""
        raw_members = self.mystv_client.get_members_stream_raw()
        if not (len(raw_members) == 2 and raw_members[1] == ""):
            raise MySTVConfigurationError(
                "MySTV members stream did not return expected data."
            )
        members_df = pd.DataFrame(raw_members[0])
        members_df = self._apply_member_data_enrichment(members_df)
        return index_members(members_df, MembersColumns.MEMBER_ID)

    @property
    def members(self) -> pd.DataFrame:
        return copy.deepcopy(self._members_cached)

    @cached_property
    def _institutes_cached(self) -> INSTITUTES_TYPE:
        raw_groups = self.mystv_client.get_institute_members_raw()
        if not isinstance(raw_groups, list):
            raise MySTVConfigurationError(
                "MySTV institute response must contain a list of institute members."
            )
        groups: INSTITUTES_TYPE = {}
        for group in raw_groups:
            if not isinstance(group, dict):
                raise MySTVConfigurationError(
                    "MySTV institute response contains an invalid institute member."
                )
            institute_code = group.get("instituteCode")
            function_code = group.get("instituteFunctionCode")
            member_id = group.get("memberId")
            if not isinstance(institute_code, str):
                raise MySTVConfigurationError(
                    "MySTV institute member has an invalid institute code."
                )
            if not isinstance(function_code, str):
                raise MySTVConfigurationError(
                    "MySTV institute member has an invalid function code."
                )
            if not isinstance(member_id, str):
                raise MySTVConfigurationError(
                    "MySTV institute member has an invalid member ID."
                )
            functions = groups.setdefault(institute_code, {})
            if function_code not in functions:
                functions[function_code] = []
            functions[function_code].append(member_id)
        return groups

    @property
    def institutes(self) -> INSTITUTES_TYPE:
        return copy.deepcopy(self._institutes_cached)

    def get_member(self, member_id: str) -> pd.Series[Any]:
        members = self._members_cached
        if member_id not in members.index:
            raise ValueError(f"Could not find member with id {member_id}")
        member = members.loc[member_id]
        if isinstance(member, pd.DataFrame):
            raise TypeError(
                f"Expected one member for ID {member_id}, got multiple rows."
            )
        return copy.deepcopy(member)

    def get_functions_for_member(self, member_id: str) -> list[str]:
        if member_id not in self._members_cached.index:
            raise ValueError(f"Could not find member with id {member_id}")
        return self.get_functions_for_member_unguarded(
            member_id=member_id, institutes=self._institutes_cached
        )

    @staticmethod
    def get_functions_for_member_unguarded(
        member_id: str, institutes: INSTITUTES_TYPE
    ) -> list[str]:
        institute_functions = build_member_institute_functions(institutes).get(
            member_id, set()
        )
        return sorted({function_code for _, function_code in institute_functions})

    def _apply_member_data_enrichment(self, members_df: pd.DataFrame) -> pd.DataFrame:
        """Add any additional columns or transformations to the members DataFrame."""
        for method in [
            self._build_combined_emails_col,
            self._build_primary_email_col,
            self._build_internal_category_col,
            self._parse_dates,
            self._build_age_col,
            self._build_gets_newsletter_col,
        ]:
            members_df = method(members_df)
        return members_df

    def _build_combined_emails_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        email_columns = [
            MembersColumns.EMAIL_PRIVATE,
            MembersColumns.EMAIL_ALTERNATIVE,
            MembersColumns.EMAIL_VEREIN,
            MembersColumns.EMAIL_VERBAND,
        ]

        def combine_emails(row: pd.Series[Any]) -> str | float:
            emails = [
                value
                for col in email_columns
                if isinstance((value := row[col]), str) and value.strip()
            ]
            return "; ".join(emails) if emails else float("nan")

        members_df[MembersColumns._COMBINED_EMAILS] = members_df.apply(
            combine_emails, axis=1
        )
        return members_df

    def _build_primary_email_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        email_columns = [
            MembersColumns.EMAIL_PRIVATE,
            MembersColumns.EMAIL_ALTERNATIVE,
            MembersColumns.EMAIL_VEREIN,
            MembersColumns.EMAIL_VERBAND,
        ]

        def get_primary_email(row: pd.Series[Any]) -> str | float:
            for col in email_columns:
                value = row[col]
                if isinstance(value, str) and value.strip():
                    return value
            return float("nan")

        members_df[MembersColumns._PRIMARY_EMAIL] = members_df.apply(
            get_primary_email, axis=1
        )
        return members_df

    def _build_internal_category_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        def get_internal_cat(row: pd.Series[Any]) -> InternalCategory:
            membership_cat = row[MembersColumns.MEMBERSHIP_CATEGORIES]
            membership_addition = row[MembersColumns.MEMBERSHIP_ADDITIONS]
            category_tuple = (membership_cat, membership_addition)

            internal_cat = MAP_CATEGORY_TO_INTERNAL.get(category_tuple)
            if internal_cat is not None:
                return internal_cat
            raise MySTVConfigurationError(
                f"Unable to map category tuple to internal category: {category_tuple}"
            )

        members_df[MembersColumns._INTERNAL_CATEGORY] = members_df.apply(
            get_internal_cat, axis=1
        )
        return members_df

    def _parse_dates(self, members_df: pd.DataFrame) -> pd.DataFrame:
        for col, expected_format in EXPECTED_DATE_FORMAT_PER_COL.items():
            members_df[col] = pd.to_datetime(
                members_df[col].replace(["", EMPTY_DATE_STR], None),
                format=expected_format,
            )
        return members_df

    def _build_age_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        ts = pd.Timestamp.now()

        def get_age(row: pd.Series[Any]) -> int:
            birthday = row[MembersColumns.BIRTHDAY]
            if pd.isna(birthday):
                raise MySTVConfigurationError(
                    f"Missing birthday for member {row[MembersColumns.MEMBER_ID]}."
                )
            return calculate_age_at_ts(birthday=birthday, ts=ts)

        members_df[MembersColumns._AGE] = members_df.apply(get_age, axis=1)
        return members_df

    def _build_gets_newsletter_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        blacklist = pd.read_excel(
            WORKING_DIR_PATH + FILENAME_NEWSLETTER_BLACKLIST, header=0
        )
        emails_on_blacklist = blacklist["EMAIL"].values
        members_df[MembersColumns._GETS_NEWSLETTER] = ~members_df[
            MembersColumns._PRIMARY_EMAIL
        ].isin(emails_on_blacklist)
        return members_df

    def institute_id_to_name(self, institute_code: str) -> str:
        return MAPPER_INSTITUTE_CODE_TO_NAME.get(
            institute_code, f"Unknown Institute Code {institute_code}"
        )

    def function_id_to_name(self, function_code: str) -> str:
        return MAPPER_FUNCTION_CODE_TO_NAME.get(
            function_code, f"Unknown Function Code {function_code}"
        )

    def pretty_print_institutes(self, groups: INSTITUTES_TYPE) -> None:
        for institute_code, functions in groups.items():
            institute_name = self.institute_id_to_name(institute_code)
            print(f"Institute: {institute_name} (Code: {institute_code})")
            for function_code, member_ids in functions.items():
                function_name = self.function_id_to_name(function_code)
                print(
                    f"  Function: {function_name} (Code: {function_code}): {len(member_ids)}"
                )

    def add_members_to_institute_with_function(
        self, member_ids: list[str], institute_code: str, function_code: str
    ) -> None:
        """Add multiple members to the same institute and clear cache only at the end"""
        try:
            for member_id in member_ids:
                self.add_member_to_institute_with_function(
                    member_id=member_id,
                    institute_code=institute_code,
                    function_code=function_code,
                    clear_cache=False,
                )
        finally:
            self.__dict__.pop("_institutes_cached", None)

    def add_member_to_institute_with_function(
        self,
        member_id: str,
        institute_code: str,
        function_code: str,
        clear_cache: bool = True,
    ) -> dict[str, Any]:
        """Add a member to an institute with a function; return the unchanged JSON."""
        if (
            not member_id
            or institute_code not in MAPPER_INSTITUTE_CODE_TO_NAME
            or function_code not in MAPPER_FUNCTION_CODE_TO_NAME
        ):
            raise ValueError(
                "member_id, institute_code and function_code are required."
            )
        try:
            return self.mystv_client.add_member_to_institute_with_function(
                member_id=member_id,
                institute_code=institute_code,
                function_code=function_code,
            )
        finally:
            if clear_cache:
                # The server may have applied the change before the response failed.
                self.__dict__.pop("_institutes_cached", None)

    def change_memberships(
        self,
        member_ids: list[str],
        current: MembershipCategory,
        new: MembershipCategory,
    ) -> None:
        try:
            for member_id in member_ids:
                self.change_membership(
                    member_id=member_id, current=current, new=new, clear_cache=False
                )
        finally:
            # Discard cached data even if the server changed it but the response failed.
            self.__dict__.pop("_members_cached", None)

    def change_membership(
        self,
        member_id: str,
        current: MembershipCategory,
        new: MembershipCategory,
        clear_cache: bool = True,
    ) -> None:
        """Verify the current category and change it, preserving membership details."""
        if not member_id:
            raise ValueError("member_id is required.")
        if (
            type(current) is not MembershipCategory
            or type(new) is not MembershipCategory
        ):
            raise TypeError("current and new must be MembershipCategory members.")
        new_code = new.code
        if new_code is None:
            raise ValueError("The new membership category has no API code.")

        memberships = self.mystv_client.get_member_memberships_raw(member_id)
        matches = [
            membership
            for membership in memberships
            if membership["vereinsMitgliedschaft"] is True
            and membership["active"] is True
            and membership["verein"]["code"] == self.club_id
            and membership["category"]["code"] == current.code
        ]
        if not matches:
            raise ValueError(
                f"Member {member_id} has no active membership with category "
                f"{current} in club {self.club_id}. No change was made."
            )
        if len(matches) > 1:
            raise ValueError(
                f"Member {member_id} has multiple active memberships with category "
                f"{current} in club {self.club_id}. No change was made."
            )

        if current == new:
            return

        membership = matches[0]
        try:
            self.mystv_client.update_member_membership_unguarded(
                member_id=member_id,
                subscription_group=new_code,
                line_no=membership["lineNumber"],
                entry_date=membership["entryDate"],
                type_of_disability=membership["typeOfDisability"],
            )
        finally:
            if clear_cache:
                # Discard cached data even if the server changed it but the response failed.
                self.__dict__.pop("_members_cached", None)

    def delete_memberships(
        self,
        member_ids: list[str],
        current: MembershipCategory,
    ) -> None:
        try:
            for member_id in member_ids:
                self.delete_membership(
                    member_id=member_id, current=current, clear_cache=False
                )
        finally:
            # Discard cached data even if the server changed it but the response failed.
            self.__dict__.pop("_members_cached", None)

    def delete_membership(
        self, member_id: str, current: MembershipCategory, clear_cache: bool = True
    ) -> None:
        if not member_id:
            raise ValueError("member_id is required.")
        if type(current) is not MembershipCategory:
            raise TypeError("current must be MembershipCategory member.")
        memberships = self.mystv_client.get_member_memberships_raw(member_id)
        matches = [
            membership
            for membership in memberships
            if membership["vereinsMitgliedschaft"] is True
            and membership["active"] is True
            and membership["verein"]["code"] == self.club_id
            and membership["category"]["code"] == current.code
        ]
        if not matches:
            raise ValueError(
                f"Member {member_id} has no active membership with category "
                f"{current} in club {self.club_id}. No change was made."
            )
        if len(matches) > 1:
            raise ValueError(
                f"Member {member_id} has multiple active memberships with category "
                f"{current} in club {self.club_id}. No change was made."
            )

        membership = matches[0]
        try:
            self.mystv_client.delete_member_membership_unguarded(
                member_id=member_id, line_no=membership["lineNumber"]
            )
        finally:
            if clear_cache:
                # Discard cached data even if the server changed it but the response failed.
                self.__dict__.pop("_members_cached", None)
