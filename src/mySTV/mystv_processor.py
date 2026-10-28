import copy
import json
import logging
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any, Self

import pandas as pd

from src.config.paths import FILENAME_NEWSLETTER_BLACKLIST, WORKING_DIR_PATH
from src.mySTV.mystv_client_v2 import MySTVClientV2
from src.utils.utils import calculate_age_at_ts

logger = logging.getLogger(__name__)


class MySTVConfigurationError(RuntimeError):
    """Errors caused by misconfiguration / metadata issues"""


class InternalCategory(StrEnum):
    JUGENDMITGLIED = "Jugendmitglied"
    AKTIVMITGLIED = "Aktivmitglied"
    PASSIVMITGLIED = "Passivmitglied"
    EHRENMITGLIED = "Ehrenmitglied"
    EHRENMITGLIED_NT = "Ehrenmitglied nturnend"
    FREIMITGLIED = "Freimitglied"
    FREIMITGLIED_NT = "Freimitglied nturnend"


class MembershipCategory(StrEnum):
    code: str | None

    def __new__(cls, label: str, code: str | None) -> Self:
        member = str.__new__(cls, label)
        member._value_ = label
        member.code = code
        return member

    ERWACHSENE_STANDARD = ("Erwachsene Standard", "101")
    ERWACHSENE_LIGHT = ("Erwachsene Light", "102")
    ERWACHSENE_INKLUSION = ("Erwachsene Inklusion", "110")
    PASSIVMITGLIEDER = ("Passivmitglieder", "120")
    EHRENMIGLIED_NT = ("Ehrenmitg. nturnend", "11")
    KINDER_JUGEND = ("Kinder & Jugend", "105")
    KINDER_JUGEND_INKLUSION = ("Kinder & Jugend Inklusion", "115")


class MembershipAddition(StrEnum):
    EMPTY = "-"
    FREIMITGLIED_T = "Freimitg. turnend"
    FREIMITGLIED_NT = "Freimitg. turnend"  # unverified #ToDo: discuss this
    EHRENMITGLIED_T = "Ehrenmitg. turnend"


MAP_CATEGORY_TO_INTERNAL = {
    (
        MembershipCategory.KINDER_JUGEND,
        MembershipAddition.EMPTY,
    ): InternalCategory.JUGENDMITGLIED,
    (
        MembershipCategory.ERWACHSENE_STANDARD,
        MembershipAddition.EMPTY,
    ): InternalCategory.AKTIVMITGLIED,
    (
        MembershipCategory.ERWACHSENE_LIGHT,
        MembershipAddition.EMPTY,
    ): InternalCategory.AKTIVMITGLIED,
    (
        MembershipCategory.PASSIVMITGLIEDER,
        MembershipAddition.EMPTY,
    ): InternalCategory.PASSIVMITGLIED,
    (
        MembershipCategory.ERWACHSENE_STANDARD,
        MembershipAddition.EHRENMITGLIED_T,
    ): InternalCategory.EHRENMITGLIED,
    (
        MembershipCategory.ERWACHSENE_LIGHT,
        MembershipAddition.EHRENMITGLIED_T,
    ): InternalCategory.EHRENMITGLIED,
    (
        MembershipCategory.EHRENMIGLIED_NT,
        MembershipAddition.EMPTY,
    ): InternalCategory.EHRENMITGLIED_NT,
    (
        MembershipCategory.ERWACHSENE_STANDARD,
        MembershipAddition.FREIMITGLIED_T,
    ): InternalCategory.FREIMITGLIED,
    (
        MembershipCategory.ERWACHSENE_LIGHT,
        MembershipAddition.FREIMITGLIED_T,
    ): InternalCategory.FREIMITGLIED,
    (
        MembershipCategory.PASSIVMITGLIEDER,
        MembershipAddition.FREIMITGLIED_NT,
    ): InternalCategory.FREIMITGLIED_NT,
}


class MembersColumns(StrEnum):
    MEMBER_ID = "memberId"
    SOCIAL_INSURANCE_NR = "socialInsuranceNr"
    SWISS_ATHLETICS_NR = "swissAthleticsNr"
    SALUTATION = "salutation"
    LANGUAGE = "language"
    SURNAME = "surname"
    FIRST_NAME = "firstName"
    ADDRESS = "address"
    ADDITION = "addition"
    ADDITION_2 = "addition2"
    POST_CODE = "postCode"
    CITY = "city"
    EMAIL_PRIVATE = "emailPrivate"
    EMAIL_ALTERNATIVE = "emailAlternative"
    EMAIL_VEREIN = "emailVerein"
    EMAIL_VERBAND = "emailVerband"
    PHONE_PRIVATE = "phonePrivate"
    PHONE_BUSINESS = "phoneBusiness"
    PHONE_MOBILE = "phoneMobile"
    MY_STV_COMMENT = "mySTVComment"
    BIRTHDAY = "birthday"
    ADVERTISING = "advertising"
    GYM_LIVE_ABO = "gymLiveAbo"
    REGIONAL_ABO = "regionalAbo"
    ADDRESS_RELEASE = "addressRelease"
    REGIONAL_ABO_NO = "regionalAboNo"
    MEMBERSHIP_CATEGORIES = "membershipCategories"
    MEMBERSHIP_ENTRY_DATES = "membershipEntryDates"
    MEMBERSHIP_ADDITIONS = "membershipAdditions"
    SQUADS = "squads"
    VERBANDS_ANSICHT_MEMBERSHIP_TEXT = "verbandsAnsichtMembershipText"
    VERBANDS_ANSICHT_MEMBERSHIP_NUMBER = "verbandsAnsichtMembershipNumber"
    HAS_DIRECT_VERBAND_MEMBERSHIP = "hasDirectVerbandMembership"
    HAS_INDIRECT_VERBAND_MEMBERSHIP = "hasIndirectVerbandMembership"
    MEMBERSHIPS = "memberships"
    HONORS = "honors"
    STATUS_MY_STV = "statusMySTV"
    RELEASE_MY_STV = "releaseMySTV"
    TYPE_OF_SPORT_LSA = "typeOfSportLSA"
    YEAR_VALID_LSA = "yearValidLSA"
    CLUB_NAME_LSA = "clubNameLSA"
    # Own additions to the MySTV export, not part of the official API.
    _COMBINED_EMAILS = (
        "combinedEmails"  # all emails combined into one string, separated by semicolons
    )
    _PRIMARY_EMAIL = "primaryEmail"  # the first non-empty email
    _INTERNAL_CATEGORY = "internalCategory"  # the internal category of the member
    _AGE = "age"
    _GETS_NEWSLETTER = "getsNewsletter"


YOUTH_INSTITUTE_CODES = ["3", "4", "8", "9", "10", "24", "25", "26"]
INFOHEFT_DIGITAL_INSTITUTE_CODE = "29"
ADMIN_INSTITUTE_CODES = [
    INFOHEFT_DIGITAL_INSTITUTE_CODE
]  # institutes that do not represent actual groups
COACH_FUNCTION_CODES = ["3", "4"]

MALE_SALUTATION = "MR"
FEMALE_SALUTATION = "MS"
EXPECTED_DATE_FORMAT_PER_COL = {
    MembersColumns.BIRTHDAY: "%Y-%m-%d",
    MembersColumns.MEMBERSHIP_ENTRY_DATES: "%d.%m.%Y",
}
EMPTY_DATE_STR = "-"

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

    def _load_mapper(self, filename: str) -> dict[str, Any]:
        """Load a JSON file from the same directory as this source file."""
        path = Path(__file__).parent / filename
        try:
            with path.open("r", encoding="utf-8") as f:
                data: object = json.load(f)
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            raise MySTVConfigurationError(
                f"Could not load mapper file {path}."
            ) from None
        if not isinstance(data, dict):
            raise MySTVConfigurationError(f"Mapper file {path} must contain an object.")
        mapper: dict[str, str] = {}
        for code, name in data.items():
            if not isinstance(code, str) or not isinstance(name, str):
                raise MySTVConfigurationError(
                    f"Mapper file {path} must contain string codes and names."
                )
            mapper[code] = name
        return mapper

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
        return self._apply_member_data_enrichment(members_df)

    @property
    def members(self) -> pd.DataFrame:
        return copy.deepcopy(self._members_cached)

    @cached_property
    def _institutes_cached(self) -> dict[str, dict[str, list[str]]]:
        raw_groups = self.mystv_client.get_institute_members_raw()
        if not isinstance(raw_groups, list):
            raise MySTVConfigurationError(
                "MySTV institute response must contain a list of assignments."
            )
        groups: dict[str, dict[str, list[str]]] = {}
        for group in raw_groups:
            if not isinstance(group, dict):
                raise MySTVConfigurationError(
                    "MySTV institute response contains an invalid assignment."
                )
            institute_code = group.get("instituteCode")
            function_code = group.get("instituteFunctionCode")
            member_id = group.get("memberId")
            if not isinstance(institute_code, str):
                raise MySTVConfigurationError(
                    "MySTV institute assignment has an invalid institute code."
                )
            if not isinstance(function_code, str):
                raise MySTVConfigurationError(
                    "MySTV institute assignment has an invalid function code."
                )
            if not isinstance(member_id, str):
                raise MySTVConfigurationError(
                    "MySTV institute assignment has an invalid member ID."
                )
            assignments = groups.setdefault(institute_code, {})
            if function_code not in assignments:
                assignments[function_code] = []
            assignments[function_code].append(member_id)
        return groups

    @property
    def institutes(self) -> dict[str, dict[str, list[str]]]:
        return copy.deepcopy(self._institutes_cached)

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
        def _to_datetime(date: str, expected_format: str):
            if date == EMPTY_DATE_STR:
                return pd.NA
            return pd.to_datetime(date, format=expected_format)
        for col, expected_format in EXPECTED_DATE_FORMAT_PER_COL.items():
            members_df[col] = members_df[col].apply(_to_datetime, args=(expected_format,))
        return members_df

    def _build_age_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        ts = pd.Timestamp.now()

        def get_age(row: pd.Series[Any]) -> int:
            birthday = row[MembersColumns.BIRTHDAY]
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

    @cached_property
    def mapper_institute_code_to_name(self) -> dict[str, str]:
        mapper_institute_code_to_name = self._load_mapper(
            "mySTV_mapper_institute_code_to_name.json"
        )
        return {code: name for code, name in mapper_institute_code_to_name.items()}

    @cached_property
    def mapper_function_code_to_name(self) -> dict[str, str]:
        mapper_function_code_to_name = self._load_mapper(
            "mySTV_mapper_function_code_to_name.json"
        )
        return {code: name for code, name in mapper_function_code_to_name.items()}

    def institute_id_to_name(self, institute_code: str) -> str:
        return self.mapper_institute_code_to_name.get(
            institute_code, f"Unknown Institute Code {institute_code}"
        )

    def function_id_to_name(self, function_code: str) -> str:
        return self.mapper_function_code_to_name.get(
            function_code, f"Unknown Function Code {function_code}"
        )

    def pretty_print_institutes(self, groups: dict[str, dict[str, list[str]]]) -> None:
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
        """Add an institute assignment and return response.json() unchanged."""
        if (
            not member_id
            or institute_code not in self.mapper_institute_code_to_name
            or function_code not in self.mapper_function_code_to_name
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

    def delete_memberships(self,
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

    def delete_membership(self, member_id: str, current: MembershipCategory, clear_cache: bool = True):
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
                member_id=member_id,
                line_no=membership["lineNumber"]
            )
        finally:
            if clear_cache:
                # Discard cached data even if the server changed it but the response failed.
                self.__dict__.pop("_members_cached", None)