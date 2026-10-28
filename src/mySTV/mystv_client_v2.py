import codecs
import json
import logging
import math
import re
import secrets
import time
from collections.abc import Generator, Iterable, Iterator
from contextlib import closing, contextmanager
from html.parser import HTMLParser
from http.cookiejar import Cookie
from types import TracebackType
from typing import (
    Any,
    Literal,
    Self,
    cast,
)
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from authlib.integrations.requests_client import OAuth2Session
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.jwk import KeySet, KeySetSerialization
from joserfc.jws import JWSRegistry

from src.config.constants import OP_MYSTV_ITEM_UUID
from src.utils.credentials import CredentialsBase

logger = logging.getLogger(__name__)

HTTP_CONNECT_TIMEOUT_S = 10
HTTP_READ_TIMEOUT_S = 60
HTTP_STREAM_READ_TIMEOUT_S = 120
REFRESH_START_READ_TIMEOUT_S = 2
MEMBERS_STREAM_TIMEOUT_S = 300
TOKEN_REFRESH_MARGIN_S = 30
OIDC_CLOCK_SKEW_S = 60
MAX_AUTH_REDIRECTS = 5

ACCESS_TOKEN_COOKIE_NAME = "kc_token"
REFRESH_TOKEN_COOKIE_NAME = "kc_refresh_token"
ID_TOKEN_COOKIE_NAME = "kc_id_token"


class MySTVAPIError(RuntimeError):
    """An API failure; messages omit credentials and response bodies."""


class MySTVAuthenticationError(MySTVAPIError):
    """Authentication is missing, expired, or rejected."""


class MySTVReadTimeoutError(MySTVAPIError):
    """The HTTP response did not arrive within the read timeout."""


class MySTVHTTPError(MySTVAPIError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"MySTV API returned HTTP {status_code}.")


class _LoginScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self._script_parts: list[str] = []
        self._in_inline_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        self._script_parts = []
        self._in_inline_script = not any(name.lower() == "src" for name, _ in attrs)

    def handle_data(self, data: str) -> None:
        if self._in_inline_script:
            self._script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_inline_script:
            self.scripts.append("".join(self._script_parts))
            self._script_parts = []
            self._in_inline_script = False


class MySTVClientV2:
    _BASE_URL = "https://my.stv-fsg.ch"
    _LOGIN_ORIGIN = "https://login.stv-fsg.ch"
    _ISSUER_PATH = "/realms/Stv"
    _AUTHORIZATION_PATH = "/realms/Stv/protocol/openid-connect/auth"
    _TOKEN_PATH = "/realms/Stv/protocol/openid-connect/token"
    _JWKS_PATH = "/realms/Stv/protocol/openid-connect/certs"
    _LOGIN_ACTION_PATH = "/realms/Stv/login-actions/authenticate"
    _SET_TOKENS_PATH = "/backend/api/auth/set-tokens"
    _CLIENT_ID = "mystv"
    _REDIRECT_URI = _BASE_URL + "/"

    _MEMBERS_PAGE_PATH = "/club/members"
    _MEMBER_PAGE_PATH = "/club/members/member"
    _GROUPS_PAGE_PATH = "/club/groups/"
    _GROUP_MEMBERS_PAGE_PATH = "/club/groups/group-members"

    _MEMBERS_STREAM_PATH = "/backend/api/club/list-members/stream"
    _MEMBERS_STREAM_STATUS_PATH = _MEMBERS_STREAM_PATH + "/status"
    _CLUB_ADDRESSES_PATH = "/backend/api/institutes/allAddressesInClub"
    _INSTITUTE_ADDRESS_CREATE_PATH = "/backend/api/institutes/addresses/create"
    _MEMBERSHIP_PATH = "/backend/api/club/membership"

    def __init__(self, club_id: str):
        if not club_id:
            raise ValueError("club_id is required.")
        self.club_id = club_id
        self.creds = CredentialsBase(item_uuid=OP_MYSTV_ITEM_UUID)

        self._oauth: OAuth2Session | None = OAuth2Session(
            client_id=self._CLIENT_ID,
            token_endpoint_auth_method="none",
            redirect_uri=self._REDIRECT_URI,
            code_challenge_method="S256",
            scope="openid",
            leeway=0,
        )
        self._oauth.trust_env = False
        self._session: requests.Session | None = requests.Session()
        self._session.trust_env = False
        self._response: requests.Response | None = None
        self._nonce: str | None = None
        self._subject: str | None = None

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc_value, traceback
        if exc_type is not None:
            try:
                self.close()
            except BaseException:  # noqa: BLE001
                # Preserve the original operation error if secondary cleanup fails.
                logger.warning(
                    "Could not fully close the MySTV client while preserving "
                    "the original operation error."
                )
            return False
        self.close()
        return False

    def _ensure_open(self) -> None:
        if self._session is None or self._oauth is None:
            raise MySTVAPIError("This client is closed. Create a new MySTVClientV2.")

    @property
    def _oauth_session(self) -> OAuth2Session:
        oauth = self._oauth
        if oauth is None:
            raise MySTVAPIError("This client is closed. Create a new MySTVClientV2.")
        return oauth

    @property
    def _api_session(self) -> requests.Session:
        session = self._session
        if session is None:
            raise MySTVAPIError("This client is closed. Create a new MySTVClientV2.")
        return session

    def _ensure_no_active_response(self) -> None:
        if self._response is not None:
            raise MySTVAPIError(
                "Finish or close the active MySTV response before starting another operation."
            )

    def _members_referer(self) -> str:
        return (
            f"{self._BASE_URL}{self._MEMBERS_PAGE_PATH}?"
            f"{urlencode({'clubId': self.club_id})}"
        )

    @staticmethod
    def _validated_https_url(url: str, expected_origin: str) -> bool:
        try:
            actual = urlsplit(url)
            expected = urlsplit(expected_origin)
            actual_port = actual.port
            expected_port = expected.port
        except ValueError:
            return False
        actual_host = actual.hostname
        expected_host = expected.hostname
        return (
            actual.scheme == "https"
            and actual_host is not None
            and expected_host is not None
            and actual_host.lower() == expected_host.lower()
            and actual_port in (None, 443)
            and expected_port in (None, 443)
            and actual.username is None
            and actual.password is None
        )

    @staticmethod
    def _request_timeout(read_timeout: int = HTTP_READ_TIMEOUT_S) -> tuple[int, int]:
        return HTTP_CONNECT_TIMEOUT_S, read_timeout

    def _clear_authentication(self) -> None:
        if self._oauth is not None:
            self._oauth.token = {}
            self._oauth.cookies.clear()
        if self._session is not None:
            self._session.cookies.clear()
        self._nonce = None
        self._subject = None

    def login(self) -> None:
        """Complete one fresh password and authorization-code login."""
        self._ensure_open()
        self._ensure_no_active_response()
        self._clear_authentication()
        oauth = self._oauth_session
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)

        try:
            self._nonce = nonce
            authorization_url, returned_state = oauth.create_authorization_url(
                self._LOGIN_ORIGIN + self._AUTHORIZATION_PATH,
                state=state,
                code_verifier=verifier,
                redirect_uri=self._REDIRECT_URI,
                response_type="code",
                response_mode="fragment",
                scope="openid",
                nonce=nonce,
                ui_locales="de",
            )
            if returned_state != state:
                raise MySTVAuthenticationError(
                    "Could not initialize the MySTV authorization request."
                )

            page_html, login_page_url = self._get_login_page(authorization_url)
            action, credential_id = self._read_password_login_context(page_html)

            username: str | None = None
            password: str | None = None
            try:
                username, password = self.creds.get_client_credentials()
            except Exception:  # noqa: BLE001
                # Do not expose credential-provider details in UI errors or tracebacks.
                raise MySTVAuthenticationError(
                    "Unable to retrieve MySTV credentials. Check the configured credential item."
                ) from None
            try:
                if not username:
                    raise MySTVAuthenticationError("The MySTV username is missing.")
                if not password:
                    raise MySTVAuthenticationError("The MySTV password is missing.")
                with oauth.request(
                    "POST",
                    action,
                    data={
                        "username": username,
                        "password": password,
                        "credentialId": credential_id,
                    },
                    headers={
                        "Origin": self._LOGIN_ORIGIN,
                        "Referer": login_page_url,
                    },
                    timeout=self._request_timeout(),
                    allow_redirects=False,
                    withhold_token=True,
                ) as response:
                    if response.status_code not in (302, 303):
                        raise MySTVAuthenticationError(
                            "MySTV did not accept the supported password-login flow."
                        )
                    location = response.headers.get("Location")
            except requests.RequestException:
                raise MySTVAuthenticationError(
                    "The MySTV credential submission failed or timed out."
                ) from None
            finally:
                username = None
                password = None

            authorization_response = self._validate_authorization_response(
                location or "", state
            )
            try:
                oauth.fetch_token(
                    self._LOGIN_ORIGIN + self._TOKEN_PATH,
                    authorization_response=authorization_response,
                    state=state,
                    code_verifier=verifier,
                    redirect_uri=self._REDIRECT_URI,
                    timeout=self._request_timeout(),
                    allow_redirects=False,
                )
            except Exception:  # noqa: BLE001
                # Do not expose token-endpoint details in UI errors or tracebacks.
                raise MySTVAuthenticationError(
                    "MySTV authorization-code exchange failed."
                ) from None

            self._validate_token_response()
            self._synchronize_token_cookies()
        except BaseException as error:
            self._clear_authentication()
            if isinstance(error, Exception) and not isinstance(error, MySTVAPIError):
                raise MySTVAuthenticationError(
                    "MySTV login failed. Check credentials and the supported login flow."
                ) from None
            raise

    def _get_login_page(self, authorization_url: str) -> tuple[str, str]:
        current_url = authorization_url
        oauth = self._oauth_session
        for redirect_count in range(MAX_AUTH_REDIRECTS + 1):
            if not self._validated_https_url(current_url, self._LOGIN_ORIGIN):
                raise MySTVAuthenticationError(
                    "MySTV authorization redirected outside the configured identity provider."
                )
            try:
                with oauth.request(
                    "GET",
                    current_url,
                    timeout=self._request_timeout(),
                    allow_redirects=False,
                    withhold_token=True,
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if redirect_count == MAX_AUTH_REDIRECTS:
                            raise MySTVAuthenticationError(
                                "MySTV authorization exceeded the redirect limit."
                            )
                        location = response.headers.get("Location")
                        if not location:
                            raise MySTVAuthenticationError(
                                "MySTV authorization returned an invalid redirect."
                            )
                        current_url = urljoin(current_url, location)
                        continue
                    if not 200 <= response.status_code < 300:
                        raise MySTVHTTPError(response.status_code)
                    return response.text, response.url
            except requests.RequestException:
                raise MySTVAuthenticationError(
                    "Could not retrieve the MySTV password-login page."
                ) from None
        raise MySTVAuthenticationError(
            "Could not retrieve the MySTV password-login page."
        )

    def _read_password_login_context(self, html: str) -> tuple[str, str]:
        parser = _LoginScriptParser()
        parser.feed(html)
        parser.close()
        scripts = [script for script in parser.scripts if "kcContext" in script]
        if len(scripts) != 1:
            raise MySTVAuthenticationError(
                "The MySTV login page changed or does not expose the supported password flow."
            )
        bootstrap = scripts[0]

        def read_string(name: str) -> str:
            pattern = rf'"{re.escape(name)}"\s*:\s*("(?:\\.|[^"\\])*")'
            matches = re.findall(pattern, bootstrap)
            if len(matches) != 1:
                raise MySTVAuthenticationError(
                    "The MySTV login page changed or has ambiguous login context."
                )
            try:
                value = json.loads(matches[0])
            except ValueError:
                raise MySTVAuthenticationError(
                    "The MySTV login page contains malformed login context."
                ) from None
            if not isinstance(value, str) or not value:
                raise MySTVAuthenticationError(
                    "The MySTV login page contains unsupported login context."
                )
            return value

        page_id = read_string("pageId")
        if page_id not in ("login", "login.ftl"):
            raise MySTVAuthenticationError(
                "MySTV requires an unsupported authentication step."
            )
        action = read_string("loginAction")
        parsed_action = urlsplit(action)
        if (
            not self._validated_https_url(action, self._LOGIN_ORIGIN)
            or parsed_action.path != self._LOGIN_ACTION_PATH
            or parsed_action.fragment
            or not parsed_action.query
        ):
            raise MySTVAuthenticationError(
                "The MySTV login page supplied an unsafe authentication action."
            )

        credential_matches = re.findall(
            r'"selectedCredential"\s*:\s*(("(?:\\.|[^"\\])*")|null)',
            bootstrap,
        )
        if len(credential_matches) > 1:
            raise MySTVAuthenticationError(
                "The MySTV login page has ambiguous selected-credential context."
            )
        credential_id = ""
        if credential_matches:
            encoded_value = credential_matches[0][0]
            if encoded_value != "null":
                try:
                    credential_id = json.loads(encoded_value)
                except ValueError:
                    raise MySTVAuthenticationError(
                        "The MySTV login page contains malformed credential context."
                    ) from None
                if not isinstance(credential_id, str):
                    raise MySTVAuthenticationError(
                        "The MySTV login page contains unsupported credential context."
                    )
        return action, credential_id

    def _validate_authorization_response(self, location: str, state: str) -> str:
        if not self._validated_https_url(location, self._BASE_URL):
            raise MySTVAuthenticationError(
                "MySTV returned an invalid authorization callback."
            )
        callback = urlsplit(location)
        if callback.path != "/" or callback.query or callback.fragment == "":
            raise MySTVAuthenticationError(
                "MySTV returned an invalid authorization callback."
            )

        parameters = parse_qsl(callback.fragment, keep_blank_values=True)
        names = [name for name, _ in parameters]
        if len(names) != len(set(names)):
            raise MySTVAuthenticationError(
                "MySTV returned duplicate authorization response parameters."
            )
        values = dict(parameters)
        if "error" in values or "error_description" in values:
            raise MySTVAuthenticationError("MySTV rejected the authorization request.")
        if (
            values.get("state") != state
            or not values.get("code")
            or values.get("iss") != self._LOGIN_ORIGIN + self._ISSUER_PATH
        ):
            raise MySTVAuthenticationError(
                "MySTV returned an invalid authorization response."
            )
        return urlunsplit(
            (
                callback.scheme,
                callback.netloc,
                callback.path,
                urlencode(parameters),
                "",
            )
        )

    def _validate_token_response(self, is_refresh: bool = False) -> None:
        token = self._oauth_session.token
        if not isinstance(self._nonce, str) or not self._nonce:
            raise MySTVAuthenticationError(
                "MySTV authentication is missing its login nonce."
            )
        if not isinstance(token, dict):
            raise MySTVAuthenticationError("MySTV returned an invalid token response.")
        for name in ("refresh_token", "id_token"):
            if not isinstance(token.get(name), str) or not token[name]:
                raise MySTVAuthenticationError(
                    "MySTV returned an incomplete token response."
                )
        if (
            not isinstance(token.get("token_type"), str)
            or token["token_type"].lower() != "bearer"
        ):
            raise MySTVAuthenticationError("MySTV returned an unsupported token type.")

        expires_in = token.get("expires_in")
        _, expires_at = self._access_token_state(token)
        if (
            not isinstance(expires_in, (int, float))
            or isinstance(expires_in, bool)
            or not math.isfinite(expires_in)
            or expires_in <= 0
            or expires_at <= time.time()
        ):
            raise MySTVAuthenticationError(
                "MySTV returned unusable access-token expiry metadata."
            )

        try:
            with self._oauth_session.request(
                "GET",
                self._LOGIN_ORIGIN + self._JWKS_PATH,
                headers={"Accept": "application/json"},
                timeout=self._request_timeout(),
                allow_redirects=False,
                withhold_token=True,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise MySTVAuthenticationError(
                        "Could not retrieve MySTV signing keys."
                    )
                key_data = response.json()
        except requests.RequestException:
            raise MySTVAuthenticationError(
                "Could not retrieve MySTV signing keys."
            ) from None
        except ValueError:
            raise MySTVAuthenticationError(
                "MySTV returned invalid signing keys."
            ) from None

        if not isinstance(key_data, dict) or not isinstance(key_data.get("keys"), list):
            raise MySTVAuthenticationError("MySTV returned invalid signing keys.")
        try:
            key_set = KeySet.import_key_set(cast(KeySetSerialization, key_data))
            decoded = jwt.decode(
                token["id_token"],
                key=key_set,
                registry=JWSRegistry(
                    algorithms=["RS256"],
                    strict_check_header=False,
                ),
            )
            claims_params = {
                "client_id": self._CLIENT_ID,
                "access_token": token["access_token"],
            }
            if not is_refresh or "nonce" in decoded.claims:
                claims_params["nonce"] = self._nonce
            claims = CodeIDToken(
                decoded.claims,
                decoded.header,
                {
                    "iss": {
                        "essential": True,
                        "value": self._LOGIN_ORIGIN + self._ISSUER_PATH,
                    },
                    "aud": {
                        "essential": True,
                        "values": [self._CLIENT_ID],
                    },
                },
                claims_params,
            )
            claims.validate(leeway=OIDC_CLOCK_SKEW_S)
        except MySTVAPIError:
            raise
        except Exception:  # noqa: BLE001
            # Convert JWT/key/claim failures to a sanitized authentication error.
            raise MySTVAuthenticationError(
                "MySTV returned an invalid or unverifiable ID token."
            ) from None

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise MySTVAuthenticationError(
                "MySTV returned an invalid ID-token subject."
            )
        if is_refresh:
            if self._subject is None or subject != self._subject:
                raise MySTVAuthenticationError(
                    "MySTV refresh changed the authenticated identity."
                )
        else:
            self._subject = subject

    def _synchronize_token_cookies(self) -> None:
        token = self._oauth_session.token
        _, expires_at = self._access_token_state(token)
        cookie_values = (
            (REFRESH_TOKEN_COOKIE_NAME, "refresh_token", True),
            (ACCESS_TOKEN_COOKIE_NAME, "access_token", False),
            (ID_TOKEN_COOKIE_NAME, "id_token", False),
        )
        for cookie_name, token_name, expires_with_access in cookie_values:
            if expires_at <= time.time():
                raise MySTVAuthenticationError(
                    "The MySTV access token expired during cookie synchronization."
                )
            expires = -1
            if expires_with_access:
                remaining = expires_at - time.time()
                if remaining <= 0:
                    raise MySTVAuthenticationError(
                        "The MySTV access token expired during cookie synchronization."
                    )
                expires = max(1, int(remaining))
            url = self._BASE_URL + self._SET_TOKENS_PATH
            headers = {
                "Accept": "application/json",
                "Origin": self._BASE_URL,
                "Referer": self._BASE_URL + "/",
            }
            headers.update(self._xsrf_headers(url))
            with self._api_session.post(
                url,
                headers=headers,
                json={
                    "name": cookie_name,
                    "value": token[token_name],
                    "expiry": expires,
                },
                timeout=self._request_timeout(),
                allow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise MySTVAuthenticationError(
                        "MySTV redirected a token-cookie synchronization request."
                    )
                if not 200 <= response.status_code < 300:
                    raise MySTVAuthenticationError(
                        "MySTV rejected token-cookie synchronization."
                    )

        if expires_at <= time.time():
            raise MySTVAuthenticationError(
                "The MySTV access token expired during cookie synchronization."
            )
        for cookie_name, token_name, _ in cookie_values:
            matches = [
                cookie.value
                for cookie in self._applicable_cookies(
                    self._BASE_URL + self._MEMBERS_STREAM_PATH
                )
                if cookie.name == cookie_name
            ]
            if matches != [token[token_name]]:
                raise MySTVAuthenticationError(
                    "MySTV token cookies do not match the validated token set."
                )

    def _ensure_usable_authentication(self) -> None:
        self._ensure_open()
        token = self._oauth_session.token
        _, expires_at = self._access_token_state(token)
        refresh_token = token.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise MySTVAuthenticationError("Call login() before using the MySTV API.")
        if expires_at - time.time() > TOKEN_REFRESH_MARGIN_S:
            return

        try:
            self._oauth_session.refresh_token(
                self._LOGIN_ORIGIN + self._TOKEN_PATH,
                refresh_token=refresh_token,
                timeout=self._request_timeout(),
                allow_redirects=False,
            )
            self._validate_token_response(is_refresh=True)
            self._synchronize_token_cookies()
        except BaseException as error:
            self._clear_authentication()
            if isinstance(error, Exception) and not isinstance(error, MySTVAPIError):
                raise MySTVAuthenticationError(
                    "MySTV token refresh failed. Call login() before retrying."
                ) from None
            raise

    def _applicable_cookies(self, url: str) -> list[Cookie]:
        self._ensure_open()
        probe = requests.Session()
        probe.trust_env = False
        applicable: list[Cookie] = []
        try:
            for cookie in self._api_session.cookies:
                probe.cookies.clear()
                probe.cookies.set_cookie(cookie)
                prepared = probe.prepare_request(requests.Request("GET", url))
                if prepared.headers.get("Cookie"):
                    applicable.append(cookie)
        finally:
            probe.close()
        return applicable

    def _xsrf_headers(self, url: str) -> dict[str, str]:
        matches = [
            cookie.value
            for cookie in self._applicable_cookies(url)
            if cookie.name == "XSRF-TOKEN" and isinstance(cookie.value, str)
        ]
        if len(matches) > 1:
            raise MySTVAPIError("MySTV returned ambiguous XSRF cookies.")
        if not matches:
            return {}
        return {"X-XSRF-TOKEN": unquote(matches[0])}

    def get_cookies(self) -> list[dict[str, Any]]:
        """Return applicable application cookies with available scope metadata."""
        self._ensure_open()
        cookies: list[dict[str, Any]] = []
        seen = set()
        for path in (
            self._MEMBERS_STREAM_PATH,
            self._CLUB_ADDRESSES_PATH,
            self._MEMBERSHIP_PATH,
        ):
            for cookie in self._applicable_cookies(self._BASE_URL + path):
                key = (cookie.name, cookie.value, cookie.domain, cookie.path)
                if key in seen:
                    continue
                seen.add(key)
                cookies.append(
                    {
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": cookie.domain,
                        "path": cookie.path,
                        "expires": cookie.expires if cookie.expires is not None else -1,
                        "httpOnly": cookie.has_nonstandard_attr("HttpOnly"),
                        "secure": cookie.secure,
                        "sameSite": cookie.get_nonstandard_attr("SameSite"),
                    }
                )
        return cookies

    def get_access_token(self) -> str:
        """Return the current access token without refreshing or making a request."""
        self._ensure_open()
        access_token, expires_at = self._access_token_state(self._oauth_session.token)
        if expires_at <= time.time():
            raise MySTVAuthenticationError(
                "MySTV access token is missing or expired. Complete login() first."
            )
        return access_token

    @staticmethod
    def _access_token_state(token: Any) -> tuple[str, float]:
        if not isinstance(token, dict):
            raise MySTVAuthenticationError(
                "MySTV authentication is missing or invalid."
            )
        access_token = token.get("access_token")
        expires_at = token.get("expires_at")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(expires_at, (int, float))
            or isinstance(expires_at, bool)
            or not math.isfinite(expires_at)
        ):
            raise MySTVAuthenticationError(
                "MySTV authentication is missing or invalid."
            )
        return access_token, float(expires_at)

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
        read_timeout: int | None = None,
    ) -> Generator[requests.Response]:
        self._ensure_open()
        self._ensure_no_active_response()
        self._ensure_usable_authentication()
        url = self._BASE_URL + path
        token, _ = self._access_token_state(self._oauth_session.token)
        headers = {
            "Accept": "text/event-stream" if stream else "application/json",
            "Authorization": f"Bearer {token}",
            "Referer": referer,
        }
        if extra_headers:
            headers.update(extra_headers)
        headers.update(self._xsrf_headers(url))
        if read_timeout is None:
            read_timeout = HTTP_STREAM_READ_TIMEOUT_S if stream else HTTP_READ_TIMEOUT_S
        response: requests.Response | None = None
        try:
            response = self._api_session.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                json=json_body,
                files=files,
                stream=stream,
                timeout=self._request_timeout(read_timeout),
                allow_redirects=False,
            )
            self._response = response
            if response.status_code == 401:
                self._clear_authentication()
                raise MySTVAuthenticationError(
                    "MySTV rejected authentication (HTTP 401). Call login() before retrying."
                )
            if 300 <= response.status_code < 400:
                raise MySTVAPIError(
                    "MySTV redirected the API request. API redirects are disabled."
                )
            if not 200 <= response.status_code < 300:
                raise MySTVHTTPError(response.status_code)
            yield response
        except requests.RequestException as error:
            if stream:
                message = (
                    "MySTV stream failed or timed out and may be incomplete; "
                    "no retry was attempted."
                )
            else:
                message = (
                    "MySTV request failed or timed out. The outcome may be unknown; "
                    "verify it before retrying."
                )
            if isinstance(error, requests.ReadTimeout):
                raise MySTVReadTimeoutError(message) from None
            raise MySTVAPIError(message) from None
        finally:
            if response is not None:
                try:
                    response.close()
                finally:
                    self._response = None

    @staticmethod
    def _sse_lines(chunks: Iterable[bytes]) -> Iterator[str]:
        """Handle UTF-8, an optional BOM, and CR/LF/CRLF across read boundaries."""
        decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
        pending: list[str] = []
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
        data: list[str] = []
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
        self, response: requests.Response, deadline: float
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

    def _members_stream_params(self, *, overwrite: bool = False) -> dict[str, str]:
        return {
            "clubId": self.club_id,
            "clubMembershipsOnly": "true",
            "activeMembersOnly": "false",
            "language": "de",
            "overwrite": str(overwrite).lower(),
        }

    @staticmethod
    def _validate_members_stream_response(response: requests.Response) -> None:
        content_type = (
            response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type != "text/event-stream":
            raise MySTVAPIError("Expected Content-Type text/event-stream.")

    def is_members_refresh_running(self) -> bool:
        """Return the server's running flag; it does not report success or freshness."""
        logger.info("Retrieving MySTV refresh status")
        with self._request(
            path=self._MEMBERS_STREAM_STATUS_PATH,
            params={"clubId": self.club_id},
            referer=self._members_referer(),
        ) as response:
            try:
                running = response.json()
            except ValueError:
                raise MySTVAPIError(
                    "MySTV refresh status was not valid JSON."
                ) from None
        if not isinstance(running, bool):
            raise MySTVAPIError("MySTV refresh status was not a JSON boolean.")
        logger.info("Retrieved MySTV refresh status: running=%s", running)
        return running

    def start_members_refresh(self) -> None:
        """Start at most one refresh and confirm running status without reading SSE.

        Return once a running refresh is observed, including an existing one.
        The server exposes no job identifier or completion guarantee. A failed
        confirmation leaves the outcome unknown; never retry the trigger here.
        """
        if self.is_members_refresh_running():
            logger.info("MySTV refresh already running; no additional refresh started")
            return
        logger.info("Starting MySTV members refresh")
        try:
            with self._request(
                path=self._MEMBERS_STREAM_PATH,
                params=self._members_stream_params(overwrite=True),
                referer=self._members_referer(),
                stream=True,
                read_timeout=REFRESH_START_READ_TIMEOUT_S,
            ) as response:
                self._validate_members_stream_response(response)
                # Leaving the context closes the stream without consuming its body.
        except MySTVReadTimeoutError:
            # Status can become active before headers arrive. Requests closes the
            # timed-out connection; only the separate status check confirms a start.
            logger.info("MySTV refresh response timed out; checking server status")
        else:
            logger.info("MySTV refresh connection closed without reading SSE data")
        if not self.is_members_refresh_running():
            raise MySTVAPIError(
                "MySTV refresh start could not be confirmed. Check status before "
                "trying again; the trigger was not retried."
            )
        logger.info("MySTV members refresh confirmed running")

    def iter_members_stream(self) -> Generator[Any]:
        """Yield raw SSE payloads; deadline checks cannot preempt a blocked socket read.

        The Requests read timeout remains an inactivity limit, not a total deadline.
        """
        deadline = time.monotonic() + MEMBERS_STREAM_TIMEOUT_S
        with self._request(
            path=self._MEMBERS_STREAM_PATH,
            params=self._members_stream_params(),
            referer=self._members_referer(),
            stream=True,
        ) as response:
            self._validate_members_stream_response(response)
            lines = self._sse_lines(
                self._stream_chunks_before_deadline(response, deadline)
            )
            for raw_data in self._sse_data(lines):
                try:
                    data = json.loads(raw_data)
                except ValueError:
                    data = raw_data
                yield data

    def close(self) -> None:
        """Close open responses and transports. Safe to call repeatedly."""
        response = self._response
        oauth = self._oauth
        session = self._session
        self._response = None
        self._oauth = None
        self._session = None
        self._nonce = None
        self._subject = None
        errors = []

        # Attempt remaining cleanup even if a resource fails; report labels only.
        if response is not None:
            try:
                response.close()
            except Exception:  # noqa: BLE001
                errors.append("response")
        if oauth is not None:
            try:
                oauth.token = {}
            except Exception:  # noqa: BLE001
                errors.append("identity-provider token")
            try:
                oauth.cookies.clear()
            except Exception:  # noqa: BLE001
                errors.append("identity-provider cookies")
            try:
                oauth.close()
            except Exception:  # noqa: BLE001
                errors.append("identity-provider session")
        if session is not None:
            try:
                session.cookies.clear()
            except Exception:  # noqa: BLE001
                errors.append("application cookies")
            try:
                session.close()
            except Exception:  # noqa: BLE001
                errors.append("application session")
        if errors:
            logger.warning(
                "Could not release all MySTV resources: %s", ", ".join(errors)
            )
            raise MySTVAPIError(
                "Could not release all MySTV resources; cleanup is incomplete."
            ) from None

    def get_members_stream_raw(self) -> list[Any]:
        """Collect raw SSE payloads into a list; one payload need not be one member."""
        with closing(self.iter_members_stream()) as events:
            logger.info("Retrieved members raw")
            return list(events)

    def get_institute_members_raw(self) -> Any:
        """Return the allAddressesInClub response unchanged."""
        referer = (
            f"{self._BASE_URL}{self._GROUPS_PAGE_PATH}?"
            f"{urlencode({'clubId': self.club_id})}"
        )
        with self._request(
            path=self._CLUB_ADDRESSES_PATH,
            params={"clubNo": self.club_id},
            referer=referer,
        ) as response:
            try:
                logger.info("Retrieved institute members raw")
                return response.json()
            except ValueError:
                raise MySTVAPIError(
                    "MySTV addresses response was not valid JSON."
                ) from None

    def add_member_to_institute_with_function(
        self, member_id: str, institute_code: str, function_code: str
    ) -> dict[str, Any]:
        """Add an institute assignment and return response.json() unchanged."""
        if not member_id or not institute_code or not function_code:
            raise ValueError(
                "member_id, institute_code and function_code are required."
            )

        referer_params = {"clubId": self.club_id, "code": institute_code}
        empty_date = "0001-01-01T00:00:00"
        payload = {
            "Entry_No": "23795",
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

            if not isinstance(result, dict):
                raise MySTVAPIError(
                    "MySTV institute assignment response was not a JSON object."
                )
            if all(value is None for value in result.values()):
                raise MySTVAPIError(
                    "MySTV returned all None values. It seems like something went wrong."
                ) from None
            logger.info(
                "Added member %s to institute %s with function %s",
                member_id,
                institute_code,
                function_code,
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
        """Update one membership line; successful responses have no body."""
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
            logger.info(
                "Updated member %s to subscription group %s",
                member_id,
                subscription_group,
            )

    def delete_member_membership_unguarded(self, member_id: str, line_no: str) -> None:
        """Delete one membership line without checking it first; response has no body."""
        if not member_id or not line_no:
            raise ValueError("member_id and line_no are required.")

        referer_params = {"memberId": str(member_id), "clubId": self.club_id}
        with self._request(
            path=self._MEMBERSHIP_PATH,
            params={"memberId": str(member_id), "lineNumber": str(line_no)},
            referer=(
                f"{self._BASE_URL}{self._MEMBER_PAGE_PATH}?{urlencode(referer_params)}"
            ),
            method="DELETE",
            extra_headers={"Origin": self._BASE_URL},
        ):
            logger.info(
                "Deleted membership line %s for member %s",
                line_no,
                member_id,
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
            if not isinstance(result, list) or not all(
                isinstance(membership, dict) for membership in result
            ):
                raise MySTVAPIError(
                    "MySTV memberships response had an unexpected structure."
                )

            logger.info("Retrieved memberships for member %s", member_id)
            return result
