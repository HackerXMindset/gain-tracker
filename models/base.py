from __future__ import annotations

from db import db


class BaseModel:
    def __init__(self, db_pool=None) -> None:
        self.db = db_pool or db
