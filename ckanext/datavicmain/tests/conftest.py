import pytest
import factory
from pytest_factoryboy import register

from ckan.tests import factories


@pytest.fixture
def clean_db(reset_db, migrate_db_for, with_plugins):
    reset_db()

    migrate_db_for("flakes")
    migrate_db_for("mailcraft")


@register
class PackageFactory(factories.Dataset):
    access = "yes"
    category = factory.LazyFunction(lambda: factories.Group()["id"])
    date_created_data_asset = factory.Faker("date")
    extract = factory.Faker("sentence")
    license_id = "notspecified"
    personal_information = "yes"
    organization_visibility = "all"
    update_frequency = "unknown"
    workflow_status = "test"
    protective_marking = "official"


@register
class ResourceFactory(factories.Resource):
    pass


@register
class UserFactory(factories.UserWithToken):
    pass


@register
class OrganizationFactory(factories.Organization):
    pass


class SysadminFactory(factories.SysadminWithToken):
    pass


register(SysadminFactory, "sysadmin")
