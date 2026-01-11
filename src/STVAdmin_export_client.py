import os
import copy
import logging
import pandas as pd
import numpy as np
from typing import Optional
from pathlib import Path

from src import (
    ADULT_CAT,
    EHRENMITGLIEDER_CAT,
    NOT_ACTIVE_ERW_CAT,
    MALE,
    JUGEND_CAT,
    is_jugend_riege,
)
from src.utils.cleverreach_client import (
    ALLE_MITGLIEDER_GROUP_ID,
    AUSGETRETEN_FILTER_ID,
    CleverreachClient,
)
from src.utils.dynamics_client import DynamicsClient

from src.utils.databases import MailBasedDatabase, Database, HouseBasedDatabase
from src.utils.cleverreach_database import CleverreachDatabase
from src.utils.adress_databases import (
    AdressDatabase,
    RiegenAdressDatabase,
    HouseBasedAdressDatabase,
)
from src.config.paths import WORKING_DIR_PATH

OUTPUT_FOLDER = "OUT"
FILENAME_ADDITIONAL_PEOPLE = "Newsletter_Zusaetzlich.xlsx"
FILENAME_HOUSEMATES = "TVW_Mitglieder_Housemates.xlsx"
FILENAME_BACKUP_LIST = "TVW_Mitglieder_Backup_10_23.xlsx"
FILENAME_REMOVE_LIST = "Newsletter_abmeldungen.xlsx"
FILENAME_JUBILARE = "TVW_List_OUT_Jubilare_{year}.xlsx"

FILENAME_NEUMITGLIEDER = "TVW_List_OUT_neumitglieder.xlsx"
FILENAME_JUGENDUEBERTRITT = "TVW_List_OUT_jugenduebertritte.xlsx"
FILENAME_LOST_EMAIL = "TVW_List_OUT_lost_email.xlsx"
FILENAME_INFOHEFT = "TVW_List_OUT_Infoheft.xlsx"


class STVAdminExportClient:
    tag_base_member = "BaseMember"
    tag_non_member_newsletter_recipient = "NonMemberNewsletterRecipient"

    def __init__(
        self,
        path: Optional[str] = None,
        keep_files: Optional[bool] = False,
        debugging_mode: Optional[bool] = False,
    ):
        self.path = path or WORKING_DIR_PATH
        self.path = Path(self.path)
        Path(os.path.join(self.path, OUTPUT_FOLDER)).mkdir(parents=True, exist_ok=True)
        self._userlist_filename: Optional[Path] = None
        self._riegenlist_filename: Optional[Path] = None
        self._main_db = None
        self._keep_files = keep_files
        self._debugging_mode = debugging_mode
        self.cr_client = CleverreachClient()

    def __del__(self):
        if self._keep_files:
            return
        if self._userlist_filename:
            os.remove(os.path.join(self.path, self._userlist_filename))
        if self._riegenlist_filename:
            os.remove(os.path.join(self.path, self._riegenlist_filename))

    @property
    def userlist_filename(self):
        if self._userlist_filename is None:
            self._userlist_filename = self._get_userlist_file_from_dynamics()
        return self._userlist_filename

    @property
    def riegenlist_filename(self):
        if self._riegenlist_filename is None:
            self._riegenlist_filename = self._get_riegenlist_file_from_dynamics()
        return self._riegenlist_filename

    @property
    def main_db(self):
        if self._main_db is None:
            self._main_db = self._load_main_db()
            self._detect_missing_emails_from_backup()
            self._remove_mail_from_removelist()
            self._add_additional_newsletter_recipients()
        return self._main_db

    def export_riegenlisten_excel(self):
        riegen = self._get_riegen()
        path = Path(os.path.join(self.path, OUTPUT_FOLDER, "Riegenlisten"))
        path.mkdir(parents=True, exist_ok=True)

        for riege in riegen.keys():
            member_db = Database()
            member_db.add_people(riegen[riege]["members"])
            member_ad_db = AdressDatabase(input_db=member_db)

            coach_db = Database()
            coach_db.add_people(riegen[riege]["coaches"])
            coach_ad_db = AdressDatabase(input_db=coach_db)
            today = pd.Timestamp.now()
            filename = f"{riege}_export_{today.strftime('%d.%m.%Y')}.xlsx"

            riegen_ad_db = RiegenAdressDatabase(
                member_ad_db=member_ad_db, coach_ad_db=coach_ad_db
            )
            riegen_ad_db.to_excel(os.path.join(path, filename))

    def export_cleverreach_csv(self, output_filename: str = "TVW_List_OUT.csv"):
        mb_db = MailBasedDatabase(input_db=self.main_db)
        cr_db = CleverreachDatabase(input_mb_database=mb_db)
        cr_db.to_csv(os.path.join(self.path, OUTPUT_FOLDER, output_filename))

    def sync_to_cleverreach(self) -> list[str]:
        self.push_data_to_cleverreach()
        self.update_ausgetreten_filter_in_cleverreach(pd.Timestamp.today().floor("D"))
        removed_emails = self.remove_receivers_from_ausgetreten_filter_in_cleverreach()
        activated_emails = self.activate_inactive_receivers_in_cleverreach()
        return removed_emails, activated_emails

    def push_data_to_cleverreach(self):
        mb_db = MailBasedDatabase(input_db=self.main_db)
        cr_db = CleverreachDatabase(input_mb_database=mb_db)
        receivers = cr_db.to_receivers()
        self.cr_client.update_receivers_for_group(
            group_id=ALLE_MITGLIEDER_GROUP_ID, receivers=receivers
        )

    def update_ausgetreten_filter_in_cleverreach(self, date: pd.Timestamp):
        filter_template = {
            "id": AUSGETRETEN_FILTER_ID,
            "name": "Ausgetreten",
            "rules": [
                {"operator": "AND", "field": "(", "logic": "", "condition": ""},
                {
                    "operator": "OR",
                    "field": "a1037193.value",
                    "logic": "NEQ",
                    "condition": date.strftime("%Y-%m-%d"),
                },
                {
                    "operator": "OR",
                    "field": "a1037193.value",
                    "logic": "ISNULL",
                    "condition": "",
                },
                {"operator": "AND", "field": ")", "logic": "", "condition": ""},
            ],
        }
        self.cr_client.update_filter(
            group_id=ALLE_MITGLIEDER_GROUP_ID,
            filter_id=AUSGETRETEN_FILTER_ID,
            filter_data=filter_template,
        )

    def remove_receivers_from_ausgetreten_filter_in_cleverreach(self) -> list[str]:
        r = self.cr_client.get_receivers_for_group_filtered_complete(
            group_id=ALLE_MITGLIEDER_GROUP_ID, filter_id=AUSGETRETEN_FILTER_ID
        )
        ids_to_remove = [receiver["id"] for receiver in r]
        emails_to_remove = [receiver["email"] for receiver in r]
        if len(ids_to_remove) == 0:
            logging.info("No receivers to remove from ausgetreten filter")
            return []
        self.cr_client.delete_receivers(
            group_id=ALLE_MITGLIEDER_GROUP_ID, receivers=ids_to_remove
        )
        return emails_to_remove

    def activate_inactive_receivers_in_cleverreach(self) -> list[str]:
        r = self.cr_client.get_receivers_for_group_complete(
            group_id=ALLE_MITGLIEDER_GROUP_ID, type="inactive"
        )
        ids_to_activate = [receiver["id"] for receiver in r]
        emails_activated = [receiver["email"] for receiver in r]
        if len(ids_to_activate) == 0:
            logging.info("No inactive receivers to activate")
            return []
        for receiver_id in ids_to_activate:
            self.cr_client.activate_receiver(
                group_id=ALLE_MITGLIEDER_GROUP_ID, receiver_id=receiver_id
            )
        return emails_activated

    def export_no_mail_excel(self, output_filename: str = "TVW_List_OUT_nomail.xlsx"):
        ad_db = self._convert_no_mail_people_with_property_to_ad_db()
        ad_db.to_excel(os.path.join(self.path, OUTPUT_FOLDER, output_filename))

    def export_ehrenmitglieder_no_mail_people_excel(
        self, output_filename: str = "TVW_List_OUT_ehrenmitglieder_nomail.xlsx"
    ):
        ad_db = self._convert_no_mail_people_with_property_to_ad_db(
            values=EHRENMITGLIEDER_CAT, property="category"
        )
        ad_db.to_excel(os.path.join(self.path, OUTPUT_FOLDER, output_filename))

    def export_adult_people_joined_in_timerange_excel(
        self,
        output_filename: str,
        begin: Optional[pd.Timestamp] = None,
        end: Optional[pd.Timestamp] = None,
    ):
        adult_people = []
        for cat in ADULT_CAT:
            adult_people += self.main_db.lookup_by_property("category", cat)
        current_db = Database()
        current_db.add_people(adult_people)

        if begin:
            joined_after_date_people = current_db.lookup_by_property(
                property="date_added", search_input=begin, comparator=np.greater_equal
            )
            current_db = Database()
            current_db.add_people(joined_after_date_people)
        if end:
            joined_before_date_people = current_db.lookup_by_property(
                property="date_added", search_input=end, comparator=np.less
            )
            current_db = Database()
            current_db.add_people(joined_before_date_people)

        ad_db = AdressDatabase(input_db=current_db)
        ad_db.to_excel(os.path.join(self.path, OUTPUT_FOLDER, output_filename))

    def export_jugend_born_in_year(self, year: int, output_filename: str):
        jugend_people = []
        for cat in JUGEND_CAT:
            jugend_people += self.main_db.lookup_by_property("category", cat)
        jugend_people_db = Database()
        jugend_people_db.add_people(jugend_people)

        after_date = pd.Timestamp(year=year, month=1, day=1)
        born_after_date_people = jugend_people_db.lookup_by_property(
            "birthday", after_date, comparator=np.greater_equal
        )
        born_after_date_db = Database()
        born_after_date_db.add_people(born_after_date_people)

        before_date = pd.Timestamp(year=year + 1, month=1, day=1)
        born_before_date_people = born_after_date_db.lookup_by_property(
            "birthday", before_date, comparator=np.less
        )
        born_before_date_db = Database()
        born_before_date_db.add_people(born_before_date_people)

        ad_db = AdressDatabase(input_db=born_before_date_db)
        ad_db.to_excel(os.path.join(self.path, OUTPUT_FOLDER, output_filename))

    def export_gv_lists(self, gv_year: int):
        last_gv = pd.Timestamp(year=gv_year - 1, month=1, day=1)
        year_for_uebertritt = gv_year - 17
        self.export_adult_people_joined_in_timerange_excel(
            output_filename=FILENAME_NEUMITGLIEDER, begin=last_gv
        )
        jubilare = [25, 30, 40, 50, 60, 70, 80]
        for jubilar in jubilare:
            year = gv_year - jubilar
            self.export_adult_people_joined_in_timerange_excel(
                output_filename=FILENAME_JUBILARE.format(year=jubilar),
                begin=pd.Timestamp(year=year, month=1, day=1),
                end=pd.Timestamp(year=year + 1, month=1, day=1),
            )
        self.export_jugend_born_in_year(
            year=year_for_uebertritt, output_filename=FILENAME_JUGENDUEBERTRITT
        )

    def export_infoheft_list(self):
        printed_infoheft_people = self.main_db.lookup_by_property(
            "printed_magazine", True
        )
        printed_infoheft_db = Database()
        printed_infoheft_db.add_people(printed_infoheft_people)
        hb_db = HouseBasedDatabase(input_db=printed_infoheft_db)
        hb_db.combine_housemates(
            housemates_file=os.path.join(self.path, FILENAME_HOUSEMATES)
        )
        hb_ad_db = HouseBasedAdressDatabase(hb_db=hb_db)
        hb_ad_db.to_excel(os.path.join(self.path, OUTPUT_FOLDER, FILENAME_INFOHEFT))

    def get_statistics(self) -> str:
        # ToDo: refactor to make code easier to read / maintain
        max_age = 0
        min_age = np.inf
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
        num_total = 0
        for person in self.main_db.people:
            if self.tag_base_member not in person.tags:
                continue
            num_total += 1
            if person.age < min_age:
                min_age = person.age
            if person.age > max_age:
                max_age = person.age
            if person.category not in ADULT_CAT:
                num_of_kids += 1
                if person.gender == MALE:
                    num_of_boys += 1
                else:
                    num_of_girls += 1
            else:
                num_of_erw += 1
                if person.gender == MALE:
                    num_of_men += 1
                    if person.category in NOT_ACTIVE_ERW_CAT:
                        num_of_passive_or_nturnend_men += 1
                    else:
                        num_of_active_men += 1
                else:
                    num_of_women += 1
                    if person.category in NOT_ACTIVE_ERW_CAT:
                        num_of_passive_or_nturnend_women += 1
                    else:
                        num_of_active_women += 1

        res = f"""


            **Total Number of Members:** {str(num_total)}  

            **Number of Adults:** {str(num_of_erw)}  
            Men: {str(num_of_men)}  
            active Men: {str(num_of_active_men)}  
            passive or non-active Men: {str(num_of_passive_or_nturnend_men)}  
            Women: {str(num_of_women)}  
            active Women: {str(num_of_active_women)}  
            passive or non-active Women: {str(num_of_passive_or_nturnend_women)}  
                
            **Number of Children:** {str(num_of_kids)}  
                Boys: {str(num_of_boys)}  
                Girls: {str(num_of_girls)}  


            **Oldest Member:** {str(max_age)} years old  
            **Youngest Member:** {str(min_age)} years old
            """
        return res

    def create_riegenmatrix(
        self, output_filename: Optional[str] = "TVW_riegenmatrix.xlsx"
    ):
        riegen = self._get_riegen()
        riegen = {
            key: value for key, value in riegen.items() if not is_jugend_riege(key)
        }
        matrix = pd.DataFrame(columns=riegen.keys(), index=riegen.keys())

        for riege, value in riegen.items():
            members = value["members"]
            coaches = value["coaches"]
            combined = members + coaches

            for comparison_riege, comparison_value in riegen.items():
                comparison_members = comparison_value["members"]
                comparison_coaches = comparison_value["coaches"]
                comparison_combined = comparison_members + comparison_coaches

                people_in_both = [
                    person for person in combined if person in comparison_combined
                ]

                matrix.loc[riege, comparison_riege] = len(people_in_both)
        matrix.to_excel(os.path.join(self.path, OUTPUT_FOLDER, output_filename))

    def _convert_no_mail_people_with_property_to_ad_db(
        self,
        values: Optional[list[str]] = None,
        property: Optional[str] = None,
        comparator=None,
    ) -> AdressDatabase:
        mb_db = MailBasedDatabase(input_db=self.main_db)
        no_mail_families = mb_db.lookup_by_property("email", None)
        if len(no_mail_families) != 1:
            raise ValueError("To many no mail families!")
        no_mail_family = no_mail_families[0]
        no_mail_db = Database()
        no_mail_db.add_people(no_mail_family.people)

        if values is None:
            wanted_people_db = no_mail_db
        else:
            wanted_people = []
            for value in values:
                wanted_people += no_mail_db.lookup_by_property(
                    property=property, search_input=value, comparator=comparator
                )
            wanted_people_db = Database()
            wanted_people_db.add_people(wanted_people)
        ad_db = AdressDatabase(input_db=wanted_people_db)
        return ad_db

    def _get_riegen(self) -> dict:
        riegen = {}
        for person in self.main_db.people:
            for riege in person.riegen_member:
                if riege not in riegen.keys():
                    riegen[riege] = {"members": [], "coaches": []}
                riegen[riege]["members"].append(person)
            for riege in person.riegen_coach:
                if riege not in riegen.keys():
                    riegen[riege] = {"members": [], "coaches": []}
                riegen[riege]["coaches"].append(person)
        return riegen

    def _get_userlist_file_from_dynamics(self):
        dc = DynamicsClient(debugging_mode=self._debugging_mode)
        filename = dc.download_userlist_to_folder(self.path)
        return filename

    def _get_riegenlist_file_from_dynamics(self):
        dc = DynamicsClient(debugging_mode=self._debugging_mode)
        filename = dc.download_riegenlist_to_folder(self.path)
        return filename

    def _load_main_db(self):
        main_db = Database(os.path.join(self.path, self.userlist_filename))
        main_db.load_riegen(os.path.join(self.path, self.riegenlist_filename))
        main_db.add_tag_to_all(self.tag_base_member)
        return main_db

    def _add_additional_newsletter_recipients(self):
        additional_db = Database(os.path.join(self.path, FILENAME_ADDITIONAL_PEOPLE))
        self.main_db.add_people(
            additional_db.people, tags={self.tag_non_member_newsletter_recipient}
        )

    def _remove_mail_from_removelist(self):
        if not FILENAME_REMOVE_LIST:
            logging.warning("No removelist provided!")
            return
        remove_from_mailinglist_db = Database(
            os.path.join(self.path, FILENAME_REMOVE_LIST)
        )
        emails_to_remove = [
            person.email for person in remove_from_mailinglist_db.people
        ]
        logging.info(f"Removing the following emails: {str(emails_to_remove)}")
        for email in emails_to_remove:
            self.main_db.remove_value_for_property_from_people(
                value=email, property="email"
            )

    def _detect_missing_emails_from_backup(self):
        if not FILENAME_BACKUP_LIST:
            logging.warning("No backup list provided!")
            return
        backup_db = Database(os.path.join(self.path, FILENAME_BACKUP_LIST))
        copied_db = copy.deepcopy(self.main_db)
        people_no_mail = [person for person in copied_db.people if person.email is None]

        copied_db.copy_value_of_property_from_referencelist_if_empty_and_all_other_properties_match_except_exclusion_list(
            property="email",
            referencelist=backup_db.people,
            exclusion_list=["category", "tags", "riegen_coach", "riegen_member"],
        )
        people_lost_email = [
            person for person in people_no_mail if person.email is not None
        ]
        if len(people_lost_email) == 0:
            return
        for person in people_lost_email:
            logging.warning(
                f"Person {person.first_name} {person.last_name} is missing email {person.email} that was present in backup"
            )
        lost_email_db = Database()
        lost_email_db.add_people(people_lost_email)
        lost_email_ad_db = AdressDatabase(input_db=lost_email_db)
        lost_email_ad_db.to_excel(
            os.path.join(self.path, OUTPUT_FOLDER, FILENAME_LOST_EMAIL)
        )
