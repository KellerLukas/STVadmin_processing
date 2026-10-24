import logging
from enum import StrEnum

import pandas as pd

from src.cleverreach.cleverreach_client import CleverreachClient, Receiver
from src.config.constants import CR_ALLE_MITGLIEDER_GROUP_ID, CR_AUSGETRETEN_FILTER_ID
from src.config.paths import FILENAME_CLEVERREACH_DATA
from src.mySTV.mystv_processor import (
    FEMALE_SALUTATION,
    MALE_SALUTATION,
    InternalCategory,
    MembersColumns,
)
from src.utils.utils import OUTPUT_FOLDER_PATH, concatenate_unique_values_to_string


class CRAttributes(StrEnum):
    EMAIL = "Email"
    FIRST_NAME = "firstname"
    LAST_NAME = "lastname"
    UPDATED = "updated"
    MALE = "maennlich"
    FEMALE = "weiblich"
    AGE_BELOW_65 = "age_below_65"


class CleverreachProcessor:
    def __init__(self):
        self.cr_client = CleverreachClient()

    def sync_members_to_cleverreach(
        self, members: pd.DataFrame
    ) -> tuple[list[str], list[str]]:
        self._push_members_to_cleverreach(members=members)
        self._update_ausgetreten_filter_in_cleverreach(pd.Timestamp.today().floor("D"))
        removed_emails = self._remove_receivers_from_ausgetreten_filter_in_cleverreach()
        activated_emails = self._activate_inactive_receivers_in_cleverreach()
        return removed_emails, activated_emails

    def export_cleverreach_data_to_csv(self, members: pd.DataFrame):
        receivers = self._create_receivers_from_members(members)
        self._export_receivers_to_csv(receivers)

    def _export_receivers_to_csv(self, receivers: list[Receiver]):
        rows = []
        for receiver in receivers:
            rows.append(
                {CRAttributes.EMAIL: receiver.email, **receiver.global_attributes}
            )
        data = pd.DataFrame(rows)
        data.to_csv(OUTPUT_FOLDER_PATH / FILENAME_CLEVERREACH_DATA, index=False)

    def _push_members_to_cleverreach(self, members: pd.DataFrame):
        receivers = self._create_receivers_from_members(members)
        self.cr_client.update_receivers_for_group(
            group_id=CR_ALLE_MITGLIEDER_GROUP_ID, receivers=receivers
        )

    def _update_ausgetreten_filter_in_cleverreach(self, date: pd.Timestamp):
        filter_template = {
            "id": CR_AUSGETRETEN_FILTER_ID,
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
            group_id=CR_ALLE_MITGLIEDER_GROUP_ID,
            filter_id=CR_AUSGETRETEN_FILTER_ID,
            filter_data=filter_template,
        )

    def _remove_receivers_from_ausgetreten_filter_in_cleverreach(self) -> list[str]:
        r = self.cr_client.get_receivers_for_group_filtered_complete(
            group_id=CR_ALLE_MITGLIEDER_GROUP_ID, filter_id=CR_AUSGETRETEN_FILTER_ID
        )
        ids_to_remove = [receiver["id"] for receiver in r]
        emails_to_remove = [receiver["email"] for receiver in r]
        if len(ids_to_remove) == 0:
            logging.info("No receivers to remove from ausgetreten filter")
            return []
        self.cr_client.delete_receivers(
            group_id=CR_ALLE_MITGLIEDER_GROUP_ID, receivers=ids_to_remove
        )
        return emails_to_remove

    def _activate_inactive_receivers_in_cleverreach(self) -> list[str]:
        r = self.cr_client.get_receivers_for_group_complete(
            group_id=CR_ALLE_MITGLIEDER_GROUP_ID, type="inactive"
        )
        ids_to_activate = [receiver["id"] for receiver in r]
        emails_activated = [receiver["email"] for receiver in r]
        if len(ids_to_activate) == 0:
            logging.info("No inactive receivers to activate")
            return []
        for receiver_id in ids_to_activate:
            self.cr_client.activate_receiver(
                group_id=CR_ALLE_MITGLIEDER_GROUP_ID, receiver_id=receiver_id
            )
        return emails_activated

    def _create_receivers_from_members(self, members: pd.DataFrame) -> list[Receiver]:
        receivers = []

        members = members.loc[members[MembersColumns._GETS_NEWSLETTER]]
        email_groups = members.groupby(MembersColumns._PRIMARY_EMAIL)
        for email, group in email_groups:
            if pd.isna(email) or email.strip() == "":
                continue  # Skip members without an email address

            global_attributes = {}
            global_attributes[CRAttributes.FIRST_NAME] = (
                concatenate_unique_values_to_string(group[MembersColumns.FIRST_NAME])
            )
            global_attributes[CRAttributes.LAST_NAME] = (
                concatenate_unique_values_to_string(group[MembersColumns.SURNAME])
            )

            global_attributes[CRAttributes.UPDATED] = (
                pd.Timestamp.today().floor(freq="D").strftime("%d.%m.%Y")
            )

            global_attributes[CRAttributes.MALE] = (
                MALE_SALUTATION in group[MembersColumns.SALUTATION].unique()
            )
            global_attributes[CRAttributes.FEMALE] = (
                FEMALE_SALUTATION in group[MembersColumns.SALUTATION].unique()
            )

            global_attributes[CRAttributes.AGE_BELOW_65] = any(
                group[MembersColumns._AGE] < 65
            )

            for cat in InternalCategory:
                key = cat.lower().replace(" ", "_")
                global_attributes[key] = cat in group[MembersColumns._INTERNAL_CATEGORY]

            receiver = Receiver(email=email, global_attributes=global_attributes)
            receivers.append(receiver)
        return receivers
