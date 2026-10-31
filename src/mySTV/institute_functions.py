from src.mySTV.mystv_config import INSTITUTES_TYPE


def build_member_institute_functions(
    institutes: INSTITUTES_TYPE,
) -> dict[str, set[tuple[str, str]]]:
    """Index institute/function pairs once for all members in a data snapshot."""
    member_institute_functions: dict[str, set[tuple[str, str]]] = {}
    for institute_code, functions in institutes.items():
        for function_code, member_ids in functions.items():
            for member_id in member_ids:
                member_institute_functions.setdefault(member_id, set()).add(
                    (institute_code, function_code)
                )
    return member_institute_functions
