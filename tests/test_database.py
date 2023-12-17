import pytest
import pandas as pd
import numpy as np
from unittest import TestCase
from src.utils.databases import Database, Person


class TestDatabase(TestCase):
    def test_load_database_excel(self):
        file = "tests/data/test_database.xlsx"
        db = Database(file)
        self.assertTrue(len(db.people) == 4)

    def test_load_database_csv(self):
        file = "tests/data/test_database.csv"
        db = Database(file)
        self.assertTrue(len(db.people) == 4)

    def test_lookup_by_property(self):
        file = "tests/data/test_database.xlsx"
        db = Database(file)
        people_found = db.lookup_by_property("first_name", "vorname1")
        self.assertEqual(len(people_found), 1)
        
        people_found = db.lookup_by_property("birthday", pd.Timestamp('1999-01-01'), comparator=np.greater)
        self.assertEqual(len(people_found), 1)
        
        people_found = db.lookup_by_property("birthday", pd.Timestamp('1999-01-01'), comparator=np.greater_equal)
        self.assertEqual(len(people_found), 2)
        
    def test_remove_property_for_person(self):
        file = "tests/data/test_database.xlsx"
        db = Database(file)
        person_to_remove = Person(first_name="vorname2", last_name="nachname2")
        
        self.assertEqual(len(db.lookup_by_property('email', None)), 1)
        db.remove_property_for_people_matching_removelist(property="email", removelist=[person_to_remove])
        self.assertEqual(len(db.lookup_by_property('email', None)), 2)      
