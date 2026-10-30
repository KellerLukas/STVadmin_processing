import logging
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import requests

from src.config.constants import OP_CLEVERREACH_ITEM_UUID
from src.utils.credentials import CredentialsBase

logger = logging.getLogger(__name__)

JsonObject = dict[str, object]


class CleverReachError(RuntimeError):
    """An error returned by the CleverReach client."""


def _json_object(value: object, description: str) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError(f"CleverReach returned invalid {description}.")
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"CleverReach returned invalid {description}.")
        result[key] = item
    return result


def _json_objects(value: object, description: str) -> list[JsonObject]:
    if not isinstance(value, list):
        raise TypeError(f"CleverReach returned invalid {description}.")
    return [_json_object(item, description) for item in value]


def _response_objects(
    response: requests.Response, description: str
) -> list[JsonObject]:
    payload: object = response.json()
    return _json_objects(payload, description)


def _response_object(response: requests.Response, description: str) -> JsonObject:
    payload: object = response.json()
    return _json_object(payload, description)


def _required_count(stats: JsonObject, key: str) -> int:
    value = stats.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"CleverReach returned an invalid {key} group statistic.")
    if value < 0:
        raise ValueError(f"CleverReach returned invalid {key} group statistics.")
    return value


@dataclass
class Receiver:
    email: str

    """
    - provide 'registered' with current time if receiver is new.
    - provide 'activated' only for immedite activation (no DOI mail will work then).
    - provide 'deactivated' other than 0 and your receiver will definitely be inactive. 0 will eventually reactivate receivers!

    Omission of all of those fields leads to an activated receiver, if new ('registered' and 'activated' to current time)!
    """
    registered: str | None = None  # timestamp
    activated: str | None = None  # timestamp
    deactivated: str | None = None  # timestamp

    source: str = "User Import"
    attributes: dict[str, str | bool] = field(default_factory=dict)
    global_attributes: dict[str, str | bool] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class CleverreachClient:
    _URL = "https://rest.cleverreach.com"
    _TOKEN_URL = "https://rest.cleverreach.com/oauth/token.php"

    def __init__(self) -> None:
        self.creds = CredentialsBase(item_uuid=OP_CLEVERREACH_ITEM_UUID)
        self._token: str | None = None
        self._token_expiry: float | None = None

    @property
    def headers(self) -> dict[str, str]:
        return self._get_headers()

    def _get_token(self) -> str:
        if (
            self._token is not None
            and self._token_expiry is not None
            and time.time() + 60 < self._token_expiry
        ):
            logger.debug("Using cached CleverReach token")
            return self._token

        logger.info("Retrieving new CleverReach access token")
        response = requests.post(
            self._TOKEN_URL,
            auth=(self.creds.client_id, self.creds.client_secret),
            data={"grant_type": "client_credentials"},
        )
        if response.status_code != 200:
            logger.error(f"Failed to retrieve CleverReach token: {response.text}")
            raise CleverReachError(f"Failed to retrieve token: {response.text}")
        token_data = _response_object(response, "access token")
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(expires_in, (int, float))
            or isinstance(expires_in, bool)
            or not math.isfinite(expires_in)
            or expires_in <= 0
        ):
            raise ValueError("CleverReach returned invalid access-token data.")
        self._token = access_token
        self._token_expiry = time.time() + expires_in
        logger.info("Successfully retrieved new CleverReach access token")
        return self._token

    def _get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def update_receivers_for_group(
        self, group_id: int, receivers: list[Receiver]
    ) -> bool:
        logger.info(f"Updating {len(receivers)} receivers for group {group_id}")
        path = f"/v3/groups.json/{group_id}/receivers/upsert"
        payload = [receiver.to_dict() for receiver in receivers]
        res = requests.post(self._URL + path, json=payload, headers=self.headers)
        if res.status_code != 200:
            logger.error(
                f"Failed to update receivers for group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to update receivers for group {group_id}: {res.text}"
            )
        results = _response_objects(res, "receiver update response")
        status_per_receiver = [result.get("status") for result in results]
        if not all(
            isinstance(status, str) and "success" in status
            for status in status_per_receiver
        ):
            failed = []
            for result in results:
                status = result.get("status")
                if not isinstance(status, str) or "success" not in status:
                    failed.append(result)
            logger.error(
                f"Failed to update some receivers for group {group_id}: {failed}"
            )
            raise CleverReachError(
                f"Failed to update receivers for group {group_id}: {failed}"
            )
        logger.info(f"Successfully updated receivers for group {group_id}")
        return True

    def get_receivers_for_group(
        self,
        group_id: int,
        pagesize: int | None = None,
        page: int | None = None,
        type: str | None = None,
    ) -> list[JsonObject]:
        if type and type not in ["active", "inactive", "all", "bounce"]:
            raise ValueError(
                "type must be one of 'active', 'inactive', 'all', 'bounce'"
            )
        logger.info(f"Retrieving receivers for group {group_id}")
        path = f"/v3/groups.json/{group_id}/receivers"
        params: dict[str, str | int] = {}
        if pagesize is not None:
            params["pagesize"] = pagesize
        if page is not None:
            params["page"] = page
        if type is not None:
            params["type"] = type
        res = requests.get(self._URL + path, headers=self.headers, params=params)
        if res.status_code != 200:
            logger.error(
                f"Failed to get receivers for group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to get receivers for group {group_id}: {res.text}"
            )
        receivers = _response_objects(res, "receiver list")
        logger.info(f"Retrieved {len(receivers)} receivers for group {group_id}")
        return receivers

    def get_receivers_for_group_complete(
        self, group_id: int, type: str | None = None
    ) -> list[JsonObject]:
        stats = self.get_group_stats(group_id)
        if type is None or type == "all":
            total_count = _required_count(stats, "total_count")
        elif type == "active":
            total_count = _required_count(stats, "active_count")
        elif type == "inactive":
            total_count = _required_count(stats, "inactive_count")
        elif type == "bounce":
            total_count = _required_count(stats, "bounce_count")
        else:
            raise ValueError(
                "type must be one of 'active', 'inactive', 'all', 'bounce'"
            )
        all_receivers: list[JsonObject] = []
        page = 0
        while len(all_receivers) < total_count:
            receivers = self.get_receivers_for_group(group_id, page=page, type=type)
            if len(receivers) == 0:
                logger.warning(
                    f"Received empty receiver list for group {group_id} on page {page} without reaching total count {total_count}. Stopping pagination to avoid infinite loop."
                )
                break
            all_receivers.extend(receivers)
            page += 1
        return all_receivers

    def get_attributes(self) -> list[JsonObject]:
        logger.info("Retrieving CleverReach attributes")
        path = "/v3/attributes.json"
        res = requests.get(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logger.error(
                f"Failed to get attributes, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to get attributes, got status {res.status_code}: {res.text}"
            )
        attributes = _response_objects(res, "attribute list")
        logger.info(f"Retrieved {len(attributes)} attributes")
        return attributes

    def get_filter(self, group_id: int, filter_id: int) -> JsonObject:
        logger.info(f"Retrieving filter {filter_id}")
        path = f"/v3/groups.json/{group_id}/filters/{filter_id}"
        res = requests.get(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logger.error(
                f"Failed to get filter {filter_id}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to get filter {filter_id}, got status {res.status_code}: {res.text}"
            )
        filter_data = _response_object(res, "filter")
        logger.info(f"Retrieved filter {filter_id}")
        return filter_data

    def update_filter(
        self,
        group_id: int,
        filter_id: int,
        filter_data: dict[str, object],
    ) -> bool:
        logger.info(f"Updating filter {filter_id}")
        path = f"/v3/groups.json/{group_id}/filters/{filter_id}"
        res = requests.put(self._URL + path, json=filter_data, headers=self.headers)
        if res.status_code != 200:
            logger.error(
                f"Failed to update filter {filter_id}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to update filter {filter_id}, got status {res.status_code}: {res.text}"
            )
        success = _response_object(res, "filter update response").get("success")
        if not isinstance(success, bool):
            raise TypeError("CleverReach returned an invalid filter update response.")
        if not success:
            logger.error(f"Failed to update filter {filter_id}: success=false")
            raise CleverReachError(
                f"Failed to update filter {filter_id}: success=false"
            )
        logger.info(f"Successfully updated filter {filter_id}")
        return success

    def delete_receivers(self, group_id: int, receivers: list[str | int]) -> bool:
        logger.info(f"Deleting {len(receivers)} receivers from group {group_id}")
        path = f"/v3/groups.json/{group_id}/receivers/delete"
        res = requests.post(self._URL + path, json=receivers, headers=self.headers)
        if res.status_code != 200:
            logger.error(
                f"Failed to delete receivers from group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to delete receivers from group {group_id}, got status {res.status_code}: {res.text}"
            )
        results = _response_objects(res, "receiver deletion response")
        success_per_receiver = [result.get("success", False) for result in results]
        if not all(s for s in success_per_receiver):
            failed = [result for result in results if result.get("success") is not True]
            logger.error(
                f"Failed to delete all receivers from group {group_id}, got status {res.status_code}: {failed}"
            )
            raise CleverReachError(
                f"Failed to delete all receivers from group {group_id}, got status {res.status_code}: {failed}"
            )
        logger.info(f"Successfully deleted receivers from group {group_id}")
        return True

    def get_receivers_for_group_filtered(
        self,
        group_id: int,
        filter_id: int,
        pagesize: int | None = None,
        page: int | None = None,
    ) -> list[JsonObject]:
        logger.info(
            f"Retrieving filtered receivers for group {group_id} with filter {filter_id}, page {page}, pagesize {pagesize}"
        )
        path = f"/v3/groups.json/{group_id}/filters/{filter_id}/receivers"
        params: dict[str, str | int] = {}
        if pagesize is not None:
            params["pagesize"] = pagesize
        if page is not None:
            params["page"] = page
        res = requests.get(self._URL + path, headers=self.headers, params=params)
        if res.status_code != 200:
            logger.error(
                f"Failed to get filtered receivers for group {group_id} with filter {filter_id}, page {page}, pagesize {pagesize}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to get filtered receivers for group {group_id} with filter {filter_id}, page {page}, pagesize {pagesize}, got status {res.status_code}: {res.text}"
            )
        receivers = _response_objects(res, "filtered receiver list")
        logger.info(
            f"Retrieved {len(receivers)} filtered receivers for group {group_id} with filter {filter_id}, page {page}, pagesize {pagesize}"
        )
        return receivers

    def get_receivers_for_group_filtered_complete(
        self, group_id: int, filter_id: int
    ) -> list[JsonObject]:
        total_count = _required_count(
            self.get_group_stats_based_on_filter(group_id, filter_id), "total_count"
        )
        all_receivers: list[JsonObject] = []
        page = 0
        while len(all_receivers) < total_count:
            receivers = self.get_receivers_for_group_filtered(
                group_id, filter_id, page=page
            )
            if len(receivers) == 0:
                logger.warning(
                    f"Received empty receiver list for group {group_id} with filter {filter_id} on page {page} without reaching total count {total_count}. Stopping pagination to avoid infinite loop."
                )
                break
            all_receivers.extend(receivers)
            page += 1
        return all_receivers

    def get_group_stats(self, group_id: int) -> JsonObject:
        logger.info(f"Retrieving group statistics for group {group_id}")
        path = f"/v3/groups.json/{group_id}/stats"
        res = requests.get(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logger.error(
                f"Failed to get group statistics for group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to get group statistics for group {group_id}, got status {res.status_code}: {res.text}"
            )
        statistics = _response_object(res, "group statistics")
        logger.info(f"Retrieved group statistics for group {group_id}")
        return statistics

    def get_group_stats_based_on_filter(
        self, group_id: int, filter_id: int
    ) -> JsonObject:
        logger.info(
            f"Retrieving group statistics for group {group_id} based on filter {filter_id}"
        )
        path = f"/v3/groups.json/{group_id}/filters/{filter_id}/stats"
        res = requests.get(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logger.error(
                f"Failed to get group statistics for group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to get group statistics for group {group_id}, got status {res.status_code}: {res.text}"
            )
        statistics = _response_object(res, "filtered group statistics")
        logger.info(f"Retrieved group statistics for group {group_id}")
        return statistics

    def activate_receiver(self, group_id: int, receiver_id: str | int) -> object:
        logger.info(f"Activating receiver {receiver_id} in group {group_id}")
        path = f"/v3/groups.json/{group_id}/receivers/{receiver_id}/activate"
        res = requests.put(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logger.error(
                f"Failed to activate receiver {receiver_id} in group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise CleverReachError(
                f"Failed to activate receiver {receiver_id} in group {group_id}, got status {res.status_code}: {res.text}"
            )
        logger.info(
            f"Successfully activated receiver {receiver_id} in group {group_id}"
        )
        activated: object = res.json()
        return activated
