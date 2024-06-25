from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ckan import model
from ckan.model.types import make_uuid
from ckan.plugins import toolkit as tk
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Query, relationship
from typing_extensions import Self


log = logging.getLogger(__name__)


class HomeSectionItem(tk.BaseModel):
    __tablename__ = "home_section_item"

    class State:
        active = "active"
        inactive = "inactive"

    class SectionType:
        news = "news"
        data = "data"
        resources = "resources"

    id = Column(Text, primary_key=True, default=make_uuid)

    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    image_id = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    entity_url = Column(Text, nullable=False)
    state = Column(Text, nullable=False, default=State.active)
    section_type = Column(Text, nullable=False, default=SectionType.news)
    weight = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    modified_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"HomeSectionItem(title={self.title})"

    @classmethod
    def create(cls, data_dict) -> Self:
        item = cls(**data_dict)

        model.Session.add(item)
        model.Session.commit()

        return item

    def delete(self) -> None:
        model.Session().autoflush = False
        model.Session.delete(self)

    def dictize(self, context):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "image_id": self.image_id,
            "url": self.url,
            "entity_url": self.entity_url,
            "state": self.state,
            "section_type": self.section_type,
            "weight": self.weight,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }

    @classmethod
    def get(cls, item_id: str) -> Self | None:
        query: Query = model.Session.query(cls).filter(cls.id == item_id)

        return query.one_or_none()

    @classmethod
    def get_by_section(cls, section_type: str) -> list[Self]:
        query: Query = model.Session.query(cls).filter(
            cls.section_type == section_type
        )

        return query.all()

    @classmethod
    def all(cls) -> list[Self]:
        query: Query = model.Session.query(cls)

        return query.all()
