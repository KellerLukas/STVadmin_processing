import pandas as pd
import numpy as np

from src.utils.databases import MailBasedDatabase, Database, Person
from src.utils.cleverreach_database import CleverreachDatabase
from src.utils.adress_databases import AdressDatabase


def export_no_mail_people_excel(mb_db: MailBasedDatabase, output_file: str):
    no_mail_families = mb_db.lookup_by_property("email", None)
    assert len(no_mail_families) == 1
    no_mail_family = no_mail_families[0]
    no_mail_db = Database()
    no_mail_db.add_people(no_mail_family.people)
    ad_db = AdressDatabase(input_db=no_mail_db)
    ad_db.to_excel(output_file)

def load_main_db(input_file: str) -> Database:
    main_db = Database(input_file)
    return main_db

def load_mail_based_db(main_db: Database) -> MailBasedDatabase:
    mb_db = MailBasedDatabase(input_db=main_db)
    return mb_db

def add_from_additional_list(main_db: Database, input_file: str) -> Database:
    additional_db = Database(input_file)
    main_db.add_people(additional_db.people)
    return main_db

def add_mail_from_backup_db(main_db: Database, input_file: str) -> Database:
    backup_db = Database(input_file)
    main_db.copy_value_of_property_from_referencelist_if_empty_and_all_other_properties_match("email", backup_db.people)
    return main_db

def remove_mail_from_removelist(main_db: Database, input_file: str) -> Database:
    remove_from_mailinglist_db = Database(input_file)
    remove_from_mailinglist_db_only_mail = [Person(emails=[person.email]) for person in remove_from_mailinglist_db.people]
    main_db.remove_property_for_people_matching_removelist("email", remove_from_mailinglist_db_only_mail)
    return main_db

def export_as_cleverreach_csv(mb_db: MailBasedDatabase, output_file: str):
    cr_db = CleverreachDatabase(input_mb_database=mb_db)
    cr_db.to_csv(output_file)
    
def export_adult_people_joined_at_or_after_date_excel(main_db: Database, date: pd.Timestamp, output_file: str):
    adult_cat = ["Aktive Turner", "Aktive Turnerin", "Passivmitglied", "Freimitg. Turnend (1)", "Freimitg. nturnend (10)", "Ehrenmitg. nturnend", "Ehrenmitg. turnend"]
    adult_people = []
    for cat in adult_cat:
        adult_people += main_db.lookup_by_property("category", cat)
    adult_people_db = Database()
    adult_people_db.add_people(adult_people)
    joined_after_date_people = adult_people_db.lookup_by_property("date_added", date, comparator=np.greater_equal)
    
    joined_after_date_db = Database()
    joined_after_date_db.add_people(joined_after_date_people)
    ad_db = AdressDatabase(input_db=joined_after_date_db)
    ad_db.to_excel(output_file)
    
def export_jugend_born_in_year(main_db: Database, year: int, output_file: str):
    jugend_cat = ["Mädchen", "Knaben"]
    jugend_people = []
    for cat in jugend_cat:
        jugend_people += main_db.lookup_by_property("category", cat)
    jugend_people_db = Database()
    jugend_people_db.add_people(jugend_people)
    
    after_date = pd.Timestamp(str(year))
    born_after_date_people = jugend_people_db.lookup_by_property("birthday", after_date, comparator=np.greater_equal)
    born_after_date_db = Database()
    born_after_date_db.add_people(born_after_date_people)
    
    before_date = pd.Timestamp(str(year+1))
    born_before_date_people = born_after_date_db.lookup_by_property("birthday", before_date, comparator=np.less)
    born_before_date_db = Database()
    born_before_date_db.add_people(born_before_date_people)
    
    ad_db = AdressDatabase(input_db=born_before_date_db)
    ad_db.to_excel(output_file)
    
    
path = "/Users/Lukas/Library/CloudStorage/OneDrive-FreigegebeneBibliotheken–TurnvereinWürenlos/Kommunikation - Dokumente/Interne Kommunikation/CleverReach/Adressen/"
#path = path.replace(" ", "\ ")

fin = "Kontaktliste/Mitglieder12-4_23.xlsx"
fadditional = "Newsletter_Zusaetzlich.xlsx"
fremove = "Newsletter_abmeldungen.xlsx"

fbackup = "Kontaktliste/Mitglieder10_23.xlsx"

fout = "TVW_List_OUT.csv"
fout_nomail = "TVW_List_OUT_nomail.xlsx"
fout_neumitglieder = "TVW_List_OUT_neumitglieder.xlsx"
fout_jugenduebertritt = "TVW_List_OUT_jugenduebertritte.xlsx"

main_db = load_main_db(path + fin)


main_db = add_from_additional_list(main_db, path + fadditional)
main_db = add_mail_from_backup_db(main_db, path + fbackup)
main_db = remove_mail_from_removelist(main_db, path + fremove)

mb_db = load_mail_based_db(main_db)
export_as_cleverreach_csv(mb_db, path + fout)
export_no_mail_people_excel(mb_db, path + fout_nomail)

#GV
#export_adult_people_joined_at_or_after_date_excel(main_db, pd.Timestamp('2023-01-15'), path+fout_neumitglieder)
#export_jugend_born_in_year(main_db, 2007, path+fout_jugenduebertritt)


