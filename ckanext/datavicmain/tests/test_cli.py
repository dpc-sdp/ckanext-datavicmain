from __future__ import annotations

import csv
from typing import Any, Callable
from io import StringIO

import pytest

import ckanext.datavicmain.cli as cli


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
