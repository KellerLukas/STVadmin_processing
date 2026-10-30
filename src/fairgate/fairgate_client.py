import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from types import TracebackType
from typing import Any, Self
from urllib.parse import urljoin

import requests

from src.config.constants import OP_FAIRGATE_ITEM_UUID
from src.config.paths import FAIRGATE_EXPORT_CONFIG_PATH
from src.utils.credentials import CredentialsBase

logger = logging.getLogger(__name__)

HTTP_CONNECT_TIMEOUT_S = 10
HTTP_READ_TIMEOUT_S = 60
HTTP_EXPORT_READ_TIMEOUT_S = 120
HTML_CONTENT_TYPE = "text/html"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_SIGNATURE = b"PK\x03\x04"

CSRF_FIELD = "_csrf_token"
USERNAME_FIELD = "_username"
PASSWORD_FIELD = "_password"
LOGIN_FIELDS = {CSRF_FIELD, USERNAME_FIELD, PASSWORD_FIELD}

EXPORT_COLUMN_TYPES = "columnType"
EXPORT_COLUMN_NAMES = "columnNames"
EXPORT_EXTRA_SEARCH = "extraSearch"
EXPORT_CLUB_SLUG = "club_slug"
EXPORT_DEFAULTS = {
    "selectIds": "",
    "filterdata": None,
    "searchvalue": "",
    "exportflag": 1,
    "functionShow": "",
    "assignedClubsShow": "",
}
EXPORT_FORM_DEFAULTS = {"Columns": "savedColset", "contactType": "contact"}


class FairgateError(RuntimeError):
    """A Fairgate failure; messages omit credentials and response bodies."""


class FairgateAuthenticationError(FairgateError):
    """Authentication is missing, expired, or rejected."""


class FairgateHTTPError(FairgateError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Fairgate returned HTTP {status_code}.")


class _LoginPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[tuple[str, str, dict[str, str]]] = []
        self.links: set[str] = set()
        self._current_form: tuple[str, str, dict[str, str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._current_form = (
                attributes.get("action") or "",
                (attributes.get("method") or "get").lower(),
                {},
            )
            self.forms.append(self._current_form)
        elif tag == "input" and self._current_form is not None:
            name = attributes.get("name")
            if name:
                self._current_form[2][name] = attributes.get("value") or ""
        elif tag == "a":
            self.links.add(attributes.get("href") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._current_form = None


class FairgateClient:
    """Synchronous website login and Excel export. Use from one thread at a time."""

    _BASE_URL = "https://mein.fairgate.ch"
    _BACKEND_PATH = "/{club_slug}/backend"
    _SIGNIN_PATH = "/signin"
    _DASHBOARD_PATH = "/dashboard"
    _SIGNOUT_PATH = "/signout"
    _EXPORT_PAGE_PATH = "/contact/export/contact"
    _EXPORT_DATA_PATH = "/contact/exportdata"

    def __init__(self, club_slug: str) -> None:
        if not re.fullmatch(r"[a-z0-9_-]+", club_slug):
            raise ValueError("club_slug must be a Fairgate club URL identifier.")
        self.club_slug = club_slug
        self.creds = CredentialsBase(item_uuid=OP_FAIRGATE_ITEM_UUID)
        self._session: requests.Session | None = requests.Session()
        self._session.trust_env = False
        self._authenticated = False

    def __enter__(self) -> Self:
        self._get_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.close()
        else:
            try:
                self.close()
            except Exception:  # noqa: BLE001
                # Preserve the original operation error if secondary cleanup fails.
                logger.warning(
                    "Could not fully close the Fairgate client after failure."
                )

    def _get_session(self) -> requests.Session:
        if self._session is None:
            raise FairgateError("This client is closed. Create a new FairgateClient.")
        return self._session

    def _url(self, path: str) -> str:
        return (
            self._BASE_URL + self._BACKEND_PATH.format(club_slug=self.club_slug) + path
        )

    @contextmanager
    def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
        referer: str | None = None,
        expected_status: tuple[int, ...] = (200,),
        read_timeout: int = HTTP_READ_TIMEOUT_S,
        accept: str = HTML_CONTENT_TYPE,
    ) -> Iterator[requests.Response]:
        headers = {"Accept": accept}
        if referer is not None:
            headers["Referer"] = self._url(referer)
        if method == "POST":
            headers["Origin"] = self._BASE_URL
        logger.debug("Fairgate request: %s %s", method, path)
        try:
            with self._get_session().request(
                method,
                self._url(path),
                data=data,
                headers=headers,
                timeout=(HTTP_CONNECT_TIMEOUT_S, read_timeout),
                allow_redirects=False,
            ) as response:
                logger.debug("Fairgate response: HTTP %s", response.status_code)
                redirect = urljoin(
                    self._url(path), response.headers.get("Location", "")
                )
                if response.status_code in (401, 403) or (
                    300 <= response.status_code < 400
                    and redirect == self._url(self._SIGNIN_PATH)
                ):
                    self._authenticated = False
                    raise FairgateAuthenticationError(
                        "Fairgate rejected the session or access. Call login() before retrying."
                    )
                if response.status_code not in expected_status:
                    raise FairgateHTTPError(response.status_code)
                yield response
        except requests.RequestException:
            raise FairgateError(
                "Fairgate request failed or timed out. No automatic retry was attempted."
            ) from None

    def login(self) -> None:
        """Start a fresh cookie session using the configured 1Password credentials."""
        session = self._get_session()
        self._authenticated = False
        session.cookies.clear()
        logger.info("Logging in to Fairgate")
        try:
            with self._request("GET", self._SIGNIN_PATH) as response:
                page = _LoginPageParser()
                page.feed(response.text)
            forms = [form for form in page.forms if LOGIN_FIELDS <= form[2].keys()]
            if len(forms) != 1:
                raise FairgateAuthenticationError(
                    "Expected exactly one Fairgate login form."
                )
            action, method, fields = forms[0]
            if (
                method != "post"
                or urljoin(self._url(self._SIGNIN_PATH), action)
                != self._url(self._SIGNIN_PATH)
                or not fields[CSRF_FIELD]
            ):
                raise FairgateAuthenticationError(
                    "Fairgate returned an unexpected login form."
                )
            username, password = self.creds.get_client_credentials()
            if not username or not password:
                raise FairgateAuthenticationError(
                    "Fairgate username and password are required."
                )
            with self._request(
                "POST",
                self._SIGNIN_PATH,
                data={
                    CSRF_FIELD: fields[CSRF_FIELD],
                    USERNAME_FIELD: username,
                    PASSWORD_FIELD: password,
                },
                referer=self._SIGNIN_PATH,
                expected_status=(200, 302, 303),
            ) as response:
                destination = urljoin(
                    self._url(self._SIGNIN_PATH), response.headers.get("Location", "")
                )
                if response.status_code == 200 or destination != self._url(
                    self._DASHBOARD_PATH
                ):
                    raise FairgateAuthenticationError(
                        "Fairgate login failed or requires an additional step."
                    )
            with self._request("GET", self._DASHBOARD_PATH) as response:
                page = _LoginPageParser()
                page.feed(response.text)
            links = {
                urljoin(self._url(self._DASHBOARD_PATH), link) for link in page.links
            }
            if self._url(self._SIGNOUT_PATH) not in links or any(
                PASSWORD_FIELD in form[2] for form in page.forms
            ):
                raise FairgateAuthenticationError(
                    "Could not verify the Fairgate login."
                )
            self._authenticated = True
            logger.info("Successfully logged in to Fairgate")
        finally:
            if not self._authenticated:
                session.cookies.clear()

    def _export_form_data(self) -> dict[str, str]:
        """Load column metadata only; never reuse captured sessions or row filters."""
        try:
            settings: object = json.loads(
                FAIRGATE_EXPORT_CONFIG_PATH.read_text(encoding="utf-8")
            )
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            raise FairgateError(
                "Could not read the Fairgate export configuration."
            ) from None
        if not isinstance(settings, dict) or not (
            isinstance(settings.get(EXPORT_COLUMN_TYPES), dict)
            and settings[EXPORT_COLUMN_TYPES]
            and isinstance(settings.get(EXPORT_COLUMN_NAMES), list)
            and settings[EXPORT_COLUMN_NAMES]
            and isinstance(settings.get(EXPORT_EXTRA_SEARCH), dict)
        ):
            raise FairgateError(
                "Fairgate export configuration has invalid column metadata."
            )
        if settings.get(EXPORT_CLUB_SLUG) != self.club_slug:
            raise FairgateError(
                "Fairgate export configuration belongs to a different club."
            )
        payload: dict[str, Any] = dict(EXPORT_DEFAULTS)
        for key in (EXPORT_COLUMN_TYPES, EXPORT_COLUMN_NAMES, EXPORT_EXTRA_SEARCH):
            payload[key] = settings[key]
        return {
            **EXPORT_FORM_DEFAULTS,
            "selctCol": json.dumps(payload[EXPORT_COLUMN_TYPES], ensure_ascii=False),
            "formhidden": json.dumps(payload, ensure_ascii=False),
        }

    def export_contacts(self) -> bytes:
        """Download the configured, unfiltered active-contact Excel export unchanged."""
        self._get_session()
        if not self._authenticated:
            raise FairgateAuthenticationError(
                "Call login() before exporting Fairgate contacts."
            )
        data = self._export_form_data()
        logger.info("Downloading Fairgate contacts as Excel")
        with self._request(
            "POST",
            self._EXPORT_DATA_PATH,
            data=data,
            referer=self._EXPORT_PAGE_PATH,
            read_timeout=HTTP_EXPORT_READ_TIMEOUT_S,
            accept=XLSX_CONTENT_TYPE,
        ) as response:
            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if content_type == HTML_CONTENT_TYPE:
                page = _LoginPageParser()
                page.feed(response.text)
                if any(LOGIN_FIELDS <= form[2].keys() for form in page.forms):
                    self._authenticated = False
                    raise FairgateAuthenticationError(
                        "Fairgate session expired. Call login() again."
                    )
            if content_type != XLSX_CONTENT_TYPE or not response.content.startswith(
                XLSX_SIGNATURE
            ):
                raise FairgateError("Fairgate did not return an Excel workbook.")
            content = response.content
        logger.info(
            "Successfully downloaded Fairgate contacts (%s bytes)", len(content)
        )
        return content

    def close(self) -> None:
        """Close the local session and discard its cookies. Safe to call repeatedly."""
        session = self._session
        self._session = None
        self._authenticated = False
        if session is not None:
            try:
                session.cookies.clear()
            finally:
                session.close()
