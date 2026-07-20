from __future__ import annotations

import csv
import datetime
import logging
import os
from typing import Iterator

import click

import ckan.model as model
import ckan.plugins.toolkit as tk
from ckanext.harvest.model import HarvestObject, HarvestSource
from ckanext.syndicate.plugin import CONFIG_SYNC_ON_CHANGES

log = logging.getLogger(__name__)

DEFAULT_DD_CUSTODIAN_REPORT_DIR = (
    "/app/filestore/backfill_dd_custodian_reports"
)
DEFAULT_DD_CUSTODIAN_BATCH_SIZE = 500
DEFAULT_DD_CONTACT_POINT = "https://www.data.vic.gov.au/contact-us"

DD_HARVEST_SOURCE_FIELD_VALUES = {
    "barwon-water": (
        "info@barwonwater.vic.gov.au",
        "Barwon Water",
    ),
    "central-highlands-water": (
        "BusinessSystems@chw.net.au",
        "Central Highlands Water",
    ),
    "city-of-ballarat-ods": (
        "info@ballarat.vic.gov.au",
        "City of Ballarat",
    ),
    "city-of-casey-ods": (
        "https://data.casey.vic.gov.au/pages/how-to-guides",
        "City of Casey",
    ),
    "city-of-melbourne-ods": (
        "https://data.melbourne.vic.gov.au/pages/contact_us_form",
        "City of Melbourne",
    ),
    "delwp-harvester": (
        "https://datashare.maps.vic.gov.au/contact-us",
        None,
    ),
    "dtp-data-portal": (
        "https://opendata.transport.vic.gov.au/Help-And-Support",
        "Department of Transport and Planning",
    ),
    "geelong-ods": (
        "https://www.geelongdataexchange.com.au/pages/feedback",
        "City of Greater Geelong",
    ),
    "melbourne-water-data-json": (
        "enquiry@melbournewater.com.au",
        "Melbourne Water Corporation",
    ),
}

DD_CUSTODIAN_REPORT_COLUMNS = [
    "dataset_id",
    "dataset_name",
    "dataset_state",
    "harvest_source",
    "action",
    "contact_point",
    "contact_point_action",
    "data_owner",
    "data_owner_action",
    "error",
]


# Load DD package rows in small ordered chunks and resolve harvest sources per
# chunk so large portals are not materialised in memory.
def _iter_dd_dataset_rows(
    batch_size: int,
) -> Iterator[tuple[str, str, str, str, str]]:
    last_id = ""

    while True:
        rows = (
            model.Session.query(
                model.Package.id,
                model.Package.name,
                model.Package.state,
                model.Package.owner_org,
                model.Group.name,
                model.Group.title,
            )
            .outerjoin(model.Group, model.Package.owner_org == model.Group.id)
            .filter(model.Package.type == "dataset")
            .filter(model.Package.id > last_id)
            .order_by(model.Package.id)
            .limit(batch_size)
            .all()
        )
        if not rows:
            return

        harvest_sources = _harvest_sources_for_package_ids(
            [row[0] for row in rows]
        )
        for row in rows:
            last_id = row[0]
            org_label = row[5] or row[4] or row[3] or "unknown"
            yield (
                row[0],
                row[1],
                row[2],
                org_label,
                harvest_sources.get(row[0], ""),
            )


# Resolve one harvest source package name per package, preferring a source that
# has a dedicated mapping if historical harvest objects point at multiple
# sources.
def _harvest_sources_for_package_ids(package_ids: list[str]) -> dict[str, str]:
    if not package_ids:
        return {}

    sources: dict[str, str] = {}
    rows = (
        model.Session.query(
            HarvestObject.package_id,
            model.Package.name,
            HarvestSource.id,
            HarvestSource.title,
        )
        .join(
            HarvestSource,
            HarvestObject.harvest_source_id == HarvestSource.id,
        )
        .join(model.Package, HarvestSource.id == model.Package.id)
        .filter(HarvestObject.package_id.in_(package_ids))
        .order_by(HarvestObject.package_id)
        .all()
    )

    for package_id, source_name, source_id, source_title in rows:
        source = source_name or source_id or source_title or ""
        if not source:
            continue
        if package_id not in sources:
            sources[package_id] = source
            continue
        if (
            sources[package_id] not in DD_HARVEST_SOURCE_FIELD_VALUES
            and source in DD_HARVEST_SOURCE_FIELD_VALUES
        ):
            sources[package_id] = source

    return sources


# Build the two custodian field values for mapped harvest sources or the DD
# default, using the organisation label where the rules require it.
def _dd_custodian_values(
    harvest_source: str,
    org_label: str,
) -> tuple[str, str, bool]:
    if harvest_source in DD_HARVEST_SOURCE_FIELD_VALUES:
        contact_point, data_owner = DD_HARVEST_SOURCE_FIELD_VALUES[
            harvest_source
        ]
        return (
            contact_point,
            data_owner or org_label,
            True,
        )

    return (
        DEFAULT_DD_CONTACT_POINT,
        org_label,
        False,
    )


# Decide whether one custodian field should be changed. Existing
# whitespace-only values are treated as empty.
def _dd_custodian_extra_action(
    package_id: str,
    key: str,
    value: str,
    override_existing: bool,
) -> str:
    existing = (
        model.Session.query(model.PackageExtra)
        .filter_by(package_id=package_id, key=key)
        .first()
    )
    if existing:
        current = existing.value or ""
        if existing.value == value and existing.state == "active":
            return "unchanged"
        if not override_existing and current.strip():
            return "skipped_existing"
        return "updated"

    return "inserted"


# Collapse per-field outcomes to one report action for the dataset.
def _dd_custodian_row_action(
    field_actions: list[str],
    dry_run: bool,
) -> str:
    if any(action in ("inserted", "updated") for action in field_actions):
        return "would_backfill" if dry_run else "updated"
    if all(action == "skipped_existing" for action in field_actions):
        return "skipped_existing"
    return "unchanged"


# Resolve the affected-datasets CSV destination.
def _dd_custodian_report_path(report_path: str | None) -> str:
    if report_path:
        return report_path
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(
        DEFAULT_DD_CUSTODIAN_REPORT_DIR.rstrip("/"),
        f"backfill_dd_custodian_fields_{ts}.csv",
    )


# Write contact_point and data_owner directly to package_extra via ORM,
# bypassing package_update to avoid validation and IPackageController hooks.
# Syndication is suppressed by the caller disabling CONFIG_SYNC_ON_CHANGES for
# the duration of the run. Session is committed by the caller per batch.
def _package_update_custodian_fields(
    dataset_id: str,
    contact_point: str,
    data_owner: str,
    contact_point_action: str,
    data_owner_action: str,
) -> None:
    updates = {}
    if contact_point_action in ("inserted", "updated"):
        updates["contact_point"] = contact_point
    if data_owner_action in ("inserted", "updated"):
        updates["data_owner"] = data_owner

    if not updates:
        return

    for key, value in updates.items():
        extra = (
            model.Session.query(model.PackageExtra)
            .filter_by(package_id=dataset_id, key=key)
            .first()
        )
        if extra:
            extra.value = value
            extra.state = "active"
        else:
            model.Session.add(
                model.PackageExtra(
                    package_id=dataset_id,
                    key=key,
                    value=value,
                    state="active",
                )
            )


@click.command("backfill-dd-custodian-fields")
@click.option(
    "--execute",
    "do_execute",
    is_flag=True,
    default=False,
    help="Write backfilled values. Without this flag the command is a dry-run.",
)
@click.option(
    "--override-existing",
    is_flag=True,
    default=False,
    help=(
        "Overwrite existing non-empty values. By default only missing or "
        "whitespace-only values are populated."
    ),
)
@click.option(
    "--batch-size",
    default=DEFAULT_DD_CUSTODIAN_BATCH_SIZE,
    show_default=True,
    type=click.IntRange(min=1),
    help="Number of DD dataset rows to load from the database per batch.",
)
@click.option(
    "--report-path",
    default=None,
    type=click.Path(),
    help=(
        "Path for the affected-datasets CSV report. Defaults to "
        "<DEFAULT_DD_CUSTODIAN_REPORT_DIR>/"
        "backfill_dd_custodian_fields_<timestamp>.csv."
    ),
)
def backfill_dd_custodian_fields(
    do_execute: bool,
    override_existing: bool,
    batch_size: int,
    report_path: str | None,
) -> None:
    """Backfill contact_point and data_owner extras for DD datasets."""
    mode = "EXECUTE" if do_execute else "DRY-RUN"
    click.secho(
        f"=== Backfill DD custodian fields [{mode}] ===\n",
        fg="cyan",
        bold=True,
    )
    click.secho(
        "Existing values: "
        + (
            "overwrite non-empty values"
            if override_existing
            else "populate empty values only"
        ),
        fg="blue",
    )

    report_path = _dd_custodian_report_path(report_path)
    report_dir = os.path.dirname(report_path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)

    _syndicate_original = tk.config.get(CONFIG_SYNC_ON_CHANGES)
    tk.config[CONFIG_SYNC_ON_CHANGES] = False

    counters = {
        "checked": 0,
        "harvest_source_mapped": 0,
        "default_mapped": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped_existing": 0,
        "errors": 0,
        "report_rows": 0,
    }

    with open(report_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=DD_CUSTODIAN_REPORT_COLUMNS)
        writer.writeheader()

        # Stream package rows and apply the source-specific or default mapping.
        for (
            dataset_id,
            dataset_name,
            dataset_state,
            org_label,
            harvest_source,
        ) in _iter_dd_dataset_rows(batch_size):
            counters["checked"] += 1
            if counters["checked"] % batch_size == 0:
                if do_execute:
                    model.Session.commit()
                click.secho(
                    f"  Checked {counters['checked']} DD datasets...",
                    fg="blue",
                )

            contact_point, data_owner, mapped = _dd_custodian_values(
                harvest_source,
                org_label,
            )
            if mapped:
                counters["harvest_source_mapped"] += 1
            else:
                counters["default_mapped"] += 1

            row = {
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "dataset_state": dataset_state,
                "harvest_source": harvest_source,
                "action": "",
                "contact_point": contact_point,
                "contact_point_action": "",
                "data_owner": data_owner,
                "data_owner_action": "",
                "error": "",
            }

            # Use the same field decision path for dry-run and execute.
            try:
                data_owner_result = _dd_custodian_extra_action(
                    dataset_id,
                    "data_owner",
                    data_owner,
                    override_existing,
                )
                contact_point_result = _dd_custodian_extra_action(
                    dataset_id,
                    "contact_point",
                    contact_point,
                    override_existing,
                )
                row["data_owner_action"] = data_owner_result
                row["contact_point_action"] = contact_point_result
                row["action"] = _dd_custodian_row_action(
                    [data_owner_result, contact_point_result],
                    dry_run=not do_execute,
                )

                if do_execute and row["action"] == "updated":
                    _package_update_custodian_fields(
                        dataset_id,
                        contact_point,
                        data_owner,
                        contact_point_result,
                        data_owner_result,
                    )

                if row["action"] in ("would_backfill", "updated"):
                    counters["updated"] += 1
                    writer.writerow(row)
                    counters["report_rows"] += 1
                elif row["action"] == "skipped_existing":
                    counters["skipped_existing"] += 1
                else:
                    counters["unchanged"] += 1
            except Exception as exc:
                counters["errors"] += 1
                model.Session.rollback()
                row["action"] = "error"
                row["error"] = str(exc)
                writer.writerow(row)
                counters["report_rows"] += 1
                log.error(
                    "Failed to backfill DD custodian fields for %s (%s): %s",
                    dataset_name,
                    dataset_id,
                    exc,
                )
                click.secho(
                    f"  ERROR updating {dataset_name}: {exc}",
                    fg="red",
                )

    try:
        if do_execute:
            model.Session.commit()
    finally:
        tk.config[CONFIG_SYNC_ON_CHANGES] = _syndicate_original

    # Print a compact operational summary after all rows have been scanned.
    click.secho("\n--- Summary ---", fg="cyan", bold=True)
    click.secho(f"  Checked:               {counters['checked']}", fg="blue")
    click.secho(
        "  Harvest-source mapped: "
        f"{counters['harvest_source_mapped']}",
        fg="green",
    )
    click.secho(
        f"  Default mapped:        {counters['default_mapped']}",
        fg="yellow",
    )
    click.secho(f"  Updated:               {counters['updated']}", fg="green")
    click.secho(f"  Unchanged:             {counters['unchanged']}", fg="blue")
    click.secho(
        f"  Skipped existing:      {counters['skipped_existing']}",
        fg="blue",
    )
    click.secho(
        f"  Errors:                {counters['errors']}",
        fg="red" if counters["errors"] else "green",
    )
    click.secho(
        f"  Report rows:           {counters['report_rows']}",
        fg="blue",
    )
    click.secho(f"\nAffected-datasets report written to: {report_path}", fg="green")
