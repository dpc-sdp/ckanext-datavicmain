from __future__ import annotations

import os
import requests
import logging

from ckan import model
from ckan.lib.search import rebuild, commit

log = logging.getLogger(__name__)


def ckan_worker_job_monitor():
    monitor_url = os.environ.get('MONITOR_URL_JOBWORKER')
    try:
        if monitor_url:
            log.info(f'Sending notification for CKAN worker job monitor')
            requests.get(monitor_url, timeout=10)
            log.info(f'Successfully sent notification for CKAN worker job monitor')
        else:
            log.error(f'The env variable MONITOR_URL_JOBWORKER is not set for CKAN worker job monitor')
    except requests.RequestException as e:
        log.error(f'Failed to send CKAN worker job monitor notification to {monitor_url}')
        log.error(str(e))


def reindex_organization(id_or_name: str):
    """Rebuild search index for all datasets inside the organization.
    """
    org = model.Group.get(id_or_name)
    if not org:
        log.warning("Organization with ID or name %s not found", id_or_name)
        return

    query = model.Session.query(model.Package.id).filter_by(owner_org=org.id)

    rebuild(
        package_ids=(p.id for p in query),
        force=True
    )
    commit()
