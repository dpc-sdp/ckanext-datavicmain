"""Unit tests for :class:`DatavicDatapusherPlusPlugin`.

These tests exercise the dispatch logic in ``notify`` and the format
inference in ``_infer_format_and_submit`` directly, so they don't need
the CKAN DB stack or a loaded DataPusher+. The parent's
``_submit_to_datapusher`` is patched on the instance to assert exactly
when (and with what) it would be invoked.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ckan.model.domain_object import DomainObjectOperation
from ckan.model.resource import Resource
from ckan.plugins import toolkit

from ckanext.datavicmain.datapusher_plus_plugin import (
    DatavicDatapusherPlusPlugin,
)

PLUGIN_MODULE = "ckanext.datavicmain.datapusher_plus_plugin"


@pytest.fixture
def plugin(mocker):
    instance = DatavicDatapusherPlusPlugin()
    mocker.patch.object(instance, "_submit_to_datapusher")
    return instance


@pytest.fixture
def resource_entity():
    """A SQLAlchemy ``Resource``-shaped mock that passes ``isinstance``."""
    entity = MagicMock(spec=Resource)
    entity.id = "res-1"
    return entity


class TestNotifyDispatch:
    """``notify`` should only call ``_submit_to_datapusher`` for *new*
    ``Resource`` entities — every other path is the parent plugin's
    responsibility (or no-op)."""

    def test_ignores_non_resource_entities(self, plugin, mocker):
        get_action = mocker.patch(f"{PLUGIN_MODULE}.toolkit.get_action")
        not_a_resource = MagicMock()  # no spec=Resource

        plugin.notify(not_a_resource, DomainObjectOperation.new)

        get_action.assert_not_called()
        plugin._submit_to_datapusher.assert_not_called()

    def test_ignores_changed_resources(
        self, plugin, resource_entity, mocker
    ):
        # Parent's IResourceUrlChange.notify already handles URL changes;
        # duplicating here would rely on the task_status_show guard for
        # dedup. We avoid that on purpose.
        get_action = mocker.patch(f"{PLUGIN_MODULE}.toolkit.get_action")

        plugin.notify(resource_entity, DomainObjectOperation.changed)

        get_action.assert_not_called()
        plugin._submit_to_datapusher.assert_not_called()

    def test_ignores_deleted_resources(
        self, plugin, resource_entity, mocker
    ):
        get_action = mocker.patch(f"{PLUGIN_MODULE}.toolkit.get_action")

        plugin.notify(resource_entity, DomainObjectOperation.deleted)

        get_action.assert_not_called()
        plugin._submit_to_datapusher.assert_not_called()

    def test_new_resource_submits_with_resource_dict(
        self, plugin, resource_entity, mocker
    ):
        resource_dict = {
            "id": "res-1",
            "url": "https://example.com/data.csv",
            "format": "CSV",
        }
        resource_show = MagicMock(return_value=resource_dict)
        mocker.patch(
            f"{PLUGIN_MODULE}.toolkit.get_action", return_value=resource_show
        )

        plugin.notify(resource_entity, DomainObjectOperation.new)

        resource_show.assert_called_once_with(
            {"ignore_auth": True}, {"id": "res-1"}
        )
        plugin._submit_to_datapusher.assert_called_once_with(resource_dict)

    def test_new_resource_swallows_object_not_found(
        self, plugin, resource_entity, mocker
    ):
        # Race condition: an entity that appears in ``session._object_cache['new']``
        # may have already been rolled back / detached when we call ``resource_show``.
        resource_show = MagicMock(side_effect=toolkit.ObjectNotFound)
        mocker.patch(
            f"{PLUGIN_MODULE}.toolkit.get_action", return_value=resource_show
        )

        plugin.notify(resource_entity, DomainObjectOperation.new)

        plugin._submit_to_datapusher.assert_not_called()


class TestInferFormatAndSubmit:
    """``_infer_format_and_submit`` always submits — only the ``format`` it
    submits with varies. This fallback exists because DPP's
    ``_submit_to_datapusher`` silently no-ops on a missing format, which
    would drop any harvested resource that didn't carry one."""

    def test_existing_format_is_preserved(self, plugin):
        resource = {
            "id": "r",
            "url": "https://example.com/data.csv",
            "format": "XLSX",
        }

        plugin._infer_format_and_submit(resource)

        assert resource["format"] == "XLSX"
        plugin._submit_to_datapusher.assert_called_once_with(resource)

    def test_format_inferred_from_url_extension(self, plugin):
        resource = {"id": "r", "url": "https://example.com/data.CSV"}

        plugin._infer_format_and_submit(resource)

        assert resource["format"] == "csv"
        plugin._submit_to_datapusher.assert_called_once_with(resource)

    def test_format_inference_strips_query_string(self, plugin):
        resource = {
            "id": "r",
            "url": "https://example.com/data.json?token=abc&v=1",
        }

        plugin._infer_format_and_submit(resource)

        assert resource["format"] == "json"
        plugin._submit_to_datapusher.assert_called_once_with(resource)

    def test_empty_format_treated_as_missing(self, plugin):
        # ``resource.get("format")`` returns ``""`` for an explicitly empty
        # field, which the falsiness check should treat as missing.
        resource = {
            "id": "r",
            "url": "https://example.com/data.tsv",
            "format": "",
        }

        plugin._infer_format_and_submit(resource)

        assert resource["format"] == "tsv"
        plugin._submit_to_datapusher.assert_called_once_with(resource)

    def test_url_type_set_skips_inference(self, plugin):
        # When ``url_type`` is set (e.g. ``upload``), the CKAN-managed URL
        # doesn't carry the true file extension. Inferring would produce
        # garbage, so we leave ``format`` untouched and let DPP's
        # submission gate decide.
        resource = {
            "id": "r",
            "url": "https://example.com/dataset/res-1/download/x",
            "url_type": "upload",
        }

        plugin._infer_format_and_submit(resource)

        assert "format" not in resource
        plugin._submit_to_datapusher.assert_called_once_with(resource)

    def test_submit_called_even_without_inferable_format(self, plugin):
        # URL with no extension at all — falls through inference as the
        # path-segment ``data``. We still submit; DPP's gate handles the
        # final decision.
        resource = {"id": "r", "url": "https://example.com/data"}

        plugin._infer_format_and_submit(resource)

        plugin._submit_to_datapusher.assert_called_once_with(resource)


class TestNotifyEndToEnd:
    """The single happy path: a new harvested Resource hits ``_submit_to_datapusher``
    with ``format`` filled in from the URL when the harvester didn't set one."""

    def test_new_harvested_resource_without_format_is_inferred_and_submitted(
        self, plugin, resource_entity, mocker
    ):
        resource_dict = {
            "id": "res-1",
            "url": "https://harvest.example.com/dataset/file.geojson?v=2",
            # harvester left format unset
        }
        mocker.patch(
            f"{PLUGIN_MODULE}.toolkit.get_action",
            return_value=MagicMock(return_value=resource_dict),
        )

        plugin.notify(resource_entity, DomainObjectOperation.new)

        # ``_submit_to_datapusher`` is called with the mutated dict where
        # ``format`` has been inferred from the URL.
        plugin._submit_to_datapusher.assert_called_once()
        submitted = plugin._submit_to_datapusher.call_args[0][0]
        assert submitted["id"] == "res-1"
        assert submitted["format"] == "geojson"
