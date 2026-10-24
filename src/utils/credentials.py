from onepassword import OnePassword


class CredentialsBase:
    def __init__(self, item_uuid: str = None):
        self._client_id = None
        self._client_secret = None
        self.op = OnePassword()
        self.item_uuid = item_uuid  # to be defined in subclasses

    @property
    def client_id(self):
        if self._client_id is None:
            self._client_id = self.get_client_id()
        return self._client_id

    @property
    def client_secret(self):
        if self._client_secret is None:
            self._client_secret = self.get_client_secret()
        return self._client_secret

    def get_client_id(self):
        return self.get_field("username")

    def get_client_secret(self):
        return self.get_field("credential")

    def get_client_credentials(self):
        fields = self.op.get_item(uuid=self.item_uuid)["fields"]
        return (
            self._get_field_value(fields, "username"),
            self._get_field_value(fields, "credential"),
        )

    def _get_field_value(self, fields, label):
        for field in fields:
            if field["id"] == label:
                if "value" in field:
                    return field["value"]
                if "reference" in field:
                    return self.op.read(field["reference"])
        raise ValueError(f"Field with label {label} not found in item {self.item_uuid}")

    def get_field(self, label):
        item = self.op.get_item(uuid=self.item_uuid)
        return self._get_field_value(item["fields"], label)
