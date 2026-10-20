import os
import re
import unicodedata
from pathlib import Path
import pandas as pd

from functools import wraps
from threading import get_ident

from src.config.paths import WORKING_DIR_PATH, OUTPUT_FOLDER

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


def concatenate_unique_values_to_string(values: list) -> str:
    unique = list({str(value) for value in values})
    unique.sort()
    return " & ".join(unique)


def calculate_age_at_ts(birthday: pd.Timestamp, ts: pd.Timestamp) -> int:
    age = ts.year - birthday.year
    age -= (ts.month, ts.day) < (birthday.month, birthday.day)
    return age


def on_browser_thread(method):
    # Jupyter runs an asyncio loop, so synchronous Playwright calls use a dedicated thread.
    # The decorator keeps browser operations on that thread and handles nested calls directly.
    # Without a running event loop, the client executes normally on the calling thread.
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        worker = self._browser_worker
        if worker is None or get_ident() == self._browser_thread_id:
            return method(self, *args, **kwargs)
        return worker.submit(method, self, *args, **kwargs).result()

    return wrapper
