import pandas as pd
from functools import cached_property
import itertools
from src.cleverreach.cleverreach_processor import CleverreachProcessor
from src.mySTV.mystv_client import (
    COACH_FUNCTION_CODES,
    FEMALE_SALUTATION,
    InternalCategory,
    MALE_SALUTATION,
    MembersColumns,
    MySTVClient,
    YOUTH_INSTITUTE_CODES,
)
from src.utils.utils import sanitize_filename, OUTPUT_FOLDER_PATH
from src.config.constants import HARDCODED_HOUSEMATES, MYSTV_CLUB_ID
from src.config.paths import (FILENAME_INFOHEFT, FILENAME_JUBILARE, FILENAME_JUGENDUEBERTRITT,
    FILENAME_NEUMITGLIEDER, FILENAME_NO_MAIL, FILENAME_RIEGENMATRIX, FOLDERNAME_RIEGENLISTEN,
    OUTPUT_FOLDER)
import typing

FUNCTION_COLUMN_NAME = "Function"
INSTITUTE_COLUMN_NAME = "Institute"


class Orchestrator:
    def __init__(self):
        self.cr_processor = CleverreachProcessor()

    @cached_property
    def mystv_client(self) -> MySTVClient:
        client = MySTVClient(MYSTV_CLUB_ID)
        client.login()
        return client

    def export_each_institute_to_excel(self):
        required_columns = [
            FUNCTION_COLUMN_NAME,
            MembersColumns.MEMBER_ID,
            MembersColumns.FIRST_NAME,
            MembersColumns.SURNAME,
            MembersColumns.SALUTATION,
            MembersColumns._INTERNAL_CATEGORY,
        ]

        today = pd.Timestamp.now()

        for institute_id, functions in self.mystv_client.institutes.items():
            institute_name = self.mystv_client.institute_id_to_name(institute_id)
            filename = f"{institute_name}_export_{today.strftime('%d.%m.%Y')}.xlsx"
            institute_members = [pd.DataFrame()]
            for function_id, member_ids in functions.items():
                function_name = self.mystv_client.function_id_to_name(function_id)
                function_members = self.mystv_client.members.loc[
                    self.mystv_client.members[MembersColumns.MEMBER_ID].isin(member_ids)
                ].copy()
                function_members[FUNCTION_COLUMN_NAME] = function_name
                institute_members.append(function_members)
            institute_members_df = pd.concat(institute_members, ignore_index=True)
            self._export_members_to_excel(
                members_df=institute_members_df,
                filename=filename,
                required_columns=required_columns,
                subfolder=FOLDERNAME_RIEGENLISTEN
            )

    def export_coach_lists_to_excel(self):
        COACH_FUNCTION_IDS = ["3", "4"]
        today = pd.Timestamp.now()
        filename = f"coaches_export_{today.strftime('%d.%m.%Y')}.xlsx"
        self._export_function_list_to_excel(COACH_FUNCTION_IDS, filename)

    def sync_to_cleverreach(self):
        self.cr_processor.sync_members_to_cleverreach(self.mystv_client.members)

    def export_cleverreach_csv(self):
        self.cr_processor.export_cleverreach_data_to_csv(self.mystv_client.members)

    def export_no_mail_excel(self):
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
        no_mail = self.mystv_client.members.loc[
            pd.isna(self.mystv_client.members[MembersColumns._PRIMARY_EMAIL])
        ]
        no_newsletter = self.mystv_client.members.loc[
            ~self.mystv_client.members[MembersColumns._GETS_NEWSLETTER]
        ]

        result_df = pd.concat([no_mail, no_newsletter])
        self._export_members_to_excel(
            members_df=result_df,
            filename=FILENAME_NO_MAIL,
            required_columns=required_columns,
        )

    def export_gv_lists(self, gv_year: int):
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
            MembersColumns.MEMBERSHIP_ENTRY_DATES
        ]

        def joined_in_year(row, year: int):
            if row[MembersColumns.MEMBER_ID] == "599086": # person has no entry date ToDo: remove once fixed
                return False
            return pd.Timestamp(row[MembersColumns.MEMBERSHIP_ENTRY_DATES]).year == year

        adults = self.mystv_client.members.loc[
            self.mystv_client.members[MembersColumns._INTERNAL_CATEGORY]
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
            milestoners = self.mystv_client.members.loc[
                self.mystv_client.members.apply(
                    joined_in_year, axis=1, year=year
                )
            ]
            self._export_members_to_excel(
                members_df=milestoners,
                filename=FILENAME_JUBILARE.format(year=milestone),
                required_columns=required_columns,
            )

        def born_in_or_before_year(row, year: int):
            return pd.Timestamp(row[MembersColumns.BIRTHDAY]).year <= year

        conversion_year = gv_year - 17
        youth = self.mystv_client.members.loc[
            self.mystv_client.members[MembersColumns._INTERNAL_CATEGORY]
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

    def export_infoheft_address_list(self):
        PEOPLE_COLUMN = "Personen"
        NAME_COLUMN = "Name"
        required_columns = [
            NAME_COLUMN,
            MembersColumns.ADDRESS,
            MembersColumns.POST_CODE,
            MembersColumns.CITY,
            PEOPLE_COLUMN,
        ]
        # ToDo: filter out Non-infoheft people

        def clean_street_name(street: str) -> str:
            return street.lower().replace("str.", "strasse")

        def build_address_check_col(row):
            # some people share no last name -> we cannot know if they live in the same apartment or are just neighbors.
            # -> we hardcode known housemates as HARDCODED_HOUSEMATES: list[tuple[str]] where each str is a member id
            for group in HARDCODED_HOUSEMATES:
                if row[MembersColumns.MEMBER_ID] not in group:
                    continue
                return str(group)

            return (
                clean_street_name(row[MembersColumns.ADDRESS]).lower(),
                row[MembersColumns.POST_CODE].lower(),
                row[MembersColumns.CITY].lower(),
                row[MembersColumns.SURNAME].lower(),
            )

        CHECK_COLUMN = "address_check"
        members = self.mystv_client.members
        members[CHECK_COLUMN] = members.apply(build_address_check_col, axis=1)

        result = []
        address_groups = members.groupby(CHECK_COLUMN)
        for _, group in address_groups:
            entry = {}
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

    def create_riegenmatrix(self):
        adult_institutes = {
            k: v
            for k, v in self.mystv_client.institutes.items()
            if k not in YOUTH_INSTITUTE_CODES
        }
        riegen = {}
        for institute in adult_institutes.values():
            coach_member_lists = [institute.get(code,[]) for code in COACH_FUNCTION_CODES]
            coach_members = list(itertools.chain.from_iterable(coach_member_lists))
            for function_code, members in institute.items():
                if function_code in COACH_FUNCTION_CODES:
                    continue
                name = self.mystv_client.mapper_function_code_to_name[function_code]
                riegen[name] = members + coach_members
        matrix = pd.DataFrame(columns=riegen.keys(), index=riegen.keys())
        for x_riege in riegen:
            for y_riege in riegen:
                common_members = [
                    member for member in riegen[x_riege] if member in riegen[y_riege]
                ]

                matrix.loc[x_riege, y_riege] = len(common_members)
        matrix.to_excel(OUTPUT_FOLDER_PATH / FILENAME_RIEGENMATRIX, index=False)

    def get_statistics(self) -> str:
        members = self.mystv_client.members
        num_of_members = len(members)

        max_age = max(members[MembersColumns._AGE])
        min_age = min(members[MembersColumns._AGE])

        adults = members.loc[
            members[MembersColumns._INTERNAL_CATEGORY]!= InternalCategory.JUGENDMITGLIED
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
        num_of_girls = len(kids.loc[kids[MembersColumns.SALUTATION] == FEMALE_SALUTATION])

        res = f"""


            **Total Number of Members:** {str(num_of_members)}  

            **Number of Adults:** {str(num_of_adults)}  
                Men: {str(num_of_men)}  
                Women: {str(num_of_women)}  
                
            **Number of Children:** {str(num_of_kids)}  
                Boys: {str(num_of_boys)}  
                Girls: {str(num_of_girls)}  


            **Oldest Member:** {str(max_age)} years old  
            **Youngest Member:** {str(min_age)} years old
            
            **Categories:**

            """

        for cat in InternalCategory:
            res += f"            {cat}: {len(members.loc[members[MembersColumns._INTERNAL_CATEGORY] == cat])}\n"
        return res

    def _export_function_list_to_excel(
        self, function_ids: list[int], output_filename: str
    ):
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
        for institute_id, functions in self.mystv_client.institutes.items():
            for function_id, member_ids in functions.items():
                if function_id in function_ids:
                    for member_id in member_ids:
                        if member_id not in candidate_ids:
                            candidate_ids[member_id] = []
                        candidate_ids[member_id].append((institute_id, function_id))

        members = {}
        for member_id, function_tuples in candidate_ids.items():
            institute_ids = {id for id, _ in function_tuples}
            function_ids = {id for _, id in function_tuples}
            function_names = [
                self.mystv_client.function_id_to_name(func_id)
                for func_id in function_ids
            ]
            institute_names = [
                self.mystv_client.institute_id_to_name(inst_id)
                for inst_id in institute_ids
            ]
            member_data = self.mystv_client.members.loc[
                self.mystv_client.members[MembersColumns.MEMBER_ID] == member_id
            ]
            if not len(member_data) == 1:
                raise ValueError(
                    f"Member ID {member_id} not found or not unique in members DataFrame."
                )
            member_data = member_data.iloc[0].to_dict()
            member_data[FUNCTION_COLUMN_NAME] = ", ".join(function_names)
            member_data[INSTITUTE_COLUMN_NAME] = ", ".join(institute_names)
            members[member_id] = member_data
        result_df = pd.DataFrame.from_dict(members, orient="index")
        self._export_members_to_excel(
            members_df=result_df,
            filename=output_filename,
            required_columns=required_columns,
        )

    def _export_members_to_excel(
        self, members_df: pd.DataFrame, filename: str, required_columns: list[str], subfolder: str | None = None
    ):
        members_df = members_df[required_columns]
        filename = sanitize_filename(filename)
        path = OUTPUT_FOLDER_PATH
        if subfolder:
            subfolder = sanitize_filename(subfolder)
            path = path / subfolder
            path.mkdir(parents=True, exist_ok=True)
        members_df.to_excel(path / filename, index=False)
