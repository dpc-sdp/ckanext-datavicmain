import pytest

import ckan.plugins.toolkit as tk


def dtv_resources(package_id: str) -> list[dict]:
    """Return the DTV resources of a dataset, read after its resources were added."""
    pkg = tk.get_action("package_show")({"ignore_auth": True}, {"id": package_id})
    return tk.h.get_digital_twin_resources(pkg)


@pytest.mark.usefixtures("clean_db", "with_plugins")
class TestIsDigitalTwinSupported:
    @pytest.mark.parametrize(
        "fmt,supported",
        [
            ("wms", True),
            ("shp", True),
            ("kmz", True),
            ("GeoJSON", True),
            ("wms", True),
            ("csv", False),
            ("JSON", False),
            ("TXT", False),
            ("avi", False),
        ],
    )
    def test_formats(self, package, resource_factory, fmt, supported):
        resource_factory(package_id=package["id"], format=fmt)
        assert bool(dtv_resources(package["id"])) is supported

    def test_empty_package_is_not_supported(self, package):
        assert not dtv_resources(package["id"])

    def test_non_single_shp(self, package, resource_factory):
        resource_factory(package_id=package["id"], format="kml")
        resource_factory(package_id=package["id"], format="shp")
        assert dtv_resources(package["id"]) == []

    def test_dga_wms(self, package, resource_factory):
        resource_factory(
            package_id=package["id"],
            format="wms",
            url="https://data.gov.au/geoserver/1",
        )
        assert dtv_resources(package["id"]) == []
