import itertools
from collections.abc import Sequence
from functools import cached_property
from typing import Any

import pandas as pd

from src.cleverreach.cleverreach_processor import CleverreachProcessor
from src.comparison.compare_dbs import (
    compare_current_to_snapshot,
    compare_mystv_to_fairgate,
)
from src.comparison.comparison_models import (
    ComparisonResult,
    DBSnapshot,
    DBSnapshotType,
)
from src.config.constants import FAIRGATE_CLUB_SLUG, HARDCODED_HOUSEMATES, MYSTV_CLUB_ID
from src.config.paths import (
    FILENAME_INFOHEFT,
    FILENAME_JUBILARE,
    FILENAME_JUGENDUEBERTRITT,
    FILENAME_NEUMITGLIEDER,
    FILENAME_NO_MAIL,
    FILENAME_RIEGENMATRIX,
    FOLDERNAME_RIEGENLISTEN,
)
from src.fairgate.fairgate_processor import FairgateProcessor
from src.mySTV.mystv_config import (
    ADMIN_INSTITUTE_CODES,
    COACH_FUNCTION_CODES,
    FEMALE_SALUTATION,
    INFOHEFT_DIGITAL_INSTITUTE_CODE,
    MALE_SALUTATION,
    MAPPER_FUNCTION_CODE_TO_NAME,
    YOUTH_INSTITUTE_CODES,
    InternalCategory,
    MembersColumns,
    MySTVConfigurationError,
)
from src.mySTV.mystv_processor import MySTVProcessor
from src.mySTV.mystv_snapshot import MySTVSnapshot, MySTVSnapshotMeta
from src.utils.utils import OUTPUT_FOLDER_PATH, sanitize_filename

FUNCTION_COLUMN_NAME = "Function"
INSTITUTE_COLUMN_NAME = "Institute"


class Orchestrator:
    def __init__(self) -> None:
        self.cr_processor = CleverreachProcessor()

    @cached_property
    def mystv(self) -> MySTVProcessor:
        mystv = MySTVProcessor(MYSTV_CLUB_ID)
        return mystv

    @cached_property
    def fairgate(self) -> FairgateProcessor:
        fg = FairgateProcessor(club_slug=FAIRGATE_CLUB_SLUG)
        return fg

    def is_members_refresh_running(self) -> bool:
        """Read server status without changing the local data cache."""
        return self.mystv.mystv_client.is_members_refresh_running()

    def start_members_refresh(self) -> bool:
        """Confirm a running server refresh without changing the local data cache."""
        self.mystv.mystv_client.start_members_refresh()
        return True

    def clear_cache(self) -> None:
        """Clear local data without starting a server refresh or another login."""
        self.mystv.clear_cached_data()
        self.fairgate.clear_cached_data()

    def export_each_institute_to_excel(self) -> None:
        required_columns = [
            FUNCTION_COLUMN_NAME,
            MembersColumns.MEMBER_ID,
            MembersColumns.FIRST_NAME,
            MembersColumns.SURNAME,
            MembersColumns.SALUTATION,
            MembersColumns._INTERNAL_CATEGORY,
        ]

        today = pd.Timestamp.now()
        members = self.mystv.members

        for institute_id, functions in self.mystv.institutes.items():
            institute_name = self.mystv.institute_id_to_name(institute_id)
            filename = f"{institute_name}_export_{today.strftime('%d.%m.%Y')}.xlsx"
            institute_members = [pd.DataFrame()]
            for function_id, member_ids in functions.items():
                function_name = self.mystv.function_id_to_name(function_id)
                function_members = members.loc[members.index.isin(member_ids)].copy()
                function_members[FUNCTION_COLUMN_NAME] = function_name
                institute_members.append(function_members)
            institute_members_df = pd.concat(institute_members, ignore_index=True)
            self._export_members_to_excel(
                members_df=institute_members_df,
                filename=filename,
                required_columns=required_columns,
                subfolder=FOLDERNAME_RIEGENLISTEN,
            )

    def export_coach_list_to_excel(self) -> None:
        COACH_FUNCTION_IDS = ["3", "4"]
        today = pd.Timestamp.now()
        filename = f"coaches_export_{today.strftime('%d.%m.%Y')}.xlsx"
        self._export_function_list_to_excel(COACH_FUNCTION_IDS, filename)

    def sync_to_cleverreach(self) -> tuple[list[str], list[str]]:
        return self.cr_processor.sync_members_to_cleverreach(self.mystv.members)

    def export_cleverreach_csv(self) -> None:
        self.cr_processor.export_cleverreach_data_to_csv(self.mystv.members)

    def export_no_mail_excel(self) -> None:
        required_columns = [
            MembersColumns.MEMBER_ID,
            MembersColumns.FIRST_NAME,
            MembersColumns.SURNAME,
            MembersColumns.SALUTATION,
            MembersColumns._INTERNAL_CATEGORY,
            MembersColumns._PRIMARY_EMAIL,
            MembersColumns.ADDRESS,
            MembersColumns.POST_CODE,
            MembersColumns.CITY,
        ]
        members = self.mystv.members
        no_mail = members.loc[pd.isna(members[MembersColumns._PRIMARY_EMAIL])]
        no_newsletter = members.loc[~members[MembersColumns._GETS_NEWSLETTER]]

        result_df = pd.concat([no_mail, no_newsletter])
        self._export_members_to_excel(
            members_df=result_df,
            filename=FILENAME_NO_MAIL,
            required_columns=required_columns,
        )

    def export_gv_lists(self, gv_year: int) -> None:
        required_columns = [
            MembersColumns.MEMBER_ID,
            MembersColumns.FIRST_NAME,
            MembersColumns.SURNAME,
            MembersColumns.SALUTATION,
            MembersColumns._INTERNAL_CATEGORY,
            MembersColumns._PRIMARY_EMAIL,
            MembersColumns.ADDRESS,
            MembersColumns.POST_CODE,
            MembersColumns.CITY,
            MembersColumns.BIRTHDAY,
            MembersColumns.MEMBERSHIP_ENTRY_DATES,
        ]

        def joined_in_year(row: pd.Series[Any], year: int) -> bool:
            if (
                row[MembersColumns.MEMBER_ID] == "599086"
            ):  # person has no entry date ToDo: remove once fixed
                return False
            return pd.Timestamp(row[MembersColumns.MEMBERSHIP_ENTRY_DATES]).year == year

        members = self.mystv.members
        adults = members.loc[
            members[MembersColumns._INTERNAL_CATEGORY]
            != InternalCategory.JUGENDMITGLIED
        ]
        adults_joined_this_year = adults.loc[
            adults.apply(joined_in_year, axis=1, year=gv_year - 1)
        ]
        self._export_members_to_excel(
            members_df=adults_joined_this_year,
            filename=FILENAME_NEUMITGLIEDER,
            required_columns=required_columns,
        )

        milestones = [25, 30, 40, 50, 60, 70, 80, 90, 100]
        for milestone in milestones:
            year = gv_year - milestone
            milestoners = members.loc[members.apply(joined_in_year, axis=1, year=year)]
            self._export_members_to_excel(
                members_df=milestoners,
                filename=FILENAME_JUBILARE.format(year=milestone),
                required_columns=required_columns,
            )

        def born_in_or_before_year(row: pd.Series[Any], year: int) -> bool:
            return pd.Timestamp(row[MembersColumns.BIRTHDAY]).year <= year

        conversion_year = gv_year - 17
        youth = members.loc[
            members[MembersColumns._INTERNAL_CATEGORY]
            == InternalCategory.JUGENDMITGLIED
        ]
        youth_born_in_or_after_conversion_year = youth.loc[
            youth.apply(born_in_or_before_year, axis=1, year=conversion_year)
        ]
        self._export_members_to_excel(
            members_df=youth_born_in_or_after_conversion_year,
            filename=FILENAME_JUGENDUEBERTRITT,
            required_columns=required_columns,
        )

    def export_infoheft_address_list(self) -> None:
        PEOPLE_COLUMN = "Personen"
        NAME_COLUMN = "Name"
        required_columns = [
            NAME_COLUMN,
            MembersColumns.ADDRESS,
            MembersColumns.POST_CODE,
            MembersColumns.CITY,
            PEOPLE_COLUMN,
        ]
        function_codes = list(
            self.mystv.institutes[INFOHEFT_DIGITAL_INSTITUTE_CODE].keys()
        )
        if len(function_codes) != 1:
            raise MySTVConfigurationError(
                f"Expected only one function code in Infoheft Digital institute but got: {function_codes}"
            )
        function_code = function_codes[0]
        members_without_printed_infoheft = self.mystv.institutes[
            INFOHEFT_DIGITAL_INSTITUTE_CODE
        ][function_code]

        members = self.mystv.members
        members = members.loc[
            ~members[MembersColumns.MEMBER_ID].isin(members_without_printed_infoheft)
        ]

        def clean_street_name(street: str) -> str:
            return street.lower().replace("str.", "strasse")

        def build_address_check_col(
            row: pd.Series[Any],
        ) -> str:
            # some people share no last name -> we cannot know if they live in the same apartment or are just neighbors.
            # -> we hardcode known housemates as HARDCODED_HOUSEMATES: list[tuple[str]] where each str is a member id
            for group in HARDCODED_HOUSEMATES:
                if row[MembersColumns.MEMBER_ID] not in group:
                    continue
                return str(group)

            address_key = (
                clean_street_name(row[MembersColumns.ADDRESS]).lower(),
                row[MembersColumns.POST_CODE].lower(),
                row[MembersColumns.CITY].lower(),
                row[MembersColumns.SURNAME].lower(),
            )
            return str(address_key)

        CHECK_COLUMN = "address_check"
        members[CHECK_COLUMN] = members.apply(
            build_address_check_col, axis=1, result_type="reduce"
        )

        result: list[dict[str, object]] = []
        address_groups = members.groupby(CHECK_COLUMN)
        for _, group in address_groups:
            entry: dict[str, object] = {}
            if len(group) > 1:
                last_names = list(group[MembersColumns.SURNAME].unique())
                entry[NAME_COLUMN] = "Fam. " + " & ".join(sorted(last_names))
            else:
                entry[NAME_COLUMN] = (
                    f"{group[MembersColumns.FIRST_NAME].iloc[0]} {group[MembersColumns.SURNAME].iloc[0]}"
                )

            entry[MembersColumns.ADDRESS] = group[MembersColumns.ADDRESS].iloc[0]
            entry[MembersColumns.POST_CODE] = group[MembersColumns.POST_CODE].iloc[0]
            entry[MembersColumns.CITY] = group[MembersColumns.CITY].iloc[0]

            entry[PEOPLE_COLUMN] = ", ".join(
                [
                    f"{row[MembersColumns.FIRST_NAME]} {row[MembersColumns.SURNAME]}"
                    for _, row in group.iterrows()
                ]
            )
            result.append(entry)
        address_list = pd.DataFrame(result)
        self._export_members_to_excel(
            members_df=address_list,
            filename=FILENAME_INFOHEFT,
            required_columns=required_columns,
        )

    def create_riegenmatrix(self) -> None:
        adult_institutes = {
            k: v
            for k, v in self.mystv.institutes.items()
            if k not in YOUTH_INSTITUTE_CODES + ADMIN_INSTITUTE_CODES
        }
        riegen = {}
        for institute in adult_institutes.values():
            coach_member_lists = [
                institute.get(code, []) for code in COACH_FUNCTION_CODES
            ]
            coach_members = list(itertools.chain.from_iterable(coach_member_lists))
            for function_code, members in institute.items():
                if function_code in COACH_FUNCTION_CODES:
                    continue
                name = MAPPER_FUNCTION_CODE_TO_NAME[function_code]
                riegen[name] = members + coach_members
        categories = list(riegen)
        matrix = pd.DataFrame(columns=categories, index=categories)
        for x_riege, x_members in riegen.items():
            for y_riege, y_members in riegen.items():
                common_members = [member for member in x_members if member in y_members]

                matrix.loc[x_riege, y_riege] = len(common_members)
        matrix.to_excel(OUTPUT_FOLDER_PATH / FILENAME_RIEGENMATRIX, index=False)

    def get_statistics(
        self,
    ) -> tuple[dict[str, int | None], pd.DataFrame, pd.DataFrame]:
        """Return headline metrics, gender counts, and membership category counts."""
        members = self.mystv.members
        num_of_members = len(members)

        ages = members[MembersColumns._AGE].dropna()
        max_age = int(ages.max()) if not ages.empty else None
        min_age = int(ages.min()) if not ages.empty else None

        adults = members.loc[
            members[MembersColumns._INTERNAL_CATEGORY]
            != InternalCategory.JUGENDMITGLIED
        ]
        num_of_adults = len(adults)

        men = adults.loc[adults[MembersColumns.SALUTATION] == MALE_SALUTATION]
        women = adults.loc[adults[MembersColumns.SALUTATION] == FEMALE_SALUTATION]

        num_of_men = len(men)
        num_of_women = len(women)

        kids = members.loc[
            members[MembersColumns._INTERNAL_CATEGORY]
            == InternalCategory.JUGENDMITGLIED
        ]
        num_of_kids = len(kids)
        num_of_boys = len(kids.loc[kids[MembersColumns.SALUTATION] == MALE_SALUTATION])
        num_of_girls = len(
            kids.loc[kids[MembersColumns.SALUTATION] == FEMALE_SALUTATION]
        )

        metrics = {
            "Mitglieder gesamt": num_of_members,
            "Erwachsene": num_of_adults,
            "Kinder & Jugend": num_of_kids,
            "Jüngstes Mitglied (Jahre)": min_age,
            "Ältestes Mitglied (Jahre)": max_age,
        }
        demographics = pd.DataFrame(
            [
                {
                    "Gruppe": "Erwachsene",
                    "Männlich": num_of_men,
                    "Weiblich": num_of_women,
                },
                {
                    "Gruppe": "Kinder & Jugend",
                    "Männlich": num_of_boys,
                    "Weiblich": num_of_girls,
                },
            ]
        )
        categories = pd.DataFrame(
            [
                {
                    "Kategorie": cat.value,
                    "Mitglieder": int(
                        members[MembersColumns._INTERNAL_CATEGORY].eq(cat).sum()
                    ),
                }
                for cat in InternalCategory
            ]
        )
        return metrics, demographics, categories

    def _export_function_list_to_excel(
        self, function_ids: list[str], output_filename: str
    ) -> None:
        required_columns = [
            FUNCTION_COLUMN_NAME,
            INSTITUTE_COLUMN_NAME,
            MembersColumns.MEMBER_ID,
            MembersColumns.FIRST_NAME,
            MembersColumns.SURNAME,
            MembersColumns.SALUTATION,
            MembersColumns._INTERNAL_CATEGORY,
            MembersColumns._PRIMARY_EMAIL,
        ]

        candidate_ids: dict[str, list[tuple[str, str]]] = {}
        for institute_id, functions in self.mystv.institutes.items():
            for function_id, member_ids in functions.items():
                if function_id in function_ids:
                    for member_id in member_ids:
                        if member_id not in candidate_ids:
                            candidate_ids[member_id] = []
                        candidate_ids[member_id].append((institute_id, function_id))

        members: dict[str, dict[str, Any]] = {}
        for member_id, function_tuples in candidate_ids.items():
            institute_ids = {id for id, _ in function_tuples}
            member_function_ids = {id for _, id in function_tuples}
            function_names = [
                self.mystv.function_id_to_name(func_id)
                for func_id in member_function_ids
            ]
            institute_names = [
                self.mystv.institute_id_to_name(inst_id) for inst_id in institute_ids
            ]
            raw_record = self.mystv.get_member(member_id).to_dict()
            member_record: dict[str, Any] = {}
            for key, value in raw_record.items():
                if not isinstance(key, str):
                    raise TypeError("Member row contains a non-string column name.")
                member_record[key] = value
            member_record[FUNCTION_COLUMN_NAME] = ", ".join(function_names)
            member_record[INSTITUTE_COLUMN_NAME] = ", ".join(institute_names)
            members[member_id] = member_record
        result_df = pd.DataFrame.from_dict(members, orient="index")
        self._export_members_to_excel(
            members_df=result_df,
            filename=output_filename,
            required_columns=required_columns,
        )

    def _export_members_to_excel(
        self,
        members_df: pd.DataFrame,
        filename: str,
        required_columns: Sequence[str],
        subfolder: str | None = None,
    ) -> None:
        members_df = members_df[required_columns]
        filename = sanitize_filename(filename)
        path = OUTPUT_FOLDER_PATH
        if subfolder:
            subfolder = sanitize_filename(subfolder)
            path = path / subfolder
            path.mkdir(parents=True, exist_ok=True)
        members_df.to_excel(path / filename, index=False)

    def compare_to_fairgate_export(self) -> ComparisonResult:
        """Compare freshly downloaded MySTV and Fairgate data."""
        mystv_snapshot = MySTVSnapshot.from_processor(self.mystv)
        self.fairgate.clear_cached_data()
        fg_snapshot = DBSnapshot(
            type=DBSnapshotType.FAIRGATE, members=self.fairgate.members
        )
        return compare_mystv_to_fairgate(mystv=mystv_snapshot, fairgate=fg_snapshot)

    def take_and_dump_snapshot(self) -> MySTVSnapshotMeta:
        snapshot = MySTVSnapshot.from_processor(self.mystv)
        snapshot.dump()
        return snapshot.meta

    def list_snapshots(self) -> list[MySTVSnapshotMeta]:
        return MySTVSnapshot.list_snapshots()

    def compare_to_snapshot(self, uuid: str) -> ComparisonResult:
        """Compare fresh current data (left) with a stored snapshot (right)."""
        snapshot = MySTVSnapshot.load(uuid)
        current = MySTVSnapshot.from_processor(self.mystv)
        return compare_current_to_snapshot(current=current, snapshot=snapshot)
