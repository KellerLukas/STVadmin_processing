import json
import pandas as pd
from src.utils.databases import MailBasedFamily, MailBasedDatabase, Database, Person


class AdressDatabase:
    def __init__(self, input_file: str = None, input_db: Database = None):
        self.columns = [
            "Vorname",
            "Nachname",
            "Strasse",
            "PLZ",
            "Ort",
            "Geburtsdatum",
            "Kategorie",
            "Geschlecht",
            "Anrede",
            "Email",
            "Beitrittsdatum"
        ]
        self._df = None
        self._database = input_db
        self.input_file = input_file
        
        assert self._database or self.input_file
            
    @property
    def df(self):
        if self._df is None:
            self.__create_from_database(self.database)
        return self._df
    
    @property
    def database(self):
        if self._database is None:
            self._database = Database(self.input_file)
        return self._database

    def __create_from_database(self, db: Database):
        self._df = pd.DataFrame(columns=self.columns)
        for person in db.people:
            self.__add_entry(person)

    def __add_entry(self, person: Person):
        entry_constructor_dict = {}
        with open("src/utils/STVAdmin_to_AdressDB_translator.json", "r") as f:
            translator = json.load(f) 
        for col in self.columns:
            if col == "Anrede":
                entry_constructor_dict[col] = "Liebe" if getattr(person, translator["Geschlecht"])=="Weiblich" else "Lieber"
                continue
            entry_constructor_dict[col] = getattr(person, translator[col])

        assert set(entry_constructor_dict.keys()) == set(self.columns)

        entry_constructor_dict = {
            key: [value] for key, value in entry_constructor_dict.items()
        }

        self._df = pd.concat([self._df, pd.DataFrame.from_dict(entry_constructor_dict)])

    def to_csv(self, filename: str):
        self.df.to_csv(filename,index=False)
        
    def to_excel(self, filename: str):
        self.df.to_excel(filename, index=False)

class RiegenAdressDatabase:
    def __init__(self, member_ad_db: AdressDatabase, coach_ad_db: AdressDatabase):
        member_df = member_ad_db.df
        member_df["Funktion"] = "Mitglied"
        coach_df = coach_ad_db.df
        coach_df["Funktion"] = "Leiter*in"
        self.df = pd.concat([member_df, coach_df])
    
    def to_excel(self, filename: str):
        self.df.to_excel(filename, index=False)
        
    
    
        
    
        
        
        
