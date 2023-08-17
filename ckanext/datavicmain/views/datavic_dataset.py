from typing import Union, cast

from flask import Blueprint

import ckan.plugins.toolkit as tk
import ckan.logic as logic
import ckan.lib.navl.dictization_functions as dict_fns
from ckan.views.dataset import (
    CreateView,
    _form_save_redirect,
    _tag_string_to_list,
    EditView,
)
from ckan.types import Context, Response
from ckan.lib.search import SearchIndexError

tuplize_dict = logic.tuplize_dict
clean_dict = logic.clean_dict
parse_params = logic.parse_params

datavic_dataset = Blueprint(
    "datavic_dataset",
    __name__,
    url_prefix="/dataset",
    url_defaults={"package_type": "dataset"},
)


WITHOUT_RES = "save-without-resource"
WITH_RES = "add-resources"


class DatavicCreateView(CreateView):
    def post(self, package_type: str) -> Union[Response, str]:
        context = self._prepare()
        is_an_update = False
        ckan_phase = tk.request.form.get("_ckan_phase")
        save_as: str = tk.request.form.get("save", "")

        try:
            data_dict = clean_dict(
                dict_fns.unflatten(tuplize_dict(parse_params(tk.request.form)))
            )
        except dict_fns.DataError:
            return tk.abort(400, tk._("Integrity Error"))

        try:
            if ckan_phase:
                context["allow_partial_update"] = True

                if "tag_string" in data_dict:
                    data_dict["tags"] = _tag_string_to_list(
                        data_dict["tag_string"]
                    )

                if data_dict.get("pkg_name"):
                    is_an_update = True
                    data_dict["id"] = data_dict["pkg_name"]
                    del data_dict["pkg_name"]
                    data_dict["state"] = "draft" if save_as == WITH_RES else "active"

                    pkg_dict = tk.get_action("package_update")(
                        context, data_dict
                    )
                    if save_as == WITH_RES:
                        return tk.h.redirect_to(
                            tk.h.url_for(
                                "{}_resource.new".format(package_type),
                                id=pkg_dict["name"],
                            )
                        )
                    else:
                        return tk.h.redirect_to(
                            "{}.read".format(package_type), id=pkg_dict["id"]
                        )

                # Make sure we don't index this dataset
                if save_as not in [WITHOUT_RES, "go-metadata"]:
                    data_dict["state"] = "draft"

                # allow the state to be changed
                context["allow_state_change"] = True

            data_dict["type"] = package_type
            pkg_dict = tk.get_action("package_create")(context, data_dict)

            # create_on_ui_requires_resources = tk.config.get(
            #     'ckan.dataset.create_on_ui_requires_resources'
            # )
            if ckan_phase:
                if save_as == WITH_RES:
                    return tk.h.redirect_to(tk.h.url_for(
                        u'{}_resource.new'.format(package_type),
                        id=pkg_dict[u'name']
                    ))

                # tk.get_action("package_update")(
                #     cast(Context, dict(context, allow_state_change=True)),
                #     dict(pkg_dict, state="active"),
                # )
                return tk.h.redirect_to(
                    "{}.read".format(package_type), id=pkg_dict["id"]
                )

            return _form_save_redirect(
                pkg_dict["name"], "new", package_type=package_type
            )
        except tk.NotAuthorized:
            return tk.abort(403, tk._("Unauthorized to read package"))
        except tk.ObjectNotFound:
            return tk.abort(404, tk._("Dataset not found"))
        except SearchIndexError as e:
            try:
                exc_str = str(repr(e.args))
            except Exception:  # We don't like bare excepts
                exc_str = str(str(e))
            return tk.abort(
                500, tk._("Unable to add package to search index.") + exc_str
            )
        except tk.ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            if is_an_update:
                # we need to get the state of the dataset to show the stage we
                # are on.
                pkg_dict = tk.get_action("package_show")(context, data_dict)
                data_dict["state"] = pkg_dict["state"]
                return EditView().get(
                    package_type,
                    data_dict["id"],
                    data_dict,
                    errors,
                    error_summary,
                )
            data_dict["state"] = "none"
            return self.get(package_type, data_dict, errors, error_summary)


def register_datavicmain_plugin_rules(blueprint):
    blueprint.add_url_rule("/new", view_func=DatavicCreateView.as_view("new"))


register_datavicmain_plugin_rules(datavic_dataset)
