# IAR xloader: extends ckanext-xloader with new-resource-only submissions on update.
from __future__ import annotations

import logging

import ckan.plugins as p
import ckan.plugins.toolkit as toolkit

from ckanext.xloader.plugin import xloaderPlugin

log = logging.getLogger(__name__)


class DatavicIARXLoaderPlugin(xloaderPlugin, p.SingletonPlugin):
    p.implements(p.IPackageController, inherit=True)

    # IPackageController
    def after_dataset_create(self, context, pkg_dict):
        self._trigger_after_resource_create(pkg_dict)

    def after_dataset_update(self, context, pkg_dict):
        self._submit_new_resources_only(pkg_dict)

    def _submit_new_resources_only(self, pkg_dict):
        """Submit only newly added resources to xloader during dataset update.

        Compares current resource IDs against the previous activity snapshot
        to detect new resources. URL changes for existing resources are
        handled by the parent xloaderPlugin via ``notify()``.

        Falls back to submitting all resources if no activity data is
        available (e.g. activity plugin disabled, data migration).
        """
        current_resources = pkg_dict.get("resources", [])
        current_res_ids = {
            r.get("id") for r in current_resources if r.get("id")
        }

        previous_res_ids = self._get_previous_resource_ids(pkg_dict.get("id"))

        if previous_res_ids is None:
            log.info(
                "No previous activity for package %s — "
                "submitting all %d resources",
                pkg_dict.get("id"),
                len(current_resources),
            )
            for resource in current_resources:
                self._infer_format_and_submit(resource)
            return

        new_res_ids = current_res_ids - previous_res_ids

        if not new_res_ids:
            return

        log.info(
            "Detected %d new resource(s) for package %s: %s",
            len(new_res_ids),
            pkg_dict.get("id"),
            new_res_ids,
        )

        for resource in current_resources:
            if resource.get("id") in new_res_ids:
                self._infer_format_and_submit(resource)

    def _get_previous_resource_ids(self, pkg_id):
        """Return resource IDs from the most recent activity, or ``None``
        if unavailable.
        """
        if not pkg_id or not p.plugin_loaded("activity"):
            return None

        try:
            activities = toolkit.get_action("package_activity_list")(
                {"ignore_auth": True},
                {
                    "id": pkg_id,
                    "limit": 1,
                    "include_hidden_activity": True,
                },
            )
        except Exception:
            return None

        if not activities:
            return None

        prev_pkg = activities[0].get("data", {}).get("package", {})
        prev_resources = prev_pkg.get("resources", [])
        return {r.get("id") for r in prev_resources if r.get("id")}

    def _infer_format_and_submit(self, resource):
        """Infer the resource format from its URL if missing, then submit."""
        if resource and not resource.get("format"):
            if not resource.get("url_type"):
                url_without_params = resource.get("url", "").split("?")[0]
                resource["format"] = (
                    url_without_params.split(".")[-1].lower()
                )
        self._submit_to_xloader(resource)

    def _trigger_after_resource_create(self, pkg_dict):
        """Submit all resources after dataset creation.

        Syndication via ``package_create`` does not trigger
        ``after_resource_create``, so we handle it here.
        """
        for resource in pkg_dict.get("resources", []):
            self._infer_format_and_submit(resource)

    def _submit_to_xloader(self, resource_dict):
        """Wrapper that ensures ``url_type`` and ``format`` are present
        before calling the parent, as they may be missing for resources
        created inline via ``package_create``/``package_update``.
        """
        resource_dict.setdefault("url_type", "datavic_xloader")
        resource_dict.setdefault("format", "")

        super()._submit_to_xloader(resource_dict)

        if resource_dict["url_type"] == "datavic_xloader":
            resource_dict.pop("url_type")
