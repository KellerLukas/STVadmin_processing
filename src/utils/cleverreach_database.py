import json
import pandas as pd
from pathlib import Path
from src.utils.databases import MailBasedFamily, MailBasedDatabase


class CleverreachDatabase:
    def __init__(
        self, input_file: str = None, input_mb_database: MailBasedDatabase = None
    ):
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
        self._df = None
        self._mb_database = input_mb_database
        self.input_file = input_file

        assert self._mb_database or self.input_file

    @property
    def df(self):
        if self._df is None:
            self.__create_from_mail_based_database(self.mb_database)
        return self._df

    @property
    def mb_database(self):
        if self._mb_database is None:
            self._mb_database = MailBasedDatabase(self.input_file)
        return self._mb_database

    def __create_from_mail_based_database(self, mb_db: MailBasedDatabase):
        self._df = pd.DataFrame(columns=self.columns)
        for mbfamily in mb_db.mail_based_families:
            if mbfamily.email:
                self.__add_entry(mbfamily)

    def __add_entry(self, mbfamily: MailBasedFamily):
        entry_constructor_dict = {}
        entry_constructor_dict["Email"] = mbfamily.email
        entry_constructor_dict["Vorname"] = (
            self._concatenate_unique_list_entries_to_string(
                mbfamily.get_property_list("first_name")
            )
        )
        entry_constructor_dict["Nachname"] = (
            self._concatenate_unique_list_entries_to_string(
                mbfamily.get_property_list("last_name")
            )
        )

        entry_constructor_dict["updated"] = pd.Timestamp.today().floor(freq="D")

        for gender in ["Männlich", "Weiblich"]:
            entry_constructor_dict[gender] = gender in mbfamily.get_property_list(
                "gender"
            )

        with open(
            "src/utils/STVAdmin_to_Cleverreach_category_translator.json", "r"
        ) as f:
            translator = json.load(f)
        for category in self.categories:
            entry_constructor_dict[category] = translator[
                category
            ] in mbfamily.get_property_list("category")

        assert set(entry_constructor_dict.keys()) == set(self.columns)

        entry_constructor_dict = {
            key: [value] for key, value in entry_constructor_dict.items()
        }

        self._df = pd.concat([self._df, pd.DataFrame.from_dict(entry_constructor_dict)])

    def _concatenate_unique_list_entries_to_string(self, input_list: list) -> str:
        input_list = [str(entry) for entry in input_list]
        input_list = list(set(input_list))
        input_list.sort()
        return " & ".join(input_list)

    def to_csv(self, filename: str):
        df_copy = self.df.copy()
        df_copy["updated"] = [
            pd.Timestamp(ts).strftime("%d.%m.%Y") for ts in df_copy["updated"].values
        ]
        path = Path(filename).parent
        path.mkdir(parents=True, exist_ok=True)
        df_copy.to_csv(filename, index=False)
