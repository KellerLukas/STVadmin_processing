import pandas as pd
from unittest import TestCase
from src.utils.databases import Person


class TestPerson(TestCase):
    def test_age(self):
        me = Person(birthday="22.08.1996")
        me.age

        age1 = me.calculate_age_at_ts(pd.Timestamp("2023-08-21"))
        age2 = me.calculate_age_at_ts(pd.Timestamp("2023-08-22"))

        self.assertEqual(age1, 26)
        self.assertEqual(age2, 27)
