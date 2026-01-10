from unittest import TestCase
from src.utils.databases import MailBasedDatabase, MailBasedFamily, Person


class TestMailBasedDatabase(TestCase):
    def test_load_mail_based_database_csv(self):
        file = "tests/data/test_database.csv"

        mb_db = MailBasedDatabase(file)
        self.assertTrue(len(mb_db.mail_based_families) == 3)

        mb_db.add_mail_based_family(MailBasedFamily([Person(emails=["email3"])]))
        self.assertTrue(len(mb_db.mail_based_families) == 3)
        self.assertTrue(len(mb_db.mail_based_families[1].people) == 3)
        self.assertTrue(len(mb_db.lookup_by_property("email", None)) == 1)

    def test_load_mail_based_database_excel(self):
        file = "tests/data/test_database.xlsx"

        mb_db = MailBasedDatabase(file)
        self.assertTrue(len(mb_db.mail_based_families) == 3)

        mb_db.add_mail_based_family(MailBasedFamily([Person(emails=["email3"])]))
        self.assertTrue(len(mb_db.mail_based_families) == 3)
        self.assertTrue(len(mb_db.mail_based_families[1].people) == 3)
        self.assertTrue(len(mb_db.lookup_by_property("email", None)) == 1)
