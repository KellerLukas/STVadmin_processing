from typing import Any, Dict, List, Optional, Tuple

from onepassword import OnePassword  # type: ignore[import-untyped]


class CredentialsBase:
    def __init__(self, item_uuid: Optional[str] = None) -> None:
        self._client_id: Optional[str] = None
        self._client_secret: Optional[str] = None
        self.op = OnePassword()
        self.item_uuid = item_uuid  # to be defined in subclasses

    @property
    def client_id(self) -> str:
        value = self._client_id
        if value is None:
            value = self.get_client_id()
            self._client_id = value
        return value

    @property
    def client_secret(self) -> str:
        value = self._client_secret
        if value is None:
            value = self.get_client_secret()
            self._client_secret = value
        return value

    def get_client_id(self) -> str:
        return self.get_field("username")

    def get_client_secret(self) -> str:
        return self.get_field("credential")

    def get_client_credentials(self) -> Tuple[str, str]:
        fields = self._get_item_fields()
        return (
            self._get_field_value(fields, "username"),
            self._get_field_value(fields, "credential"),
        )

    def _get_item_fields(self) -> List[Dict[str, Any]]:
        item = self.op.get_item(uuid=self.item_uuid)
        if not isinstance(item, dict):
            raise TypeError("The configured 1Password item has an invalid structure.")
        fields = item.get("fields")
        if not isinstance(fields, list):
            raise TypeError("The configured 1Password item has no valid fields list.")
        typed_fields: List[Dict[str, Any]] = []
        for field in fields:
            if not isinstance(field, dict):
                raise TypeError("The configured 1Password item contains an invalid field.")
            typed_fields.append(field)
        return typed_fields

    def _get_field_value(self, fields: List[Dict[str, Any]], label: str) -> str:
        for field in fields:
            if field["id"] == label:
                if "value" in field:
                    value = field["value"]
                    if isinstance(value, str):
                        return value
                    raise TypeError(f"1Password field '{label}' must contain a string.")
                if "reference" in field:
                    reference = field["reference"]
                    if not isinstance(reference, str):
                        raise TypeError(
                            f"1Password field '{label}' has an invalid reference."
                        )
                    value = self.op.read(reference)
                    if isinstance(value, str):
                        return value
                    raise TypeError(f"1Password field '{label}' must contain a string.")
        raise ValueError(f"Field with label {label} not found in item {self.item_uuid}")

    def get_field(self, label: str) -> str:
        return self._get_field_value(self._get_item_fields(), label)
