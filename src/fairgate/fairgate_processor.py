from enum import StrEnum

import pandas as pd

from src.mySTV.mystv_processor import (
    EMPTY_DATE_STR,
    InternalCategory,
    MembersColumns,
    MySTVProcessor,
)


class FairgateConfigurationError(RuntimeError):
    """Errors caused by misconfiguration / metadata issues"""


class FairgateColumns(StrEnum):
    CONTACTS = "Kontakte"
    PRIMARY_EMAIL = "Primäre E-Mail"
    CORRESPONDENCE_STREET = "Strasse (Korr.)"
    CORRESPONDENCE_POST_CODE = "PLZ (Korr.)"
    CORRESPONDENCE_CITY = "Ort (Korr.)"
    MOBILE_PHONE = "Handy"
    FIRST_NAME = "Vorname"
    SURNAME = "Nachname"
    SALUTATION_TYPE = "Anredeart"
    GENDER = "Geschlecht"
    BIRTHDAY = "Geburtsdatum"
    TITLE = "Titel"
    NATIONALITY = "Nationalität"
    NATIONALITY_2 = "Nationalität 2"
    PERSONALIZED_SHORT_SALUTATION = "Personalisierte Kurzanrede"
    PERSONALIZED_SALUTATION_LINE = "Personalisierte Anredezeile"
    CORRESPONDENCE_CANTON_STATE = "Kanton/Bundesland (Korr.)"
    CORRESPONDENCE_COUNTRY = "Land (Korr.)"
    CORRESPONDENCE_PO_BOX = "Postfach (Korr.)"
    BILLING_STREET = "Strasse (Rg.)"
    BILLING_CITY = "Ort (Rg.)"
    BILLING_CANTON_STATE = "Kanton/Bundesland (Rg.)"
    BILLING_POST_CODE = "PLZ (Rg.)"
    BILLING_COUNTRY = "Land (Rg.)"
    BILLING_PO_BOX = "Postfach (Rg.)"
    MOBILE_PHONE_2 = "Handy 2"
    PARENT_1_EMAIL = "E-Mail Eltern 1"
    PARENT_2_EMAIL = "E-Mail Eltern 2"
    WEBSITE = "Web"
    CORRESPONDENCE_LANGUAGE = "Korresp.sprache"
    ENTERPRISE_IDENTIFICATION_NUMBER = "Enterprise Identification Number"
    EBILL_EMAIL = "eBill-eMail"
    STV_NUMBER = "STV-Nummer"
    SOCIAL_INSURANCE_NUMBER = "Sozialversicherungsnr"
    NDBJS_ESA_ADDRESS_NUMBER = "NDBJS/ESA Adress-Nr"
    ADDRESS_RELEASE = "Adressfreigabe"
    CREATE_GYM_LIVE_SUBSCRIPTION = "GymLive-Abo anlegen"
    CREATE_REGIONAL_SUBSCRIPTION = "Regio-Abo anlegen"
    MY_STV_REPRESENTATIVE_RELEASE = "Freigabe für Stellvertreter in mySTV-FSG (STV-ID)"
    ALTERNATIVE_EMAIL = "E-Mail alternativ"
    CLUB_EMAIL = "E-Mail Verein"
    MEMBERSHIP = "Mitgliedschaft"
    FIRST_ENTRY_DATE = "Ersteintrittsdatum"
    LAST_ENTRY_OR_TRANSFER_DATE = "Letztes Ein-/Übertrittsdatum"
    WITHDRAWAL_DATE = "Austrittsdatum"
    MEMBERSHIP_YEARS = "Mitgliederjahre"
    HOUSEHOLD_LINK = "Haushaltsverbindung"
    HOUSEHOLD_MAIN_CONTACT = "Haushaltshauptkontakt"
    COMPANY_LINK = "Firmenverbindung"
    NOTES = "Notizen"
    SALUTATION_TEXT = "Anredetext"
    DOCUMENTS = "Dokumente"
    LOGIN_COUNT = "Anzahl Logins"
    BIRTH_YEAR = "Jahrgang"
    AGE = "Alter"
    DELIVERY_PREFERENCE = "Versandpräferenz"
    NEWSLETTER_SUBSCRIPTION = "NL-Abonnement"
    LAST_INVOICE_DATE = "Letzte Rechnungsstellung"
    LAST_LOGIN = "Zuletzt angemeldet"
    LAST_MODIFIED = "Zuletzt geändert"
    CREATED_AT = "Erstellt am"
    CLUB_CONTACT_ID = "Kontakt-ID Verein"
    ASSOCIATION_CONTACT_ID = "Kontakt-ID Verband"
    MAIN_CLUB_ASSIGNMENT = "Hauptverein-Zuweisung"
    MAIN_CLUB_ASSIGNMENT_TO_THIS_ORGANIZATION = (
        "Haupt-Verein-Zuweisung zu dieser Organisation"
    )
    ASSOCIATION_MEMBERSHIP_YEARS = "Mitgliederjahre (Verband)"
    ASSOCIATION_WITHDRAWAL_DATE = "Austrittsdatum (Verband)"
    ASSOCIATION_ENTRY_DATE = "Eintrittsdatum (Verband)"
    ASSOCIATION_FIRST_ENTRY_DATE = "Ersteintrittsdatum (verband)"
    MANDATORY_ASSIGNMENT = "Pflichtzuweisung"
    SHOW_MAIN_CONTACT_NAME_IN_ADDRESS_BLOCK = "Hauptkontaktname im Adressblock anzeigen"
    COMPANY = "Firma"


FAIRGATE_DATE_COLS = [
    FairgateColumns.BIRTHDAY,
    FairgateColumns.FIRST_ENTRY_DATE,
    FairgateColumns.ASSOCIATION_ENTRY_DATE,
    FairgateColumns.ASSOCIATION_FIRST_ENTRY_DATE,
    FairgateColumns.LAST_ENTRY_OR_TRANSFER_DATE,
    FairgateColumns.WITHDRAWAL_DATE,
    FairgateColumns.LAST_INVOICE_DATE,
    FairgateColumns.LAST_LOGIN,
    FairgateColumns.LAST_MODIFIED,
    FairgateColumns.CREATED_AT,
    FairgateColumns.ASSOCIATION_WITHDRAWAL_DATE,
    FairgateColumns.LAST_LOGIN,
    FairgateColumns.LAST_MODIFIED,
    FairgateColumns.CREATED_AT,
]

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

FORMER_MEMBER_WEBSITE = "http://Ehemaliges_Mitglied.tvw"
MAP_WEBSITE_TO_INTERNAL_CAT = {
    "http://Passivmitglieder.tvw": InternalCategory.PASSIVMITGLIED,
    "http://Mädchen.tvw": InternalCategory.JUGENDMITGLIED,
    "http://Knaben.tvw": InternalCategory.JUGENDMITGLIED,
    "http://Aktiver_Turner.tvw": InternalCategory.AKTIVMITGLIED,
    "http://Aktive_Turnerin.tvw": InternalCategory.AKTIVMITGLIED,
    "http://Kitu_Kinder.tvw": InternalCategory.JUGENDMITGLIED,
    "http://Freimitg._Turnend__1.tvw": InternalCategory.FREIMITGLIED,
    "http://Ehrenmitg._turnend.tvw": InternalCategory.EHRENMITGLIED,
    "http://Ehrenmitg._nturnend.tvw": InternalCategory.EHRENMITGLIED_NT,
    "http://Freimitg._nturnend__10.tvw": InternalCategory.FREIMITGLIED_NT,
}
EXPECTED_DATE_FORMAT_PER_COL = {
    MembersColumns.BIRTHDAY: "%Y-%m-%d",
    MembersColumns.MEMBERSHIP_ENTRY_DATES: "%d.%m.%Y",
}


class FairgateProcessor:
    def __init__(self, fg_data: pd.DataFrame):
        self.fg_data = self._preprocess_data(fg_data)

    def _preprocess_data(self, fg_data: pd.DataFrame) -> pd.DataFrame:
        def _to_datetime(date: str):
            expected_date_formats = ["%d.%m.%Y", "%Y-%m-%d %H:%M:%S"]
            if date == EMPTY_DATE_STR or pd.isna(date):
                return pd.NA
            for expected_date_format in expected_date_formats:
                try:
                    return pd.to_datetime(date, format=expected_date_format)
                except ValueError:
                    pass
            raise FairgateConfigurationError(f"Unknown date format: {date}")

        for date_col in FAIRGATE_DATE_COLS:
            fg_data[date_col] = fg_data[date_col].apply(_to_datetime)
        return fg_data

    @classmethod
    def from_excel(cls, filename: str) -> FairgateProcessor:
        fg_data = pd.read_excel(
            filename, dtype=str
        )  # no not parse Member numbers as int due to leading zeros
        return cls(fg_data)

    @property
    def members(self) -> pd.DataFrame:
        excluded = self.former_members.index.union(self.other_members.index)
        members = self.fg_data.drop(index=excluded).copy()

        if not members[FairgateColumns.WEBSITE].isin(MAP_WEBSITE_TO_INTERNAL_CAT).all():
            raise FairgateConfigurationError("Not all Websites are mapped.")

        return members

    @property
    def former_members(self) -> pd.DataFrame:
        return self.fg_data.loc[
            self.fg_data[FairgateColumns.WEBSITE] == FORMER_MEMBER_WEBSITE
        ]

    @property
    def other_members(self) -> pd.DataFrame:
        return self.fg_data.loc[pd.isna(self.fg_data[FairgateColumns.WEBSITE])]

    def get_member(self, member_id: str) -> pd.Series:
        matches = self.members.loc[
            self.members[FairgateColumns.STV_NUMBER] == member_id
        ]
        if len(matches) > 1:
            raise FairgateConfigurationError(
                f"Found multiple members with id {member_id}!"
            )
        if len(matches) == 0:
            raise ValueError(f"Could not find member with id {member_id}")
        return matches.iloc[0]


def find_db_row_diffs(
    mystv_row: pd.Series, fg_row: pd.Series
) -> list[InternalCategory]:
    MAP_GENDER_TO_SALUTATION = {"Männlich": "Er", "Weiblich": "Sie"}
    diffs = []
    for mystv_col, fg_col in MAP_MYSTV_TO_FAIRGATE_COLUMN.items():
        if mystv_row[mystv_col] != fg_row[fg_col]:
            diffs.append(mystv_col)
    if (
        MAP_WEBSITE_TO_INTERNAL_CAT[fg_row[FairgateColumns.WEBSITE]]
        != mystv_row[MembersColumns._INTERNAL_CATEGORY]
    ):
        diffs.append(MembersColumns._INTERNAL_CATEGORY)
    if (
        MAP_GENDER_TO_SALUTATION[fg_row[FairgateColumns.GENDER]]
        != mystv_row[MembersColumns.SALUTATION]
    ):
        diffs.append(MembersColumns.SALUTATION)
    return diffs


def compare_dbs(
    mystv_members: pd.DataFrame, fg_members: pd.DataFrame
) -> dict[str, list[str]]:
    diffs = {}
    not_found = []
    for _, mystv_row in mystv_members.iterrows():
        member_number = mystv_row[MembersColumns.MEMBER_ID]
        matches = fg_members.loc[
            fg_members[FairgateColumns.STV_NUMBER] == member_number
        ]
        if len(matches) > 1:
            raise FairgateConfigurationError(
                f"Found multiple entries for member id {member_number}"
            )
        if len(matches) == 0:
            not_found.append(member_number)
            continue
        diffs[member_number] = find_db_row_diffs(
            mystv_row=mystv_row, fg_row=matches.iloc[0, :]
        )
    return diffs


def _values_equal(mystv_val: Any, fg_value: Any) -> bool:
    if mystv_val == fg_value:
        return True
    if ((mystv_val is None) or pd.isna(mystv_val) or mystv_val == "") and (
        (fg_value is None) or pd.isna(fg_value) or fg_value == ""
    ):
        return True
    return False


def find_db_row_diffs(
    mystv_row: pd.Series, fg_row: pd.Series
) -> list[InternalCategory]:
    MAP_GENDER_TO_SALUTATION = {"Männlich": "Er", "Weiblich": "Sie"}
    diffs = []
    ignore = [
        MembersColumns.REGIONAL_ABO,
        MembersColumns.GYM_LIVE_ABO,
        MembersColumns.LANGUAGE,
        MembersColumns.ADDRESS_RELEASE,
        MembersColumns.MY_STV_COMMENT,
        MembersColumns.MEMBERSHIP_ENTRY_DATES,
    ]
    for mystv_col, fg_col in MAP_MYSTV_TO_FAIRGATE_COLUMN.items():
        if mystv_col in ignore:
            continue
        if mystv_col == MembersColumns._INTERNAL_CATEGORY:
            if (
                MAP_WEBSITE_TO_INTERNAL_CAT[fg_row[FairgateColumns.WEBSITE]]
                != mystv_row[MembersColumns._INTERNAL_CATEGORY]
            ):
                diffs.append(MembersColumns._INTERNAL_CATEGORY)
            continue
        if mystv_col == MembersColumns.SALUTATION:
            if (
                MAP_GENDER_TO_SALUTATION[fg_row[FairgateColumns.GENDER]]
                != mystv_row[MembersColumns.SALUTATION]
            ):
                diffs.append(MembersColumns.SALUTATION)
            continue
        if not _values_equal(mystv_val=mystv_row[mystv_col], fg_value=fg_row[fg_col]):
            diffs.append(mystv_col)
    return diffs


def compare_dbs(
    mystv: MySTVProcessor, fg: FairgateProcessor
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    diffs = {}
    ids_missing_in_fg = []
    ids_missing_in_mystv = [
        member_number
        for member_number in fg.members[FairgateColumns.STV_NUMBER]
        if member_number not in mystv.members[MembersColumns.MEMBER_ID].values
    ]
    for _, mystv_row in mystv.members.iterrows():
        member_number = mystv_row[MembersColumns.MEMBER_ID]
        try:
            fg_row = fg.get_member(member_number)
        except ValueError:
            ids_missing_in_fg.append(member_number)
            continue
        member_diffs = find_db_row_diffs(mystv_row=mystv_row, fg_row=fg_row)
        if len(member_diffs) != 0:
            diffs[member_number] = member_diffs
    return diffs, ids_missing_in_mystv, ids_missing_in_fg


def get_diff_summary(
    diffs: dict[str, list[str]], mystv: MySTVProcessor, fg: FairgateProcessor
) -> str:
    summary = []
    for member_id, cols in diffs.items():
        mystv_row = mystv.get_member(member_id)
        summary.append(
            f"**{member_id}** {mystv_row[MembersColumns.FIRST_NAME]} {mystv_row[MembersColumns.SURNAME]}:"
        )
        fg_row = fg.get_member(member_id)
        for col in cols:
            fg_col = MAP_MYSTV_TO_FAIRGATE_COLUMN[col]
            summary.append(f"- {col}: {mystv_row[col]}  -  {fg_row[fg_col]}")
        summary.append("")
    return "\n".join(summary)
