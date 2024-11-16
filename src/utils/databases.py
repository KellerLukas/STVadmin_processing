import pandas as pd
import numpy as np
import json
from typing import Optional


EXCEPTIONS_MEMBER_NUMBERS = [317492, 871369]

class Person:
    def __init__(
        self,
        member_number: int = None,
        gender: str = None,
        first_name: str = None,
        last_name: str = None,
        street: str = None,
        plz = None,
        city: str = None,
        birthday: str = None,
        emails: list[str] = None,
        phone_p: str = None,
        phone_m: str = None,
        phone_g: str = None,
        category: str = None,
        date_added: str = None,
        riegen_member: list[str] = None,
        riegen_coach: list[str] = None,
        tags: Optional[set[str]] = None
    ):
        self.member_number = int(member_number) if member_number else None
        self.gender = gender
        self.first_name = first_name
        self.last_name = last_name
        self.street = street
        self.plz = str(plz) if plz else None
        self.city = city
        self._birthday = birthday
        self._email = None
        self.emails = [email for email in emails if isinstance(email, str)] if emails else None
        self.phone_p = Person.__no_spaces(phone_p) if Person.__nans_to_none(phone_p) else None
        self.phone_m = Person.__no_spaces(phone_m) if Person.__nans_to_none(phone_m) else None
        self.phone_g = Person.__no_spaces(phone_g) if Person.__nans_to_none(phone_g) else None
        self.category = category
        self._date_added = date_added
        self.riegen_member = riegen_member if riegen_member else []
        self.riegen_coach = riegen_coach if riegen_coach else []
        self.tags = tags if tags else set()

    @property
    def email(self):
        if self._email is None:
            if self.emails is None:
                return self._email
            if len(self.emails) > 0:
                self._email = self.emails[0]
        return self._email
    
    @email.setter
    def email(self, value):
        self._email = value
        if value is None:
            self.emails = None
        else:
            self.emails = [value]

    @property
    def birthday(self):
        if isinstance(self._birthday, str):
            self._birthday = pd.Timestamp(self._birthday)
        return self._birthday
    
    @birthday.setter
    def birthday(self, value):
        self._birthday = value

    @property
    def date_added(self):
        if isinstance(self._date_added, str):
            self._date_added = pd.Timestamp(self._date_added)
        return self._date_added
    
    @date_added.setter
    def date_added(self, value):
        self._date_added = value

    @property
    def age(self):
        if not isinstance(self.birthday, pd.Timestamp):
            return None
        now = pd.Timestamp.now()
        return self.calculate_age_at_ts(now)
    
    @age.setter
    def age(self, value):
        pass

    def calculate_age_at_ts(self, ts: pd.Timestamp) -> int:
        assert isinstance(self.birthday, pd.Timestamp)

        age = ts.year - self.birthday.year
        age -= (ts.month, ts.day) < (self.birthday.month, self.birthday.day)
        return age
    
    @staticmethod
    def __nans_to_none(x):
        if x is None:
            return None
        if not isinstance(x, float):
            return x
        if np.isnan(x):
            return None
        return x
    
    @staticmethod
    def __no_spaces(x):
        if not isinstance(x, str):
            return x
        return x.replace(" ","")

class Database:
    def __init__(self, input_file: str = None):
        self.people = []
        self.riegen = None
        if input_file is not None:
            self.people = self._load_people_from_input_file(input_file)

    def lookup_by_property(self, property: str, search_input, comparator=None) -> list[Person]:
        comparator = comparator or np.equal
        people_found = []
        for person in self.people:
            attr = getattr(person, property, None)
            if attr is None and search_input is not None:
                continue
            if comparator(attr, search_input):
                people_found.append(person)
        return people_found
    
    def add_people(self, people_list: list[Person], tags: Optional[set[str]]=None):
        if tags is not None:
            for person in people_list:
                person.tags = person.tags.union(tags)
        self.people += people_list
        
    def add_tag_to_all(self, tag: str):
        for person in self.people:
                person.tags.add(tag)

    def _load_people_from_input_file(self, input_file: str) -> list[Person]:
        input_df = self.__load_input_file(input_file)
        input_df = input_df.dropna(how="all")
        people_list = []
        with open("src/utils/STVAdmin_export_translator.json", "r") as f:
            translator = json.load(f)
        for idx in input_df.index:
            row = input_df.loc[idx, :]
            person_constructor_dict = {}
            for key in translator:
                if key in ["riege","organ"]:
                    continue
                if isinstance(translator[key], str):
                    person_constructor_dict[key] = getattr(row, translator[key], None)
                if isinstance(translator[key], list):
                    person_constructor_dict[key] = [
                        getattr(row, sub_key, None) for sub_key in translator[key]
                    ]

            people_list.append(Person(**person_constructor_dict))

        return people_list
    
    def load_riegen(self, input_file: str):
        input_df = self.__load_input_file(input_file, 'latin1')
        input_df = input_df.dropna(how="all")            
        with open("src/utils/STVAdmin_export_translator.json", "r") as f:
            translator = json.load(f)
        with open("src/utils/STVAdmin_organ_to_riegenlist.json", "r") as f:
            organ_to_riegenlist = json.load(f)
        unique_riegen = []
        for idx in input_df.index:
            row = input_df.loc[idx, :]
            member_number = getattr(row, translator['member_number'], None)
            if member_number is None:
                continue
            if member_number in EXCEPTIONS_MEMBER_NUMBERS:
                continue
            people = self.lookup_by_property('member_number', member_number)
            if len(people) !=1:
                continue
            assert len(people) == 1
            person = people[0]
            riege = getattr(row, translator['riege'], None)
            if riege not in ["Leiter", "Leiterin"]:
                person.riegen_member.append(riege)
                if riege not in unique_riegen:
                    unique_riegen.append(riege)
                continue
            organ = getattr(row, translator['organ'], None)
            riegenlist = organ_to_riegenlist[organ]
            person.riegen_coach += riegenlist
        
        self._load_kitu_separately()
        if "Kitu" not in unique_riegen:
            unique_riegen.append("Kitu")
        self.riegen = unique_riegen
    
    def _load_kitu_separately(self):
        for person in self.people:
            if person.category == "Kitu (Kinder)":
                if "Kitu" in person.riegen_member:
                    raise ValueError("Something about the organe changed! This is not supposed to be true")
                person.riegen_member.append("Kitu")
            

            
                

    def __load_input_file(self, input_file: str, encoding: str=None) -> pd.DataFrame:
        if "csv" in input_file:
            return self.__load_csv(input_file, encoding)
        excel_endings = ["xls", "xlsx", "xlsm", "xlsb"]
        for ending in excel_endings:
            if ending in input_file:
                return self.__load_excel(input_file)
        raise IOError("wrong input file")

    def __load_csv(self, input_file: str, encoding: str = "utf8") -> pd.DataFrame:
        csv = pd.read_csv(input_file, encoding=encoding, sep=";")
        if len(csv.columns)<3:
            csv = pd.read_csv(input_file, encoding=encoding, sep=",", quotechar='+')
        return csv
    
    def __load_excel(self, input_file: str) -> pd.DataFrame:
        return pd.read_excel(input_file)
    
    def copy_value_of_property_from_reference_if_empty_and_all_other_properties_match_except_exclusion_list(self, property: str, reference: Person, exclusion_list: list[str]):
        for person in self.people:
            if self._person_matches_all_properties_present_in_reference_except_property_list(person, reference, [property]+exclusion_list):
                if getattr(person, property, None) is None:
                    setattr(person, property, getattr(reference, property))
                
    def copy_value_of_property_from_referencelist_if_empty_and_all_other_properties_match_except_exclusion_list(self, property: str, referencelist: list[Person], exclusion_list: list[str]):
        for reference in referencelist:
            self.copy_value_of_property_from_reference_if_empty_and_all_other_properties_match_except_exclusion_list(property, reference, exclusion_list)
    
    def remove_property_for_people_matching_removelist(self, property: str, removelist: list[Person]):
        for person_to_remove in removelist:
            self.remove_property_for_people_matching_reference(property, person_to_remove)
    
    def remove_property_for_people_matching_reference(self, property: str, reference: Person):
        for person in self.people:
            if self._person_matches_all_properties_present_in_reference(person, reference):
                setattr(person, property, None)
            
    
    def _person_matches_all_properties_present_in_reference(self, person: Person, reference: Person):
        return Database._person_matches_all_properties_present_in_reference_except_property_list(person, reference, [])
    
    @staticmethod
    def _person_matches_all_properties_present_in_reference_except_property_list(person: Person, reference: Person, property_list: list[str]):
        for key, value in vars(reference).items():
            if "email" in property_list:
                property_list.append("emails")
            if key in property_list:
                continue
            if value is None:
                continue
            if getattr(person, key) != getattr(reference, key):
                return False
        return True
    
    def remove_value_for_property_from_people(self, value:str, property: str):
        for person in self.people:
            if isinstance(getattr(person, property), list):
                setattr(person, property, [x for x in getattr(person,property) if x != value])
                continue
            if isinstance(getattr(person,property), set):   
                setattr(person, property, {x for x in getattr(person,property) if x != value})
                continue
            if getattr(person,property) == value:
                setattr(person, property, None)

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
    def __init__(self, input_file: str = None, input_db: Database = None):
        self.mail_based_families = []
        self.input_db = input_db
        if input_file is not None:
            self.input_db = Database(input_file)
        if self.input_db is not None:
            self.add_from_database(self.input_db)
        
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
