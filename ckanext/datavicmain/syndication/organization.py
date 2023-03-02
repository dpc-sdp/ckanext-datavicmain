import logging

import ckanapi

import ckan.model as model
import ckan.plugins.toolkit as toolkit

import ckanext.syndicate.utils as syndicate_utils
from ckanext.syndicate.interfaces import Profile


log = logging.getLogger(__name__)


def sync_organization(organization: model.Group):
    """Organization synchronization between the portals we send datasets to,
    if the remote organization contains at least 1 package"""
    profiles: list[Profile] = [p for p in syndicate_utils.get_profiles()]

    for profile in profiles:
        _sync_org_for_profile(organization, profile)


def _sync_org_for_profile(organization: model.Group, profile: Profile) -> None:
    ckan = syndicate_utils.get_target(profile.ckan_url, profile.api_key)
    remote_organization = None

    try:
        remote_organization = ckan.action.organization_show(id=organization.name)
    except ckanapi.NotFound:
        return

    if not remote_organization["package_count"]:
        return

    toolkit.get_action("syndicate_sync_organization")(
        {"ignore_auth": True},
        {
            "id": organization.id,
            "profile": profile.id,
            "update_existing": profile.update_organization,
        },
    )

    log.info(
        "Remote organization has been updated. "
        f"Organization ID: {organization.id}, portal: {profile.ckan_url}"
    )
