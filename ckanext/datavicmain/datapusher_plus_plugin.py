# DataPusher+: fills the trigger gap in ckanext-datapusher-plus for
# resources that arrive via ``package_create``/``package_update`` (e.g.
# harvesters).
#
# CKAN core does not call ``after_resource_create`` for resources created
# inline via ``package_create``/``package_update``, and
# ``IResourceUrlChange.notify`` only fires for *changed* URLs, not new
# resources. DataPusher+'s vanilla triggers therefore miss every resource
# coming in via a harvest.
#
# ``IDomainObjectModification.notify`` does fire for new Resource entities
# regardless of how they were created (see
# ``ckan.model.modification.DomainObjectModificationExtension``), so we
# hook in there for the ``new`` case only. ``changed`` URL updates are
# already covered by the parent plugin's ``IResourceUrlChange.notify``;
# direct ``resource_create`` API calls are already covered by the parent's
# ``after_resource_create``. The parent's ``task_status_show``
# "pending/submitting" guard in ``_submit_to_datapusher`` makes the
# overlap with ``after_resource_create`` safely idempotent.
#
# This mirrors the upstream xloader fix in
# https://github.com/ckan/ckanext-xloader/pull/265 (open as of 2025-11).
from __future__ import annotations

import logging

import ckan.plugins as p
import ckan.plugins.toolkit as toolkit
from ckan.model.domain_object import DomainObjectOperation
from ckan.model.resource import Resource

from ckanext.datapusher_plus.plugin import DatapusherPlusPlugin

log = logging.getLogger(__name__)


class DatavicDatapusherPlusPlugin(DatapusherPlusPlugin, p.SingletonPlugin):
    p.implements(p.IDomainObjectModification)

    # IDomainObjectModification
    def notify(self, entity, operation):
        """Submit *new* Resource entities to DataPusher+.

        Fires for resources created via ``package_create`` /
        ``package_update`` with inline resources (the harvester path),
        which the parent plugin's ``after_resource_create`` /
        ``IResourceUrlChange.notify`` triggers miss.

        ``changed`` and ``deleted`` are intentionally ignored: URL changes
        are handled by the parent's ``IResourceUrlChange.notify``; deletes
        don't need a DataPusher+ run.
        """
        if not isinstance(entity, Resource):
            return
        if operation != DomainObjectOperation.new:
            return

        try:
            resource_dict = toolkit.get_action("resource_show")(
                {"ignore_auth": True}, {"id": entity.id}
            )
        except toolkit.ObjectNotFound:
            return

        self._infer_format_and_submit(resource_dict)

    def _infer_format_and_submit(self, resource):
        """Infer the resource format from its URL if missing, then submit.

        DataPusher+'s ``_submit_to_datapusher`` silently no-ops when
        ``format`` is missing (see ``DatapusherPlusPlugin._submit_to_datapusher``).
        Harvested resources frequently arrive without a format set, so
        without this fallback they would never reach the download stage
        that could detect a mimetype.
        """
        if resource and not resource.get("format"):
            if not resource.get("url_type"):
                url_without_params = resource.get("url", "").split("?")[0]
                resource["format"] = (
                    url_without_params.split(".")[-1].lower()
                )
        self._submit_to_datapusher(resource)
