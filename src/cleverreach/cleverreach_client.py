import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from src.config.constants import OP_CLEVERREACH_ITEM_UUID
from src.utils.credentials import CredentialsBase


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
    attributes: dict[str, str] = field(default_factory=dict)
    global_attributes: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class CleverreachClient:
    _URL = "https://rest.cleverreach.com"
    _TOKEN_URL = "https://rest.cleverreach.com/oauth/token.php"

    def __init__(self):
        self.creds = CredentialsBase(item_uuid=OP_CLEVERREACH_ITEM_UUID)
        self._token = None
        self._token_expiry = None

    @property
    def headers(self) -> dict[str, str]:
        return self._get_headers()

    def _get_token(self) -> str:
        if self._token and time.time() + 60 < self._token_expiry:
            logging.debug("Using cached CleverReach token")
            return self._token

        logging.info("Retrieving new CleverReach access token")
        response = requests.post(
            self._TOKEN_URL,
            auth=(self.creds.client_id, self.creds.client_secret),
            data={"grant_type": "client_credentials"},
        )
        if response.status_code != 200:
            logging.error(f"Failed to retrieve CleverReach token: {response.text}")
            raise Exception(f"Failed to retrieve token: {response.text}")
        token_data = response.json()
        self._token = token_data["access_token"]
        self._token_expiry = time.time() + token_data["expires_in"]
        logging.info("Successfully retrieved new CleverReach access token")
        return self._token

    def _get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def update_receivers_for_group(
        self, group_id: str, receivers: list[Receiver]
    ) -> bool:
        logging.info(f"Updating {len(receivers)} receivers for group {group_id}")
        path = f"/v3/groups.json/{group_id}/receivers/upsert"
        receivers = [r.to_dict() for r in receivers]
        res = requests.post(self._URL + path, json=receivers, headers=self.headers)
        if res.status_code != 200:
            logging.error(
                f"Failed to update receivers for group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to update receivers for group {group_id}: {res.text}"
            )
        status_per_receiver = [x.get("status") for x in res.json()]
        if not all("success" in s for s in status_per_receiver):
            failed = [x for x in res.json() if "success" not in x.get("status")]
            logging.error(
                f"Failed to update some receivers for group {group_id}: {failed}"
            )
            raise Exception(
                f"Failed to update receivers for group {group_id}: {failed}"
            )
        logging.info(f"Successfully updated receivers for group {group_id}")
        return True

    def get_receivers_for_group(
        self,
        group_id: int,
        pagesize: int | None = None,
        page: int | None = None,
        type: str | None = None,
    ) -> list:
        if type and type not in ["active", "inactive", "all", "bounce"]:
            raise ValueError(
                "type must be one of 'active', 'inactive', 'all', 'bounce'"
            )
        logging.info(f"Retrieving receivers for group {group_id}")
        path = f"/v3/groups.json/{group_id}/receivers"
        params = {}
        if pagesize is not None:
            params["pagesize"] = pagesize
        if page is not None:
            params["page"] = page
        if type is not None:
            params["type"] = type
        res = requests.get(self._URL + path, headers=self.headers, params=params)
        if res.status_code != 200:
            logging.error(
                f"Failed to get receivers for group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise Exception(f"Failed to get receivers for group {group_id}: {res.text}")
        receivers = res.json()
        logging.info(f"Retrieved {len(receivers)} receivers for group {group_id}")
        return receivers

    def get_receivers_for_group_complete(
        self, group_id: int, type: str | None = None
    ) -> list:
        stats = self.get_group_stats(group_id)
        if type is None or type == "all":
            total_count = stats["total_count"]
        elif type == "active":
            total_count = stats["active_count"]
        elif type == "inactive":
            total_count = stats["inactive_count"]
        elif type == "bounce":
            total_count = stats["bounce_count"]
        else:
            raise ValueError(
                "type must be one of 'active', 'inactive', 'all', 'bounce'"
            )
        all_receivers = []
        page = 0
        while len(all_receivers) < total_count:
            receivers = self.get_receivers_for_group(group_id, page=page, type=type)
            if len(receivers) == 0:
                logging.warning(
                    f"Received empty receiver list for group {group_id} on page {page} without reaching total count {total_count}. Stopping pagination to avoid infinite loop."
                )
                break
            all_receivers.extend(receivers)
            page += 1
        return all_receivers

    def get_attributes(self) -> list:
        logging.info("Retrieving CleverReach attributes")
        path = "/v3/attributes.json"
        res = requests.get(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logging.error(
                f"Failed to get attributes, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to get attributes, got status {res.status_code}: {res.text}"
            )
        attributes = res.json()
        logging.info(f"Retrieved {len(attributes)} attributes")
        return attributes

    def get_filter(self, group_id: int, filter_id: int) -> dict:
        logging.info(f"Retrieving filter {filter_id}")
        path = f"/v3/groups.json/{group_id}/filters/{filter_id}"
        res = requests.get(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logging.error(
                f"Failed to get filter {filter_id}, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to get filter {filter_id}, got status {res.status_code}: {res.text}"
            )
        filter_data = res.json()
        logging.info(f"Retrieved filter {filter_id}")
        return filter_data

    def update_filter(self, group_id: int, filter_id: int, filter_data: dict) -> bool:
        logging.info(f"Updating filter {filter_id}")
        path = f"/v3/groups.json/{group_id}/filters/{filter_id}"
        res = requests.put(self._URL + path, json=filter_data, headers=self.headers)
        if res.status_code != 200:
            logging.error(
                f"Failed to update filter {filter_id}, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to update filter {filter_id}, got status {res.status_code}: {res.text}"
            )
        logging.info(f"Successfully updated filter {filter_id}")
        return res.json()["success"]

    def delete_receivers(self, group_id: int, receivers: list[str]) -> bool:
        logging.info(f"Deleting {len(receivers)} receivers from group {group_id}")
        path = f"/v3/groups.json/{group_id}/receivers/delete"
        res = requests.post(self._URL + path, json=receivers, headers=self.headers)
        if res.status_code != 200:
            logging.error(
                f"Failed to delete receivers from group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to delete receivers from group {group_id}, got status {res.status_code}: {res.text}"
            )
        success_per_receiver = [x.get("success", False) for x in res.json()]
        if not all(s for s in success_per_receiver):
            failed = [x for x in res.json() if not x.get("success", False)]
            logging.error(
                f"Failed to delete all receivers from group {group_id}, got status {res.status_code}: {failed}"
            )
            raise Exception(
                f"Failed to delete all receivers from group {group_id}, got status {res.status_code}: {failed}"
            )
        logging.info(f"Successfully deleted receivers from group {group_id}")
        return True

    def get_receivers_for_group_filtered(
        self,
        group_id: int,
        filter_id: int,
        pagesize: int | None = None,
        page: int | None = None,
    ) -> list:
        logging.info(
            f"Retrieving filtered receivers for group {group_id} with filter {filter_id}, page {page}, pagesize {pagesize}"
        )
        path = f"/v3/groups.json/{group_id}/filters/{filter_id}/receivers"
        params = {}
        if pagesize is not None:
            params["pagesize"] = pagesize
        if page is not None:
            params["page"] = page
        res = requests.get(self._URL + path, headers=self.headers, params=params)
        if res.status_code != 200:
            logging.error(
                f"Failed to get filtered receivers for group {group_id} with filter {filter_id}, page {page}, pagesize {pagesize}, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to get filtered receivers for group {group_id} with filter {filter_id}, page {page}, pagesize {pagesize}, got status {res.status_code}: {res.text}"
            )
        receivers = res.json()
        logging.info(
            f"Retrieved {len(receivers)} filtered receivers for group {group_id} with filter {filter_id}, page {page}, pagesize {pagesize}"
        )
        return receivers

    def get_receivers_for_group_filtered_complete(
        self, group_id: int, filter_id: int
    ) -> list:
        total_count = self.get_group_stats_based_on_filter(group_id, filter_id)[
            "total_count"
        ]
        all_receivers = []
        page = 0
        while len(all_receivers) < total_count:
            receivers = self.get_receivers_for_group_filtered(
                group_id, filter_id, page=page
            )
            if len(receivers) == 0:
                logging.warning(
                    f"Received empty receiver list for group {group_id} with filter {filter_id} on page {page} without reaching total count {total_count}. Stopping pagination to avoid infinite loop."
                )
                break
            all_receivers.extend(receivers)
            page += 1
        return all_receivers

    def get_group_stats(self, group_id: int) -> int:
        logging.info(f"Retrieving group statistics for group {group_id}")
        path = f"/v3/groups.json/{group_id}/stats"
        res = requests.get(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logging.error(
                f"Failed to get group statistics for group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to get group statistics for group {group_id}, got status {res.status_code}: {res.text}"
            )
        statistics = res.json()
        logging.info(f"Retrieved group statistics for group {group_id}")
        return statistics

    def get_group_stats_based_on_filter(self, group_id: int, filter_id: int) -> int:
        logging.info(
            f"Retrieving group statistics for group {group_id} based on filter {filter_id}"
        )
        path = f"/v3/groups.json/{group_id}/filters/{filter_id}/stats"
        res = requests.get(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logging.error(
                f"Failed to get group statistics for group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to get group statistics for group {group_id}, got status {res.status_code}: {res.text}"
            )
        statistics = res.json()
        logging.info(f"Retrieved group statistics for group {group_id}")
        return statistics

    def activate_receiver(self, group_id: int, receiver_id: int) -> bool:
        logging.info(f"Activating receiver {receiver_id} in group {group_id}")
        path = f"/v3/groups.json/{group_id}/receivers/{receiver_id}/activate"
        res = requests.put(self._URL + path, headers=self.headers)
        if res.status_code != 200:
            logging.error(
                f"Failed to activate receiver {receiver_id} in group {group_id}, got status {res.status_code}: {res.text}"
            )
            raise Exception(
                f"Failed to activate receiver {receiver_id} in group {group_id}, got status {res.status_code}: {res.text}"
            )
        logging.info(
            f"Successfully activated receiver {receiver_id} in group {group_id}"
        )
        return res.json()
