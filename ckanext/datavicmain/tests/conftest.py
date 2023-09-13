
import factory
from pytest_factoryboy import register

from ckan.tests import factories


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
    enable_dtv = False


@register
class ResourceFactory(factories.Resource):
    pass


@register
class UserFactory(factories.UserWithToken):
    pass


class SysadminFactory(factories.SysadminWithToken):
    pass

register(SysadminFactory, "sysadmin")
