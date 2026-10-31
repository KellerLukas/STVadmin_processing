from enum import StrEnum


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
]


FORMER_MEMBER_WEBSITE = "http://Ehemaliges_Mitglied.tvw"
