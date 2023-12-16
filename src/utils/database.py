import pandas as pd
import json


class Person:
    def __init__(self,
        gender: str = None,
        first_name: str = None,
        last_name: str = None,
        street: str = None,
        plz = None,
        city: str = None,
        birthday: str = None,
        emails: list[str] = [],
        category: str = None,
    ):
        self.gender = gender
        self.first_name = first_name
        self.last_name = last_name
        self.street = street
        self.plz = str(plz)
        self.city = city
        self._birthday = birthday
        self._email = None
        self.emails = [email for email in emails if isinstance(email, str)]
        self.category = category

    @property
    def email(self):
        if self._email == None:
            if len(self.emails) > 0:
                self._email = self.emails[0]
        return self._email
    
    @property
    def birthday(self):
        if isinstance(self._birthday, str):
            self._birthday = pd.Timestamp(self._birthday)
        return self._birthday


class Database:
    def __init__(self, input_file: str = None):
        self.people = []
        if input_file is not None:
            self.people = self._load_people_from_input_file(input_file)

    def lookup_by_property(self, property: str, search_input) -> list[Person]:
        people_found = []
        for person in self.people:
            if getattr(person, property) == search_input:
                people_found.append(person)
        return people_found

    def _load_people_from_input_file(self, input_file: str) -> list[Person]:
        input_df = self.__load_input_file(input_file)
        input_df = input_df.dropna(how="all")
        people_list = []
        for idx in input_df.index:
            row = input_df.loc[idx,:]
            with open("src/utils/STVAdmin_export_translator.json", "r") as f:
                translator = json.load(f)
            
            person_constructor_dict = {}
            for key in translator:
                if isinstance(translator[key], str):
                    person_constructor_dict[key] = row[translator[key]]
                if isinstance(translator[key], list):
                    person_constructor_dict[key] = [row[sub_key] for sub_key in translator[key]]
            
                
            people_list.append(Person(**person_constructor_dict))
            
        return people_list

    def __load_input_file(self, input_file: str) -> pd.DataFrame:
        if "csv" in input_file:
            return self.__load_csv(input_file)
        excel_endings = ["xls", "xlsx", "xlsm", "xlsb"]
        for ending in excel_endings:
            if ending in input_file:
                return self.__load_excel(input_file)
        raise IOError("wrong input file")

    def __load_csv(self, input_file: str) -> pd.DataFrame:
        return pd.read_csv(input_file,encoding='utf8',delimiter=";")

    def __load_excel(self, input_file: str) -> pd.DataFrame:
        return pd.read_excel(input_file)

