import pandas as pd
from src.utils.databases import MailBasedFamily, MailBasedDatabase


class CleverreachDatabase:
    def __init__(self, input_file: str = None):
        self.categories = [
            "Aktive Turner",
            "Aktive Turnerin",
            "Passivmitglied",
            "Kitu",
            "Mädchen",
            "Knaben",
            "Freimitglied turnend",
            "Freimitglied nicht turnend",
            "Ehrenmitglied nicht turnend",
            "Ehrenmitglied turnend",
        ]
        self.columns = [
            "Vorname",
            "Nachname",
            "Email",
            "Männlich",
            "Weiblich",
            "updated",
        ] + self.categories
        self.df = pd.DataFrame(columns=self.columns)
        if input_file is not None:
            self.add_from_mail_based_database(MailBasedDatabase(input_file))

    def add_from_mail_based_database(self, mb_db: MailBasedDatabase):
        for mbfamily in mb_db.mail_based_families:
            self.add_entry(mbfamily)

    def add_entry(self, mbfamily: MailBasedFamily):
        entry_constructor_dict = {}
        entry_constructor_dict["Email"] = mbfamily.email
        entry_constructor_dict[
            "Vorname"
        ] = self._concatenate_unique_list_entries_to_string(
            mbfamily.get_property_list("first_name")
        )
        entry_constructor_dict[
            "Nachname"
        ] = self._concatenate_unique_list_entries_to_string(
            mbfamily.get_property_list("last_name")
        )

        entry_constructor_dict["updated"] = pd.Timestamp.today().floor(freq="D")

        for gender in ["Männlich", "Weiblich"]:
            entry_constructor_dict[gender] = gender in mbfamily.get_property_list(
                "gender"
            )

        for category in self.categories:
            entry_constructor_dict[category] = category in mbfamily.get_property_list(
                "category"
            )

        assert set(entry_constructor_dict.keys()) == set(self.columns)

        entry_constructor_dict = {
            key: [value] for key, value in entry_constructor_dict.items()
        }

        self.df = pd.concat([self.df, pd.DataFrame.from_dict(entry_constructor_dict)])

    def _concatenate_unique_list_entries_to_string(self, input_list: list) -> str:
        input_list = [str(entry) for entry in input_list]
        input_list = list(set(input_list))
        input_list.sort()
        return " & ".join(input_list)
