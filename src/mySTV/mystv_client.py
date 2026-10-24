import asyncio
import base64
import codecs
import hashlib
import json
import logging
import math
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing, contextmanager
from functools import wraps
from pathlib import Path
from threading import Event, Lock, get_ident
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit

import requests
from playwright.sync_api import sync_playwright

from src.config.constants import OP_MYSTV_ITEM_UUID
from src.utils.credentials import CredentialsBase

PROFILE_DIR = (Path(__file__).resolve().parents[2] / ".stv-browser").expanduser()
HEADLESS = True  # Set to False to support visible manual prompts.
LOGIN_TIMEOUT_S = 180
AUTHENTICATION_CALLER_ALLOWANCE_S = 30
AUTHENTICATION_BROWSER_OPERATION_TIMEOUT_S = (
    LOGIN_TIMEOUT_S + AUTHENTICATION_CALLER_ALLOWANCE_S
)
SHORT_BROWSER_OPERATION_TIMEOUT_S = 30
BROWSER_CLEANUP_WAIT_TIMEOUT_S = 30
NAVIGATION_TIMEOUT_MS = 30000
LOGIN_POLL_INTERVAL_MS = 250
ACTION_TIMEOUT_MS = 10_000
AUTH_RENEWAL_WAIT_S = 5
MEMBERS_STREAM_TIMEOUT_S = 300
HTTP_CONNECT_TIMEOUT_S = 10
HTTP_READ_TIMEOUT_S = 60
HTTP_STREAM_READ_TIMEOUT_S = 120
ACCESS_TOKEN_COOKIE_NAME = "kc_token"

FACTOR_S_TO_MS = 1000


def on_browser_thread(method=None, *, cleanup=False, timeout_s=None):
    """Run browser operations on the owning thread with bounded caller waiting."""
    if method is None:
        return lambda wrapped: on_browser_thread(
            wrapped, cleanup=cleanup, timeout_s=timeout_s
        )

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        worker = self._browser_worker
        if self._browser_unavailable and not cleanup:
            raise MySTVAPIError(
                "MySTV browser work is still running or cleanup is incomplete; "
                "this client cannot be reused."
            )
        if worker is None or get_ident() == self._browser_thread_id:
            return method(self, *args, **kwargs)

        def invoke():
            if self._browser_unavailable and not cleanup:
                raise MySTVAPIError(
                    "MySTV browser work is still running or cleanup is incomplete; "
                    "this client cannot be reused."
                )
            return method(self, *args, **kwargs)

        try:
            future = worker.submit(invoke)
        except BaseException:
            if cleanup:
                with self._browser_state_lock:
                    self._browser_cleanup_scheduled = False
                    self._browser_cleanup_failed = True
                    self._browser_unavailable = True
            raise
        try:
            wait_timeout = (
                timeout_s
                if timeout_s is not None
                else SHORT_BROWSER_OPERATION_TIMEOUT_S
            )
            return future.result(timeout=wait_timeout)
        except (TimeoutError, KeyboardInterrupt) as error:
            if future.done():
                if cleanup:
                    _finish_browser_cleanup(self, worker, future)
                raise
            self._browser_unavailable = True
            future.cancel()
            if cleanup:
                with self._browser_state_lock:
                    self._browser_cleanup_scheduled = True
                    self._browser_cleanup_failed = False
                future.add_done_callback(
                    lambda completed: _finish_browser_cleanup(
                        self, worker, completed
                    )
                )
            else:
                self._browser_cancel_requested.set()
                future.add_done_callback(
                    lambda _: _schedule_browser_cleanup(self, worker)
                )
            if isinstance(error, TimeoutError):
                raise TimeoutError(
                    "MySTV browser operation timed out. The client is unavailable "
                    "until its outstanding work and cleanup finish."
                ) from None
            raise
        except BaseException:
            if cleanup:
                with self._browser_state_lock:
                    self._browser_cleanup_scheduled = False
                    self._browser_cleanup_failed = True
                    self._browser_unavailable = True
            raise

    return wrapper


def _schedule_browser_cleanup(client, worker):
    """Queue cleanup after abandoned work, preserving Playwright thread ownership."""
    with client._browser_state_lock:
        if client._browser_cleanup_scheduled:
            return
        client._browser_cleanup_scheduled = True
        client._browser_cleanup_failed = False
    try:
        cleanup = worker.submit(client._close_resources)
    except RuntimeError:
        logging.exception("Could not schedule MySTV browser cleanup")
        with client._browser_state_lock:
            client._browser_cleanup_scheduled = False
            client._browser_cleanup_failed = True
        return
    cleanup.add_done_callback(
        lambda completed: _finish_browser_cleanup(client, worker, completed)
    )


def _finish_browser_cleanup(client, worker, future):
    try:
        future.result()
    except BaseException:
        logging.warning("MySTV browser cleanup did not complete")
        with client._browser_state_lock:
            client._browser_cleanup_scheduled = False
            client._browser_cleanup_failed = True
            client._browser_unavailable = True
        return
    client._finalize_browser_cleanup(worker)


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
    _MEMBER_PAGE_PATH = "/club/members/member"
    _GROUPS_PAGE_PATH = "/club/groups/"
    _GROUP_MEMBERS_PAGE_PATH = "/club/groups/group-members"

    # API endpoints
    _MEMBERS_STREAM_PATH = "/backend/api/club/list-members/stream"
    _CLUB_ADDRESSES_PATH = "/backend/api/institutes/allAddressesInClub"
    _INSTITUTE_ADDRESS_CREATE_PATH = "/backend/api/institutes/addresses/create"

    _MEMBERSHIP_PATH = "/backend/api/club/membership"

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
        self._rejected_token_fingerprint = None
        # Avoid ambient .netrc credentials replacing the Bearer token.
        # This also disables automatic environment proxy configuration.
        self._session.trust_env = False

        # Enables compatibility with both jupyter notebooks and scripts (sync vs async)
        self._browser_worker = None
        self._browser_thread_id = None
        self._browser_cleanup_scheduled = False
        self._browser_cleanup_failed = False
        self._browser_state_lock = Lock()
        self._browser_unavailable = False
        self._browser_cancel_requested = Event()
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
        if exc_type is not None:
            try:
                self.close()
            except BaseException:
                logging.warning(
                    "Could not fully close the MySTV client while preserving "
                    "the original operation error."
                )
            return
        self.close()

    def _ensure_open(self) -> None:
        if self._session is None:
            raise MySTVAPIError("This client is closed. Create a new MySTVClient.")

    def _members_referer(self) -> str:
        return (
            f"{self._BASE_URL}{self._MEMBERS_PAGE_PATH}?"
            f"{urlencode({'clubId': self.club_id})}"
        )

    @staticmethod
    def _has_origin(url: str, expected_url: str) -> bool:
        actual = urlsplit(url)
        expected = urlsplit(expected_url)
        return (actual.scheme, actual.netloc) == (expected.scheme, expected.netloc)

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
            try:
                self.close()
            except BaseException:
                logging.warning("Could not fully clean up failed MySTV browser startup.")
            if not isinstance(error, Exception):
                raise
            raise MySTVAPIError(
                "Could not start Chromium. Check its installation and ensure the "
                "profile is not open elsewhere. Error: " + str(error)
            ) from None

    @on_browser_thread(timeout_s=AUTHENTICATION_BROWSER_OPERATION_TIMEOUT_S)
    def login(self) -> None:
        """Reuse usable authentication or complete one bounded login workflow."""
        deadline = time.monotonic() + LOGIN_TIMEOUT_S
        try:
            self._ensure_usable_authentication(deadline)
        except MySTVAPIError:
            raise
        except Exception:
            raise MySTVAPIError(
                "Browser login failed. Check the browser and retry explicitly."
            ) from None

    def _ensure_usable_authentication(self, deadline: float) -> None:
        """Allow browser renewal, then perform at most one bounded login attempt."""
        self._open_browser()
        if time.monotonic() >= deadline:
            raise MySTVAuthenticationError("MySTV authentication workflow timed out.")
        if self._page is None or self._page.is_closed():
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()

        page_is_mystv = self._has_origin(self._page.url, self._BASE_URL)
        cookies = self._read_cookies([self._BASE_URL + self._MEMBERS_STREAM_PATH])
        token = self._cookie_value(cookies, ACCESS_TOKEN_COOKIE_NAME)
        if self._accept_authenticated_token(token):
            return

        if page_is_mystv:
            renewal_deadline = min(deadline, time.monotonic() + AUTH_RENEWAL_WAIT_S)
            while time.monotonic() < renewal_deadline:
                self._check_browser_cancellation()
                self._page.wait_for_timeout(
                    min(
                        LOGIN_POLL_INTERVAL_MS,
                        (renewal_deadline - time.monotonic()) * FACTOR_S_TO_MS,
                    )
                )
                cookies = self._read_cookies(
                    [self._BASE_URL + self._MEMBERS_STREAM_PATH]
                )
                token = self._cookie_value(cookies, ACCESS_TOKEN_COOKIE_NAME)
                if self._accept_authenticated_token(token):
                    return

        self._check_browser_cancellation()
        if self._has_origin(self._page.url, self._LOGIN_ORIGIN):
            self._wait_for_login_authentication(deadline)
            return
        self._page.goto(
            self._members_referer(),
            wait_until="domcontentloaded",
            timeout=self._workflow_timeout_ms(deadline, NAVIGATION_TIMEOUT_MS),
        )
        self._wait_for_login_authentication(deadline)

    def _check_browser_cancellation(self) -> None:
        if self._browser_cancel_requested.is_set():
            raise MySTVAPIError(
                "MySTV browser operation was interrupted and is being cleaned up."
            )

    @staticmethod
    def _workflow_timeout_ms(deadline: float, maximum_ms: int) -> int:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MySTVAuthenticationError(
                "MySTV authentication workflow timed out."
            )
        return max(1, min(maximum_ms, int(remaining * FACTOR_S_TO_MS)))

    def _wait_for_login_authentication(self, deadline: float) -> None:
        """Wait for a token or complete one credential submission under the deadline."""
        submitted = False
        while True:
            self._check_browser_cancellation()
            if time.monotonic() >= deadline:
                raise MySTVAuthenticationError(
                    "Login timed out. Check the browser for MFA or another prompt. "
                    "Use HEADLESS = False if manual interaction is needed."
                )
            if self._has_origin(self._page.url, self._BASE_URL):
                cookies = self._read_cookies(
                    [self._BASE_URL + self._MEMBERS_STREAM_PATH]
                )
                token = self._cookie_value(cookies, ACCESS_TOKEN_COOKIE_NAME)
                if self._accept_authenticated_token(token):
                    logging.info("MySTV authentication is available")
                    return
            elif self._has_origin(self._page.url, self._LOGIN_ORIGIN):
                if submitted:
                    if self._page.locator(
                        "#input-error, #kc-error-message"
                    ).first.is_visible():
                        raise MySTVAuthenticationError(
                            "MySTV reported a login error. Check the credentials and browser; "
                            "no automatic retry was attempted."
                        )
                elif (
                    self._page.locator("#username").is_visible()
                    and self._page.locator("#password").is_visible()
                ):
                    self._submit_login_form(deadline)
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
            self._page.wait_for_timeout(
                min(LOGIN_POLL_INTERVAL_MS, remaining * FACTOR_S_TO_MS)
            )

    @staticmethod
    def _token_fingerprint(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _token_is_usable(self, token: str | None) -> bool:
        if not token or self._access_token_has_expired(token):
            return False
        fingerprint = self._token_fingerprint(token)
        return fingerprint != self._rejected_token_fingerprint

    def _accept_authenticated_token(self, token: str | None) -> bool:
        if not self._token_is_usable(token):
            return False
        if self._rejected_token_fingerprint is not None:
            self._rejected_token_fingerprint = None
        return True

    def _submit_login_form(self, deadline: float) -> None:
        if not self._has_origin(self._page.url, self._LOGIN_ORIGIN):
            raise MySTVAuthenticationError(
                "Refusing to fill credentials outside the MySTV login page."
            )
        email, password = self.creds.get_client_credentials()
        if not email or not password:
            raise MySTVAuthenticationError(
                "Unable to retrieve MySTV credentials. Check the OnePassword item and its fields."
            )
        try:
            self._page.locator("#username").fill(
                email, timeout=self._workflow_timeout_ms(deadline, ACTION_TIMEOUT_MS)
            )
            self._page.locator("#password").fill(
                password, timeout=self._workflow_timeout_ms(deadline, ACTION_TIMEOUT_MS)
            )
            self._page.locator("#kc-login").click(
                timeout=self._workflow_timeout_ms(deadline, ACTION_TIMEOUT_MS)
            )
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
    def _read_cookies(self, urls: list[str]) -> list[dict[str, Any]]:
        self._ensure_open()
        if self._context is None:
            raise MySTVAPIError("Call login() before using the API.")
        try:
            return self._context.cookies(urls)
        except Exception:
            raise MySTVAPIError(
                "Could not read browser cookies. Check that the browser is open."
            ) from None

    def get_cookies(self) -> list[dict[str, Any]]:
        """Return current API cookies with scope metadata. Do not log their values."""
        return self._read_cookies(
            [
                self._BASE_URL + self._MEMBERS_STREAM_PATH,
                self._BASE_URL + self._CLUB_ADDRESSES_PATH,
            ]
        )

    @staticmethod
    def _cookie_value(cookies: list[dict[str, Any]], name: str) -> str | None:
        # Playwright already filters by URL and expiry. Prefer the longest path
        # if multiple applicable cookies have the same name.
        matches = [cookie for cookie in cookies if cookie["name"] == name]
        if not matches:
            return None
        return max(matches, key=lambda cookie: len(cookie.get("path", "/")))["value"]

    @staticmethod
    def _access_token_has_expired(token: str | None) -> bool:
        """Assess local expiry without treating decoding as authentication verification."""
        if not token:
            return True
        parts = token.split(".")
        if len(parts) != 3:
            return True
        payload = parts[1]
        if not payload:
            return True
        padded = payload + "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            claims = json.loads(decoded)
        except (OverflowError, TypeError, ValueError):
            return True
        if not isinstance(claims, dict):
            return True
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or isinstance(exp, bool):
            return True
        try:
            expiry = float(exp)
        except (OverflowError, TypeError, ValueError):
            return True
        return not math.isfinite(expiry) or expiry <= time.time()

    def get_access_token(self) -> str:
        """Read the current browser access token. Reading it does not renew it."""
        cookies = self._read_cookies([self._BASE_URL + self._MEMBERS_STREAM_PATH])
        token = self._cookie_value(cookies, ACCESS_TOKEN_COOKIE_NAME)
        if not self._accept_authenticated_token(token):
            raise MySTVAuthenticationError(
                f"MySTV {ACCESS_TOKEN_COOKIE_NAME} is missing, expired, or rejected. "
                "Complete login() first."
            )
        return token

    @on_browser_thread(timeout_s=AUTHENTICATION_BROWSER_OPERATION_TIMEOUT_S)
    def _request_cookies(self, url: str) -> list[dict[str, Any]]:
        """Recover browser authentication before returning one fresh cookie snapshot."""
        self._ensure_open()
        if self._context is None:
            raise MySTVAPIError("Call login() before using the API.")
        deadline = time.monotonic() + LOGIN_TIMEOUT_S
        self._ensure_usable_authentication(deadline)
        cookies = self._read_cookies([url])
        token = self._cookie_value(cookies, ACCESS_TOKEN_COOKIE_NAME)
        if not self._accept_authenticated_token(token):
            raise MySTVAuthenticationError(
                "MySTV authentication recovery did not produce a usable token."
            )
        return cookies

    @contextmanager
    def _request(
        self,
        path: str,
        params: dict[str, str],
        referer: str,
        stream: bool = False,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        files: dict[str, Any] | None = None,
    ):
        url = self._BASE_URL + path
        cookies = self._request_cookies(url)
        token = self._cookie_value(cookies, ACCESS_TOKEN_COOKIE_NAME)
        if not token:
            raise MySTVAuthenticationError(
                f"No usable {ACCESS_TOKEN_COOKIE_NAME} cookie."
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
                files=files,
                stream=stream,
                timeout=(
                    HTTP_CONNECT_TIMEOUT_S,
                    HTTP_STREAM_READ_TIMEOUT_S if stream else HTTP_READ_TIMEOUT_S,
                ),
                allow_redirects=False,
            ) as response:
                self._response = response
                if response.status_code == 401:
                    self._rejected_token_fingerprint = self._token_fingerprint(token)
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

    def _stream_chunks_before_deadline(
        self, response: Any, deadline: float
    ) -> Iterator[bytes]:
        """Check elapsed time between chunks; a blocked socket read cannot be preempted."""
        for chunk in response.iter_content(chunk_size=1):
            if time.monotonic() >= deadline:
                raise MySTVAPIError(
                    "MySTV members stream exceeded its total elapsed-time budget. "
                    "The result is incomplete."
                )
            yield chunk
        if time.monotonic() >= deadline:
            raise MySTVAPIError(
                "MySTV members stream exceeded its total elapsed-time budget. "
                "The result is incomplete."
            )

    def iter_members_stream(self) -> Iterator[Any]:
        """Yield raw SSE payloads; deadline checks cannot preempt a blocked socket read.

        The Requests read timeout remains an inactivity limit, not a total deadline.
        """
        deadline = time.monotonic() + MEMBERS_STREAM_TIMEOUT_S
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
            lines = self._sse_lines(self._stream_chunks_before_deadline(response, deadline))
            for raw_data in self._sse_data(lines):
                try:
                    data = json.loads(raw_data)
                except ValueError:
                    data = raw_data
                yield data

    @on_browser_thread(cleanup=True, timeout_s=BROWSER_CLEANUP_WAIT_TIMEOUT_S)
    def _close_resources(self) -> None:
        """Close HTTP/browser resources. Safe to repeat; keeps the profile on disk."""
        errors = []
        if self._response is not None:
            try:
                self._response.close()
            except Exception:
                errors.append("response")
            else:
                self._response = None
        if self._session is not None:
            session = self._session
            try:
                session.cookies.clear()
            except Exception:
                errors.append("HTTP session")
            try:
                session.close()
            except Exception:
                errors.append("HTTP session")
            else:
                self._session = None
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                errors.append("browser context")
            else:
                self._context = None
                self._page = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                errors.append("Playwright")
            else:
                self._playwright = None
        if errors:
            logging.warning("Could not release all MySTV resources: %s", ", ".join(errors))
            raise MySTVAPIError(
                "Could not release all MySTV resources; cleanup is incomplete."
            ) from None

    def close(self) -> None:
        """Close client resources and stop the optional browser worker."""
        worker = self._browser_worker
        cleanup_runs_inline = worker is None or get_ident() == self._browser_thread_id
        with self._browser_state_lock:
            if self._browser_cleanup_scheduled:
                raise MySTVAPIError("MySTV browser cleanup is still pending.")
            if (
                self._session is None
                and self._context is None
                and self._playwright is None
                and self._response is None
            ):
                worker = self._browser_worker
                already_closed = True
            else:
                already_closed = False
                if self._browser_unavailable and not self._browser_cleanup_failed:
                    raise MySTVAPIError(
                        "MySTV browser cleanup has not completed; retry is not yet safe."
                    )
                worker = self._browser_worker
                self._browser_cleanup_scheduled = True
                self._browser_cleanup_failed = False
        if already_closed:
            self._finalize_browser_cleanup(worker)
            return
        try:
            self._close_resources()
        except BaseException:
            if cleanup_runs_inline:
                with self._browser_state_lock:
                    self._browser_cleanup_scheduled = False
                    self._browser_cleanup_failed = True
                    self._browser_unavailable = True
            raise
        self._finalize_browser_cleanup(worker)

    def _finalize_browser_cleanup(self, worker=None) -> None:
        with self._browser_state_lock:
            self._browser_cleanup_scheduled = False
            self._browser_cleanup_failed = False
            self._browser_worker = None
            self._browser_thread_id = None
        if worker is not None:
            worker.shutdown(wait=False, cancel_futures=True)

    def get_members_stream_raw(self) -> list[Any]:
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

            if all(v is None for v in result.values()):
                raise MySTVAPIError(
                    "MySTV returned all None values. It seems like something went wrong."
                ) from None

            logging.info(
                f"Added member {member_id} to institute {institute_code} with function {function_code}"
            )
            return result

    def update_member_membership_unguarded(
        self,
        member_id: str,
        subscription_group: str,
        line_no: str,
        entry_date: str,
        type_of_disability: str = "",
    ) -> None:
        """Update one membership line. Successful responses have no body.
        Warning - this probably overwrite whatever is there, so make sure entry_date etc. are set correctly!"""
        if not member_id or not subscription_group or not line_no or not entry_date:
            raise ValueError(
                "member_id, subscription_group, line_no and entry_date are required."
            )

        referer_params = {"memberId": str(member_id), "clubId": self.club_id}
        payload = {
            "Subscription_Group": str(subscription_group),
            "mySTVSection": self.club_id,
            "Type_of_Disability": type_of_disability,
            "No": str(member_id),
            "Line_No": str(line_no),
            "Entry_date": entry_date,
        }
        files = {
            "data": (
                "blob",
                json.dumps(payload, separators=(",", ":")),
                "application/json",
            )
        }
        with self._request(
            path=self._MEMBERSHIP_PATH,
            params={},
            referer=(
                f"{self._BASE_URL}{self._MEMBER_PAGE_PATH}?{urlencode(referer_params)}"
            ),
            method="PUT",
            files=files,
            extra_headers={"Origin": self._BASE_URL},
        ):
            logging.info(
                f"Updated member {member_id} to subscription group {subscription_group}"
            )

    def get_member_memberships_raw(
        self, member_id: str, hide_former_memberships: bool = True
    ) -> list[dict[str, Any]]:
        """Return the member's membership list unchanged."""
        if not member_id:
            raise ValueError("member_id is required.")

        referer_params = {"memberId": str(member_id), "clubId": self.club_id}
        with self._request(
            path=self._MEMBERSHIP_PATH,
            params={
                **referer_params,
                "hideFormerMemberships": str(hide_former_memberships).lower(),
            },
            referer=(
                f"{self._BASE_URL}{self._MEMBER_PAGE_PATH}?{urlencode(referer_params)}"
            ),
        ) as response:
            try:
                result = response.json()
            except ValueError:
                raise MySTVAPIError(
                    "MySTV memberships response was not valid JSON."
                ) from None

            logging.info(f"Retrieved memberships for member {member_id}")
            return result
