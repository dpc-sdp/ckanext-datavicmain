from __future__ import annotations

import copy
import csv
import datetime
import logging
import mimetypes
import os
import re
import shutil
from itertools import groupby
from os import path, stat
from typing import Any
from urllib.parse import urlparse

import click
import openpyxl
import tqdm
from sqlalchemy import or_
from sqlalchemy.orm import Query

import ckan.logic.validators as validators
import ckan.model as model
import ckan.plugins.toolkit as tk
from ckan.lib.munge import munge_title_to_name
from ckan.lib.search import clear as search_clear
from ckan.lib.search import rebuild
from ckan.lib.uploader import get_resource_uploader, get_uploader
from ckan.model import Resource, ResourceView
from ckan.types import Context

from ckanext.datastore.backend import get_all_resources_ids_in_datastore
from ckanext.harvest.model import HarvestObject, HarvestSource

from ckanext.datavicmain.helpers import field_choices, localized_filesize

log = logging.getLogger(__name__)

IDX_ID = 0
IDX_NAME = 1
IDX_TITLE = 2
IDX_STATE = 3
NAME_FIELD_LENGTH = 99

XLSX_IDX_TITLE = 0
XLSX_IDX_CURRENT_URL = 5
XLSX_IDX_NEW_URL = 6

# Relative to ckan.storage_path.
FILESTORE_AUDIT_OUTPUT_DIR = "audit_reports"


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
                f"Found invalid date for {field} in {resource['name']}:"
                f" {resource[field]}",
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
            click.secho(
                f"Error purging <{dataset_name}> dataset: {e}", fg="red"
            )
        else:
            click.secho(
                f"Dataset <{dataset_name}> has been purged", fg="green"
            )

    file.close()


@maintain.command("recline-to-datatable")
@click.option("-d", "--delete", is_flag=True, help="Delete recline_view views")
def replace_recline_with_datatables(delete: bool):
    """Replaces recline_view with datatables_view
    Args:
        delete (bool): delete existing `recline_view` views
    """
    resources = [
        res
        for res in model.Session.query(Resource).all()
        if res.extras.get("datastore_active")
    ]
    if not resources:
        click.secho("No resources have been found", fg="green")
        return click.secho(
            "NOTE: `datatables_view` works only with resources uploaded to"
            " datastore",
            fg="green",
        )
    click.secho(
        f"{len(resources)} resources have been found. Updating views...",
        fg="green",
    )
    with tqdm.tqdm(resources) as bar:
        for res in bar:
            res_views = _get_existing_views(res.id)
            if not _is_datatable_view_exist(res_views):
                _create_datatable_view(res.id)
            if delete:
                _delete_recline_views(res_views)


def _get_existing_views(resource_id: str) -> list[ResourceView]:
    """Returns a list of resource view entities
    Args:
        resource_id (str): resource ID
    Returns:
        list[ResourceView]: list of resource views
    """
    return (
        model.Session.query(ResourceView)
        .filter(ResourceView.resource_id == resource_id)
        .all()
    )


def _is_datatable_view_exist(res_views: list[ResourceView]) -> bool:
    """Checks if at least one view from resource views is `datatables_view`
    Args:
        res_views (list[ResourceView]): list of resource views
    Returns:
        bool: True if `datatables_view` view exists
    """
    for view in res_views:
        if view.view_type == "datatables_view":
            return True
    return False


def _create_datatable_view(resource_id: str):
    """Creates a datatable view for resource
    Args:
        resource_id (str): resource ID
    """
    tk.get_action("resource_view_create")(
        {"ignore_auth": True},
        {
            "resource_id": resource_id,
            "show_fields": _get_resource_fields(resource_id),
            "title": "Datatable",
            "view_type": "datatables_view",
        },
    )


def _get_resource_fields(resource_id: str) -> list[str]:
    """Fetches list of resource fields from datastore
    Args:
        resource_id (str): resource ID
    Returns:
        list[str]: list of resource fields
    """
    ctx = {"ignore_auth": True}
    data_dict = {
        "resource_id": resource_id,
        "limit": 0,
        "include_total": False,
    }
    try:
        search = tk.get_action("datastore_search")(ctx, data_dict)
    except tk.ObjectNotFound:
        click.echo(f"Resource {resource_id} orphaned")
        return []

    fields = [field for field in search["fields"]]
    return [f["id"] for f in fields]


def _delete_recline_views(res_views: list[ResourceView]):
    for view in res_views:
        if view.view_type != "recline_view":
            continue
        view.delete()
    model.repo.commit()


@maintain.command(
    "purge-delwp-duplicates", short_help="Purge duplicates of DELWP datasets"
)
def purge_delwp_duplicates():
    """
    Purge all duplicates of DELWP datasets and rename them in order to match
    their names with titles
    """

    click.secho("Searching for duplicated DELWP datasets...")

    taken_names = [
        name[0] for name in model.Session.query(model.Package.name).all()
    ]

    query = _get_query_delwp_datasets()
    datasets = (
        query.with_entities(
            model.Package.id,
            model.Package.name,
            model.Package.title,
            model.Package.state,
        )
        .distinct()
        .order_by(model.Package.title)
        .all()
    )

    click.secho(
        f"{len(datasets)} DELWP datasets have been found.",
        fg="green",
    )
    click.secho("Purging duplicates and renaming datasets...", fg="green")

    counter_purged = 0
    counter_renamed = 0
    unchanged_pkgs = []
    for key, grp in groupby(datasets, lambda x: x[IDX_TITLE]):
        pkgs = [dataset for dataset in grp]
        pkgs_sorted = sorted(pkgs, key=lambda x: x[IDX_NAME], reverse=False)
        pkgs_len = len(pkgs_sorted)

        if pkgs_len < 2:
            continue

        for idx, pkg in enumerate(pkgs_sorted):
            if (idx == pkgs_len - 1) and (pkg[IDX_STATE] == "active"):
                # Renaming datasets (names match with titles)
                pkg_obj = model.Session.query(model.Package).get(pkg[IDX_ID])
                cur_name = pkg_obj.name
                new_name = munge_title_to_name(pkg_obj.title)
                if (
                    new_name in taken_names
                    or len(pkg.title) > NAME_FIELD_LENGTH
                ):
                    click.secho(
                        f"Dataset <{pkg_obj.title}> with the name"
                        f" <{cur_name}>: Couldn't generate the unique name"
                        f" {new_name} from the title.",
                        fg="red",
                    )
                    unchanged_pkgs.append(pkg_obj.title)
                    continue
                pkg_obj.name = new_name
                click.secho(
                    f"Renamed: from <{cur_name}> to <{pkg_obj.name}>",
                    fg="green",
                )
                counter_renamed += 1
            else:
                # Purging duplicates of datasets from DB entirely
                site_user = tk.get_action("get_site_user")(
                    {"ignore_auth": True}, {}
                )
                context: Context = {
                    "user": site_user["name"],
                    "ignore_auth": True,
                }
                try:
                    tk.get_action("dataset_purge")(
                        context, {"id": pkg[IDX_ID]}
                    )
                except tk.ObjectNotFound as e:
                    click.secho(
                        "Purging ERROR occurred in the dataset"
                        f" <{pkg[IDX_ID]}>: {e}",
                        fg="red",
                    )
                else:
                    taken_names.remove(pkg[IDX_NAME])
                    click.secho(
                        f"Purged: {pkg[IDX_TITLE]} - ID: {pkg[IDX_ID]}",
                        fg="yellow",
                    )
                    counter_purged += 1

    model.Session.commit()

    click.secho("Done.", fg="green")
    click.secho(f"{counter_purged} DELWP datasets - purged.", fg="green")
    click.secho(f"{counter_renamed} DELWP datasets - renamed.", fg="green")
    click.secho(
        f"{len(unchanged_pkgs)} DELWP datasets - unchanged: ", fg="yellow"
    )
    click.secho(f"{unchanged_pkgs}", fg="yellow")


@maintain.command(
    "list-delwp-wrong-names", short_help="List DELWP datasets with wrong names"
)
def list_delwp_wrong_names():
    """
    Display a list of DELWP datasets with active state and wrong names
    which do not correspond their titles
    """

    click.secho("Searching for DELWP datasets...")

    query = _get_query_delwp_datasets()
    datasets = (
        query.filter(model.Package.state == model.State.ACTIVE)
        .with_entities(
            model.Package.id, model.Package.name, model.Package.title
        )
        .distinct()
        .order_by(model.Package.title)
        .all()
    )

    click.secho(
        f"{len(datasets)} DELWP datasets have been found.",
        fg="green",
    )

    counter = 0
    for dataset in datasets:
        pkg = model.Session.query(model.Package).get(dataset[IDX_ID])
        cur_name = pkg.name
        new_name = munge_title_to_name(pkg.title)
        if cur_name != new_name:
            counter += 1
            click.secho(
                f"{dataset[IDX_TITLE]} - {dataset[IDX_NAME]}", fg="yellow"
            )

    click.secho(
        f"{counter} active DELWP datasets with wrong names.", fg="green"
    )


def _get_query_delwp_datasets() -> Query[model.Package]:
    """Get all DELWP datasets

    Returns:
        Query[model.Package]: Package model query object
    """
    return (
        model.Session.query(model.Package)
        .join(HarvestObject, model.Package.id == HarvestObject.package_id)
        .join(
            HarvestSource, HarvestObject.harvest_source_id == HarvestSource.id
        )
        .filter(HarvestSource.type == "delwp")
    )


@maintain.command("get-broken-recline")
def identify_resources_with_broken_recline():
    """Return a list of resources with a broken recline_view"""

    query = (
        model.Session.query(model.Resource)
        .join(
            model.ResourceView,
            model.ResourceView.resource_id == model.Resource.id,
        )
        .filter(
            model.ResourceView.view_type.in_(
                ["datatables_view", "recline_view"]
            )
        )
    )

    resources = [resource for resource in query.all()]

    if not resources:
        return click.secho("No resources with inactive datastore")

    for resource in resources:
        if resource.extras.get("datastore_active"):
            continue

        res_url = tk.url_for(
            "resource.read",
            id=resource.package_id,
            resource_id=resource.id,
            _external=True,
        )
        click.secho(
            f"Resource {res_url} has a table view but datastore is inactive",
            fg="green",
        )


@maintain.command
@click.option("--patch", "-p", is_flag=True, help="Patch missing fields.")
def handle_missing_mandatory_metadata(patch: bool):
    """Searches for datasets with missing mandatory metadata and optionally patches them with default values."""

    if not (incomplete_datasets := _search_incomplete_datasets()):
        click.secho("No incomplete datasets found.", fg="green")
        return

    click.secho(
        f"Found {len(incomplete_datasets)} incomplete datasets.", fg="green"
    )

    for dataset_name, missing_fields in incomplete_datasets.items():
        click.secho(
            f"Dataset name: {dataset_name}. Missing fields with patch values:"
            f" {missing_fields}."
        )

    if not patch:
        return

    for dataset_name, missing_fields in tqdm.tqdm(incomplete_datasets.items()):
        try:
            tk.get_action("package_patch")(
                {"ignore_auth": True},
                {
                    "id": dataset_name,
                    **missing_fields,
                },
            )
        except (tk.ValidationError, tk.ObjectNotFound) as e:
            click.secho(
                f"Error while patching the package {dataset_name}: {e}"
            )


def _search_incomplete_datasets() -> dict[str, dict[str, str]]:
    """Identifies datasets with missing fields, preparing patch values to complete them."""
    incomplete_datasets = {}

    max_rows = tk.config["ckan.search.rows_max"]
    start = 0
    has_datasets = True

    while has_datasets:
        result = tk.get_action("package_search")(
            {"ignore_auth": True},
            {
                "rows": max_rows,
                "start": start,
                "include_private": True,
            },
        )

        datasets: list[dict[str, Any]] = result["results"]
        incomplete_datasets.update(_search_in_batch(datasets))

        start += len(datasets)
        has_datasets = start < result["count"]

    return incomplete_datasets


def _search_in_batch(
    datasets: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """Processes a batch of datasets to find and list those with missing fields,
    providing default values for these fields.
    """
    incomplete_datasets = {}
    for dataset in datasets:
        missing_fields = {
            field: _get_default_values_for_missing_fields(dataset, field)
            for field in _missing_value_fields
            if not dataset.get(field)
        }

        update_frequency = dataset.get("update_frequency")
        choices = [
            choice["value"] for choice in field_choices("update_frequency")
        ]
        if update_frequency and update_frequency not in choices:
            missing_fields["update_frequency"] = "unknown"

        if missing_fields:
            incomplete_datasets[dataset["name"]] = missing_fields
    return incomplete_datasets


_missing_value_fields: list[str] = [
    "date_created_data_asset",
    "update_frequency",
    "access",
    "personal_information",
    "protective_marking",
    "category",
]


def _get_default_values_for_missing_fields(
    dataset: dict[str, Any], field: str
) -> str:
    """Get values for missing fields"""
    if field == "date_created_data_asset":
        return _get_date_created(dataset)
    elif field == "update_frequency":
        return "unknown"
    elif field == "access":
        return "yes"
    elif field == "personal_information":
        return "no"
    elif field == "protective_marking":
        return "official"
    elif field == "category":
        return _get_category(dataset)
    return ""


def _get_date_created(pkg: dict[str, Any]) -> str:
    """For 'date_created_data_asset' returns the oldest 'release_date' from the resources, or the 'metadata_created'
    date if no 'release_date' are available.
    """
    min_release_date = min(
        [
            resource["release_date"]
            for resource in pkg.get("resources", [])
            if resource.get("release_date")
        ],
        default="",
    )
    if min_release_date:
        return min_release_date
    return pkg.get("metadata_created", "")


def _get_category(pkg: dict[str, Any]) -> str:
    """
    For missing field 'category' set its value as group id related to this dataset
    """
    if groups := pkg.get("groups"):
        return groups[0].get("id")
    return ""


@maintain.command(
    "update-broken-urls", short_help="Update resources with broken urls"
)
def update_broken_urls():
    """Change resources urls' protocols from http to https listed in XLSX file"""

    file = path.join(
        path.dirname(__file__),
        "data/DTF Content list bulk URL change 20231017.xlsx",
    )
    wb = openpyxl.load_workbook(file)
    ws = wb.active

    for row in ws.iter_rows(min_row=2):
        title = row[XLSX_IDX_TITLE].value
        url = row[XLSX_IDX_CURRENT_URL].value

        resource = (
            model.Session.query(model.Resource)
            .filter(model.Resource.url == url)
            .first()
        )

        if not resource:
            click.secho(
                f"Resource <{title}> with URL <{url}> does not exist", fg="red"
            )
            continue

        resource.url = row[XLSX_IDX_NEW_URL].value
        click.secho(
            f"URL of resource <{title}> has been updated to <{resource.url}>",
            fg="green",
        )

        model.Session.commit()


@maintain.command("ckan-resources-format-fix")
def ckan_iar_resources_format_fix():
    """Fix resources with empty format field."""

    resources = (
        model.Session.query(Resource).filter(model.Resource.format == "").all()
    )

    if not resources:
        return click.secho("No resources with empty format", fg="green")

    for resource in resources:
        resource.format = _suggest_file_format(resource.url)

        click.secho(
            f"Resource '{resource.name}' changed format to: {resource.format}",
            fg="green",
        )
    model.Session.commit()
    click.secho(
        "All formats was corrected.",
        fg="green",
    )


def _suggest_file_format(url: str | None) -> str:
    if not url:
        return "unknown"

    parsed = urlparse(url)
    if parsed.scheme and not parsed.path:
        return "unknown"

    mimetype, _ = mimetypes.guess_type(url)
    return validators.clean_format(mimetype) if mimetype else "unknown"


@maintain.command
def delete_datastore_tables_with_no_related_resource():
    """Delete from Datastore all tables that do not have a related resource."""
    res_ids = _get_datastore_tables_with_no_related_resource()

    if not res_ids:
        click.secho(
            "Nothing to delete. "
            "All Datastore tables are associated with an existing resource",
            fg="green",
        )
        return

    for res_id in res_ids:
        try:
            click.secho(
                f"Deleting Datastore table with ID {res_id}", fg="green"
            )
            tk.get_action("datastore_delete")(
                {"ignore_auth": True}, {"resource_id": res_id, "force": True}
            )
        except tk.ObjectNotFound:
            continue


@maintain.command
def list_datastore_tables_with_no_related_resource():
    """Show all Datastore tables that do not have a related resource."""
    res_ids = _get_datastore_tables_with_no_related_resource()

    if not res_ids:
        click.secho(
            "All Datastore tables are associated with an existing resource",
            fg="green",
        )
        return

    for res_id in res_ids:
        click.secho(f"{res_id}", fg="red")
    click.secho(
        f"Total number of Datastore tables that don't have a related resource is "
        f"{len(res_ids)}",
        fg="green",
    )


def _get_datastore_tables_with_no_related_resource() -> list[str]:
    """Return a list of Datastore table names that are not associated with
    the currently active resource."""
    res_ids = []
    for res_id in get_all_resources_ids_in_datastore():
        res = model.Resource.get(res_id)
        if not res or res.state == model.State.DELETED:
            res_ids.append(res_id)
    return res_ids


@maintain.command()
@click.option("--update", is_flag=True, type=click.BOOL, default=False)
def recalculate_resource_size(update: bool):
    """Update file size for uploaded resources"""

    packages = set()
    resources = (
        model.Session.query(model.Resource).filter_by(url_type="upload").all()
    )

    if not update:
        click.secho(
            "You're in a display mode."
            " If you want to update the resources, please use the --update flag.",
            fg="blue",
            italic=True,
        )

    click.secho("Found {} resource(s)".format(len(resources)), fg="green")

    for resource in resources:
        resource_path = get_resource_uploader({}).get_path(resource.id)
        if not path.exists(resource_path):
            tk.error_shout(f"Resource does not exist with id: {resource.id}")
            continue

        size = stat(resource_path).st_size
        old_size = resource.extras.get("filesize")
        extras = copy.deepcopy(resource.extras or {})
        extras["filesize"] = size

        click.secho(
            f"Resource {resource.name} ({resource.id}). Old size {old_size}, new size {size}",
            fg="blue",
        )

        if not update:
            continue

        resource.extras = extras
        packages.add(resource.package_id)

    if update:
        model.Session.commit()
        rebuild(package_ids=packages)


@maintain.command()
@click.option(
    "-e", "--empty", is_flag=True, help="Get resources with empty size"
)
@click.option(
    "-l",
    "--limit",
    is_flag=True,
    help="Get resources with size > max_content_length",
)
@click.option(
    "-r",
    "--restricted",
    is_flag=True,
    help="Get resources with restricted size autocalculation",
)
def get_resources_by_size(empty: bool, limit: bool, restricted: bool):
    """
    Get resources by file size.
    Return all resources with not empty size by default
    """

    resources = model.Session.query(model.Resource).filter_by(state="active")
    click.secho(
        f"Total number of resources is {resources.count()}",
        fg="green",
    )
    if empty:
        resources = resources.filter(model.Resource.size.is_(None))
    elif limit:
        resources = resources.filter_by(size=-1)
    elif restricted:
        resources = resources.filter_by(size=0)
    else:
        resources = resources.filter(model.Resource.size.isnot(None))

    click.secho(
        "Searching for resources...",
        fg="green",
    )

    if not resources:
        return click.secho("No resources found.", fg="green")

    for resource in resources:
        if not empty:
            click.secho(
                f"Dataset ID {resource.package_id} - resource {resource.name}",
                fg="green",
            )

    click.secho(
        f"Found {resources.count()} resources...",
        fg="green",
    )


@maintain.command("make-datatables-view-prioritized")
def make_datatables_view_prioritized():
    """Check if there are resources that have recline_view and datatables_view and
    reorder them so that datatables_view is first."""
    resources = model.Session.query(Resource).all()
    number_reordered = 0
    for resource in tqdm.tqdm(resources):
        result = tk.get_action("datavic_datatables_view_prioritize")(
            {"ignore_auth": True}, {"resource_id": resource.id}
        )
        if result.get("updated"):
            number_reordered += 1
    click.secho(f"Reordered {number_reordered} resources", fg="green")


@maintain.command()
@click.option("--update", is_flag=True, type=click.BOOL, default=False)
def convert_resources_filesize(update: bool):
    """Convert resources filesize from non-numeric values to bytes"""
    if not update:
        ResourceFilesizeConvert.list_broken_resources()
    else:
        ResourceFilesizeConvert.convert()


class ResourceFilesizeConvert:
    @classmethod
    def list_broken_resources(cls):
        """List resources with non-valid filesize"""
        click.secho(
            "This command will only show the resources with non-numeric filesize."
            " If you want to update the resources, please use the --update flag.",
            fg="blue",
            italic=True,
        )

        click.secho(
            "Searching for resources with non-numeric filesize...",
            fg="blue",
        )

        resources = ResourceFilesizeConvert.get_broken_resources()

        if not resources:
            return click.secho(
                "No resources found with non-numeric filesize.",
                fg="blue",
            )

        for resource in ResourceFilesizeConvert.get_broken_resources():
            old = resource.extras.get("filesize") or "empty"
            new = cls.convert_to_byte_int(resource.extras.get("filesize"))
            resource_url = tk.url_for(
                "resource.read",
                id=resource.package_id,
                resource_id=resource.id,
            )

            click.secho(
                click.style("Resource ")
                + click.style(f"{resource_url}", fg="blue", italic=True)
                + click.style(" has non-numeric filesize: ")
                + click.style(f"{old} → {new}", fg="blue", italic=True)
            )

    @classmethod
    def get_broken_resources(cls) -> list[Resource]:
        """Get resources with non-valid filesize"""
        resources = (
            model.Session.query(model.Resource)
            .filter(model.Resource.state == model.State.ACTIVE)
            .filter(model.Resource.extras.ilike("%filesize%"))
            .all()
        )

        return [
            resource
            for resource in resources
            if not cls.is_valid_size(resource.extras.get("filesize", ""))
        ]

    @classmethod
    def is_valid_size(cls, size: str | int) -> bool:
        """Check if the size is valid

        Only integer >= 0 or empty string is valid

        Args:
            size (str | int): filesize

        Returns:
            True if the size is valid
        """
        if isinstance(size, int) and size >= 0:
            return True

        if isinstance(size, str) and size == "":
            return True

        return False

    @classmethod
    def convert(cls):
        resources = cls.get_broken_resources()
        package_ids = set()

        if not resources:
            return click.secho(
                "No resources found with non-numeric filesize.",
                fg="blue",
            )

        click.secho(
            f"Total number of broken resources is {len(resources)}",
            fg="blue",
        )

        for resource in resources:
            package_ids.add(resource.package_id)

            old_size = resource.extras.get("filesize")
            new_size = cls.convert_to_byte_int(resource.extras.get("filesize"))

            resource_url = tk.url_for(
                "resource.read",
                id=resource.package_id,
                resource_id=resource.id,
            )

            click.secho(
                click.style("Resource ")
                + click.style(f"{resource_url}", fg="blue", italic=True)
                + click.style(" filesize updated ")
                + click.style(
                    f"{old_size} → {new_size}",
                    fg="blue",
                    italic=True,
                )
            )

            extras = copy.deepcopy(resource.extras or {})
            extras["filesize"] = new_size
            resource.extras = extras

        click.secho(
            "Committing changes and rebuilding the search-index...", fg="blue"
        )

        model.Session.commit()
        rebuild(package_ids=package_ids)

    @classmethod
    def convert_to_byte_int(cls, size: Any) -> int | str:
        """Convert a string size to bytes integer if possible.

        If we can't calculate the size, we return an empty string, because
        we have a custom logic, that will try to evaluate the size later.
        """
        if isinstance(size, int):
            return cls.convert_int_to_byte_int(size)
        elif isinstance(size, str):
            return cls.convert_string_to_byte_int(size)
        elif isinstance(size, float):
            return int(size)

        return ""

    @classmethod
    def convert_int_to_byte_int(cls, size: int) -> int | str:
        if size < 0:
            return ""

        return size

    @classmethod
    def convert_string_to_byte_int(cls, size: str) -> int | str:
        size = size.lower()

        if not size:
            return ""

        if "eg" in size:
            return ""

        if size.isdigit():
            return int(size)

        try:
            return cls.convert_to_bytes(size)
        except ValueError:
            pass

        if "." in size:
            try:
                return int(float(size))
            except ValueError:
                pass

        return ""

    @classmethod
    def convert_to_bytes(cls, size) -> int:
        """
        Convert a human-readable file size string to bytes.

        Args:
            size (str): File size string (e.g., "7.4 KB", "24MB", "20KB").

        Returns:
            File size in bytes.

        Raises:
            ValueError: If the size_str format is invalid.
        """
        size = size.strip().upper()
        size_units = {
            "BYTES": 1,
            "KB": 1024,
            "MB": 1024**2,
            "GB": 1024**3,
            "TB": 1024**4,
            "B": 1,
        }

        for unit, multiplier in size_units.items():
            if not size.endswith(unit):
                continue

            try:
                value = float(size.replace(unit, "").strip())
                return int(value * multiplier)
            except ValueError:
                raise ValueError(f"Invalid size value: {size}")

        raise ValueError(f"Unrecognized size unit in: {size}")


@maintain.command()
@click.option("--delete", is_flag=True, type=click.BOOL, default=False)
@click.option(
    "--csv-path",
    default=None,
    type=click.Path(),
    help="Path for the CSV audit report.  "
    "Defaults to /app/filestore/purge_reports/dd_delwp_purged_<timestamp>.csv",
)
def delete_detached_delwp_datasets(delete: bool, csv_path: str | None):
    """Delete DELWP datasets that are not attached to a harvest object"""
    if not delete:
        DeleteDetachedDelwpDatasets.list_detached_datasets()
    else:
        DeleteDetachedDelwpDatasets.purge_datasets(csv_path=csv_path)


class DeleteDetachedDelwpDatasets:
    def __init__(self, delete: bool):
        self.delete = delete

    @classmethod
    def list_detached_datasets(cls) -> None:
        click.secho("Listing detached datasets...", fg="blue")

        datasets = cls.get_datasets()

        active_count = 0
        deleted_count = 0
        other_count = 0

        for dataset in datasets:
            url = tk.url_for("dataset.read", id=dataset.name, _external=True)
            click.secho(f"Dataset {url} is detached (state={dataset.state})", fg="red")

            if dataset.state == model.State.ACTIVE:
                active_count += 1
            elif dataset.state == model.State.DELETED:
                deleted_count += 1
            else:
                other_count += 1

        click.secho(
            f"Found {len(datasets)} detached datasets"
            f" (active={active_count}, deleted={deleted_count}"
            + (f", other={other_count}" if other_count else "")
            + ")",
            fg="blue",
        )
        click.secho("Use --delete flag to delete them", fg="blue")

        # Exit with non-zero status when detached datasets are found so the
        # calling shell script can report to the monitoring service.
        if datasets:
            raise SystemExit(1)

    @classmethod
    def get_datasets(cls) -> set[model.Package]:
        package = model.Package
        extras = model.PackageExtra

        packages_with_harvest_objects = {
            row[0]
            for row in model.Session.query(HarvestObject.package_id).all()  # type: ignore
        }

        result = set()

        # No state filter — detached DELWP datasets should be purged
        # regardless of whether they are active, deleted, or in any other
        # state.  They have no harvest object linking them to a source so
        # they serve no purpose.
        for package in (
            model.Session.query(package)
            .join(extras, package.id == extras.package_id)
            .filter(extras.key == "harvest_source_type")
            .filter(extras.value == "delwp")
            .all()
        ):
            if package.id in packages_with_harvest_objects:
                continue

            result.add(package)

        return result - packages_with_harvest_objects

    @classmethod
    def purge_datasets(cls, csv_path: str | None = None) -> None:
        import sys

        datasets = cls.get_datasets()
        dataset_refs = [(d.id, d.name, d.state) for d in datasets]

        if not dataset_refs:
            click.secho("No detached DELWP datasets found.", fg="green")
            return

        # Collect syndicated_id extras for DD→DV cross-reference audit trail.
        syndicated_ids: dict[str, str] = dict(
            model.Session.query(
                model.PackageExtra.package_id, model.PackageExtra.value
            )
            .filter(model.PackageExtra.key == "syndicated_id")
            .filter(
                model.PackageExtra.package_id.in_(
                    [d[0] for d in dataset_refs]
                )
            )
            .all()
        )

        # Resolve CSV path — default to persistent filestore.
        if not csv_path:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = (
                f"/app/filestore/purge_reports/dd_delwp_purged_{ts}.csv"
            )
        csv_dir = os.path.dirname(csv_path)
        if csv_dir:
            os.makedirs(csv_dir, exist_ok=True)

        active_count = sum(
            1 for _, _, s in dataset_refs if s == model.State.ACTIVE
        )
        deleted_count = sum(
            1 for _, _, s in dataset_refs if s == model.State.DELETED
        )
        other_count = len(dataset_refs) - active_count - deleted_count

        click.secho(
            f"Purging {len(dataset_refs)} detached DELWP datasets"
            f" (active={active_count}, deleted={deleted_count}"
            + (f", other={other_count}" if other_count else "")
            + f", {len(syndicated_ids)} have DV syndicated_id)...",
            fg="blue",
        )
        sys.stdout.flush()

        purged = 0
        failed = 0

        for dataset_id, dataset_name, _initial_state in dataset_refs:
            try:
                dv_id = syndicated_ids.get(dataset_id, "")
                click.secho(
                    f"  Purging {dataset_name}"
                    + (f" (DV={dv_id})" if dv_id else ""),
                    fg="blue",
                )
                sys.stdout.flush()

                # 1. Clear from Solr index (works without package in DB).
                search_clear(dataset_id)

                # 2. Delete child rows that do NOT have DB-level
                #    ON DELETE CASCADE.
                #
                #    Tables with DB-level CASCADE (auto-handled):
                #      resource_view  → cascades from resource
                #      user_following_dataset → cascades from package
                #      harvest_object → cascades from package (migration)
                model.Session.query(model.Resource).filter_by(
                    package_id=dataset_id
                ).delete()
                model.Session.query(model.PackageExtra).filter_by(
                    package_id=dataset_id
                ).delete()
                model.Session.query(model.PackageTag).filter_by(
                    package_id=dataset_id
                ).delete()
                model.Session.query(model.PackageRelationship).filter(
                    or_(
                        model.PackageRelationship.subject_package_id
                        == dataset_id,
                        model.PackageRelationship.object_package_id
                        == dataset_id,
                    )
                ).delete(synchronize_session="fetch")
                model.Session.query(model.Member).filter(
                    model.Member.table_id == dataset_id,
                    model.Member.table_name == "package",
                ).delete()
                model.Session.query(model.PackageMember).filter_by(
                    package_id=dataset_id
                ).delete()

                # 3. Delete the package row — triggers DB CASCADE for
                #    resource_view, user_following_dataset, harvest_object.
                model.Session.query(model.Package).filter_by(
                    id=dataset_id
                ).delete()
                model.Session.commit()
                purged += 1

            except Exception as e:
                click.secho(
                    f"  ERROR purging {dataset_name}: {e}", fg="red"
                )
                log.error(
                    "Failed to purge dataset %s (%s): %s",
                    dataset_name,
                    dataset_id,
                    e,
                )
                model.Session.rollback()
                failed += 1

        # -- Post-purge: Solr orphan cleanup (safety net) ----------------
        click.secho("\nCleaning up Solr orphaned entries...", fg="blue")
        sys.stdout.flush()
        try:
            from ckan.cli.search_index import get_orphans

            orphans = get_orphans()
            for orphan_id in orphans:
                search_clear(orphan_id)
            if orphans:
                click.secho(
                    f"  Cleared {len(orphans)} orphaned Solr entries",
                    fg="green",
                )
            else:
                click.secho("  No orphaned Solr entries found", fg="green")
        except Exception as e:
            click.secho(
                f"  WARNING: Solr orphan cleanup failed: {e}", fg="yellow"
            )
            log.warning("Solr orphan cleanup failed: %s", e)

        # -- Post-purge: datastore orphan cleanup ------------------------
        click.secho("Cleaning up orphaned datastore tables...", fg="blue")
        sys.stdout.flush()
        try:
            site_user = tk.get_action("get_site_user")(
                {"ignore_auth": True}, {}
            )
            ds_dropped = 0
            for resid in get_all_resources_ids_in_datastore():
                try:
                    tk.get_action("resource_show")(
                        {"user": site_user["name"]}, {"id": resid}
                    )
                except (tk.ObjectNotFound, KeyError):
                    try:
                        tk.get_action("datastore_delete")(
                            {"user": site_user["name"]},
                            {"resource_id": resid, "force": True},
                        )
                        ds_dropped += 1
                    except Exception:
                        pass
            if ds_dropped:
                click.secho(
                    f"  Dropped {ds_dropped} orphaned datastore tables",
                    fg="green",
                )
            else:
                click.secho(
                    "  No orphaned datastore tables found", fg="green"
                )
        except Exception as e:
            click.secho(
                f"  WARNING: datastore cleanup failed: {e}", fg="yellow"
            )
            log.warning("Datastore cleanup failed: %s", e)

        # -- CSV audit report ------------------------------------------------
        try:
            with open(csv_path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    ["dd_id", "dd_name", "dd_state", "dv_syndicated_id"]
                )
                for did, dname, dstate in dataset_refs:
                    writer.writerow(
                        [did, dname, dstate, syndicated_ids.get(did, "")]
                    )
            click.secho(f"\nCSV report written to {csv_path}", fg="green")
        except Exception as e:
            click.secho(
                f"\nWARNING: failed to write CSV report: {e}", fg="yellow"
            )
            log.warning("Failed to write CSV report to %s: %s", csv_path, e)

        # -- Summary -----------------------------------------------------
        click.secho(
            f"\nDone. {purged} datasets purged, {failed} failed.",
            fg="green" if failed == 0 else "yellow",
        )
        if syndicated_ids:
            click.secho(
                f"\nDD→DV cross-reference"
                f" ({len(syndicated_ids)} syndicated datasets):",
                fg="blue",
            )
            for dd_id, dv_id in sorted(syndicated_ids.items()):
                click.secho(f"  DD {dd_id} → DV {dv_id}", fg="blue")
        sys.stdout.flush()


@maintain.command("cleanup-group-images")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List unused images without moving them.",
)
def cleanup_group_images(dry_run: bool):
    """Move unused group/organisation images to a _unused subdirectory.

    Fetches all organisations and groups, collects their image_url values,
    then compares against files on disk.  Any file not referenced by an active
    org or group is moved to <storage_path>/_unused for safe manual review.
    """
    storage_path = get_uploader("group").storage_path

    if dry_run:
        click.secho("Dry-run mode — no files will be moved.", fg="blue")

    try:
        referenced = _collect_referenced_group_images()
    except Exception as e:
        click.secho(f"Aborting: could not collect referenced images: {e}", fg="red")
        log.error("cleanup-group-images aborted during collection: %s", e)
        return

    click.secho(
        f"Found {len(referenced)} referenced image filename(s) across all orgs/groups.",
        fg="green",
    )

    if not os.path.isdir(storage_path):
        click.secho(f"Storage path does not exist: {storage_path}", fg="red")
        return

    unused_dir = os.path.join(storage_path, "_unused")

    disk_files: list[str] = []
    for filename in os.listdir(storage_path):
        filepath = os.path.join(storage_path, filename)
        if not os.path.isfile(filepath):
            continue
        disk_files.append(filename)

    unused: list[str] = []
    for filename in disk_files:
        if filename not in referenced:
            unused.append(filename)

    if not unused:
        click.secho("No unused images found.", fg="green")
        return

    click.secho(f"Found {len(unused)} unused image(s).", fg="yellow")

    if dry_run:
        for filename in unused:
            click.secho(f"  Would move: {filename}", fg="yellow")
        return

    os.makedirs(unused_dir, exist_ok=True)

    moved = 0
    skipped = 0
    failed = 0
    for filename in unused:
        src = os.path.join(storage_path, filename)
        dst = os.path.join(unused_dir, filename)
        if os.path.exists(dst):
            click.secho(
                f"  Skipped (already in _unused): {filename}", fg="yellow"
            )
            log.warning(
                "cleanup-group-images: skipped %s — destination already exists",
                filename,
            )
            skipped += 1
            continue
        try:
            shutil.move(src, dst)
            click.secho(f"  Moved: {filename}", fg="yellow")
            moved += 1
        except OSError as e:
            click.secho(f"  ERROR moving {filename}: {e}", fg="red")
            log.error("Failed to move group image %s: %s", filename, e)
            failed += 1

    click.secho(
        f"\nDone. {moved} moved, {skipped} skipped (already in _unused),"
        f" {failed} failed.",
        fg="green" if failed == 0 else "yellow",
    )


def _collect_referenced_group_images() -> set[str]:
    """Return the set of image filenames referenced by all orgs and groups.

    Raises an exception if the top-level list call for either orgs or groups
    fails, so the caller can abort rather than treating all files as unused.
    """
    ctx = {"ignore_auth": True}
    referenced: set[str] = set()

    actions = [
        ("organization_list", "organization_show"),
        ("group_list", "group_show"),
    ]

    for list_action, detail_action in actions:
        names: list[str] = tk.get_action(list_action)(ctx, {"all_fields": False})

        for name in names:
            try:
                data = tk.get_action(detail_action)(
                    ctx, {"id": name, "include_datasets": False}
                )
            except Exception as e:
                log.warning(
                    "Could not fetch %s for %s: %s", detail_action, name, e
                )
                continue

            value = data.get("image_url") or ""
            if value:
                referenced.add(os.path.basename(value.rstrip("/")))

    return referenced


@maintain.command("audit-filestore")
@click.option(
    "--purge-orphanage",
    is_flag=True,
    help="Move files not referenced in the database to orphanage under ckan.storage_path.",
)
def audit_filestore(purge_orphanage: bool = False):
    """Audit filestore usage and database references, writing CSV reports.

    Reports are written to audit_reports under ckan.storage_path.
    Existing reports are overwritten. With --purge-orphanage, unreferenced
    files are moved after the baseline reports are written.
    """

    # Validate storage configuration before creating the report directory.
    storage_path = tk.config.get("ckan.storage_path")
    if not storage_path:
        click.secho("ckan.storage_path is not configured.", fg="red")
        return

    storage_path = os.path.realpath(storage_path)
    output_dir = os.path.join(storage_path, FILESTORE_AUDIT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    # Use the same UTC measurement time for this run.
    measured_at = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    # Inventory disk files, then match absolute paths against database references.
    files, errors = _filestore_audit_scan(storage_path)
    _filestore_audit_mark_database_references(files)
    # Calculate overall totals and per-namespace summaries.
    total_files = len(files)
    total_size = 0
    for item in files:
        total_size += item["size_bytes"]
    namespace_rows = _filestore_audit_namespace_summary(
        storage_path, files, total_size
    )

    # Write one row per file with its reference flags.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "files.csv"),
        [
            "namespace",
            "path",
            "exists_in_database",
            "resource_in_trash",
            "size_bytes",
            "size_human",
            "last_modified",
        ],
        _filestore_audit_file_report_rows(files),
    )
    # Write counts and sizes grouped by namespace.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "namespace-summary.csv"),
        [
            "namespace",
            "path",
            "file_count",
            "size_bytes",
            "size_human",
            "percentage_of_filestore",
            "exists_in_database_file_count",
            "exists_in_database_size_bytes",
            "exists_in_database_size_human",
            "exists_in_database_percentage",
            "resource_in_trash_file_count",
            "resource_in_trash_size_bytes",
            "resource_in_trash_size_human",
            "resource_in_trash_percentage",
            "not_exists_in_database_file_count",
            "not_exists_in_database_size_bytes",
            "not_exists_in_database_size_human",
            "not_exists_in_database_percentage",
        ],
        namespace_rows,
    )
    # Write overall totals for this run.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "summary.csv"),
        [
            "measured_at",
            "storage_path",
            "total_file_count",
            "total_size_bytes",
            "total_size_human",
            "exists_in_database_file_count",
            "exists_in_database_size_bytes",
            "exists_in_database_size_human",
            "exists_in_database_percentage",
            "resource_in_trash_file_count",
            "resource_in_trash_size_bytes",
            "resource_in_trash_size_human",
            "resource_in_trash_percentage",
            "not_exists_in_database_file_count",
            "not_exists_in_database_size_bytes",
            "not_exists_in_database_size_human",
            "not_exists_in_database_percentage",
        ],
        [
            {
                "measured_at": measured_at,
                "storage_path": storage_path,
                "total_file_count": total_files,
                "total_size_bytes": total_size,
                "total_size_human": localized_filesize(total_size),
                **_filestore_audit_database_summary(files, total_size),
            }
        ],
    )
    # Write filesystem errors to identify incomplete scan coverage.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "scan-errors.csv"),
        ["path", "error"],
        errors,
    )
    # Write database uploads whose expected files are absent.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "missing-resource-files.csv"),
        [
            "resource_id",
            "resource_name",
            "resource_state",
            "resource_url",
            "resource_size_bytes",
            "resource_size_human",
            "missing_file_relative_path",
            "expected_file_path",
            "dataset_id",
            "dataset_title",
            "dataset_state",
            "organization_title",
            "data_owner",
            "contact_point",
        ],
        _filestore_audit_missing_resource_rows(storage_path),
    )

    # Check that grouping preserved the complete scanned inventory.
    counted_files = 0
    counted_size = 0
    for row in namespace_rows:
        counted_files += row["file_count"]
        counted_size += row["size_bytes"]
    if counted_files != total_files or counted_size != total_size:
        click.secho("Namespace totals do not match file inventory.", fg="red")
        return

    click.secho(f"Wrote filestore baseline to {output_dir}", fg="green")
    click.secho(
        f"Files: {total_files:,}; size: {localized_filesize(total_size)}",
        fg="green",
    )
    if errors:
        click.secho(
            f"Scan completed with {len(errors):,} errors; see scan-errors.csv",
            fg="yellow",
        )

    if purge_orphanage:
        _filestore_audit_move_orphans(storage_path, files, output_dir)


def _filestore_audit_orphanage_path() -> str:
    """Resolve the orphanage inside the configured CKAN filestore."""
    return os.path.join(os.path.realpath(tk.config["ckan.storage_path"]), "orphanage")


def _filestore_audit_move_orphans(
    storage_path: str, files: list[dict[str, Any]], output_dir: str
) -> None:
    """Move unreferenced files, preserving their storage-relative directory tree."""
    orphanage = _filestore_audit_orphanage_path()
    moved = skipped = failed = 0
    # Flush each result so a partial run still leaves a useful move log.
    report_path = os.path.join(output_dir, "orphanage-moves.csv")
    with open(report_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["namespace", "source", "destination", "status", "error"]
        )
        writer.writeheader()
        for item in files:
            if item["exists_in_database"] or item["resource_in_trash"]:
                continue
            source = item["path"]
            relative_path = os.path.relpath(source, storage_path)
            destination = os.path.join(orphanage, relative_path)
            row = dict(namespace=item["namespace"], source=source,
                       destination=destination, status="", error="")
            try:
                if relative_path == os.pardir or relative_path.startswith(os.pardir + os.sep):
                    raise ValueError("Source is outside the configured filestore")
                if os.path.islink(source) or not os.path.isfile(source):
                    raise ValueError("Source is no longer a regular file")
                # Reject symlinked destination directories that escape the orphanage.
                if not _filestore_audit_is_in_path(
                    os.path.realpath(os.path.dirname(destination)), os.path.realpath(orphanage)
                ):
                    raise ValueError("Destination directory escapes the orphanage")
                if os.path.lexists(destination):
                    row["status"] = "skipped"
                    row["error"] = "Destination already exists"
                    skipped += 1
                else:
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    shutil.move(source, destination)
                    row["status"] = "moved"
                    moved += 1
            except (OSError, ValueError, shutil.Error) as exc:
                row["status"] = "failed"
                row["error"] = str(exc)
                failed += 1
            writer.writerow(row)
            handle.flush()
    click.echo(f"Orphanage: {orphanage}; {moved} moved, {skipped} skipped, {failed} failed.")
    if failed:
        raise click.ClickException(f"Some files could not be moved; see {report_path}")


def _filestore_audit_is_in_path(file_path: str, absolute_directory: str) -> bool:
    """Check whether an absolute path matches a directory or lies beneath it."""
    return file_path == absolute_directory or file_path.startswith(
        absolute_directory.rstrip(os.sep) + os.sep
    )


def _filestore_audit_file_row(
    namespace: str,
    absolute_path: str,
) -> dict[str, Any]:
    """Read file metadata and build an inventory row for its absolute path."""
    stat_result = os.stat(absolute_path, follow_symlinks=False)
    last_modified = (
        datetime.datetime.fromtimestamp(stat_result.st_mtime, datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "namespace": namespace,
        "path": os.path.abspath(absolute_path),
        "size_bytes": stat_result.st_size,
        "last_modified": last_modified,
    }


def _filestore_audit_namespaces() -> dict[str, dict[str, Any]]:
    """Define each scan directory and its database reference collector together."""
    namespaces = {
        "resource": {
            "path": "resources",
            "collector": _filestore_audit_resource_paths,
        },
        "group": {
            "path": "storage/uploads/group",
            "collector": _filestore_audit_group_image_paths,
        },
        "user": {
            "path": "storage/uploads/user",
            "collector": _filestore_audit_user_image_paths,
        },
        "page_images": {
            "path": "storage/uploads/page_images",
            "collector": _filestore_audit_page_image_paths,
        },
        "vic_home": {
            "path": "storage/vic_home",
            "collector": _filestore_audit_files_file_paths,
        },
    }
    return namespaces


def _filestore_audit_resource_paths(relative_directory: str) -> set[str]:
    """Collect resource paths using CKAN's uploader instead of relative_directory."""
    paths: set[str] = set()
    resource_ids = (
        model.Session.query(model.Resource.id)
        .filter(model.Resource.url_type == "upload")
        .all()
    )
    for resource_id, in resource_ids:
        if resource_id:
            paths.add(_filestore_audit_resource_path(resource_id))
    return paths


def _filestore_audit_resource_path(resource_id: str) -> str:
    """Resolve an absolute resource file path through CKAN's uploader."""
    return get_resource_uploader({}).get_path(resource_id)


def _filestore_audit_group_image_paths(relative_directory: str) -> set[str]:
    """Collect image paths referenced by groups and organizations."""
    return _filestore_audit_upload_image_paths(model.Group.image_url, relative_directory)


def _filestore_audit_user_image_paths(relative_directory: str) -> set[str]:
    """Collect image paths referenced by user profiles."""
    return _filestore_audit_upload_image_paths(model.User.image_url, relative_directory)


def _filestore_audit_upload_image_paths(column: Any, relative_directory: str) -> set[str]:
    """Collect image paths referenced by a database column under the given relative directory."""
    paths: set[str] = set()
    for value, in model.Session.query(column).filter(column != "").all():
        _filestore_audit_add_referenced_path(paths, relative_directory, value)
    return paths


def _filestore_audit_page_image_paths(relative_directory: str) -> set[str]:
    """Extract uploaded page image paths from stored page content."""
    from ckanext.pages.db import Page

    paths: set[str] = set()
    pattern = re.compile(r"(?:storage/)?uploads/page_images/([^\"'<>\s)]+)")
    page_content = (
        model.Session.query(Page.content)
        .filter(Page.content != "")
        .all()
    )
    for content, in page_content:
        if not content:
            continue
        for filename in pattern.findall(content):
            _filestore_audit_add_referenced_path(
                paths,
                relative_directory,
                filename,
            )
    return paths


def _filestore_audit_files_file_paths(relative_directory: str) -> set[str]:
    """Collect vic_home paths for files registered in the default files storage."""
    from ckanext.files.model.file import FilesFile

    paths: set[str] = set()
    storage_path = os.path.realpath(tk.config["ckan.storage_path"])
    for location, in (
        model.Session.query(FilesFile.location)
        .filter(FilesFile.storage == "default")
        .all()
    ):
        if location:
            paths.add(os.path.join(
                storage_path, relative_directory, str(location).strip("/")
            ))
    return paths


def _filestore_audit_add_referenced_path(
    paths: set[str],
    relative_directory: str,
    value: Any,
) -> None:
    """Normalize an upload reference into an absolute path and add it to the set."""
    if not value:
        return

    # Extract the URL path, ignoring query strings and fragments.
    value_path = urlparse(str(value).strip()).path.strip("/")
    if not value_path:
        return

    storage_path = os.path.realpath(tk.config["ckan.storage_path"])
    # Accept references with the full storage-relative directory.
    if value_path.startswith(f"{relative_directory}/"):
        paths.add(os.path.join(storage_path, value_path))
        return

    # Public upload URLs omit the leading storage/ directory.
    upload_url_directory = relative_directory.removeprefix("storage/")
    if value_path.startswith(f"{upload_url_directory}/"):
        paths.add(os.path.join(storage_path, "storage", value_path))
        return

    # Treat other nonempty references as filenames in this upload namespace.
    basename = os.path.basename(value_path.rstrip("/"))
    if basename:
        paths.add(os.path.join(storage_path, relative_directory, basename))


def _filestore_audit_database_paths() -> dict[str, set[str]]:
    """Collect database references using the namespace registry."""
    database_paths: dict[str, set[str]] = {}
    for name, namespace in _filestore_audit_namespaces().items():
        collector = namespace["collector"]
        database_paths[name] = collector(relative_directory=namespace["path"])
    return database_paths


def _filestore_audit_deleted_resource_paths() -> set[str]:
    """Collect absolute file paths for uploaded resources marked as deleted."""
    paths: set[str] = set()
    resource_ids = (
        model.Session.query(model.Resource.id)
        .filter(model.Resource.url_type == "upload")
        .filter(model.Resource.state == "deleted")
        .all()
    )
    for resource_id, in resource_ids:
        if resource_id:
            paths.add(_filestore_audit_resource_path(resource_id))
    return paths


def _filestore_audit_mark_database_references(
    files: list[dict[str, Any]],
) -> None:
    """Load database references and add reference/trash flags to inventory rows."""
    database_paths = _filestore_audit_database_paths()
    deleted_resource_paths = _filestore_audit_deleted_resource_paths()

    for item in files:
        namespace_paths = database_paths.get(item["namespace"], set())
        item["exists_in_database"] = (
            item["path"] in namespace_paths
        )
        item["resource_in_trash"] = (
            item["path"] in deleted_resource_paths
        )


def _filestore_audit_file_report_rows(
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Format inventory rows for CSV, including yes/no flags and readable sizes."""
    rows: list[dict[str, Any]] = []
    for item in files:
        row = {
            "namespace": item["namespace"],
            "path": item["path"],
            "exists_in_database": "yes" if item["exists_in_database"] else "no",
            "resource_in_trash": "yes" if item["resource_in_trash"] else "no",
            "size_bytes": item["size_bytes"],
            "size_human": localized_filesize(item["size_bytes"]),
            "last_modified": item["last_modified"],
        }
        rows.append(row)
    return rows


def _filestore_audit_database_summary(
    files: list[dict[str, Any]],
    total_size: int,
) -> dict[str, Any]:
    """Summarize referenced, unreferenced, and trashed file counts and sizes."""
    exists_file_count = 0
    exists_size = 0
    resource_in_trash_file_count = 0
    resource_in_trash_size = 0

    # Trashed resources are also database references, so these categories overlap.
    for item in files:
        if item["exists_in_database"]:
            exists_file_count += 1
            exists_size += item["size_bytes"]
        if item["resource_in_trash"]:
            resource_in_trash_file_count += 1
            resource_in_trash_size += item["size_bytes"]

    # Unreferenced totals are the remainder of the scanned inventory.
    not_exists_file_count = len(files) - exists_file_count
    not_exists_size = total_size - exists_size

    return {
        "exists_in_database_file_count": exists_file_count,
        "exists_in_database_size_bytes": exists_size,
        "exists_in_database_size_human": localized_filesize(exists_size),
        "exists_in_database_percentage": (
            f"{exists_size / total_size * 100:.2f}" if total_size else "0.00"
        ),
        "resource_in_trash_file_count": resource_in_trash_file_count,
        "resource_in_trash_size_bytes": resource_in_trash_size,
        "resource_in_trash_size_human": localized_filesize(
            resource_in_trash_size
        ),
        "resource_in_trash_percentage": (
            f"{resource_in_trash_size / total_size * 100:.2f}"
            if total_size
            else "0.00"
        ),
        "not_exists_in_database_file_count": not_exists_file_count,
        "not_exists_in_database_size_bytes": not_exists_size,
        "not_exists_in_database_size_human": localized_filesize(not_exists_size),
        "not_exists_in_database_percentage": (
            f"{not_exists_size / total_size * 100:.2f}"
            if total_size
            else "0.00"
        ),
    }


def _filestore_audit_missing_resource_rows(
    storage_path: str,
) -> list[dict[str, Any]]:
    """Build report rows for uploaded resources whose expected files are missing."""
    resources = (
        model.Session.query(model.Resource)
        .filter(model.Resource.url_type == "upload")
        .order_by(model.Resource.id)
        .all()
    )
    rows: list[dict[str, Any]] = []

    for resource in resources:
        # Use CKAN's upload path and report only missing files.
        expected_file_path = _filestore_audit_resource_path(resource.id)
        if os.path.exists(expected_file_path):
            continue

        # Include dataset and owner details to help identify the missing upload.
        package = resource.package
        organization = (
            model.Group.get(package.owner_org)
            if package and package.owner_org
            else None
        )
        resource_size = resource.size

        rows.append(
            {
                "resource_id": resource.id,
                "resource_name": resource.name or "",
                "resource_state": resource.state or "",
                "resource_url": (
                    f"/dataset/{package.name}/resource/{resource.id}"
                    if package
                    else ""
                ),
                "resource_size_bytes": (
                    resource_size if resource_size is not None else ""
                ),
                "resource_size_human": (
                    localized_filesize(resource_size)
                    if resource_size is not None
                    else ""
                ),
                "missing_file_relative_path": os.path.relpath(
                    expected_file_path, storage_path
                ),
                "expected_file_path": os.path.abspath(expected_file_path),
                "dataset_id": package.id if package else "",
                "dataset_title": package.title if package else "",
                "dataset_state": package.state if package else "",
                "organization_title": organization.title if organization else "",
                "data_owner": (
                    package.extras.get("data_owner", "") if package else ""
                ),
                "contact_point": (
                    package.extras.get("contact_point", "") if package else ""
                ),
            }
        )

    return rows


def _filestore_audit_scan_directory(
    absolute_root: str,
    namespace: str,
    ignored_paths: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Recursively inventory regular files, skipping symlinks and collecting errors."""
    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    absolute_root = os.path.abspath(absolute_root)

    if not os.path.exists(absolute_root):
        return files, errors
    if not os.path.isdir(absolute_root):
        return files, [
            {
                "path": os.path.abspath(absolute_root),
                "error": "Configured scan path is not a directory",
            }
        ]

    # Traverse subdirectories using a stack of absolute paths.
    stack = [absolute_root]
    while stack:
        abs_dir = stack.pop()
        try:
            with os.scandir(abs_dir) as entries:
                for entry in entries:
                    # Prune excluded directories before descending into them.
                    is_ignored = False
                    if ignored_paths:
                        for ignored_path in ignored_paths:
                            if _filestore_audit_is_in_path(entry.path, ignored_path):
                                is_ignored = True
                                break

                    if is_ignored:
                        continue
                    try:
                        # Skip links so their targets are not counted again.
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        # Record regular files only; directories have no inventory row.
                        if entry.is_file(follow_symlinks=False):
                            files.append(
                                _filestore_audit_file_row(
                                    namespace,
                                    entry.path,
                                )
                            )
                    # Record the error and continue with other accessible paths.
                    except OSError as e:
                        errors.append(
                            {
                                "path": os.path.abspath(entry.path),
                                "error": repr(e),
                            }
                        )
        # Record the error and continue with other accessible paths.
        except OSError as e:
            errors.append(
                {
                    "path": os.path.abspath(abs_dir),
                    "error": repr(e),
                }
            )

    return files, errors


def _filestore_audit_scan(storage_path: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Scan known storage roots and classify unmatched files there as UNKNOWN."""
    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    # Full namespace directories to exclude from the later UNKNOWN scan.
    # Example: /app/filestore/resources.
    orphanage_paths = {_filestore_audit_orphanage_path()}
    known_paths: set[str] = set(orphanage_paths)
    namespaces = _filestore_audit_namespaces()
    for namespace in namespaces.values():
        relative_path = namespace["path"]
        if relative_path.strip("/"):
            known_paths.add(os.path.join(storage_path, relative_path))

    # Scan each configured directory with its own namespace label.
    for name, namespace in namespaces.items():
        relative_root = namespace["path"]
        namespace_files, namespace_errors = _filestore_audit_scan_directory(
            os.path.join(storage_path, relative_root),
            name,
            ignored_paths=orphanage_paths,
        )
        files.extend(namespace_files)
        errors.extend(namespace_errors)

    # Deduplicate top-level roots: currently resources/ and storage/.
    scan_roots: set[str] = set()
    for namespace in namespaces.values():
        relative_path = namespace["path"]
        root_directory = relative_path.split("/", 1)[0]
        scan_roots.add(os.path.join(storage_path, root_directory))
    # Collect remaining files under these roots without recounting known paths.
    for root in sorted(scan_roots):
        unknown_files, unknown_errors = _filestore_audit_scan_directory(
            root,
            "UNKNOWN",
            ignored_paths=known_paths,
        )
        files.extend(unknown_files)
        errors.extend(unknown_errors)

    # Keep report order stable regardless of filesystem traversal order.
    files.sort(key=lambda item: item["path"])
    errors.sort(key=lambda item: item["path"])
    return files, errors


def _filestore_audit_write_csv(
    csv_path: str, fieldnames: list[str], rows: list[dict[str, Any]]
) -> None:
    """Write report rows to a UTF-8 CSV file with the specified column order."""
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _filestore_audit_namespace_summary(
    storage_path: str, files: list[dict[str, Any]], total_size: int
) -> list[dict[str, Any]]:
    """Group inventory files by namespace and calculate each namespace summary."""
    # Include empty namespaces and a bucket for unmatched files.
    namespace_paths: dict[str, str] = {}
    for name, namespace in _filestore_audit_namespaces().items():
        namespace_paths[name] = namespace["path"]
    namespace_paths["UNKNOWN"] = ""
    files_by_namespace: dict[str, list[dict[str, Any]]] = {}
    for name in namespace_paths:
        files_by_namespace[name] = []
    for item in files:
        files_by_namespace[item["namespace"]].append(item)

    rows: list[dict[str, Any]] = []
    # Reuse the reference calculation with each namespace as its scope.
    for name, relative_path in namespace_paths.items():
        namespace_files = files_by_namespace[name]
        namespace_size = 0
        for item in namespace_files:
            namespace_size += item["size_bytes"]
        percentage = namespace_size / total_size * 100 if total_size else 0
        rows.append(
            {
                "namespace": name,
                "path": (
                    os.path.join(storage_path, relative_path)
                    if relative_path
                    else storage_path
                ),
                "file_count": len(namespace_files),
                "size_bytes": namespace_size,
                "size_human": localized_filesize(namespace_size),
                "percentage_of_filestore": f"{percentage:.2f}",
                **_filestore_audit_database_summary(
                    namespace_files, namespace_size
                ),
            }
        )

    return sorted(rows, key=lambda row: (-row["size_bytes"], row["namespace"]))
