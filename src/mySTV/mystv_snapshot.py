import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.comparison.comparison_config import DBSnapshot, DBSnapshotType
from src.config.paths import MYSTV_SNAPSHOT_FOLDER, WORKING_DIR_PATH
from src.mySTV.mystv_processor import INSTITUTES_TYPE, MySTVProcessor

MYSTV_SNAPSHOT_PATH = Path(os.path.join(WORKING_DIR_PATH, MYSTV_SNAPSHOT_FOLDER))
MYSTV_SNAPSHOT_PATH.mkdir(parents=True, exist_ok=True)


@dataclass
class MySTVSnapshotMeta:
    uuid: str
    date: pd.Timestamp

    @classmethod
    def load(cls, filename) -> MySTVSnapshotMeta:
        with open(filename, "r") as f:
            meta = MySTVSnapshotMeta(**json.load(f))
        return meta


@dataclass
class MySTVSnapshot(DBSnapshot):
    institutes: INSTITUTES_TYPE
    meta: MySTVSnapshotMeta

    def dump(self):
        uuid = self.meta
        self.members.to_csv(self._members_name(uuid))
        with open(self._institutes_name(uuid), "w") as f:
            json.dump(self.institutes, f)
        with open(self._meta_name(uuid), "w") as f:
            json.dump(self.meta, f)

    @classmethod
    def load(cls, uuid: str) -> MySTVSnapshot:
        members = pd.read_csv(cls._members_name(uuid))
        with open(cls._institutes_name(uuid), "r") as f:
            institutes = json.load(f)
        meta = MySTVSnapshotMeta.load(cls._meta_name(uuid))
        return cls(
            members=members, institutes=institutes, meta=meta, type=DBSnapshotType.MYSTV
        )

    @staticmethod
    def _members_name(uuid: str) -> str:
        return MYSTV_SNAPSHOT_FOLDER / f"{uuid}_members.csv"

    @staticmethod
    def _institutes_name(uuid: str) -> str:
        return MYSTV_SNAPSHOT_FOLDER / f"{uuid}_institutes.json"

    @staticmethod
    def _meta_name(uuid: str) -> str:
        return MYSTV_SNAPSHOT_FOLDER / f"{uuid}_meta.json"

    @staticmethod
    def is_meta_name(filename: str) -> str:
        return filename.endswith("_meta.json")


class MySTVSnapshots:
    @staticmethod
    def create_snapshot(processor: MySTVProcessor) -> MySTVSnapshot:
        meta = MySTVSnapshotMeta(uuid=uuid.uuid4(), date=pd.Timestamp.now())
        return MySTVSnapshot(
            members=processor.members, institutes=processor.institutes, meta=meta
        )

    @staticmethod
    def load_snapshot(uuid: str) -> MySTVSnapshot:
        return MySTVSnapshot.load(uuid)

    @staticmethod
    def list_snapshots() -> list[MySTVSnapshotMeta]:
        files = os.listdir(MYSTV_SNAPSHOT_FOLDER)
        meta_files = [f for f in files if MySTVSnapshot.is_meta_name(f)]
        return [MySTVSnapshotMeta.load(meta_files)]
