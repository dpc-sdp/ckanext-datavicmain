from __future__ import annotations

import os
import logging
from typing import Any
from werkzeug.datastructures import FileStorage as FlaskFileStorage
import requests

import ckan.plugins.toolkit as tk
import ckan.model as model
from ckan.lib.uploader import get_resource_uploader
import ckanapi

from ckanext.syndicate.utils import get_target

CONFIG_INTERNAL_HOSTS = "ckan.datavic.syndication.internal_hosts"
DEFAULT_INTERNAL_HOSTS = []

log = logging.getLogger(__name__)


def after_syndication_listener(package_id, **kwargs):
    log.debug("Synchronizing uploaded files of %s", package_id)
    profile = kwargs["profile"]
    remote = kwargs["remote"]

    if "id" not in remote:
        log.debug("Cannot detect remote ID. Skip")
        return

    ckan = get_target(profile.ckan_url, profile.api_key)
    resources = remote.get("resources")

    pkg = model.Package.get(package_id)

    if not pkg:
        return

    hosts = tk.aslist(
        tk.config.get(CONFIG_INTERNAL_HOSTS, DEFAULT_INTERNAL_HOSTS)
    )

    hosts.append(profile.ckan_url)

    for res in resources:
        _update_remote_resource(res, hosts, pkg, ckan)


def _update_remote_resource(
    res: dict[str, Any],
    hosts: list[str],
    pkg: model.Package,
    ckan: ckanapi.RemoteCKAN,
) -> None:
    log.debug("Checking resource %s", res["id"])

    _synchronize_views(res, ckan)

    if not any(host in res["url"] for host in hosts):
        return log.debug("External resource with a url %s. Skip", res["url"])

    local_res = _get_original_resource(pkg.resources, res["id"])

    if not local_res:
        return log.debug(
            "Cannot locate resource with ID %s locally. Skip", res["id"]
        )

    check_res = requests.head(res["url"])

    if check_res.ok:
        remote_size = int(check_res.headers.get("Content-Length", 0))

        if remote_size == local_res.size:
            return log.debug("File already exists on remote portal. Skip")

    log.debug(
        "File does not exist or differ for %s resource, copying it.",
        res["id"],
    )

    uploader = get_resource_uploader(local_res.as_dict())

    try:
        with open(uploader.get_path(local_res.id), "rb") as file_data:
            name = os.path.basename(local_res.url)

            ckan.action.resource_patch(
                id=res["id"],
                upload=FlaskFileStorage(file_data, name, name),
                size=None,
                url=local_res.url,
            )
    except Exception:
        log.exception(
            "Cannot upload file from local resource %s to the remote %s",
            local_res.id,
            res["id"],
        )


def _get_original_resource(
    resources: list[model.Resource], res_id: str
) -> model.Resource | None:
    for resource in resources:
        if resource.id != res_id:
            continue

        return resource


def _synchronize_views(res: dict[str, Any], ckan: ckanapi.RemoteCKAN):
    """Recreate public views if they are not the same as internal."""
    remote = ckan.action.resource_view_list(id=res["id"])
    local = tk.get_action("resource_view_list")(
        {"ignore_auth": True}, {"id": res["id"]}
    )

    if len(remote) == len(local) and all(
        _view_data(left) == _view_data(right)
        for left, right in zip(local, remote)
    ):
        log.debug("Skip view synchronization because views are identical")
        return

    for view in remote:
        ckan.action.resource_view_delete(id=view["id"])

    for view in local:
        data = _view_data(view)
        try:
            ckan.action.resource_view_create(**data)
        except ckanapi.ValidationError as e:
            log.error("Cannot synchronize view %s: %s", view["id"], e)


def _view_data(view: dict[str, Any]) -> dict[str, Any]:
    """Extract fields allowed by view_create schema."""
    return {
        f: view[f]
        for f in [
            "description",
            "filter_fields",
            "filter_values",
            "resource_id",
            "title",
            "view_type",
        ]
        if f in view
    }
