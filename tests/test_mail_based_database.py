import pytest
from unittest import TestCase
from src.utils.databases import MailBasedDatabase, MailBasedFamily, Person


class TestMailBasedDatabase(TestCase):
    def test_load_mail_based_database(self):
        file = "tests/data/test_database.xlsx"

        mb_db = MailBasedDatabase(file)
        self.assertTrue(len(mb_db.mail_based_families) == 2)
        
        mb_db.add_mail_based_family(MailBasedFamily([Person(emails=["email3"])]))
        self.assertTrue(len(mb_db.mail_based_families) == 2)
        self.assertTrue(len(mb_db.mail_based_families[1].people)==3)
