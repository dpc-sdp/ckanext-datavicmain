from __future__ import annotations

import csv
from typing import Any, Callable
from io import StringIO

import pytest

import ckanext.datavicmain.cli as cli

import ckan.model as model
from ckan.tests.helpers import call_action


class TestResourceFilesizeConvert:
    @pytest.mark.parametrize(
        "filesize, expected",
        [
            (120, True),
            ("100", False),
            ("100 KB", False),
            ("100 mb", False),
            ("100mb", False),
            ("0", False),
            ("eg 100kb", False),
            ("a lot", False),
            (1.7727, False),
            (-1, False),
            ("20KB", False),
            ("24MB", False),
            ("10.2", False),
            ("7.4 KB", False),
            ("117.0 bytes", False),
            ("N/A", False),
            ("", True),
        ],
    )
    def test_is_broken_resource(self, filesize: str, expected: bool):
        assert (
            cli.maintain.ResourceFilesizeConvert.is_valid_size(filesize)
            == expected
        )

    @pytest.mark.parametrize(
        "filesize, expected",
        [
            ("100", 100),
            ("100 KB", 100 * 1024),
            ("100 mb", 100 * 1024 * 1024),
            ("100mb", 100 * 1024 * 1024),
            ("0", 0),
            ("eg 100kb", ""),
            ("a lot", ""),
            (1.7727, 1),
            (120, 120),
            (-1, ""),
            ("20KB", 20 * 1024),
            ("24MB", 24 * 1024 * 1024),
            ("10.2", 10),
            ("7.4 KB", 7577),
            ("N/A", ""),
            ("3.4     MB", 3565158),
            ("245.0 MB", 256901120),
            ("1.1 gb", 1181116006),
            ("117.0 bytes", 117),
        ],
    )
    def test_convert_values(self, filesize: str, expected: int):
        assert (
            cli.maintain.ResourceFilesizeConvert.convert_to_byte_int(filesize)
            == expected
        )

    @pytest.mark.usefixtures("with_plugins", "clean_db")
    def test_broken_resource(
        self, resource_factory: Callable[..., dict[str, Any]]
    ):
        resource = resource_factory()
        self._update_resource_size(resource["id"], "broken")

        resources = cli.maintain.ResourceFilesizeConvert.get_broken_resources()

        assert len(resources) == 1

    @pytest.mark.usefixtures("with_plugins", "clean_db")
    def test_fix_multiple_broken_resources(
        self,
        dataset: dict[str, Any],
        resource_factory: Callable[..., dict[str, Any]],
    ):
        resource1 = resource_factory(package_id=dataset["id"])
        resource2 = resource_factory(package_id=dataset["id"])
        resource3 = resource_factory(package_id=dataset["id"])

        self._update_resource_size(resource1["id"], "xxx", defer_commit=True)
        self._update_resource_size(resource2["id"], "51kb", defer_commit=True)
        self._update_resource_size(resource3["id"], "100 mb")

        cli.maintain.ResourceFilesizeConvert.convert()

        assert not cli.maintain.ResourceFilesizeConvert.get_broken_resources()

        dataset = call_action("package_show", id=dataset["id"])

        result = [resource["filesize"] for resource in dataset["resources"]]

        assert "" in result
        assert 52224 in result
        assert 104857600 in result

    def _update_resource_size(
        self, resource_id: str, size: Any, defer_commit=False
    ):
        resource = model.Session.query(model.Resource).get(resource_id)

        if not resource:
            return

        resource.extras = {"filesize": size}

        if not defer_commit:
            model.Session.commit()


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestReportPackageAuthors:
    def test_no_datasets(self):
        result = cli.report.get_package_authors()

        assert result == '"ID","Name","Email","Packages"\r\n'

    def test_with_datasets(
        self,
        package_factory: Callable[..., dict[str, Any]],
        user: dict[str, Any],
    ):
        package_factory(user=user)
        result = cli.report.get_package_authors()

        data = [row for row in csv.DictReader(StringIO(result))]

        assert len(data) == 1
        assert data[0]["ID"] == user["id"]
        assert data[0]["Name"] == user["name"]
        assert data[0]["Email"] == user["email"]
        assert data[0]["Packages"] == "1"
