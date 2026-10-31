import logging
import pickle
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Self
from uuid import UUID, uuid4

import pandas as pd

from src.comparison.comparison_models import DBSnapshot, DBSnapshotType
from src.config.paths import MYSTV_SNAPSHOT_FOLDER, WORKING_DIR_PATH
from src.mySTV.mystv_config import INSTITUTES_TYPE

if TYPE_CHECKING:
    from src.mySTV.mystv_processor import MySTVProcessor

logger = logging.getLogger(__name__)

MYSTV_SNAPSHOT_PATH = Path(WORKING_DIR_PATH) / MYSTV_SNAPSHOT_FOLDER
SNAPSHOT_SUFFIX = ".pkl"


@dataclass
class MySTVSnapshotMeta:
    uuid: str
    date: pd.Timestamp


@dataclass(eq=False)
class MySTVSnapshot(DBSnapshot):
    institutes: INSTITUTES_TYPE
    meta: MySTVSnapshotMeta
    type: DBSnapshotType = field(default=DBSnapshotType.MYSTV, init=False)

    @classmethod
    def from_processor(cls, processor: MySTVProcessor) -> Self:
        processor.clear_cached_data()
        members = processor.members
        institutes = processor.institutes
        meta = MySTVSnapshotMeta(uuid=str(uuid4()), date=pd.Timestamp.now(tz="UTC"))
        logger.info("Captured MySTV snapshot %s (%s members)", meta.uuid, len(members))
        return cls(members=members, institutes=institutes, meta=meta)

    def dump(self) -> None:
        data = {
            item.name: getattr(self, item.name) for item in fields(self) if item.init
        }
        MYSTV_SNAPSHOT_PATH.mkdir(parents=True, exist_ok=True)
        with self._path(self.meta.uuid).open("wb") as file:
            pickle.dump(data, file, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(
            "Saved MySTV snapshot %s (%s members)", self.meta.uuid, len(self.members)
        )

    @classmethod
    def load(cls, snapshot_id: str) -> Self:
        with cls._path(snapshot_id).open("rb") as file:
            data: object = pickle.load(file)
        if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
            raise TypeError("The snapshot must contain dataclass fields.")
        snapshot = cls(**data)
        logger.info(
            "Loaded MySTV snapshot %s (%s members)",
            snapshot.meta.uuid,
            len(snapshot.members),
        )
        return snapshot

    @classmethod
    def list_snapshots(cls) -> list[MySTVSnapshotMeta]:
        snapshots = [
            cls.load(path.stem).meta
            for path in MYSTV_SNAPSHOT_PATH.glob(f"*{SNAPSHOT_SUFFIX}")
        ]
        return sorted(snapshots, key=lambda meta: meta.date, reverse=True)

    @staticmethod
    def _path(snapshot_id: str) -> Path:
        return MYSTV_SNAPSHOT_PATH / f"{UUID(snapshot_id)}{SNAPSHOT_SUFFIX}"
