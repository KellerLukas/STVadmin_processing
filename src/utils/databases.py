import pandas as pd
import json


class Person:
    def __init__(
        self,
        gender: str = None,
        first_name: str = None,
        last_name: str = None,
        street: str = None,
        plz=None,
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

    @property
    def age(self):
        if not isinstance(self.birthday, pd.Timestamp):
            return None
        now = pd.Timestamp.now()
        return self.calculate_age_at_ts(now)

    def calculate_age_at_ts(self, ts: pd.Timestamp) -> int:
        assert isinstance(self.birthday, pd.Timestamp)

        age = ts.year - self.birthday.year
        age -= (ts.month, ts.day) < (self.birthday.month, self.birthday.day)
        return age

class Database:
    def __init__(self, input_file: str = None):
        self.people = []
        if input_file is not None:
            self.people = self._load_people_from_input_file(input_file)

    def lookup_by_property(self, property: str, search_input) -> list[Person]:
        people_found = []
        for person in self.people:
            if getattr(person, property, None) == search_input:
                people_found.append(person)
        return people_found

    def _load_people_from_input_file(self, input_file: str) -> list[Person]:
        input_df = self.__load_input_file(input_file)
        input_df = input_df.dropna(how="all")
        people_list = []
        for idx in input_df.index:
            row = input_df.loc[idx, :]
            with open("src/utils/STVAdmin_export_translator.json", "r") as f:
                translator = json.load(f)

            person_constructor_dict = {}
            for key in translator:
                if isinstance(translator[key], str):
                    person_constructor_dict[key] = row[translator[key]]
                if isinstance(translator[key], list):
                    person_constructor_dict[key] = [
                        row[sub_key] for sub_key in translator[key]
                    ]

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
        return pd.read_csv(input_file, encoding="utf8", delimiter=";")

    def __load_excel(self, input_file: str) -> pd.DataFrame:
        return pd.read_excel(input_file)

class MailBasedFamily:
    def __init__(self, people: list[Person]):
        assert self.__all_emails_are_equal(people)
        assert len(people) > 0
        self.people = people
        self.email = self.people[0].email
    

    def get_property_list(self, property: str) -> list:
        property_list = list(set([getattr(person, property, None) for person in self.people]))
        property_list.sort()
        return property_list

    def __all_emails_are_equal(self, people: list[Person]):
        email_list = [person.email for person in people]
        return len(set(email_list)) == 1
    
    def add_person(self, new_person: Person):
        assert self.__all_emails_are_equal(self.people+[new_person])
        self.people.append(new_person)


class MailBasedDatabase:
    def __init__(self, input_file: str = None):
        self.mail_based_families = []
        if input_file is not None:
            self.add_from_database(Database(input_file))
        
    def add_from_database(self, db: Database):
        for person in db.people:
            self.add_person(person)
    
    
    def add_mail_based_family(self, new_mbfamily: MailBasedFamily):
        for mbfamily in self.mail_based_families:
            if new_mbfamily.email == mbfamily.email:
                for person in new_mbfamily.people:
                    mbfamily.add_person(person)
                    return
        self.mail_based_families.append(new_mbfamily)
    
    def add_person(self, new_person: Person):
        self.add_mail_based_family(MailBasedFamily([new_person]))
    
    def lookup_by_property(self, property: str, search_input) -> list[MailBasedFamily]:
        mbfamilies_found = []
        for mbfamily in self.mail_based_families:
            if search_input in mbfamily.get_property_list(property):
                mbfamilies_found.append(mbfamily)
        return mbfamilies_found
