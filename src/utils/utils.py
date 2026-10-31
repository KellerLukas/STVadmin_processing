import os
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from src.config.paths import OUTPUT_FOLDER, WORKING_DIR_PATH

OUTPUT_FOLDER_PATH = Path(os.path.join(WORKING_DIR_PATH, OUTPUT_FOLDER))
OUTPUT_FOLDER_PATH.mkdir(parents=True, exist_ok=True)

MAX_FILENAME_BYTES = 240  # Includes the extension


def sanitize_filename(filename: str) -> str:
    """Sanitize a single filename while preserving Unicode characters."""
    name = unicodedata.normalize("NFC", filename)

    # Includes #, % and ; for stricter SharePoint/Office compatibility.
    name = "".join(
        "_"
        if char in '<>:"/\\|?*#%;' or unicodedata.category(char) in {"Cc", "Cs"}
        else char
        for char in name
    )

    # SharePoint forbids this sequence anywhere in a filename.
    name = re.sub(r"_vti_", "-", name, flags=re.IGNORECASE)

    # Remove surrounding whitespace and trailing periods.
    name = name.strip().rstrip(" .") or "unnamed"

    # Windows device names remain reserved even with an extension.
    stem = name.split(".", 1)[0].rstrip(" ").upper()
    if (
        stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        or re.fullmatch(r"(?:COM|LPT)[0-9¹²³]", stem)
        or name.casefold() in {".lock", "desktop.ini", ".ds_store", "forms"}
        or name.startswith("~$")
    ):
        name = "_" + name

    if len(name.encode("utf-8")) > MAX_FILENAME_BYTES:
        raise ValueError(
            f"Filename exceeds {MAX_FILENAME_BYTES} UTF-8 bytes; shorten it."
        )

    return name


def concatenate_unique_values_to_string(values: Iterable[object]) -> str:
    unique = list({str(value) for value in values})
    unique.sort()
    return " & ".join(unique)


def calculate_age_at_ts(birthday: pd.Timestamp, ts: pd.Timestamp) -> int:
    age = ts.year - birthday.year
    age -= (ts.month, ts.day) < (birthday.month, birthday.day)
    return age


def index_members(members: pd.DataFrame, id_column: str) -> pd.DataFrame:
    """Index a member snapshot once; reject missing or ambiguous member IDs."""
    member_ids = members[id_column]
    if isinstance(member_ids, pd.DataFrame):
        raise TypeError(
            f"Expected one ID column named {id_column}, got multiple columns."
        )
    if (
        member_ids.isna().any()
        or member_ids.map(
            lambda value: isinstance(value, str) and not value.strip()
        ).any()
    ):
        raise ValueError(f"Missing or blank member IDs in {id_column}.")
    if not member_ids.map(lambda value: isinstance(value, str)).all():
        raise TypeError(f"Member IDs in {id_column} must be strings.")
    if members.index.name != id_column or not members.index.equals(
        pd.Index(member_ids)
    ):
        members = members.set_index(id_column, drop=False)
    if not members.index.is_unique:
        raise ValueError(f"Duplicate member IDs in {id_column}.")
    return members
