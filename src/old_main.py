import pandas as pd
import numpy as np

from src.utils.databases import MailBasedDatabase, Database, Person
from src.utils.cleverreach_database import CleverreachDatabase
from src.utils.adress_databases import AdressDatabase, RiegenAdressDatabase
from src.utils.dynamics_client import DynamicsClient


raise Exception("This is Outdated")



def export_no_mail_people_excel(mb_db: MailBasedDatabase, output_file: str):
    no_mail_families = mb_db.lookup_by_property("email", None)
    assert len(no_mail_families) == 1
    no_mail_family = no_mail_families[0]
    no_mail_db = Database()
    no_mail_db.add_people(no_mail_family.people)
    ad_db = AdressDatabase(input_db=no_mail_db)
    ad_db.to_excel(output_file)
    
def export_ehrenmitglieder_no_mail_people_excel(mb_db: MailBasedDatabase, output_file: str):
    no_mail_families = mb_db.lookup_by_property("email", None)
    assert len(no_mail_families) == 1
    no_mail_family = no_mail_families[0]
    no_mail_db = Database()
    no_mail_db.add_people(no_mail_family.people)
    
    ehrenmitglied_kat = [
        "Ehrenmitg. nturnend",
        "Ehrenmitg. turnend",
    ]
    ehren_people = []
    for cat in ehrenmitglied_kat:
        ehren_people += no_mail_db.lookup_by_property("category", cat)
    ehren_people_db = Database()
    ehren_people_db.add_people(ehren_people)
    
    ad_db = AdressDatabase(input_db=ehren_people_db)
    ad_db.to_excel(output_file)
    

def load_main_db(userlist_file: str, riegenlist_file: str = None) -> Database:
    main_db = Database(userlist_file)
    main_db.load_riegen(riegenlist_file)
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
    main_db.copy_value_of_property_from_referencelist_if_empty_and_all_other_properties_match_except_exclusion_list(
        "email", backup_db.people,exclusion_list=['category', 'tags', 'riegen_coach', 'riegen_member']
    )
    return main_db


def remove_mail_from_removelist(main_db: Database, input_file: str) -> Database:
    remove_from_mailinglist_db = Database(input_file)
    emails_to_remove = [person.email for person in remove_from_mailinglist_db.people]
    
    for email in emails_to_remove:
        main_db.remove_value_for_property_from_people(value=email, property="email")
    return main_db


def export_as_cleverreach_csv(mb_db: MailBasedDatabase, output_file: str):
    cr_db = CleverreachDatabase(input_mb_database=mb_db)
    cr_db.to_csv(output_file)

def export_adult_people_joined_at_or_after_date_excel(
    main_db: Database, date: pd.Timestamp, output_file: str
):
    adult_people = []
    for cat in ADULT_CAT:
        adult_people += main_db.lookup_by_property("category", cat)
    adult_people_db = Database()
    adult_people_db.add_people(adult_people)
    joined_after_date_people = adult_people_db.lookup_by_property(
        "date_added", date, comparator=np.greater_equal
    )

    joined_after_date_db = Database()
    joined_after_date_db.add_people(joined_after_date_people)
    ad_db = AdressDatabase(input_db=joined_after_date_db)
    ad_db.to_excel(output_file)


def export_riegenlisten_excel(main_db: Database, path: str):
    riegen = get_riegen(main_db=main_db)
    
    for riege in riegen.keys():
        member_db = Database()
        member_db.add_people(riegen[riege]["members"])
        member_ad_db = AdressDatabase(input_db=member_db)
        
        coach_db = Database()
        coach_db.add_people(riegen[riege]["coaches"])
        coach_ad_db = AdressDatabase(input_db=coach_db)
        today = pd.Timestamp.now()
        filename = f"{riege}_export_{today.strftime("%d.%m.%Y")}.xlsx"
        
        riegen_ad_db = RiegenAdressDatabase(member_ad_db=member_ad_db, coach_ad_db=coach_ad_db)
        riegen_ad_db.to_excel(path + filename)
            
def get_riegen(main_db: Database) -> dict:
    riegen = {}
    for person in main_db.people:
        for riege in person.riegen_member:
            if riege not in riegen.keys():
                riegen[riege] = {"members":[], "coaches": []}
            riegen[riege]["members"].append(person)
        for riege in person.riegen_coach:
            if riege not in riegen.keys():
                riegen[riege] = {"members":[], "coaches": []}
            riegen[riege]["coaches"].append(person)
    return riegen        
    
def is_jugend_riege(riege:str)-> bool:
    jugend_strings = ["Meitliriege", "Knaben", "Jugi", "Kids", "Jugend", "klein", "Mädchen", "Elki"]
    for string in jugend_strings:
        if string in riege:
            return True
    return False

def create_riegenmatrix(main_db: Database, path: str):
    riegen = get_riegen(main_db=main_db)
    riegen = {key:value for key,value in riegen.items() if not is_jugend_riege(key)}
    matrix = pd.DataFrame(columns=riegen.keys(), index=riegen.keys())
    
    for riege, value in riegen.items():
        members = value["members"]
        coaches = value["coaches"]
        combined = members+coaches
        
        for comparison_riege, comparison_value in riegen.items():
            comparison_members = comparison_value["members"]
            comparison_coaches = comparison_value["coaches"]
            comparison_combined = comparison_members+comparison_coaches
            
            people_in_both = [person for person in combined if person in comparison_combined]
            
            matrix.loc[riege, comparison_riege] = len(people_in_both)
    filename = f"TVW_riegenmatrix.xlsx"
    matrix.to_excel(path+filename)
    
    
            
            
    
    
def export_jugend_born_in_year(main_db: Database, year: int, output_file: str):
    jugend_cat = ["Mädchen", "Knaben"]
    jugend_people = []
    for cat in jugend_cat:
        jugend_people += main_db.lookup_by_property("category", cat)
    jugend_people_db = Database()
    jugend_people_db.add_people(jugend_people)

    after_date = pd.Timestamp(str(year))
    born_after_date_people = jugend_people_db.lookup_by_property(
        "birthday", after_date, comparator=np.greater_equal
    )
    born_after_date_db = Database()
    born_after_date_db.add_people(born_after_date_people)

    before_date = pd.Timestamp(str(year + 1))
    born_before_date_people = born_after_date_db.lookup_by_property(
        "birthday", before_date, comparator=np.less
    )
    born_before_date_db = Database()
    born_before_date_db.add_people(born_before_date_people)

    ad_db = AdressDatabase(input_db=born_before_date_db)
    ad_db.to_excel(output_file)
    
def get_userlist_file_from_dynamics(path):
    dc = DynamicsClient()
    fin = dc.download_userlist_to_folder(path)
    return fin

def get_riegenlist_file_from_dynamics(path):
    dc = DynamicsClient()
    fin = dc.download_riegenlist_to_folder(path)
    return fin

def get_statistics(db:Database):
    not_active_erw_cat = [
                "Passivmitglied",
                "Freimitg. nturnend (10)",
                "Ehrenmitg. nturnend"]
    max_age = 0
    min_age = 200
    num_of_men = 0
    num_of_women = 0
    num_of_girls = 0
    num_of_boys = 0
    num_of_kids = 0
    num_of_erw = 0
    num_of_active_men = 0
    num_of_passive_or_nturnend_men = 0
    num_of_active_women = 0
    num_of_passive_or_nturnend_women = 0
    for person in db.people:
        if person.age < min_age:
            min_age = person.age
        if person.age > max_age:
            max_age=person.age
        if person.category not in [
        "Aktive Turner",
        "Aktive Turnerin",
        "Passivmitglied",
        "Freimitg. Turnend (1)",
        "Freimitg. nturnend (10)",
        "Ehrenmitg. nturnend",
        "Ehrenmitg. turnend"]:
            num_of_kids+=1
            if person.gender == "Männlich":
                num_of_boys+=1
            else:
                num_of_girls+=1
        else:
            num_of_erw+=1
            if person.gender == "Männlich":
                num_of_men+=1
                if person.category in not_active_erw_cat:
                    num_of_passive_or_nturnend_men +=1
                else:
                    num_of_active_men +=1 
            else:
                num_of_women+=1
                if person.category in not_active_erw_cat:
                    num_of_passive_or_nturnend_women +=1
                else:
                    num_of_active_women +=1 
        
    
    total = len(db.people)
    print(f"""
          ältestes Mitglied: {str(max_age)} Jahre alt 
          jüngstes Mitglied: {str(min_age)} Jahre alt
          
          Anzahl Erwachsene: {str(num_of_erw)}
          davon Anzahl Männer: {str(num_of_men)}
          davon Anzahl aktive Männer: {str(num_of_active_men)}
          davon Anzahl passive Männer: {str(num_of_passive_or_nturnend_men)}
          davon Anzahl Frauen: {str(num_of_women)}
          davon Anzahl aktive Frauen: {str(num_of_active_women)}
          davon Anzahl passive Frauen: {str(num_of_passive_or_nturnend_women)}
          
          Anzahl Kinder: {str(num_of_kids)}
          davon Anzahl Jungs: {str(num_of_boys)}
          davon Anzahl Mädchen: {str(num_of_girls)}
          
          Anzahl Mitglieder: {str(total)}
          """)
    


path = "/Users/Lukas/Library/CloudStorage/OneDrive-FreigegebeneBibliotheken–TurnvereinWürenlos/Kommunikation - Dokumente/Interne Kommunikation/CleverReach/Adressen/"
# path = path.replace(" ", "\ ")


fadditional = "Newsletter_Zusaetzlich.xlsx"
fremove = "Newsletter_abmeldungen.xlsx"

fbackup = "Kontaktliste/Mitglieder10_23.xlsx"

fout = "TVW_List_OUT.csv"
fout_nomail = "TVW_List_OUT_nomail.xlsx"
fout_neumitglieder = "TVW_List_OUT_neumitglieder.xlsx"
fout_jugenduebertritt = "TVW_List_OUT_jugenduebertritte.xlsx"
fout_ehren_nomail = "TVW_List_OUT_ehrenmitglieder_nomail.xlsx"


if __name__ == "__main__":
        
    userlist_file = get_userlist_file_from_dynamics(path)
    riegenlist_file = get_riegenlist_file_from_dynamics(path)
    
    
    main_db = load_main_db(path + userlist_file, path + riegenlist_file)
    export_riegenlisten_excel(main_db, path)
    #get_statistics(main_db)
    #create_riegenmatrix(main_db, path)

    main_db = add_from_additional_list(main_db, path + fadditional)

    people_no_mail_before_backup = [person for person in main_db.people if person.email is None]
    no_mail_before_backup_db = Database()
    no_mail_before_backup_db.add_people(people_no_mail_before_backup)

    main_db = add_mail_from_backup_db(main_db, path + fbackup)
    main_db = remove_mail_from_removelist(main_db, path + fremove)

    no_mail_before_backup_address_db = AdressDatabase(input_db=no_mail_before_backup_db)
    no_mail_before_backup_address_db.to_excel(path + "TVW_List_OUT_nomail_before_backup.xlsx")

    no_mail_before_backup_but_now = [person for person in no_mail_before_backup_db.people if person.email is not None]
    no_mail_before_backup_but_now_db = Database()
    no_mail_before_backup_but_now_db.add_people(no_mail_before_backup_but_now)
    AdressDatabase(input_db=no_mail_before_backup_but_now_db).to_excel(path+"TVW_List_lost_email.xlsx")


    mb_db = load_mail_based_db(main_db)
    export_as_cleverreach_csv(mb_db, path + fout)
    export_no_mail_people_excel(mb_db, path + fout_nomail)
    export_ehrenmitglieder_no_mail_people_excel(mb_db, path+fout_ehren_nomail)





    # GV
    export_adult_people_joined_at_or_after_date_excel(main_db, pd.Timestamp('1900-12-01'), path+fout_neumitglieder)
    export_jugend_born_in_year(main_db, 2007, path+fout_jugenduebertritt)




    print("done")

