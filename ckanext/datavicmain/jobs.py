from __future__ import annotations
from itertools import chain

import os
import requests
import logging

from ckan import model
from ckan.lib.search import rebuild, commit

log = logging.getLogger(__name__)


def reindex_organization(id_or_name: str) -> None:
    """Rebuild search index for all datasets inside the organization."""
    org = model.Group.get(id_or_name)

    if not org:
        log.warning("Organization with ID or name %s not found", id_or_name)
        return

    rebuild(package_ids=_get_related_package_ids(org), force=True)
    commit()


def _get_related_package_ids(org: model.Group) -> list[str]:
    child_groups = org.get_children_group_hierarchy("organization")

    package_ids: list[str] = [
        p.id
        for p in model.Session.query(model.Package.id)
        .filter_by(state=model.State.ACTIVE)
        .filter_by(owner_org=org.id)
    ]

    child_package_ids = list(
        chain.from_iterable([
            [
                pkg.id
                for pkg in model.Session.query(model.Package.id).filter_by(
                    owner_org=org[0]
                )
            ]
            for org in child_groups
        ])
    )

    return package_ids + child_package_ids


def ckan_worker_job_monitor():
    monitor_url = os.environ.get("MONITOR_URL_JOBWORKER")
    try:
        if monitor_url:
            log.info(f"Sending notification for CKAN worker job monitor")
            requests.get(monitor_url, timeout=10)
            log.info(
                f"Successfully sent notification for CKAN worker job monitor"
            )
        else:
            log.error(
                f"The env variable MONITOR_URL_JOBWORKER is not set for CKAN worker job monitor"
            )
    except requests.RequestException as e:
        log.error(
            f"Failed to send CKAN worker job monitor notification to {monitor_url}"
        )
        log.error(str(e))
