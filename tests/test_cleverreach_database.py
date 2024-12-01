import pandas as pd
import numpy as np
from unittest import TestCase
from src.utils.cleverreach_database import CleverreachDatabase


class TestCleverreachDatabase(TestCase):
    def test_load_cleverreach_database(self):
        file = "tests/data/test_database.xlsx"
        cr_db = CleverreachDatabase(file)
        expected_df = pd.read_csv("tests/data/test_cleverreach_database_expected_output.csv")

        for col in expected_df.columns:
            if col == "updated":
                expected_df[col] = [pd.Timestamp.now().floor(freq='D') for _ in expected_df[col].values]
            if col == "Email":
                expected_df[col] = [val if not isinstance(val, type(np.nan)) else None for val in expected_df[col].values]
            np.testing.assert_array_equal(expected_df[col].values, cr_db.df[col].values)


