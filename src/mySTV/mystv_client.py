import codecs
from enum import StrEnum
from functools import cache, cached_property
import copy
import json
import logging
from src.config.paths import FILENAME_NEWSLETTER_BLACKLIST, WORKING_DIR_PATH
import time
import pandas as pd
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.parse import unquote, urlencode, urlsplit
from playwright.sync_api import sync_playwright

import requests

from src.config.constants import OP_MYSTV_ITEM_UUID
from src.utils.credentials import CredentialsBase
from src.utils.utils import calculate_age_at_ts

PROFILE_DIR = Path(".stv-browser")
HEADLESS = True  # Keep the browser visible for any MFA or other manual prompts.
LOGIN_TIMEOUT_S = 180
NAVIGATION_TIMEOUT_MS = 30000
LOGIN_POLL_INTERVAL_MS = 250
ACTION_TIMEOUT_MS = 10_000

FACTOR_S_TO_MS = 1000


class MySTVAPIError(RuntimeError):
    """A browser/API failure; messages omit credentials and response bodies."""


class MySTVAuthenticationError(MySTVAPIError):
    """Authentication is missing, expired, or rejected."""


class MySTVHTTPError(MySTVAPIError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"MySTV API returned HTTP {status_code}.")


class MySTVConfigurationError(RuntimeError):
    """Errors caused by misconfiguration / metadata issues"""


class InternalCategory(StrEnum):
    JUGENDMITGLIED = "Jugendmitglied"
    AKTIVMITGLIED = "Aktivmitglied"
    PASSIVMITGLIED = "Passivmitglied"
    EHRENMITGLIED = "Ehrenmitglied"
    EHRENMITGLIED_NT = "Ehrenmitglied nturnend"
    FREIMITGLIED = "Freimitglied"
    FREIMITGLIED_NT = "Freimitglied nturnend"


class MembershipCategory(StrEnum):
    ERWACHSENE_STANDARD = "Erwachsene Standard"
    ERWACHSENE_LIGHT = "Erwachsene Light"  # unverified
    ERWACHSENE_INKLUSION = "Erwachsene Inklusion"  # unverified
    PASSIVMITGLIEDER = "Passivmitglieder"
    EHRENMIGLIED_NT = "Ehrenmitg. nturnend"
    KINDER_JUGEND = "Kinder & Jugend"


class MembershipAddition(StrEnum):
    EMPTY = "-"
    FREIMITGLIED_T = "Freimitg. turnend"
    FREIMITGLIED_NT = "Freimitg. turnend"  # unverified #ToDo: discuss this
    EHRENMITGLIED_T = "Ehrenmitg. turnend"


MAP_CATEGORY_TO_INTERNAL = {
    (
        MembershipCategory.KINDER_JUGEND,
        MembershipAddition.EMPTY,
    ): InternalCategory.JUGENDMITGLIED,
    (
        MembershipCategory.ERWACHSENE_STANDARD,
        MembershipAddition.EMPTY,
    ): InternalCategory.AKTIVMITGLIED,
    (
        MembershipCategory.ERWACHSENE_LIGHT,
        MembershipAddition.EMPTY,
    ): InternalCategory.AKTIVMITGLIED,
    (
        MembershipCategory.ERWACHSENE_INKLUSION,
        MembershipAddition.EMPTY,
    ): InternalCategory.AKTIVMITGLIED,
    (
        MembershipCategory.PASSIVMITGLIEDER,
        MembershipAddition.EMPTY,
    ): InternalCategory.PASSIVMITGLIED,
    (
        MembershipCategory.ERWACHSENE_STANDARD,
        MembershipAddition.EHRENMITGLIED_T,
    ): InternalCategory.EHRENMITGLIED,
    (
        MembershipCategory.ERWACHSENE_LIGHT,
        MembershipAddition.EHRENMITGLIED_T,
    ): InternalCategory.EHRENMITGLIED,
    (
        MembershipCategory.ERWACHSENE_INKLUSION,
        MembershipAddition.EHRENMITGLIED_T,
    ): InternalCategory.EHRENMITGLIED,
    (
        MembershipCategory.EHRENMIGLIED_NT,
        MembershipAddition.EMPTY,
    ): InternalCategory.EHRENMITGLIED_NT,
    (
        MembershipCategory.ERWACHSENE_STANDARD,
        MembershipAddition.FREIMITGLIED_T,
    ): InternalCategory.FREIMITGLIED,
    (
        MembershipCategory.ERWACHSENE_LIGHT,
        MembershipAddition.FREIMITGLIED_T,
    ): InternalCategory.FREIMITGLIED,
    (
        MembershipCategory.ERWACHSENE_INKLUSION,
        MembershipAddition.FREIMITGLIED_T,
    ): InternalCategory.FREIMITGLIED,
    (
        MembershipCategory.PASSIVMITGLIEDER,
        MembershipAddition.FREIMITGLIED_NT,
    ): InternalCategory.FREIMITGLIED_NT,
}


class MembersColumns(StrEnum):
    MEMBER_ID = "memberId"
    SOCIAL_INSURANCE_NR = "socialInsuranceNr"
    SWISS_ATHLETICS_NR = "swissAthleticsNr"
    SALUTATION = "salutation"
    LANGUAGE = "language"
    SURNAME = "surname"
    FIRST_NAME = "firstName"
    ADDRESS = "address"
    ADDITION = "addition"
    ADDITION_2 = "addition2"
    POST_CODE = "postCode"
    CITY = "city"
    EMAIL_PRIVATE = "emailPrivate"
    EMAIL_ALTERNATIVE = "emailAlternative"
    EMAIL_VEREIN = "emailVerein"
    EMAIL_VERBAND = "emailVerband"
    PHONE_PRIVATE = "phonePrivate"
    PHONE_BUSINESS = "phoneBusiness"
    PHONE_MOBILE = "phoneMobile"
    MY_STV_COMMENT = "mySTVComment"
    BIRTHDAY = "birthday"
    ADVERTISING = "advertising"
    GYM_LIVE_ABO = "gymLiveAbo"
    REGIONAL_ABO = "regionalAbo"
    ADDRESS_RELEASE = "addressRelease"
    REGIONAL_ABO_NO = "regionalAboNo"
    MEMBERSHIP_CATEGORIES = "membershipCategories"
    MEMBERSHIP_ENTRY_DATES = "membershipEntryDates"
    MEMBERSHIP_ADDITIONS = "membershipAdditions"
    SQUADS = "squads"
    VERBANDS_ANSICHT_MEMBERSHIP_TEXT = "verbandsAnsichtMembershipText"
    VERBANDS_ANSICHT_MEMBERSHIP_NUMBER = "verbandsAnsichtMembershipNumber"
    HAS_DIRECT_VERBAND_MEMBERSHIP = "hasDirectVerbandMembership"
    HAS_INDIRECT_VERBAND_MEMBERSHIP = "hasIndirectVerbandMembership"
    MEMBERSHIPS = "memberships"
    HONORS = "honors"
    STATUS_MY_STV = "statusMySTV"
    RELEASE_MY_STV = "releaseMySTV"
    TYPE_OF_SPORT_LSA = "typeOfSportLSA"
    YEAR_VALID_LSA = "yearValidLSA"
    CLUB_NAME_LSA = "clubNameLSA"
    # Own additions to the MySTV export, not part of the official API.
    _COMBINED_EMAILS = (
        "combinedEmails"  # all emails combined into one string, separated by semicolons
    )
    _PRIMARY_EMAIL = "primaryEmail"  # the first non-empty email
    _INTERNAL_CATEGORY = "internalCategory"  # the internal category of the member
    _AGE = "age"
    _GETS_NEWSLETTER = "getsNewsletter"


YOUTH_INSTITUTE_CODES = ["3", "4", "8", "9", "10", "24", "25", "26"]
COACH_FUNCTION_CODES = ["3", "4"]

MALE_SALUTATION = "MR"
FEMALE_SALUTATION = "MS"


class MySTVClient:
    _BASE_URL = "https://my.stv-fsg.ch"
    _LOGIN_ORIGIN = "https://login.stv-fsg.ch"

    # Browser pages
    _MEMBERS_PAGE_PATH = "/club/members"
    _GROUPS_PAGE_PATH = "/club/groups/"
    _GROUP_MEMBERS_PAGE_PATH = "/club/groups/group-members"

    # API endpoints
    _MEMBERS_STREAM_PATH = "/backend/api/club/list-members/stream"
    _CLUB_ADDRESSES_PATH = "/backend/api/institutes/allAddressesInClub"
    _INSTITUTE_ADDRESS_CREATE_PATH = "/backend/api/institutes/addresses/create"

    def __init__(self, club_id: str):
        if not club_id:
            raise ValueError("club_id is required.")
        self.club_id = club_id
        self.creds = CredentialsBase(item_uuid=OP_MYSTV_ITEM_UUID)
        self._playwright = None
        self._context = None
        self._page = None
        self._response = None
        self._session = requests.Session()
        # Avoid ambient .netrc credentials replacing the Bearer token.
        # This also disables automatic environment proxy configuration.
        self._session.trust_env = False

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _ensure_open(self) -> None:
        if self._session is None:
            raise MySTVAPIError("This client is closed. Create a new MySTVClient.")

    def _members_referer(self) -> str:
        return f"{self._BASE_URL}/club/members?{urlencode({'clubId': self.club_id})}"

    def _open_browser(self) -> None:
        self._ensure_open()
        if self._context is not None:
            return
        profile = PROFILE_DIR.expanduser().resolve()
        profile.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile), headless=HEADLESS
            )
            self._context.set_default_timeout(ACTION_TIMEOUT_MS)
        except BaseException as error:
            self.close()
            if not isinstance(error, Exception):
                raise
            raise MySTVAPIError(
                "Could not start Chromium. Check its installation and ensure the "
                "profile is not open elsewhere. Error: " + str(error)
            ) from None

    def login(self) -> None:
        """Reuse the saved session or submit email / password once.

        Credentials are entered only on the verified MySTV login origin. Login
        waits up to LOGIN_TIMEOUT; it never retries rejected credentials.
        A token cookie indicates a session, but the API determines its validity.
        """
        self._open_browser()
        try:
            if self._page is None or self._page.is_closed():
                pages = self._context.pages
                self._page = pages[0] if pages else self._context.new_page()
            self._page.goto(
                self._members_referer(),
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            deadline = time.monotonic() + LOGIN_TIMEOUT_S
            submitted = False
            while True:
                url = urlsplit(self._page.url)
                origin = f"{url.scheme}://{url.netloc}"
                if origin == self._BASE_URL:
                    try:
                        self.get_access_token()
                        logging.info("MySTV authentication is available")
                        return
                    except MySTVAuthenticationError:
                        pass  # The application may still be redirecting to login.
                elif origin == self._LOGIN_ORIGIN:
                    if submitted:
                        if self._page.locator(
                            "#input-error, #kc-error-message"
                        ).first.is_visible():
                            raise MySTVAuthenticationError(
                                "MySTV reported a login error. Check the credentials "
                                "and browser; no automatic retry was attempted."
                            )
                    elif (
                        self._page.locator("#username").is_visible()
                        and self._page.locator("#password").is_visible()
                    ):
                        self._submit_login_form()
                        submitted = True
                else:
                    raise MySTVAuthenticationError(
                        "Unexpected login destination. Automatic login stopped."
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MySTVAuthenticationError(
                        "Login timed out. Check the browser for MFA or another prompt. "
                        "Use HEADLESS = False if manual interaction is needed."
                    )
                # Let Playwright process browser events while waiting for cookies.
                self._page.wait_for_timeout(
                    min(LOGIN_POLL_INTERVAL_MS, remaining * FACTOR_S_TO_MS)
                )
        except MySTVAPIError:
            raise
        except Exception:
            # Playwright's own diagnostics can include values passed to fill().
            raise MySTVAPIError(
                "Browser login failed. Check the browser and retry explicitly."
            ) from None

    def _submit_login_form(self) -> None:
        url = urlsplit(self._page.url)
        if f"{url.scheme}://{url.netloc}" != self._LOGIN_ORIGIN:
            raise MySTVAuthenticationError(
                "Refusing to fill credentials outside the MySTV login page."
            )
        email = self.creds.client_id
        password = self.creds.client_secret
        if not email or not password:
            raise MySTVAuthenticationError(
                "Unable to retrieve MySTV credentials. Check the OnePassword item and its fields."
            )
        try:
            self._page.locator("#username").fill(email)
            self._page.locator("#password").fill(password)
            self._page.locator("#kc-login").click()
            logging.info(
                "Submitted MySTV login; complete any additional browser prompts"
            )
        except Exception:
            raise MySTVAuthenticationError(
                "Could not submit the MySTV login form."
            ) from None
        finally:
            # Do not retain credentials as client attributes.
            email = password = None

    def _read_cookies(self, urls: List[str]) -> List[Dict[str, Any]]:
        self._ensure_open()
        if self._context is None:
            raise MySTVAPIError("Call login() before using the API.")
        try:
            return self._context.cookies(urls)
        except Exception:
            raise MySTVAPIError(
                "Could not read browser cookies. Check that the browser is open."
            ) from None

    def get_cookies(self) -> List[Dict[str, Any]]:
        """Return current API cookies with scope metadata. Do not log their values."""
        return self._read_cookies(
            [
                self._BASE_URL + self._MEMBERS_STREAM_PATH,
                self._BASE_URL + self._CLUB_ADDRESSES_PATH,
            ]
        )

    @staticmethod
    def _cookie_value(cookies: List[Dict[str, Any]], name: str) -> Optional[str]:
        # Playwright already filters by URL and expiry. Prefer the longest path
        # if multiple applicable cookies have the same name.
        matches = [cookie for cookie in cookies if cookie["name"] == name]
        if not matches:
            return None
        return max(matches, key=lambda cookie: len(cookie.get("path", "/")))["value"]

    def get_access_token(self) -> str:
        """Read the current browser access token. Reading it does not renew it."""
        cookies = self._read_cookies([self._BASE_URL + self._MEMBERS_STREAM_PATH])
        token = self._cookie_value(cookies, "kc_token")
        if not token:
            raise MySTVAuthenticationError(
                "No kc_token cookie. Complete login() first."
            )
        return token

    @contextmanager
    def _request(
        self, path: str, params: Dict[str, str], referer: str, stream: bool = False
    ):
        url = self._BASE_URL + path
        cookies = self._read_cookies([url])  # Fresh browser state before every request.
        token = self._cookie_value(cookies, "kc_token")
        if not token:
            raise MySTVAuthenticationError(
                "No kc_token cookie. Complete login() first."
            )
        headers = {
            "Accept": "text/event-stream" if stream else "application/json",
            "Authorization": f"Bearer {token}",
            "Referer": referer,
        }
        xsrf = self._cookie_value(cookies, "XSRF-TOKEN")
        if xsrf:
            headers["X-XSRF-TOKEN"] = unquote(xsrf)
        jar = requests.cookies.RequestsCookieJar()
        for cookie in cookies:
            expires = cookie.get("expires", -1)
            jar.set(
                cookie["name"],
                cookie["value"],
                domain=cookie["domain"],
                path=cookie.get("path", "/"),
                secure=cookie.get("secure", False),
                expires=int(expires) if expires >= 0 else None,
            )
        session = self._session
        session.cookies.clear()
        try:
            with session.get(
                url,
                params=params,
                headers=headers,
                cookies=jar,
                stream=stream,
                timeout=(10, 120) if stream else (10, 60),
                allow_redirects=False,
            ) as response:
                self._response = response
                if response.status_code == 401:
                    raise MySTVAuthenticationError(
                        "MySTV rejected authentication (HTTP 401). Call login() and retry."
                    )
                if 300 <= response.status_code < 400:
                    raise MySTVAPIError(
                        "MySTV redirected the API request. Check login(); API redirects are disabled."
                    )
                if not 200 <= response.status_code < 300:
                    print(f"message: {response.text}")
                    raise MySTVHTTPError(response.status_code)
                yield response
        except requests.RequestException:
            raise MySTVAPIError(
                "MySTV request failed or timed out. A stream may be incomplete; no retry was attempted."
            ) from None
        finally:
            self._response = None
            session.cookies.clear()

    @staticmethod
    def _sse_lines(chunks: Iterable[bytes]) -> Iterator[str]:
        """Handle UTF-8, an optional BOM, and CR/LF/CRLF across read boundaries."""
        decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
        pending = []
        skip_lf = False
        for chunk in chunks:
            for char in decoder.decode(chunk):
                if skip_lf:
                    skip_lf = False
                    if char == "\n":
                        continue
                if char in ("\r", "\n"):
                    yield "".join(pending)
                    pending = []
                    skip_lf = char == "\r"
                else:
                    pending.append(char)
        pending.extend(decoder.decode(b"", final=True))
        if pending:
            yield "".join(pending)

    @staticmethod
    def _sse_data(lines: Iterable[str]) -> Iterator[str]:
        data = []
        for line in lines:
            if line == "":
                if data:
                    yield "\n".join(data)
                data = []
                continue
            if line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "data":
                data.append(value)
        if data:
            raise MySTVAPIError("SSE stream ended with an incomplete event.")

    def iter_members_stream(self) -> Iterator[Any]:
        """Yield raw SSE payloads as JSON values or text, as in the notebook.

        Reads until EOF; no completion marker is guessed. A read timeout is an
        inactivity limit, not a total deadline. Errors are not treated as EOF.
        Use contextlib.closing() if you may stop consuming the iterator early.
        """
        with self._request(
            path=self._MEMBERS_STREAM_PATH,
            params={
                "clubId": self.club_id,
                "clubMembershipsOnly": "true",
                "activeMembersOnly": "false",
                "language": "de",
                "overwrite": "false",
            },
            referer=self._members_referer(),
            stream=True,
        ) as response:
            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if content_type != "text/event-stream":
                raise MySTVAPIError("Expected Content-Type text/event-stream.")
            # Avoid buffering short events behind a long-lived HTTP stream.
            lines = self._sse_lines(response.iter_content(chunk_size=1))
            for raw_data in self._sse_data(lines):
                try:
                    data = json.loads(raw_data)
                except ValueError:
                    data = raw_data
                yield data

    def close(self) -> None:
        """Close HTTP/browser resources. Safe to repeat; keeps the profile on disk."""
        session, context, playwright = self._session, self._context, self._playwright
        self._session = self._context = self._playwright = self._page = None
        try:
            try:
                if self._response is not None:
                    self._response.close()
                    self._response = None
            finally:
                if session is not None:
                    session.cookies.clear()
                    session.close()
        finally:
            try:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        logging.warning(
                            "Could not close the MySTV browser context cleanly"
                        )
            finally:
                if playwright is not None:
                    try:
                        playwright.stop()
                    except Exception:
                        logging.warning("Could not stop MySTV Playwright cleanly")

    def get_members_stream_raw(self) -> List[Any]:
        """Collect raw SSE payloads into a list; one payload need not be one member."""
        with closing(self.iter_members_stream()) as events:
            logging.info("Retrieved members raw")
            return list(events)

    def get_institute_members_raw(self) -> Any:
        """Return allAddressesInClub response.json() unchanged.
        The API returns a JSON object with a "data" key containing a list of members, each member contains a reference to a specific group. Members can appear multiple times if they belong to multiple groups.
        """
        referer_params = {"clubId": self.club_id}
        page = self._GROUPS_PAGE_PATH
        with self._request(
            path=self._CLUB_ADDRESSES_PATH,
            params={"clubNo": self.club_id},
            referer=f"{self._BASE_URL}{page}?{urlencode(referer_params)}",
        ) as response:
            try:
                logging.info("Retrieved institute members raw")
                return response.json()
            except ValueError:
                raise MySTVAPIError(
                    "MySTV addresses response was not valid JSON."
                ) from None

    def _load_mapper(self, filename: str) -> Dict[str, Any]:
        """Load a JSON file from the same directory as this source file."""
        path = Path(__file__).parent / filename
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            raise MySTVAPIError(f"Could not load mapper file {path}.") from None

    @cache
    def _members_cached(self) -> pd.DataFrame:
        """Return a DataFrame of all members in the club."""
        raw_members = self.get_members_stream_raw()
        if not (len(raw_members) == 2 and raw_members[1] == ""):
            raise MySTVAPIError("MySTV members stream did not return expected data.")
        members_df = pd.DataFrame(raw_members[0])
        return self._apply_member_data_enrichment(members_df)

    @property
    def members(self) -> pd.DataFrame:
        return copy.deepcopy(self._members_cached())

    @cache
    def _institutes_cached(self) -> dict[str, dict[str, list[str]]]:
        raw_groups = self.get_institute_members_raw()
        unique_institute_codes = {group["instituteCode"] for group in raw_groups}

        groups = {code: {} for code in unique_institute_codes}
        for group in raw_groups:
            institute_code = group["instituteCode"]
            function_code = group["instituteFunctionCode"]
            member_id = group["memberId"]
            if function_code not in groups[institute_code]:
                groups[institute_code][function_code] = []
            groups[institute_code][function_code].append(member_id)
        return groups

    @property
    def institutes(self) -> dict[str, dict[str, list[str]]]:
        return copy.deepcopy(self._institutes_cached())

    def _apply_member_data_enrichment(self, members_df: pd.DataFrame) -> pd.DataFrame:
        """Add any additional columns or transformations to the members DataFrame."""
        for method in [
            self._build_combined_emails_col,
            self._build_primary_email_col,
            self._build_internal_category_col,
            self._build_age_col,
            self._build_gets_newsletter_col,
        ]:
            members_df = method(members_df)
        return members_df

    def _build_combined_emails_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        email_columns = [
            MembersColumns.EMAIL_PRIVATE,
            MembersColumns.EMAIL_ALTERNATIVE,
            MembersColumns.EMAIL_VEREIN,
            MembersColumns.EMAIL_VERBAND,
        ]

        def combine_emails(row):
            emails = [
                row[col]
                for col in email_columns
                if pd.notnull(row[col]) and row[col].strip()
            ]
            return "; ".join(emails) if emails else None

        members_df[MembersColumns._COMBINED_EMAILS] = members_df.apply(
            combine_emails, axis=1
        )
        return members_df

    def _build_primary_email_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        email_columns = [
            MembersColumns.EMAIL_PRIVATE,
            MembersColumns.EMAIL_ALTERNATIVE,
            MembersColumns.EMAIL_VEREIN,
            MembersColumns.EMAIL_VERBAND,
        ]

        def get_primary_email(row):
            for col in email_columns:
                if pd.notnull(row[col]) and row[col].strip():
                    return row[col]
            return None

        members_df[MembersColumns._PRIMARY_EMAIL] = members_df.apply(
            get_primary_email, axis=1
        )
        return members_df

    def _build_internal_category_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        def get_internal_cat(row):
            membership_cat = row[MembersColumns.MEMBERSHIP_CATEGORIES]
            membership_addition = row[MembersColumns.MEMBERSHIP_ADDITIONS]
            category_tuple = (membership_cat, membership_addition)

            internal_cat = MAP_CATEGORY_TO_INTERNAL.get(category_tuple)
            if internal_cat:
                return internal_cat
            raise MySTVConfigurationError(
                f"Unable to map category tuple to internal category: {category_tuple}"
            )

        members_df[MembersColumns._INTERNAL_CATEGORY] = members_df.apply(
            get_internal_cat, axis=1
        )
        return members_df

    def _build_age_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        ts = pd.Timestamp.now()

        def get_age(row):
            birthday = pd.Timestamp(row[MembersColumns.BIRTHDAY])
            return calculate_age_at_ts(birthday=birthday, ts=ts)

        members_df[MembersColumns._AGE] = members_df.apply(get_age, axis=1)
        return members_df

    def _build_gets_newsletter_col(self, members_df: pd.DataFrame) -> pd.DataFrame:
        blacklist = pd.read_excel(
            WORKING_DIR_PATH + FILENAME_NEWSLETTER_BLACKLIST, header=0
        )
        emails_on_blacklist = blacklist["EMAIL"].values
        members_df[MembersColumns._GETS_NEWSLETTER] = ~members_df[
            MembersColumns._PRIMARY_EMAIL
        ].isin(emails_on_blacklist)
        return members_df

    @cached_property
    def mapper_institute_code_to_name(self) -> Dict[int, str]:
        mapper_institute_code_to_name = self._load_mapper(
            "mySTV_mapper_institute_code_to_name.json"
        )
        return {code: name for code, name in mapper_institute_code_to_name.items()}

    @cached_property
    def mapper_function_code_to_name(self) -> Dict[int, str]:
        mapper_function_code_to_name = self._load_mapper(
            "mySTV_mapper_function_code_to_name.json"
        )
        return {code: name for code, name in mapper_function_code_to_name.items()}

    def institute_id_to_name(self, institute_code: int) -> str:
        return self.mapper_institute_code_to_name.get(
            institute_code, f"Unknown Institute Code {institute_code}"
        )

    def function_id_to_name(self, function_code: int) -> str:
        return self.mapper_function_code_to_name.get(
            function_code, f"Unknown Function Code {function_code}"
        )

    def pretty_print_institutes(self, groups):
        for institute_code, functions in groups.items():
            institute_name = self.institute_id_to_name(institute_code)
            print(f"Institute: {institute_name} (Code: {institute_code})")
            for function_code, member_ids in functions.items():
                function_name = self.function_id_to_name(function_code)
                print(
                    f"  Function: {function_name} (Code: {function_code}): {len(member_ids)}"
                )

    def add_member_to_institute_with_function(
        self, member_id: str, institute_code: str, function_code: str
    ) -> dict:
        """Add an institute assignment and return response.json() unchanged."""
        if (
            not member_id
            or not (institute_code in self.mapper_institute_code_to_name)
            or not (function_code in self.mapper_function_code_to_name)
        ):
            raise ValueError(
                "member_id, institute_code and function_code are required."
            )

        url = self._BASE_URL + self._INSTITUTE_ADDRESS_CREATE_PATH
        cookies = self._read_cookies([url])
        token = self._cookie_value(cookies, "kc_token")
        if not token:
            raise MySTVAuthenticationError(
                "No kc_token cookie. Complete login() first."
            )

        referer_params = {"clubId": self.club_id, "code": institute_code}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Origin": self._BASE_URL,
            "Referer": (
                f"{self._BASE_URL}{self._GROUP_MEMBERS_PAGE_PATH}"
                f"?{urlencode(referer_params)}"
            ),
        }
        xsrf = self._cookie_value(cookies, "XSRF-TOKEN")
        if xsrf:
            headers["X-XSRF-TOKEN"] = unquote(xsrf)

        jar = requests.cookies.RequestsCookieJar()
        for cookie in cookies:
            expires = cookie.get("expires", -1)
            jar.set(
                cookie["name"],
                cookie["value"],
                domain=cookie["domain"],
                path=cookie.get("path", "/"),
                secure=cookie.get("secure", False),
                expires=int(expires) if expires >= 0 else None,
            )
        empty_date = "0001-01-01T00:00:00"
        payload = {
            "Entry_No": "23795",  # I don't know what this number means
            "@odata.etag": None,
            "Club_No": self.club_id,
            "Institute_Code": str(institute_code),
            "Contact_No": str(member_id),
            "Institute_Function_Code": str(function_code),
            "Start_date": empty_date,
            "End_Date": empty_date,
        }

        session = self._session
        session.cookies.clear()
        try:
            with session.post(
                url,
                json=payload,
                headers=headers,
                cookies=jar,
                timeout=(10, 60),
                allow_redirects=False,
            ) as response:
                self._response = response
                if response.status_code == 401:
                    raise MySTVAuthenticationError(
                        "MySTV rejected authentication (HTTP 401). "
                        "Call login() and retry."
                    )
                if 300 <= response.status_code < 400:
                    raise MySTVAPIError(
                        "MySTV redirected the API request. Check login(); "
                        "API redirects are disabled."
                    )
                if not 200 <= response.status_code < 300:
                    raise MySTVHTTPError(response.status_code)

                try:
                    result = response.json()
                except ValueError:
                    raise MySTVAPIError(
                        "MySTV returned success but the response was not valid JSON. "
                        "Check the institute assignment before retrying."
                    ) from None

                logging.info("Added member to institute with function")
                return result
        except requests.RequestException:
            raise MySTVAPIError(
                "MySTV request failed or timed out. The assignment may have been "
                "created; check the institute before retrying."
            ) from None
        finally:
            self._response = None
            session.cookies.clear()
            # Refresh even if the server applied the change but the response failed.
            self._institutes_cached.cache_clear()  # ToDo: optimize this? allow running this in bulk and only clearing once?
