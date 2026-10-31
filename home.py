import logging
import os
import signal
import subprocess
import unicodedata
from collections import Counter, deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from difflib import SequenceMatcher
from html import escape
from threading import Lock
from typing import Any

import pandas as pd
import streamlit as st

from src.comparison.comparison_config import (
    DIFF_FIELD_COLUMN,
    DIFF_FIRST_NAME_COLUMN,
    DIFF_ID_COLUMN,
    DIFF_SURNAME_COLUMN,
)
from src.comparison.comparison_models import ComparisonResult
from src.mySTV.mystv_snapshot import MySTVSnapshotMeta
from src.orchestrator import Orchestrator
from src.utils.utils import OUTPUT_FOLDER_PATH

# Set logging level to INFO
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DISPLAY_TIMEZONE = "Europe/Zurich"


def get_orchestrator() -> Orchestrator:
    """Expose the session's orchestrator with a checked type for UI callbacks."""
    orchestrator = st.session_state.get("orch")
    if orchestrator is None:
        orchestrator = Orchestrator()
        st.session_state.orch = orchestrator
    if not isinstance(orchestrator, Orchestrator):
        raise TypeError("The session orchestrator has an unexpected type.")
    return orchestrator


@st.cache_resource
def get_background_task_executor() -> ThreadPoolExecutor:
    """Reuse one worker across reruns; a MySTV client must be used sequentially."""
    return ThreadPoolExecutor(max_workers=1)


class ConsoleLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: deque[str] = deque(maxlen=500)
        self.messages_lock = Lock()
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        with self.messages_lock:
            self.messages.append(self.format(record))

    def get_messages(self) -> list[str]:
        with self.messages_lock:
            return list(self.messages)


@st.cache_resource
def get_console_log_handler() -> ConsoleLogHandler:
    root_logger = logging.getLogger()
    handler = ConsoleLogHandler()
    root_logger.addHandler(handler)
    if root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    return handler


def start_background_task(label: str, action: Callable[..., Any], *args: Any) -> None:
    if is_background_task_running():
        return
    st.session_state.background_task_label = label
    st.session_state.background_task_completion_rerun = False
    st.session_state.background_task = get_background_task_executor().submit(
        action, *args
    )


def start_members_refresh_task(*, start_refresh: bool = False) -> None:
    """Check or start a server refresh on the same worker as exports."""
    if is_background_task_running():
        return
    orchestrator = get_orchestrator()
    action = (
        orchestrator.start_members_refresh
        if start_refresh
        else orchestrator.is_members_refresh_running
    )
    st.session_state.members_refresh_running = None
    st.session_state.members_refresh_error = None
    st.session_state.members_refresh_starting = start_refresh
    st.session_state.members_refresh_task = get_background_task_executor().submit(
        action
    )


def collect_members_refresh_result() -> None:
    """Apply a finished background result on the UI thread, without another request."""
    task = st.session_state.get("members_refresh_task")
    if not isinstance(task, Future) or not task.done():
        return
    if (error := task.exception()) is not None:
        action = (
            "refresh start"
            if st.session_state.get("members_refresh_starting")
            else "status request"
        )
        logger.error("MySTV %s failed: %s", action, error)
        st.session_state.members_refresh_running = None
        st.session_state.members_refresh_error = str(error)
    else:
        st.session_state.members_refresh_running = task.result()
        st.session_state.members_refresh_checked_at = (
            datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S")
        )
    del st.session_state.members_refresh_task
    st.session_state.members_refresh_starting = False


def setup_page() -> None:
    st.set_page_config(page_title="mySTV Manager", page_icon="🏅", layout="wide")
    st.html(
        """
        <style>
        :root {
            --stv-red: #a7353a;
            --stv-grey: #878787;
            --stv-white: #ffffff;
        }

        [data-testid="stHeader"] { background: transparent; }

        [data-testid="stMainBlockContainer"], .main .block-container {
            max-width: 1280px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        h1, h2, h3, h4 { letter-spacing: -0.025em; }

        h2 {
            color: var(--stv-red);
        }

        h3, h4, [data-testid="stCaptionContainer"] { color: var(--stv-grey); }

        hr {
            border: 0;
            border-top: 1px solid rgba(135, 135, 135, 0.25);
            margin: 1.5rem 0;
        }

        .stButton > button {
            min-height: 2.75rem;
            font-weight: 600;
            transition: border-color 150ms ease, box-shadow 150ms ease;
        }

        .stButton > button:hover:not(:disabled) {
            border-color: var(--stv-red);
            box-shadow: 0 3px 10px rgba(167, 53, 58, 0.12);
        }

        .stButton > button:focus-visible {
            outline: 2px solid var(--stv-red);
            outline-offset: 3px;
        }

        [data-testid="stMetric"] {
            padding: 0.75rem 0;
            border-bottom: 2px solid rgba(167, 53, 58, 0.18);
        }

        [data-testid="stMetricValue"] { color: var(--stv-red); }
        [data-testid="stMetricLabel"] { color: var(--stv-grey); }

        .character-diff {
            font-family: monospace;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            padding: 0.8rem;
            border: 1px solid rgba(135, 135, 135, 0.25);
            border-radius: 0.5rem;
        }

        .character-diff mark {
            background: rgba(167, 53, 58, 0.12);
            color: var(--stv-red);
            text-decoration: underline;
            text-decoration-thickness: 2px;
        }

        /* The status pill keeps its semantic colors and compact size. */
        .st-key-btn_members_refresh_status button {
            min-height: 1.75rem;
            padding: 0.15rem 0.65rem;
            border: 1px solid transparent;
            border-radius: 999px;
            background: var(--status-background);
            color: var(--status-color);
            box-shadow: none;
        }

        .st-key-btn_members_refresh_status button p {
            font-size: 0.875rem;
            font-weight: 600;
        }

        .st-key-btn_members_refresh_status button:hover:not(:disabled) {
            border-color: var(--status-color);
            background: var(--status-background);
            color: var(--status-color);
            box-shadow: none;
        }

        .st-key-btn_members_refresh_status button:focus-visible {
            outline-color: var(--status-color);
        }

        .hero {
            padding: 2rem 2.25rem;
            border-radius: 16px;
            background: var(--stv-red);
            color: var(--stv-white);
        }

        .hero-eyebrow {
            margin: 0 0 0.6rem;
            color: var(--stv-white);
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        .hero-title {
            margin: 0;
            padding: 0;
            color: var(--stv-white);
            font-size: clamp(2rem, 4vw, 2.75rem);
            font-weight: 700;
            letter-spacing: -0.04em;
            line-height: 1.15;
        }

        @media (max-width: 640px) {
            [data-testid="stMainBlockContainer"], .main .block-container {
                padding: 1rem 1rem 2rem;
            }
            .hero { padding: 1.5rem; }
        }

        @media (prefers-reduced-motion: reduce) {
            .stButton > button { transition: none; }
        }
        </style>
        """
    )


def configure_title() -> None:
    st.markdown(
        """
        <header class="hero">
            <p class="hero-eyebrow">STV Administration · Export Center</p>
            <h1 class="hero-title">mySTV Manager</h1>
        </header>
        """,
        unsafe_allow_html=True,
    )


def configure_members_refresh_status() -> None:
    running = st.session_state.get("members_refresh_running")
    if running is True:
        label, background, foreground = "Updating...", "#e8f1ff", "#145cb1"
    elif running is False:
        label, background, foreground = "Bereit", "#e6f4ea", "#176b35"
    else:
        background, foreground = "#f0f1f3", "#505766"
        pending = "members_refresh_task" in st.session_state
        label = "Wird geprüft …" if pending else "Status unbekannt"
        if st.session_state.get("members_refresh_starting"):
            label = "Wird gestartet …"
    tooltip = "Klicken, um den Status zu aktualisieren."
    if checked_at := st.session_state.get("members_refresh_checked_at"):
        tooltip += f"\n\nLetzte erfolgreiche Statusabfrage: {checked_at}"
    if error := st.session_state.get("members_refresh_error"):
        tooltip += f"\n\nStatus konnte nicht bestätigt werden: {error}"
    # Style-only HTML takes no layout space; both colors come from fixed states above.
    st.html(
        f"""
        <style>
        .st-key-btn_members_refresh_status {{
            --status-background: {background};
            --status-color: {foreground};
        }}
        </style>
        """
    )
    if st.button(
        label,
        key="btn_members_refresh_status",
        icon=":material/refresh:",
        help=tooltip,
        disabled=is_background_task_running(),
    ):
        start_members_refresh_task()
        st.rerun()


def configure_statistics() -> None:
    st.header("Mitgliederstatistik", anchor=False)
    with st.container(border=True):
        st.caption("Aktuelle Kennzahlen aus mySTV auf Abruf.")
        statistics_output = st.empty()
        if st.button(
            "Statistik abrufen",
            key="btn_statistics",
            type="primary",
            icon=":material/bar_chart:",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Mitgliederstatistik",
                get_orchestrator().get_statistics,
            )
            st.session_state.statistics_task = st.session_state.background_task
        future = st.session_state.get("statistics_task")
        if isinstance(future, Future):
            if not future.done():
                statistics_output.info("Statistik wird abgerufen …")
            elif (error := future.exception()) is not None:
                statistics_output.error(
                    f"Statistik konnte nicht abgerufen werden: {error}"
                )
            else:
                metrics, demographics, categories = future.result()
                with statistics_output.container():
                    metric_columns = st.columns(len(metrics))
                    for column, (label, value) in zip(
                        metric_columns, metrics.items(), strict=True
                    ):
                        column.metric(label, value if value is not None else "—")
                    demographics_col, categories_col = st.columns([1, 1.4])
                    with demographics_col:
                        st.markdown("### Geschlechterverteilung")
                        st.dataframe(demographics, hide_index=True, width="stretch")
                    with categories_col:
                        st.markdown("### Mitgliedskategorien")
                        st.dataframe(
                            categories,
                            hide_index=True,
                            width="stretch",
                            height="content",
                            column_config={
                                "Mitglieder": st.column_config.ProgressColumn(
                                    "Mitglieder",
                                    format="%d",
                                    min_value=0,
                                    max_value=max(
                                        1, int(categories["Mitglieder"].max())
                                    ),
                                )
                            },
                        )


def configure_export_buttons() -> None:
    st.header("Exporte", anchor=False)

    st.markdown("### CleverReach")
    cleverreach_col1, cleverreach_col2 = st.columns(2)
    with cleverreach_col1, st.container(border=True, height="stretch"):
        st.markdown("#### Empfänger synchronisieren")
        st.caption("Mitglieder mit CleverReach abgleichen.")
        st.space("stretch")
        if st.button(
            "Sync to CleverReach",
            key="btn_cleverreach_sync",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "CleverReach-Synchronisierung",
                get_orchestrator().sync_to_cleverreach,
            )
    with cleverreach_col2, st.container(border=True, height="stretch"):
        st.markdown("#### CleverReach-Daten")
        st.caption("Die CleverReach-Daten als CSV exportieren.")
        st.space("stretch")
        if st.button(
            "Export CleverReach Data",
            key="btn_cleverreach_export",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "CleverReach-Datenexport",
                get_orchestrator().export_cleverreach_csv,
            )

    st.markdown("### Mitgliederlisten")
    member_cols = st.columns(3)
    with member_cols[0], st.container(border=True, height="stretch"):
        st.markdown("#### Riegenlisten")
        st.caption("Listen nach Institut exportieren.")
        st.space("stretch")
        if st.button(
            "Riegenlisten",
            key="btn_riegenlisten",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Riegenlisten-Export",
                get_orchestrator().export_each_institute_to_excel,
            )
    with member_cols[1], st.container(border=True, height="stretch"):
        st.markdown("#### Infoheft")
        st.caption("Adressliste für das Infoheft erstellen.")
        st.space("stretch")
        if st.button(
            "Infoheft Liste",
            key="btn_infoheft",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Infoheft-Export",
                get_orchestrator().export_infoheft_address_list,
            )
    with member_cols[2], st.container(border=True, height="stretch"):
        st.markdown("#### Coaches")
        st.caption("Aktuelle Coachliste exportieren.")
        st.space("stretch")
        if st.button(
            "Coachliste",
            key="btn_coachliste",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Coachlisten-Export",
                get_orchestrator().export_coach_list_to_excel,
            )

    no_mail_col, gv_col = st.columns(2)
    with no_mail_col, st.container(border=True, height="stretch"):
        st.markdown("#### Kein E-Mail-Versand")
        st.caption("Mitglieder ohne Mail oder Newsletter-Einwilligung.")
        st.space("stretch")
        if st.button(
            "No Mail",
            key="btn_no_mail",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "No-Mail-Export",
                get_orchestrator().export_no_mail_excel,
            )
    with gv_col, st.container(border=True, height="stretch"):
        st.markdown("#### GV-Listen nach Jahr")
        st.caption("Jahreslisten für eine Generalversammlung exportieren.")
        st.space("stretch")
        input_col, button_col = st.columns([2, 1])
        with input_col:
            gv_year = st.text_input(
                "GV lists for year:",
                value="",
                max_chars=4,
                placeholder=str(pd.Timestamp.now().year),
                label_visibility="collapsed",
            )
        with button_col:
            if st.button(
                "Export",
                key="export_gv_button",
                width="stretch",
                disabled=is_background_task_running(),
            ):
                if gv_year.isdigit() and len(gv_year) == 4:
                    start_background_task(
                        f"GV-Listen-Export {gv_year}",
                        get_orchestrator().export_gv_lists,
                        int(gv_year),
                    )
                else:
                    st.error("Please enter a valid 4-digit year.")

    sync_task = st.session_state.get("background_task")
    if (
        st.session_state.get("background_task_label") == "CleverReach-Synchronisierung"
        and isinstance(sync_task, Future)
        and sync_task.done()
        and sync_task.exception() is None
    ):
        removed_emails, activated_emails = sync_task.result()
        if removed_emails:
            st.markdown(
                f"Removed {len(removed_emails)} receivers from 'ausgetreten' "
                "filter in CleverReach:"
            )
            for email in removed_emails:
                st.markdown(f"- {email}")
        if activated_emails:
            st.markdown(
                f"Activated {len(activated_emails)} inactive receivers in CleverReach:"
            )
            for email in activated_emails:
                st.markdown(f"- {email}")


def reset_client() -> None:
    if isinstance(st.session_state.orch, Orchestrator):
        del st.session_state.orch
    st.session_state.orch = Orchestrator()


def is_background_task_running() -> bool:
    """Check local worker activity, independently of the server's refresh status."""
    # Keep actions blocked until a completed status result has been applied too.
    if "members_refresh_task" in st.session_state:
        return True
    task = st.session_state.get("background_task")
    return isinstance(task, Future) and not task.done()


@st.fragment(run_every=1)
def configure_console() -> None:
    refresh_task = st.session_state.get("members_refresh_task")
    if isinstance(refresh_task, Future) and refresh_task.done():
        # Redraw the completed result only; this never polls the MySTV API.
        st.rerun(scope="app")
    st.header("Logs", anchor=False)
    task = st.session_state.get("background_task")
    task_label = st.session_state.get("background_task_label")
    if isinstance(task, Future):
        if not task.done():
            st.toast(f"{task_label} in progress…")
            st.info(f"{task_label} in progress…")
        else:
            if not st.session_state.get("background_task_completion_rerun", False):
                st.session_state.background_task_completion_rerun = True
                st.rerun(scope="app")
            if task.exception() is not None:
                st.toast(f"{task_label} failed: {task.exception()}")
                st.error(f"{task_label} failed: {task.exception()}")
            else:
                st.toast(f"{task_label} completed.")
                st.success(f"{task_label} completed.")

    log_messages = get_console_log_handler().get_messages()
    st.code("\n".join(log_messages) or "No logs yet.", language=None, height=260)


def configure_application_actions() -> None:
    st.header("Anwendung", anchor=False)
    reload_col, cache_col = st.columns(2)
    with reload_col, st.container(border=True, height="stretch"):
        st.markdown("### Serverdaten")
        st.caption("Startet die Aktualisierung der Mitgliederdaten auf dem Server.")
        st.space("stretch")
        if st.button(
            "Datenbank neu laden",
            icon=":material/sync:",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_members_refresh_task(start_refresh=True)
            st.rerun()
    with cache_col, st.container(border=True, height="stretch"):
        st.markdown("### Lokaler Cache")
        st.caption(
            "Leert die lokalen Mitglieder- und Riegendaten. "
            "Der nächste Abruf lädt sie erneut."
        )
        st.space("stretch")
        if st.button(
            "Reset cache",
            icon=":material/delete_sweep:",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Lokalen Cache leeren", get_orchestrator().clear_cache
            )
            st.rerun()
    folder_col, shutdown_col = st.columns(2)
    with folder_col, st.container(border=True, height="stretch"):
        st.markdown("### Exportordner")
        st.caption("Öffnet den Ordner mit den exportierten Dateien.")
        st.space("stretch")
        if st.button(
            "Open output folder in Finder",
            key="btn_open_output_folder",
            icon=":material/folder_open:",
            width="stretch",
        ):
            try:
                subprocess.run(["open", str(OUTPUT_FOLDER_PATH)], check=True)
            except (OSError, subprocess.CalledProcessError) as error:
                st.error(f"Could not open the output folder: {error}")
            else:
                st.toast("Opened output folder in Finder")
    with shutdown_col, st.container(border=True, height="stretch"):
        st.markdown("### Anwendung beenden")
        st.caption("Beendet die Anwendung auf diesem Computer.")
        st.space("stretch")
        if st.button(
            "Shut down", icon=":material/power_settings_new:", width="stretch"
        ):
            os.kill(os.getpid(), signal.SIGTERM)


def show_invisible_characters(value: str) -> str:
    markers = {
        " ": "·",
        "\u00a0": "[NBSP]",
        "\t": "[TAB]",
        "\n": "[LF]",
        "\r": "[CR]",
        "\u200b": "[ZWSP]",
    }
    visible = []
    for character in value:
        if character in markers:
            visible.append(markers[character])
        elif (
            not character.isprintable()
            or character.isspace()
            or unicodedata.category(character) in {"Mn", "Me"}
        ):
            visible.append(
                f"[U+{ord(character):04X} {unicodedata.name(character, 'UNNAMED')}]"
            )
        else:
            visible.append(character)
    return "".join(visible)


def configure_difference_details(
    left_value: str, right_value: str, left_label: str, right_label: str
) -> None:
    fragments: dict[str, list[str]] = {left_label: [], right_label: []}
    characters: list[dict[str, str | int]] = []
    matcher = SequenceMatcher(None, left_value, right_value, autojunk=False)
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        for source, value, start, end in (
            (left_label, left_value, left_start, left_end),
            (right_label, right_value, right_start, right_end),
        ):
            fragment = escape(show_invisible_characters(value[start:end]))
            if tag != "equal" and start != end:
                fragment = f"<mark>{fragment}</mark>"
                for position in range(start, end):
                    character = value[position]
                    characters.append(
                        {
                            "Quelle": source,
                            "Position": position + 1,
                            "Zeichen": show_invisible_characters(character),
                            "Unicode": f"U+{ord(character):04X}",
                            "Name": unicodedata.name(character, "UNNAMED"),
                        }
                    )
            fragments[source].append(fragment)
    st.caption(
        "Abweichungen sind markiert. Leerzeichen: ·; geschütztes Leerzeichen: [NBSP]."
    )
    for column, (source, value) in zip(
        st.columns(2),
        ((left_label, left_value), (right_label, right_value)),
        strict=True,
    ):
        with column:
            st.markdown(f"**{source} · {len(value)} Zeichen**")
            content = "".join(fragments[source]) if value else "[LEER]"
            st.html(f'<div class="character-diff">{content}</div>')
    if characters:
        with st.expander("Unicode-Details der abweichenden Zeichen"):
            st.caption("Positionen beginnen bei 1; gezählt werden Unicode-Codepoints.")
            st.dataframe(pd.DataFrame(characters), hide_index=True, width="stretch")
    else:
        st.info(
            "Die Textdarstellungen sind identisch. Der Unterschied kann in den "
            "ursprünglichen Datentypen liegen."
        )


def clear_comparison(key_prefix: str) -> None:
    st.session_state.pop(f"{key_prefix}_comparison_task", None)
    st.session_state.pop(f"{key_prefix}_diff_table", None)


def get_background_result(key: str, pending_message: str) -> object | None:
    """Display local task progress/errors and return a completed result."""
    task = st.session_state.get(key)
    if not isinstance(task, Future):
        return None
    if not task.done():
        st.info(pending_message)
        return None
    if task.cancelled():
        st.warning("Der Vorgang wurde abgebrochen.")
        return None
    if (error := task.exception()) is not None:
        st.error(f"Vorgang fehlgeschlagen: {error}")
        return None
    result: object = task.result()
    return result


def configure_comparison_result(result: ComparisonResult, key_prefix: str) -> None:
    differences = result.differences
    missing_in_left = result.missing_in_left
    missing_in_right = result.missing_in_right
    missing_left_label = (
        "Fehlt im aktuellen Stand"
        if result.left_label == "Aktuell"
        else f"Fehlt in {result.left_label}"
    )
    missing_right_label = (
        "Fehlt im Snapshot"
        if result.right_label == "Snapshot"
        else f"Fehlt in {result.right_label}"
    )
    metrics = {
        "Mitglieder mit Unterschieden": differences[DIFF_ID_COLUMN].nunique(),
        "Abweichende Felder": len(differences),
        missing_left_label: len(missing_in_left),
        missing_right_label: len(missing_in_right),
    }
    for column, (label, value) in zip(
        st.columns(len(metrics)), metrics.items(), strict=True
    ):
        column.metric(label, value)
    st.caption("Werte je Feld im direkten Vergleich. Es werden keine Daten verändert.")
    diff_tab, left_tab, right_tab = st.tabs(
        [
            f"Unterschiede ({len(differences)})",
            f"{missing_left_label} ({len(missing_in_left)})",
            f"{missing_right_label} ({len(missing_in_right)})",
        ]
    )
    with diff_tab:
        if differences.empty:
            st.success(
                "Keine Unterschiede in den verglichenen Feldern gemeinsamer Mitglieder."
            )
        else:
            show_invisible = st.toggle(
                "Unsichtbare Zeichen anzeigen",
                key=f"{key_prefix}_show_invisible",
                help="Zeigt Leerzeichen und Unicode-Sonderzeichen, ohne die Daten zu ändern.",
            )
            displayed_differences = differences.copy()
            if show_invisible:
                for source in (result.left_label, result.right_label):
                    displayed_differences[source] = displayed_differences[source].map(
                        show_invisible_characters
                    )
            st.caption("Wähle eine Zeile aus, um die Zeichen im Detail zu vergleichen.")
            selection = st.dataframe(
                displayed_differences,
                key=f"{key_prefix}_diff_table",
                on_select="rerun",
                selection_mode="single-row",
                hide_index=True,
                width="stretch",
                height=min(600, (len(differences) + 1) * 35 + 3),
                column_config={
                    col: st.column_config.TextColumn(width="small")
                    for col in differences.columns
                },
            )
            if selection.selection.rows:
                row = differences.iloc[selection.selection.rows[0]]
                st.markdown("#### Zeichendetails")
                st.text(
                    f"{row[DIFF_ID_COLUMN]} · {row[DIFF_FIRST_NAME_COLUMN]} {row[DIFF_SURNAME_COLUMN]} · {row[DIFF_FIELD_COLUMN]}"
                )
                configure_difference_details(
                    row[result.left_label],
                    row[result.right_label],
                    result.left_label,
                    result.right_label,
                )
    for tab, members in (
        (left_tab, missing_in_left),
        (right_tab, missing_in_right),
    ):
        with tab:
            if members.empty:
                st.caption("Keine fehlenden Mitglieder.")
            else:
                st.dataframe(
                    members,
                    hide_index=True,
                    width="stretch",
                    height=min(600, (len(members) + 1) * 35 + 3),
                )


def format_snapshot_timestamp(meta: MySTVSnapshotMeta) -> str:
    return meta.date.tz_convert(DISPLAY_TIMEZONE).strftime("%d.%m.%Y %H:%M:%S %Z")


def get_snapshot_catalog() -> list[MySTVSnapshotMeta]:
    """Read local storage once per session, after a save, or on manual refresh."""
    snapshots = st.session_state.get("snapshot_catalog")
    if snapshots is None:
        snapshots = get_orchestrator().list_snapshots()
        st.session_state.snapshot_catalog = snapshots
    if not isinstance(snapshots, list) or not all(
        isinstance(meta, MySTVSnapshotMeta) for meta in snapshots
    ):
        raise TypeError("The snapshot list has an unexpected type.")
    return snapshots


def configure_snapshot_comparison() -> None:
    st.header("Snapshot Vergleich", anchor=False)
    save_col, compare_col = st.columns(2)
    with save_col, st.container(border=True, height="stretch"):
        st.markdown("### Aktuellen Stand speichern")
        st.caption(
            "Lädt die aktuellen Mitgliederdaten, Riegen und Funktionen und speichert sie als Snapshot."
        )
        saved = get_background_result(
            "snapshot_save_task", "Aktueller Stand wird geladen und gespeichert …"
        )
        if saved is not None:
            if not isinstance(saved, MySTVSnapshotMeta):
                raise TypeError("Saving the snapshot returned an unexpected result.")
            if not st.session_state.get("snapshot_save_applied", False):
                st.session_state.pop("snapshot_catalog", None)
                st.session_state.snapshot_selection = saved.uuid
                clear_comparison("snapshot")
                st.session_state.snapshot_save_applied = True
            st.success(f"Snapshot gespeichert: {format_snapshot_timestamp(saved)}")
        st.space("stretch")
        if st.button(
            "Snapshot erstellen",
            key="btn_save_snapshot",
            type="primary",
            icon=":material/save:",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Snapshot erstellen", get_orchestrator().take_and_dump_snapshot
            )
            st.session_state.snapshot_save_task = st.session_state.background_task
            st.session_state.snapshot_save_applied = False
            st.rerun()

    with compare_col, st.container(border=True, height="stretch"):
        st.markdown("### Gespeicherte Snapshots")
        if st.button(
            "Liste aktualisieren",
            key="btn_refresh_snapshots",
            icon=":material/refresh:",
            disabled=is_background_task_running(),
        ):
            st.session_state.pop("snapshot_catalog", None)
        try:
            snapshots = get_snapshot_catalog()
        except Exception as error:  # noqa: BLE001
            # Show storage errors at the UI boundary and allow a manual retry.
            st.error(f"Snapshots konnten nicht geladen werden: {error}")
            snapshots = []
        by_id = {meta.uuid: meta for meta in snapshots}
        snapshot_labels = {
            meta.uuid: format_snapshot_timestamp(meta) for meta in snapshots
        }
        label_counts = Counter(snapshot_labels.values())
        # Streamlit resolves selections by their displayed label. Distinguish
        # snapshots captured within the same second without cluttering other labels.
        snapshot_labels = {
            snapshot_id: f"{label} ({snapshot_id})"
            if label_counts[label] > 1
            else label
            for snapshot_id, label in snapshot_labels.items()
        }
        if st.session_state.get("snapshot_selection") not in by_id:
            st.session_state.pop("snapshot_selection", None)
            clear_comparison("snapshot")
        st.caption(
            f"{len(snapshots)} gespeicherte Snapshots · Zeitangaben für die Schweiz."
        )
        selected = st.selectbox(
            "Snapshot auswählen",
            options=list(by_id),
            index=0 if snapshots else None,
            key="snapshot_selection",
            format_func=snapshot_labels.__getitem__,
            placeholder="Noch keine Snapshots vorhanden",
            disabled=not snapshots or is_background_task_running(),
            on_change=clear_comparison,
            args=("snapshot",),
        )
        st.space("stretch")
        if (
            st.button(
                "Mit aktuellem Stand vergleichen",
                key="btn_snapshot_comparison",
                type="primary",
                icon=":material/compare_arrows:",
                width="stretch",
                disabled=selected is None or is_background_task_running(),
            )
            and selected is not None
        ):
            clear_comparison("snapshot")
            start_background_task(
                "Snapshot Vergleich",
                get_orchestrator().compare_to_snapshot,
                selected,
            )
            st.session_state.snapshot_comparison_task = st.session_state.background_task
            st.rerun()

    if "snapshot_comparison_task" in st.session_state:
        with st.container(border=True):
            result = get_background_result(
                "snapshot_comparison_task",
                "Aktueller Stand wird geladen und verglichen …",
            )
            if result is not None:
                if not isinstance(result, ComparisonResult):
                    raise TypeError("The comparison returned an unexpected result.")
                if selected is not None:
                    st.caption(
                        f"Vergleich mit dem Snapshot vom {format_snapshot_timestamp(by_id[selected])}."
                    )
                configure_comparison_result(result, "snapshot")


def configure_fairgate_comparison() -> None:
    st.header("Fairgate Vergleich", anchor=False)
    with st.container(border=True):
        st.caption("Lade und vergleiche die Fairgate-Daten mit den mySTV-Daten.")
        if st.button(
            "Vergleichen",
            key="btn_fairgate_comparison",
            type="primary",
            icon=":material/compare_arrows:",
            disabled=is_background_task_running(),
        ):
            clear_comparison("fairgate")
            start_background_task(
                "Fairgate Comparison", get_orchestrator().compare_to_fairgate_export
            )
            # Retain the result when other actions replace the shared background task.
            st.session_state.fairgate_comparison_task = st.session_state.background_task
            st.rerun()
        result = get_background_result(
            "fairgate_comparison_task", "Fairgate-Export wird verglichen …"
        )
        if result is not None:
            if not isinstance(result, ComparisonResult):
                raise TypeError("The comparison returned an unexpected result.")
            configure_comparison_result(result, "fairgate")


def run_home() -> None:
    setup_page()
    get_console_log_handler()
    get_orchestrator()
    collect_members_refresh_result()
    if "members_refresh_running" not in st.session_state:
        start_members_refresh_task()
    configure_title()
    with st.container(horizontal=True, horizontal_alignment="right"):
        configure_members_refresh_status()
    configure_statistics()
    st.divider()
    configure_export_buttons()
    st.divider()
    configure_console()
    st.divider()
    configure_application_actions()
    st.divider()
    configure_snapshot_comparison()
    st.divider()
    configure_fairgate_comparison()


if __name__ == "__main__":
    run_home()
