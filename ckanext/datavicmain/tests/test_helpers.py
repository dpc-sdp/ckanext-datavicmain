import pytest

import ckan.plugins.toolkit as tk

@pytest.mark.parametrize("package__enable_dtv", [True])
@pytest.mark.usefixtures("clean_db", "with_plugins")
class TestIsDigitalTwinSupported:
    @pytest.mark.parametrize("fmt,supported", [
        ("wms", True),
        ("shp", True),
        ("kmz", True),
        ("GeoJSON", True),
        ("wms", True),
        ("csv", False),
        ("JSON", False),
        ("TXT", False),
        ("avi", False),
    ])
    def test_formats(self, package, resource_factory, fmt, supported):
        resource_factory(package_id=package["id"], format=fmt)
        assert bool(tk.h.get_digital_twin_resources(package["id"])) is supported

    def test_empty_package_is_not_supported(self, package):
        assert not tk.h.get_digital_twin_resources(package["id"])

    def test_non_single_shp(self, package, resource_factory):
        resource_factory(package_id=package["id"], format="kml")
        resource_factory(package_id=package["id"], format="shp")
        assert tk.h.get_digital_twin_resources(package["id"]) == []

    def test_dga_wms(self, package, resource_factory):
        resource_factory(package_id=package["id"], format="wms", url="https://data.gov.au/geoserver/1")
        assert tk.h.get_digital_twin_resources(package["id"]) == []
