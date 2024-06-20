import pytest
import factory

from pytest_factoryboy import register

import ckan.model as model
from ckan.tests.factories import CKANFactory

from ckanext.datavicmain_home.model import HomeSectionItem


@pytest.fixture()
def clean_db(reset_db, migrate_db_for):
    reset_db()

    migrate_db_for("datavicmain_home")


@register
class HomeSectionItemFactory(CKANFactory):
    class Meta:
        model = HomeSectionItem
        action = "create_section_item"

    title = factory.Faker("sentence")
    description = factory.Faker("sentence")
    image_id = factory.Faker("uuid4")
    url = factory.Faker("url")
    state = HomeSectionItem.State.active
    section_type = HomeSectionItem.SectionType.news
