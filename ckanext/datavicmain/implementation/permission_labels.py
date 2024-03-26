from __future__ import annotations

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan import model
from ckan.lib.plugins import DefaultPermissionLabels

from ckanext.datavicmain import utils


class PermissionLabels(p.SingletonPlugin, DefaultPermissionLabels):
    p.implements(p.IPermissionLabels)

    def get_dataset_labels(self, dataset_obj: model.Package) -> list[str]:
        labels: list[str] = []

        if utils.is_org_restricted(dataset_obj.owner_org):
            labels.append(_org_restriction_label(dataset_obj.owner_org))
        else:
            labels.append("public")

        if tk.config["ckan.auth.allow_dataset_collaborators"]:
            labels.append(f"collaborator-{dataset_obj.id}")

        return labels

    def get_user_dataset_labels(self, user_obj: model.User) -> list[str]:
        labels: list[str] = super().get_user_dataset_labels(user_obj)

        if not user_obj or user_obj.is_anonymous:
            return labels

        for org in _get_user_orgs_ids(user_obj.name):
            if not utils.is_org_restricted(org["id"]):
                continue

            labels.append(_org_restriction_label(org["id"]))

        if tk.config["ckan.auth.allow_dataset_collaborators"]:
            datasets = tk.get_action("package_collaborator_list_for_user")(
                {"ignore_auth": True}, {"id": user_obj.id}
            )

            labels.extend(
                "collaborator-%s" % d["package_id"] for d in datasets
            )

        return labels


def _org_restriction_label(org_id: str) -> str:
    """View access for risk."""
    return f"vicmain-restricted-org-{org_id}"


def _get_user_orgs_ids(user_name: str) -> list[str]:
    """Return a list of organisation ids available to a user"""

    return tk.get_action("organization_list_for_user")(
        {
            "model": model,
            "session": model.Session,
            "user": user_name,
        },
        {"permission": "read"},
    )
