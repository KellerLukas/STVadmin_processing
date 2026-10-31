from src.fairgate.fairgate_config import FairgateColumns
from src.mySTV.mystv_config import (
    FEMALE_SALUTATION,
    MALE_SALUTATION,
    InternalCategory,
    MembersColumns,
)

MAP_MYSTV_TO_FAIRGATE_COLUMN = {
    MembersColumns.MEMBER_ID: FairgateColumns.STV_NUMBER,
    MembersColumns.SOCIAL_INSURANCE_NR: FairgateColumns.SOCIAL_INSURANCE_NUMBER,
    MembersColumns.LANGUAGE: FairgateColumns.CORRESPONDENCE_LANGUAGE,
    MembersColumns.SURNAME: FairgateColumns.SURNAME,
    MembersColumns.FIRST_NAME: FairgateColumns.FIRST_NAME,
    MembersColumns.ADDRESS: FairgateColumns.CORRESPONDENCE_STREET,
    MembersColumns.POST_CODE: FairgateColumns.CORRESPONDENCE_POST_CODE,
    MembersColumns.CITY: FairgateColumns.CORRESPONDENCE_CITY,
    MembersColumns.EMAIL_PRIVATE: FairgateColumns.PRIMARY_EMAIL,
    MembersColumns.EMAIL_ALTERNATIVE: FairgateColumns.ALTERNATIVE_EMAIL,
    MembersColumns.EMAIL_VEREIN: FairgateColumns.CLUB_EMAIL,
    MembersColumns.PHONE_MOBILE: FairgateColumns.MOBILE_PHONE,
    MembersColumns.BIRTHDAY: FairgateColumns.BIRTHDAY,
    MembersColumns.ADDRESS_RELEASE: FairgateColumns.ADDRESS_RELEASE,
    MembersColumns.MY_STV_COMMENT: FairgateColumns.NOTES,
    MembersColumns.GYM_LIVE_ABO: FairgateColumns.CREATE_GYM_LIVE_SUBSCRIPTION,
    MembersColumns.REGIONAL_ABO: FairgateColumns.CREATE_REGIONAL_SUBSCRIPTION,
    MembersColumns.MEMBERSHIP_ENTRY_DATES: FairgateColumns.ASSOCIATION_ENTRY_DATE,
    MembersColumns.SALUTATION: FairgateColumns.GENDER,
    MembersColumns._INTERNAL_CATEGORY: FairgateColumns.WEBSITE,
}
if len(MAP_MYSTV_TO_FAIRGATE_COLUMN) != len(set(MAP_MYSTV_TO_FAIRGATE_COLUMN.values())):
    raise ValueError("MAP_MYSTV_TO_FAIRGATE_COLUMN is not bijective!")
MAP_FAIRGATE_TO_MYSTV_COLUMN = {v: k for k, v in MAP_MYSTV_TO_FAIRGATE_COLUMN.items()}

MAP_GENDER_TO_SALUTATION = {"Männlich": MALE_SALUTATION, "Weiblich": FEMALE_SALUTATION}

MAP_WEBSITE_TO_INTERNAL_CAT = {
    "http://Passivmitglieder.tvw": InternalCategory.PASSIVMITGLIED,
    "http://Mädchen.tvw": InternalCategory.JUGENDMITGLIED,
    "http://Knaben.tvw": InternalCategory.JUGENDMITGLIED,
    "http://Aktiver_Turner.tvw": InternalCategory.AKTIVMITGLIED,
    "http://Aktive_Turnerin.tvw": InternalCategory.AKTIVMITGLIED,
    "http://Freimitg._Turnend__1.tvw": InternalCategory.FREIMITGLIED,
    "http://Ehrenmitg._turnend.tvw": InternalCategory.EHRENMITGLIED,
    "http://Ehrenmitg._nturnend.tvw": InternalCategory.EHRENMITGLIED_NT,
    "http://Freimitg._nturnend__10.tvw": InternalCategory.FREIMITGLIED_NT,
}
FUNCTION_CODE_MUKIELKI = "10540"
FUNCTION_CODE_KITU = "10541"
MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE = {
    "https://ELKI.tvw": FUNCTION_CODE_MUKIELKI,
    "https://ELKI": FUNCTION_CODE_MUKIELKI,
    "http://ELKI.tvw": FUNCTION_CODE_MUKIELKI,
    "http://Kitu_Kinder.tvw": FUNCTION_CODE_KITU,
}
MAP_WEBSITE_TO_INTERNAL_CAT.update(
    {k: InternalCategory.JUGENDMITGLIED for k in MAP_WEBSITES_TO_YOUTH_FUNCTION_CODE}
)


# Cross-system fields whose meanings/representations are not directly comparable.
CROSS_SYSTEM_IGNORED_COLUMNS = {
    MembersColumns.REGIONAL_ABO,
    MembersColumns.GYM_LIVE_ABO,
    MembersColumns.LANGUAGE,
    MembersColumns.ADDRESS_RELEASE,
    MembersColumns.MY_STV_COMMENT,
    MembersColumns.MEMBERSHIP_ENTRY_DATES,
}

# Keep derived data in snapshots, but do not report it as a source-data change.
MYSTV_IGNORED_COLUMNS = {col for col in MembersColumns if col.name.startswith("_")} | {
    # Opaque nested API records; categories/dates, institutes and functions are
    # compared through their explicit fields instead.
    MembersColumns.MEMBERSHIPS,
    MembersColumns.HONORS,
    MembersColumns.SQUADS,
}
FAIRGATE_IGNORED_COLUMNS = {
    FairgateColumns.AGE,
    FairgateColumns.BIRTH_YEAR,
    FairgateColumns.MEMBERSHIP_YEARS,
    FairgateColumns.ASSOCIATION_MEMBERSHIP_YEARS,
}

DIFF_ID_COLUMN = "STV-Nummer"
DIFF_FIRST_NAME_COLUMN = "Vorname"
DIFF_SURNAME_COLUMN = "Nachname"
DIFF_FIELD_COLUMN = "Feld"
DIFF_IDENTITY_COLUMNS = [DIFF_ID_COLUMN, DIFF_FIRST_NAME_COLUMN, DIFF_SURNAME_COLUMN]
INSTITUTES_FIELD = "Riegen"
