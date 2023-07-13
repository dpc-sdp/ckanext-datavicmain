import logging
import csv
import json
import base64
from io import StringIO
from ckan.types import Response

import ckan.views.dataset as dataset
import ckan.model as model
import ckan.plugins.toolkit as toolkit
import ckan.lib.helpers as h

from flask import Blueprint, make_response, jsonify
from ckanext.datavicmain import utils


NotFound = toolkit.ObjectNotFound
NotAuthorized = toolkit.NotAuthorized
check_access = toolkit.check_access
get_action = toolkit.get_action
_ = toolkit._
g = toolkit.g
render = toolkit.render
abort = toolkit.abort
log = logging.getLogger(__name__)
datavicmain = Blueprint('datavicmain', __name__)

CONFIG_BASE_MAP = "ckanext.datavicmain.dtv.base_map_id"
DEFAULT_BASE_MAP = "vic-cartographic"


def historical(id):
    package_type = dataset._get_package_type(id.split('@')[0])  # check for new function if necessary

    context = {'model': model, 'session': model.Session,
               'user': g.user or g.author, 'for_view': True,
               'auth_user_obj': g.userobj}

    data_dict = {'id': id}
    # check if package exists
    try:
        pkg_dict = get_action('package_show')(context, data_dict)
        pkg = context['package']
    except NotFound:
        abort(404, _('Dataset not found'))
    except NotAuthorized:
        abort(401, _('Unauthorized to read package %s') % id)

    # used by disqus plugin
    g.current_package_id = pkg.id
    dataset._setup_template_variables(context, data_dict,
                                      package_type=package_type)

    extra_vars = {'pkg_dict': pkg_dict, 'pkg': pkg}

    try:
        return render('package/read_historical.html', extra_vars)
    # TemplateNotFound is not added to toolkit
    except NotFound as e:
        msg = _("Viewing {package_type} datasets in {format} format is "
                "not supported (template file {file} not found).".format(
                    package_type=package_type, format=format, file='package/read_historical.html'))
        abort(404, msg)

    assert False, "We should never get here"


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
    return render('admin/admin_report.html', extra_vars={})


def toggle_organization_uploads(id: str) -> Response:
    try:
        toolkit.check_access("datavic_toggle_organization_uploads", {}, {"id": "id"})
    except toolkit.NotAuthorized:
        return toolkit.abort(403, _("Not authorized to change uploads for organization"))

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
            resource = get_action("resource_show")({}, {"id": id_})
            if resource["package_id"] not in pkg_cache:
                pkg_cache[resource["package_id"]] = get_action("package_show")(
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
    blueprint.add_url_rule('/dataset/<id>/historical', view_func=historical)
    blueprint.add_url_rule('/dataset/purge/<id>', view_func=purge)
    blueprint.add_url_rule('/ckan-admin/admin-report', view_func=admin_report)
    blueprint.add_url_rule('/dtv_config/<encoded>/config.json', view_func=dtv_config, defaults={"embedded": False})
    blueprint.add_url_rule('/dtv_config/<encoded>/embedded/config.json', view_func=dtv_config, defaults={"embedded": True})
    blueprint.add_url_rule("/organization/edit/<id>/toggle-uploads", view_func=toggle_organization_uploads, methods=["POST"])

register_datavicmain_plugin_rules(datavicmain)
