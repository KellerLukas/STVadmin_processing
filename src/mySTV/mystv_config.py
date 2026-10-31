import json
from enum import StrEnum
from pathlib import Path
from typing import Self


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


def _load_mapper(filename: str) -> dict[str, str]:
    """Load a JSON file from the same directory as this source file."""
    path = Path(__file__).parent / filename
    try:
        with path.open("r", encoding="utf-8") as f:
            data: object = json.load(f)
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        raise MySTVConfigurationError(f"Could not load mapper file {path}.") from None
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


MAPPER_INSTITUTE_CODE_TO_NAME = _load_mapper("mySTV_mapper_institute_code_to_name.json")
MAPPER_FUNCTION_CODE_TO_NAME = _load_mapper("mySTV_mapper_function_code_to_name.json")

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

INSTITUTES_TYPE = dict[str, dict[str, list[str]]]
