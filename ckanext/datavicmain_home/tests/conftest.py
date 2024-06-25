from __future__ import annotations

from io import BytesIO

import pytest
import factory
from pytest_factoryboy import register


from ckan.tests.factories import CKANFactory

from ckanext.datavicmain_home.model import HomeSectionItem
from ckanext.datavicmain_home.tests.helpers import MockFileStorage, PNG_IMAGE


@pytest.fixture()
def clean_db(reset_db, migrate_db_for):
    reset_db()

    migrate_db_for("datavicmain_home")
    migrate_db_for("files")


@register
class HomeSectionItemFactory(CKANFactory):
    class Meta:
        model = HomeSectionItem
        action = "create_section_item"

    title = factory.Faker("sentence")
    description = factory.Faker("sentence")
    # image_id = factory.Faker("uuid4")
    upload = factory.LazyAttribute(
        lambda _: MockFileStorage(BytesIO(PNG_IMAGE), "image.png")
    )

    url = factory.Faker("url")
    entity_url = factory.Faker("url")
    state = HomeSectionItem.State.active
    section_type = HomeSectionItem.SectionType.news
    weight = 0
