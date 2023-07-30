from __future__ import annotations

import datetime
import logging
import csv
from os import path
from typing import Any
from itertools import groupby

import click
import tqdm

import ckan.logic as logic
import ckan.model as model
from ckan.types import Context
import ckan.plugins.toolkit as tk
from ckan.model import Resource, ResourceView
from ckan.lib.munge import munge_title_to_name

from ckanext.harvest.model import HarvestObject, HarvestSource


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
        click.secho(
            "No resources have been found",
            fg="green"
        )
        return click.secho(
            "NOTE: `datatables_view` works only with resources uploaded to datastore",
            fg="green"
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
    search = tk.get_action("datastore_search")
    ctx = {"ignore_auth": True}
    data_dict = {
        "resource_id": resource_id,
        "limit": 0,
        "include_total": False,
    }
    fields = [field for field in search(ctx, data_dict)["fields"]]
    return [f["id"] for f in fields]


def _delete_recline_views(res_views: list[ResourceView]):
    for view in res_views:
        if view.view_type != "recline_view":
            continue
        view.delete()
    model.repo.commit()


@maintain.command(u"clean-delwp-datasets",
                  short_help=u"Purge deleted DELWP datasets")
def clean_delwp_datasets():
    """
    Purge datasets added from the DELWP harvest and deleted after
    their updating in order to remove their duplicates from DB entirely and
    make their correct names available
    """

    click.secho(u"Searching for deleted DELWP datasets...")

    datasets_deleted = model.Session.query(model.Package.id, model.Package.name) \
        .join(HarvestObject, model.Package.id == HarvestObject.package_id) \
        .join(HarvestSource, HarvestObject.harvest_source_id == HarvestSource.id) \
        .filter(HarvestSource.type == 'delwp') \
        .filter(model.Package.state == model.State.DELETED) \
        .with_entities(model.Package.id).distinct().all()

    click.secho(
        f"{len(datasets_deleted)} deleted DELWP datasets have been found.",
        fg="green",
    )
    click.secho(u"Purging datasets...", fg="green")

    counter = 0
    for dataset in datasets_deleted:
        dataset_id = dataset[0]
        try:
            site_user = logic.get_action(u'get_site_user')({u'ignore_auth': True}, {})
            context: Context = {u'user': site_user[u'name'], u'ignore_auth': True}
            logic.get_action(u'dataset_purge')(context, {u'id': dataset_id})
        except tk.ObjectNotFound as e:
            click.secho(f"Error purging <{dataset_id}> dataset: {e}", fg="red")
        else:
            click.secho(f"Dataset <{dataset_id}> has been purged", fg="green")
            counter += 1

    model.Session.commit()

    click.secho(f"Done. {counter} DELWP datasets have been purged.", fg="green")


@maintain.command(u"rename-delwp-datasets",
                  short_help=u"Rename active DELWP datasets")
def rename_delwp_datasets():
    """
    Rename active DELWP datasets in order to match their titles
    """

    used_names = [name[0] for name in model.Session.query(model.Package.name).all()]

    datasets_active = model.Session.query(model.Package.id, model.Package.title) \
        .join(HarvestObject, model.Package.id == HarvestObject.package_id) \
        .join(HarvestSource, HarvestObject.harvest_source_id == HarvestSource.id) \
        .filter(HarvestSource.type == 'delwp') \
        .filter(model.Package.state == model.State.ACTIVE) \
        .with_entities(model.Package.id, model.Package.title) \
        .distinct().order_by(model.Package.title).all()

    click.secho(
        f"{len(datasets_active)} active DELWP datasets have been found.",
        fg="green",
    )
    click.secho("Renaming datasets...", fg="green")

    field_name_length = 100
    counter = 0
    for k, grp in groupby(datasets_active, lambda x: x[1]):
        datasets = [dataset[0] for dataset in grp]
        dataset_id = datasets[0]
        pkg = model.Session.query(model.Package).get(dataset_id)
        cur_name = pkg.name
        new_name = munge_title_to_name(pkg.title)

        # Exclude active DELWP datasets with the same title
        if len(datasets) > 1:
            click.secho(
                f"Pay attention to these active duplicates with title <{pkg.title}>: "
                f"{datasets}",
                fg="yellow"
            )
            continue

        if pkg.name == new_name:
            continue
        if new_name in used_names or len(pkg.title) >= field_name_length:
            click.secho(
                f"Pay attention to this active dataset <{pkg.title}>"
                f"It may have a naming problem which could be resolved manually",
                fg="yellow"
            )
            continue

        pkg.name = new_name
        click.secho(
            f"The name of the DELWP dataset <{pkg.title}> has been changed "
            f"from {cur_name} to {new_name}",
            fg="green"
        )
        counter += 1

    model.Session.commit()

    click.secho(f"Done. {counter} DELWP datasets have been renamed.", fg="green")
