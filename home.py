import logging
import os
import signal
import subprocess
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
from threading import Lock
from typing import Any

import pandas as pd
import streamlit as st

from src.orchestrator import Orchestrator
from src.utils.utils import OUTPUT_FOLDER_PATH

# Set logging level to INFO
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    orchestrator: Orchestrator = st.session_state.orch
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
    st.markdown(
        """
        <style>
        :root {
            --stv-red: #a7353a;
            --stv-grey: #878787;
            --stv-white: #ffffff;
        }

        [data-testid="stAppViewContainer"] {
            background: var(--stv-white);
            color: var(--stv-grey);
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        .main .block-container {
            max-width: 1180px;
            padding-top: 2.5rem;
            padding-bottom: 3rem;
        }

        h1, h2, h3 {
            color: var(--stv-grey);
            letter-spacing: -0.025em;
        }

        [data-testid="stCaptionContainer"] {
            color: var(--stv-grey);
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--stv-white);
            border: 1px solid rgba(135, 135, 135, 0.3);
            border-radius: 16px;
            box-shadow: 0 5px 18px rgba(135, 135, 135, 0.12);
        }

        .stButton > button {
            min-height: 2.75rem;
            border: 1px solid var(--stv-grey);
            border-radius: 10px;
            background: var(--stv-white);
            color: var(--stv-grey);
            font-weight: 600;
            transition: border-color 150ms ease, color 150ms ease,
                box-shadow 150ms ease, transform 150ms ease;
        }

        .stButton > button:hover {
            border-color: var(--stv-red);
            color: var(--stv-red);
            box-shadow: 0 4px 12px rgba(135, 135, 135, 0.2);
            transform: translateY(-1px);
        }

        .stButton > button:focus-visible {
            outline: 3px solid var(--stv-red);
            outline-offset: 2px;
        }

        /* Scope the compact status button through Streamlit's widget keys. */
        .st-key-btn_members_refresh_status button {
            min-height: 1.75rem;
            padding: 0.15rem 0.65rem;
            border: 1px solid transparent;
            border-radius: 999px;
            background: var(--status-background);
            color: var(--status-color);
            box-shadow: none;
            transform: none;
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
            transform: none;
        }

        .st-key-btn_members_refresh_status button:focus-visible {
            outline: 2px solid var(--status-color);
            outline-offset: 2px;
        }

        .hero {
            margin-bottom: 2rem;
            padding: 2.25rem 2.5rem;
            border-radius: 22px;
            background: var(--stv-red);
            color: var(--stv-white);
            box-shadow: 0 14px 32px rgba(135, 135, 135, 0.2);
        }

        .hero-eyebrow {
            margin: 0 0 0.75rem;
            color: var(--stv-white);
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }

        .hero-title {
            margin: 0;
            color: var(--stv-white);
            font-size: clamp(2rem, 4vw, 2.8rem);
            font-weight: 750;
            letter-spacing: -0.045em;
            line-height: 1.1;
        }

        .section-intro {
            margin: 0 0 1rem;
            color: var(--stv-grey);
        }

        .danger-zone-divider {
            margin-top: 2.5rem;
            border-top: 1px solid var(--stv-grey);
        }

        @media (max-width: 640px) {
            .main .block-container {
                padding: 1rem 1rem 2rem;
            }

            .hero {
                padding: 1.6rem 1.4rem;
                border-radius: 16px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
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
    with st.container(border=True):
        st.markdown("### Mitgliederstatistik")
        st.caption("Aktuelle Kennzahlen aus mySTV auf Abruf.")
        statistics_output = st.empty()
        if st.button(
            "Statistik abrufen",
            key="btn_statistics",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Mitgliederstatistik",
                st.session_state.orch.get_statistics,
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
                        st.markdown("#### Geschlechterverteilung")
                        st.dataframe(demographics, hide_index=True, width="stretch")
                    with categories_col:
                        st.markdown("#### Mitgliedskategorien")
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
    st.markdown("## Exporte")
    st.markdown(
        '<p class="section-intro">Wähle eine Liste oder Aktion aus.</p>',
        unsafe_allow_html=True,
    )

    st.markdown("### CleverReach")
    cleverreach_col1, cleverreach_col2 = st.columns(2)
    with cleverreach_col1, st.container(border=True):
        st.markdown("#### Empfänger synchronisieren")
        st.caption("Mitglieder mit CleverReach abgleichen.")
        if st.button(
            "Sync to CleverReach",
            key="btn_cleverreach_sync",
            use_container_width=True,
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "CleverReach-Synchronisierung",
                st.session_state.orch.sync_to_cleverreach,
            )
    with cleverreach_col2, st.container(border=True):
        st.markdown("#### CleverReach-Daten")
        st.caption("Die CleverReach-Daten als CSV exportieren.")
        if st.button(
            "Export CleverReach Data",
            key="btn_cleverreach_export",
            use_container_width=True,
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "CleverReach-Datenexport",
                st.session_state.orch.export_cleverreach_csv,
            )

    st.markdown("### Mitgliederlisten")
    member_cols = st.columns(3)
    with member_cols[0], st.container(border=True):
        st.markdown("#### Riegenlisten")
        st.caption("Listen nach Institut exportieren.")
        if st.button(
            "Riegenlisten",
            key="btn_riegenlisten",
            use_container_width=True,
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Riegenlisten-Export",
                st.session_state.orch.export_each_institute_to_excel,
            )
    with member_cols[1], st.container(border=True):
        st.markdown("#### Infoheft")
        st.caption("Adressliste für das Infoheft erstellen.")
        if st.button(
            "Infoheft Liste",
            key="btn_infoheft",
            use_container_width=True,
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Infoheft-Export",
                st.session_state.orch.export_infoheft_address_list,
            )
    with member_cols[2], st.container(border=True):
        st.markdown("#### Coaches")
        st.caption("Aktuelle Coachliste exportieren.")
        if st.button(
            "Coachliste",
            key="btn_coachliste",
            use_container_width=True,
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Coachlisten-Export",
                st.session_state.orch.export_coach_list_to_excel,
            )

    no_mail_col, gv_col = st.columns(2)
    with no_mail_col, st.container(border=True):
        st.markdown("#### Kein E-Mail-Versand")
        st.caption("Mitglieder ohne Mail oder Newsletter-Einwilligung.")
        if st.button(
            "No Mail",
            key="btn_no_mail",
            use_container_width=True,
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "No-Mail-Export",
                st.session_state.orch.export_no_mail_excel,
            )
    with gv_col, st.container(border=True):
        st.markdown("#### GV-Listen nach Jahr")
        st.caption("Jahreslisten für eine Generalversammlung exportieren.")
        input_col, button_col = st.columns([3, 1])
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
                use_container_width=True,
                disabled=is_background_task_running(),
            ):
                if gv_year.isdigit() and len(gv_year) == 4:
                    start_background_task(
                        f"GV-Listen-Export {gv_year}",
                        st.session_state.orch.export_gv_lists,
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
    st.markdown("#### Console")
    task = st.session_state.get("background_task")
    task_label = st.session_state.get("background_task_label")
    if isinstance(task, Future):
        if not task.done():
            st.info(f"{task_label} in progress…")
        else:
            if not st.session_state.get("background_task_completion_rerun", False):
                st.session_state.background_task_completion_rerun = True
                st.rerun(scope="app")
            if task.exception() is not None:
                st.error(f"{task_label} failed: {task.exception()}")
            else:
                st.success(f"{task_label} completed.")

    st.caption("Recent application logs")
    log_messages = get_console_log_handler().get_messages()
    st.code("\n".join(log_messages) or "No logs yet.", language=None, height=260)


def configure_application_actions() -> None:
    st.markdown('<hr class="danger-zone-divider">', unsafe_allow_html=True)
    st.markdown("#### Anwendung")
    reload_col, cache_col = st.columns(2)
    with reload_col, st.container(border=True):
        st.caption("Startet die Aktualisierung der Mitgliederdaten auf dem Server.")
        if st.button(
            "Datenbank neu laden",
            icon=":material/sync:",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_members_refresh_task(start_refresh=True)
            st.rerun()
    with cache_col, st.container(border=True):
        st.caption(
            "Leert die lokalen Mitglieder- und Riegendaten. "
            "Der nächste Abruf lädt sie erneut."
        )
        if st.button(
            "Reset cache",
            icon=":material/delete_sweep:",
            width="stretch",
            disabled=is_background_task_running(),
        ):
            start_background_task(
                "Lokalen Cache leeren", st.session_state.orch.clear_mystv_cache
            )
            st.rerun()
    folder_col, shutdown_col = st.columns(2)
    with folder_col, st.container(border=True):
        st.caption("Öffnet den Ordner mit den exportierten Dateien.")
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
    with shutdown_col, st.container(border=True):
        st.caption("Beendet die Anwendung auf diesem Computer.")
        if st.button(
            "Shut down", icon=":material/power_settings_new:", width="stretch"
        ):
            os.kill(os.getpid(), signal.SIGTERM)


def clear_fairgate_comparison() -> None:
    st.session_state.pop("fairgate_comparison_task", None)


def configure_fairgate_comparison() -> None:
    st.markdown("## Fairgate Vergleich")
    with st.container(border=True):
        st.caption(
            "Vergleiche einen Fairgate-Excel-Export mit den geladenen mySTV-Daten."
        )
        upload = st.file_uploader(
            "Fairgate-Excel-Datei",
            type=["xlsx"],
            key="fairgate_upload",
            on_change=clear_fairgate_comparison,
            disabled=is_background_task_running(),
        )
        if (
            st.button(
                "Vergleichen",
                key="btn_fairgate_comparison",
                icon=":material/compare_arrows:",
                disabled=upload is None or is_background_task_running(),
            )
            and upload is not None
        ):
            start_background_task(
                "Fairgate Comparison",
                st.session_state.orch.compare_to_fairgate_export,
                BytesIO(upload.getvalue()),
            )
            # Retain the result when other actions replace the shared background task.
            st.session_state.fairgate_comparison_task = st.session_state.background_task
            st.rerun()

        task = st.session_state.get("fairgate_comparison_task")
        if not isinstance(task, Future):
            return
        if not task.done():
            st.info("Fairgate-Export wird verglichen …")
            return
        if (error := task.exception()) is not None:
            st.error(f"Vergleich konnte nicht durchgeführt werden: {error}")
            return

        differences, missing_in_mystv, missing_in_fairgate = task.result()
        metrics = {
            "Mitglieder mit Unterschieden": differences["STV-Nummer"].nunique(),
            "Abweichende Felder": len(differences),
            "Fehlt in mySTV": len(missing_in_mystv),
            "Fehlt in Fairgate": len(missing_in_fairgate),
        }
        for column, (label, value) in zip(
            st.columns(len(metrics)), metrics.items(), strict=True
        ):
            column.metric(label, value)
        st.caption(
            "Werte je Feld im direkten Vergleich. Es werden keine Daten verändert."
        )
        diff_tab, mystv_tab, fairgate_tab = st.tabs(
            [
                f"Unterschiede ({len(differences)})",
                f"Fehlt in mySTV ({len(missing_in_mystv)})",
                f"Fehlt in Fairgate ({len(missing_in_fairgate)})",
            ]
        )
        with diff_tab:
            if differences.empty:
                st.success(
                    "Keine Unterschiede in den verglichenen Feldern gemeinsamer Mitglieder."
                )
            else:
                st.dataframe(
                    differences,
                    hide_index=True,
                    width="stretch",
                    height=min(600, (len(differences) + 1) * 35 + 3),
                    column_config={col: st.column_config.TextColumn(width="small") for col in differences.columns},
                )
        for tab, members in (
            (mystv_tab, missing_in_mystv),
            (fairgate_tab, missing_in_fairgate),
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


def run_home() -> None:
    setup_page()
    get_console_log_handler()
    if "orch" not in st.session_state:
        st.session_state.orch = Orchestrator()
    collect_members_refresh_result()
    if "members_refresh_running" not in st.session_state:
        start_members_refresh_task()
    configure_title()
    configure_members_refresh_status()
    configure_statistics()
    configure_export_buttons()
    configure_console()
    configure_application_actions()
    configure_fairgate_comparison()


if __name__ == "__main__":
    run_home()
