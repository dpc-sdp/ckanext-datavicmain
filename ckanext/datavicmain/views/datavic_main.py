import csv
import json
import base64
from io import StringIO
from ckan.types import Response

import ckan.views.dataset as dataset
import ckan.model as model
import ckan.plugins.toolkit as toolkit
import ckan.lib.helpers as h
from ckan import types

from flask import Blueprint, make_response, jsonify
from ckanext.datavicmain import utils

datavicmain = Blueprint('datavicmain', __name__)

CONFIG_BASE_MAP = "ckanext.datavicmain.dtv.base_map_id"
DEFAULT_BASE_MAP = "vic-cartographic"


def historical(package_type: str, package_id: str):
    context: types.Context = toolkit.fresh_context({})

    data_dict = {"id": package_id}

    try:
        pkg_dict = toolkit.get_action("package_show")(context, data_dict)

    except toolkit.ObjectNotFound:
        return toolkit.abort(404, toolkit._("Dataset not found"))
    except toolkit.NotAuthorized:
        return toolkit.abort(
            401, toolkit._(f"Unauthorized to read package {package_id}")
        )

    return toolkit.render("package/read_historical.html", {"pkg_dict": pkg_dict})


def purge(id):
    try:
        # Only sysadmins can purge
        toolkit.check_access('sysadmin', {})
        toolkit.get_action('dataset_purge')({}, {'id': id})
        toolkit.h.flash_success('Successfully purged dataset ID: %s' % id)
    except Exception as e:
        print(str(e))
        toolkit.h.flash_error('Exception')

    return toolkit.h.redirect_to('/ckan-admin/trash')


def admin_report():
    context = {
        "model": model,
        "user": toolkit.c.user,
        "auth_user_obj": toolkit.c.userobj,
    }
    try:
        toolkit.check_access("sysadmin", context, {})
    except toolkit.NotAuthorized:
        return toolkit.abort(
            401, toolkit._(
                "Need to be system administrator to generate reports")
        )

    report_type = toolkit.request.args.get("report_type")
    if report_type and report_type == 'user-email-data':
        users = model.Session.query(
            model.User.email,
            model.User.id,
            model.User.name)\
            .filter(model.User.state != 'deleted')

        packages = model.Session.query(
            model.Package.id,
            model.Package.maintainer_email,
            model.Package.name)\
            .filter(model.Package.maintainer_email != '')\
            .filter(model.Package.state != 'deleted')

        report = StringIO()
        fd = csv.writer(report)
        fd.writerow(
            [
                "Entity type",
                "Email",
                "URL"
            ]
        )
        for user in users.all():
            fd.writerow(
                [
                    'user',
                    user[0],
                    h.url_for('user.read', id=user[2], qualified=True)
                ]
            )

        for package in packages.all():
            fd.writerow(
                [
                    'dataset',
                    package[1],
                    h.url_for('dataset.read', id=package[2], qualified=True)
                ]
            )

        response = make_response(report.getvalue())
        response.headers["Content-type"] = "text/csv"
        response.headers[
            "Content-disposition"
        ] = 'attachement; filename="email_report.csv"'
        return response
    return toolkit.render('admin/admin_report.html', extra_vars={})


def toggle_organization_uploads(id: str) -> Response:
    try:
        toolkit.check_access("datavic_toggle_organization_uploads", {}, {"id": "id"})
    except toolkit.NotAuthorized:
        return toolkit.abort(403, toolkit._("Not authorized to change uploads for organization"))

    if org := model.Group.get(id):
        try:
            flake = toolkit.get_action("flakes_flake_lookup")({"ignore_auth": True}, {
                "author_id": None,
                "name": utils.org_uploads_flake_name(),
            })
        except toolkit.ObjectNotFound:
            toolkit.get_action("flakes_flake_create")({"ignore_auth": True}, {
                "author_id": None,
                "name": utils.org_uploads_flake_name(),
                "data": {org.id: True},
                "extras": {"datavicmain": {"type": "organization_uploads_list"}}
            })
        else:
            flake["data"].update({org.id: not flake["data"].get(org.id, False)})
            toolkit.get_action("flakes_flake_update")({"ignore_auth": True}, flake)

    return toolkit.redirect_to("organization.edit", id=id)


def dtv_config(encoded: str, embedded: bool):
    try:
        ids: list[str] = json.loads(base64.urlsafe_b64decode(encoded))
    except ValueError:
        return toolkit.abort(409)

    base_url: str = (
        toolkit.config.get("ckanext.datavicmain.odp.public_url")
        or toolkit.config["ckan.site_url"]
    )

    catalog = []
    pkg_cache = {}

    for id_ in ids:

        try:
            resource = toolkit.get_action("resource_show")({}, {"id": id_})
            if resource["package_id"] not in pkg_cache:
                pkg_cache[resource["package_id"]] = toolkit.get_action("package_show")(
                    {}, {"id": resource["package_id"]}
                )

        except (toolkit.NotAuthorized, toolkit.ObjectNotFound):
            continue

        pkg = pkg_cache[resource["package_id"]]
        catalog.append({
            "id": f"data-vic-embed-{id_}",
            "name": "{}: {}".format(
                pkg["title"],
                resource["name"] or "Unnamed"
            ),
            "type": "ckan-item",
            "url": base_url,
            "resourceId": id_
        })

    return jsonify({
        "baseMaps": {
            "defaultBaseMapId": toolkit.config.get(
                CONFIG_BASE_MAP, DEFAULT_BASE_MAP
            )
        },
        "catalog": catalog,
        "workbench": [item["id"] for item in catalog],
        "initialCamera": {
            "focusWorkbenchItems": True
        },
        "elements": {
            "map-navigation": {
                "disabled": embedded
            },
            "menu-bar": {
                "disabled": embedded
            },
            "bottom-dock": {
                "disabled": embedded
            },
            "map-data-count": {
                "disabled": embedded
            },
            "show-workbench": {
                "disabled": embedded
            }
        }
    })


def register_datavicmain_plugin_rules(blueprint):
    blueprint.add_url_rule('/<package_type>/<package_id>/historical', view_func=historical)
    blueprint.add_url_rule('/dataset/purge/<id>', view_func=purge)
    blueprint.add_url_rule('/ckan-admin/admin-report', view_func=admin_report)
    blueprint.add_url_rule('/dtv_config/<encoded>/config.json', view_func=dtv_config, defaults={"embedded": False})
    blueprint.add_url_rule('/dtv_config/<encoded>/embedded/config.json', view_func=dtv_config, defaults={"embedded": True})
    blueprint.add_url_rule("/organization/edit/<id>/toggle-uploads", view_func=toggle_organization_uploads, methods=["POST"])

register_datavicmain_plugin_rules(datavicmain)
