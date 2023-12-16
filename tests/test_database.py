import pytest
from unittest import TestCase
from src.utils.databases import Database


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
