import codecs
import json
import logging
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.parse import unquote, urlencode, urlsplit
from playwright.sync_api import sync_playwright

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import get_ident

import requests

from src.config.constants import OP_MYSTV_ITEM_UUID
from src.utils.credentials import CredentialsBase
from src.utils.utils import on_browser_thread

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

        # Enables compatibility with both jupyter notebooks and scripts (sync vs async)
        self._browser_worker = None
        self._browser_thread_id = None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self._browser_worker = ThreadPoolExecutor(max_workers=1)
            self._browser_thread_id = self._browser_worker.submit(get_ident).result()

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

    @on_browser_thread
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

    @on_browser_thread
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
        self,
        path: str,
        params: Dict[str, str],
        referer: str,
        stream: bool = False,
        method: str = "GET",
        json_body: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
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
        if extra_headers:
            headers.update(extra_headers)
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
            with session.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                cookies=jar,
                json=json_body,
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
                    raise MySTVHTTPError(response.status_code)
                yield response
        except requests.RequestException:
            if stream:
                message = (
                    "MySTV stream failed or timed out and may be incomplete; "
                    "no retry was attempted."
                )
            else:
                message = (
                    "MySTV request failed or timed out. The outcome may be "
                    "unknown; verify it before retrying."
                )
            raise MySTVAPIError(message) from None
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

    @on_browser_thread
    def _close_resources(self) -> None:
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

    def close(self) -> None:
        """Close client resources and stop the optional browser worker."""
        worker = self._browser_worker
        try:
            self._close_resources()
        finally:
            self._browser_worker = None
            if worker is not None:
                # Startup failure can call close() from inside the worker.
                worker.shutdown(wait=get_ident() != self._browser_thread_id)
            self._browser_thread_id = None

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


    def add_member_to_institute_with_function(
        self, member_id: str, institute_code: str, function_code: str
    ) -> dict:
        """Add an institute assignment and return response.json() unchanged."""
        if not member_id or not institute_code or not function_code:
            raise ValueError(
                "member_id, institute_code and function_code are required."
            )

        referer_params = {"clubId": self.club_id, "code": institute_code}
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
        with self._request(
            path=self._INSTITUTE_ADDRESS_CREATE_PATH,
            params={},
            referer=(
                f"{self._BASE_URL}{self._GROUP_MEMBERS_PAGE_PATH}"
                f"?{urlencode(referer_params)}"
            ),
            method="POST",
            json_body=payload,
            extra_headers={"Origin": self._BASE_URL},
        ) as response:
            try:
                result = response.json()
            except ValueError:
                raise MySTVAPIError(
                    "MySTV returned success but the response was not valid JSON. "
                    "Check the institute assignment before retrying."
                ) from None

            logging.info("Added member to institute with function")
            return result
