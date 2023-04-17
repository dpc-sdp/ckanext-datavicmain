from __future__ import annotations

import datetime
import logging
import csv
from os import path

from typing import Any

import click

import ckan.plugins.toolkit as tk


log = logging.getLogger(__name__)


@click.group()
def maintain():
    """Portal maintenance tasks"""
    pass


@maintain.command("ckan-resources-date-cleanup")
def ckan_iar_resource_date_cleanup():
    """Fix resources with invalid date range. One-time task."""
    user = tk.get_action("get_site_user")({"ignore_auth": True}, {})

    limit = 100
    offset = 0
    packages_found = True

    while packages_found:
        package_list = tk.get_action("current_package_list_with_resources")(
            {"user": user["name"]}, {"limit": limit, "offset": offset}
        )
        if len(package_list) == 0:
            packages_found = False
        offset += 1

        for package in package_list:
            fix_available = False
            click.secho(
                f"Processing resources in {package['name']}", fg="green"
            )

            for resource in package.get("resources"):
                if _fix_improper_date_values(resource):
                    fix_available = True

            if not fix_available:
                continue
            try:
                tk.get_action("package_patch")(
                    {"user": user["name"]},
                    {"id": package["id"], "resources": package["resources"]},
                )
                click.secho(
                    f"Fixed date issues for resources in {package['name']}",
                    fg="green",
                )
            except tk.ValidationError as e:
                click.secho(
                    f"Failed to fix  resources {package['name']}: {e}",
                    fg="red",
                )


def _fix_improper_date_values(resource: dict[str, Any]) -> bool:
    """Make the invalid date field value to None.


    Args:
        resource (dict) : resource data.


    Returns:
        bool: True if date values updated.
    """
    date_fields = ["period_end", "period_start", "release_date"]

    old_resource = resource.copy()

    for field in date_fields:
        if not resource.get(field):
            continue
        if not _valid_date(resource[field]):
            click.secho(
                (
                    f"Found invalid date for {field} in {resource['name']}:"
                    f" {resource[field]}"
                ),
                fg="red",
            )
            resource[field] = None

    return old_resource != resource


def _valid_date(date: str) -> bool:
    """Validates given date.


    Args:
        date (str): date in YY-MM-DD format.


    Returns:
        bool: True if date is valid.
    """
    date_format = "%Y-%m-%d"
    try:
        datetime.datetime.strptime(date, date_format)
    except ValueError:
        return False

    return True


@maintain.command()
def drop_wms_records():
    """Purge old WMS records. One-time script"""

    file = open(path.join(path.dirname(__file__), "data/old_wms_records.csv"))
    csv_reader = csv.DictReader(file)

    for row in csv_reader:
        dataset_name: str = row["url"].split("/")[-1]

        try:
            tk.get_action("dataset_purge")(
                {"ignore_auth": True}, {"id": dataset_name}
            )
        except tk.ObjectNotFound as e:
            click.secho(f"Error purging <{dataset_name}> dataset: {e}", fg="red")
        else:
            click.secho(f"Dataset <{dataset_name}> has been purged", fg="green")

    file.close()
