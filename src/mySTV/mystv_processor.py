from enum import StrEnum
from functools import cache, cached_property
import copy
import json
from src.config.paths import FILENAME_NEWSLETTER_BLACKLIST, WORKING_DIR_PATH
import pandas as pd
from pathlib import Path
from typing import Any, Dict



from src.utils.utils import calculate_age_at_ts
from src.mySTV.mystv_client import MySTVClient

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
    ERWACHSENE_STANDARD = "Erwachsene Standard"
    ERWACHSENE_LIGHT = "Erwachsene Light"
    ERWACHSENE_INKLUSION = "Erwachsene Inklusion"  # unverified
    PASSIVMITGLIEDER = "Passivmitglieder"
    EHRENMIGLIED_NT = "Ehrenmitg. nturnend"
    KINDER_JUGEND = "Kinder & Jugend"


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
        MembershipCategory.ERWACHSENE_INKLUSION,
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
        MembershipCategory.ERWACHSENE_INKLUSION,
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
        MembershipCategory.ERWACHSENE_INKLUSION,
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
COACH_FUNCTION_CODES = ["3", "4"]

MALE_SALUTATION = "MR"
FEMALE_SALUTATION = "MS"


class MySTVProcessor:
    def __init__(self, club_id: str):
        self.club_id = club_id
    
    @cached_property
    def mystv_client(self):
        client = MySTVClient(club_id=self.club_id)
        client.login()
        return client
        
    def _load_mapper(self, filename: str) -> Dict[str, Any]:
        """Load a JSON file from the same directory as this source file."""
        path = Path(__file__).parent / filename
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            raise MySTVConfigurationError(f"Could not load mapper file {path}.") from None

    @cache
    def _members_cached(self) -> pd.DataFrame:
        """Return a DataFrame of all members in the club."""
        raw_members = self.mystv_client.get_members_stream_raw()
        if not (len(raw_members) == 2 and raw_members[1] == ""):
            raise MySTVConfigurationError("MySTV members stream did not return expected data.")
        members_df = pd.DataFrame(raw_members[0])
        return self._apply_member_data_enrichment(members_df)

    @property
    def members(self) -> pd.DataFrame:
        return copy.deepcopy(self._members_cached())

    @cache
    def _institutes_cached(self) -> dict[str, dict[str, list[str]]]:
        raw_groups = self.mystv_client.get_institute_members_raw()
        unique_institute_codes = {group["instituteCode"] for group in raw_groups}

        groups = {code: {} for code in unique_institute_codes}
        for group in raw_groups:
            institute_code = group["instituteCode"]
            function_code = group["instituteFunctionCode"]
            member_id = group["memberId"]
            if function_code not in groups[institute_code]:
                groups[institute_code][function_code] = []
            groups[institute_code][function_code].append(member_id)
        return groups

    @property
    def institutes(self) -> dict[str, dict[str, list[str]]]:
        return copy.deepcopy(self._institutes_cached())

    def _apply_member_data_enrichment(self, members_df: pd.DataFrame) -> pd.DataFrame:
        """Add any additional columns or transformations to the members DataFrame."""
        for method in [
            self._build_combined_emails_col,
            self._build_primary_email_col,
            self._build_internal_category_col,
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

        def combine_emails(row):
            emails = [
                row[col]
                for col in email_columns
                if pd.notnull(row[col]) and row[col].strip()
            ]
            return "; ".join(emails) if emails else None

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

        def get_primary_email(row):
            for col in email_columns:
                if pd.notnull(row[col]) and row[col].strip():
                    return row[col]
            return None

        members_df[MembersColumns._PRIMARY_EMAIL] = members_df.apply(
            get_primary_email, axis=1
        )
        return members_df

    def _build_internal_category_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        def get_internal_cat(row):
            membership_cat = row[MembersColumns.MEMBERSHIP_CATEGORIES]
            membership_addition = row[MembersColumns.MEMBERSHIP_ADDITIONS]
            category_tuple = (membership_cat, membership_addition)

            internal_cat = MAP_CATEGORY_TO_INTERNAL.get(category_tuple)
            if internal_cat:
                return internal_cat
            raise MySTVConfigurationError(
                f"Unable to map category tuple to internal category: {category_tuple}"
            )

        members_df[MembersColumns._INTERNAL_CATEGORY] = members_df.apply(
            get_internal_cat, axis=1
        )
        return members_df

    def _build_age_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        ts = pd.Timestamp.now()

        def get_age(row):
            birthday = pd.Timestamp(row[MembersColumns.BIRTHDAY])
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
    def mapper_institute_code_to_name(self) -> Dict[int, str]:
        mapper_institute_code_to_name = self._load_mapper(
            "mySTV_mapper_institute_code_to_name.json"
        )
        return {code: name for code, name in mapper_institute_code_to_name.items()}

    @cached_property
    def mapper_function_code_to_name(self) -> Dict[int, str]:
        mapper_function_code_to_name = self._load_mapper(
            "mySTV_mapper_function_code_to_name.json"
        )
        return {code: name for code, name in mapper_function_code_to_name.items()}

    def institute_id_to_name(self, institute_code: int) -> str:
        return self.mapper_institute_code_to_name.get(
            institute_code, f"Unknown Institute Code {institute_code}"
        )

    def function_id_to_name(self, function_code: int) -> str:
        return self.mapper_function_code_to_name.get(
            function_code, f"Unknown Function Code {function_code}"
        )

    def pretty_print_institutes(self, groups):
        for institute_code, functions in groups.items():
            institute_name = self.institute_id_to_name(institute_code)
            print(f"Institute: {institute_name} (Code: {institute_code})")
            for function_code, member_ids in functions.items():
                function_name = self.function_id_to_name(function_code)
                print(
                    f"  Function: {function_name} (Code: {function_code}): {len(member_ids)}"
                )
    def add_member_to_institute_with_function(
        self, member_id: str, institute_code: str, function_code: str
    ) -> dict:
        """Add an institute assignment and return response.json() unchanged."""
        if (
            not member_id
            or institute_code not in self.mapper_institute_code_to_name
            or function_code not in self.mapper_function_code_to_name
        ):
            raise ValueError(
                "member_id, institute_code and function_code are required."
            )
        response = self.mystv_client.add_member_to_institute_with_function(member_id=member_id, institute_code=institute_code, function_code=function_code)
        
        # Refresh even if the server applied the change but the response failed.
        self._institutes_cached.cache_clear()  # ToDo: optimize this? allow running this in bulk and only clearing once?
        return response
