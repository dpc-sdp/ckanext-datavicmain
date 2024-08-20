from __future__ import annotations

import logging
from typing import Union, Any, cast

from flask.views import MethodView
from flask import Blueprint, jsonify

from ckan import types, model
from ckan.plugins import toolkit as tk
from ckan.types import Response
from ckan.logic import parse_params
from ckan.lib.navl.dictization_functions import convert

from ckanext.scheming.validation import validators_from_string

from ckanext.datavicmain_home import utils

log = logging.getLogger(__name__)

datavic_home = Blueprint("datavic_home", __name__, url_prefix="/vic-home")


class HomeManage(MethodView):
    def get(self) -> str:
        return tk.render(
            "vic_home/manage.html",
            extra_vars={
                "home_items": tk.get_action("get_all_section_items")({}, {}),
            },
        )

    def post(self) -> Union[str, Response]:
        tk.h.flash_success("Hello world")

        return tk.redirect_to("datavic_home.manage")


class HomeItemCreateOrUpdate(MethodView):
    def validate_data(
        self,
        data: dict[str, Any],
        schema: dict[str, Any],
        errors: types.FlattenErrorDict,
    ) -> tuple[dict[str, Any], types.FlattenErrorDict]:
        for field_name in data:
            field: dict[str, Any] | None = tk.h.scheming_field_by_name(
                schema["fields"], field_name
            )

            if not field:
                continue

            if "validators" not in field:
                continue

            for validator in validators_from_string(
                field["validators"], field, schema
            ):
                try:
                    convert(validator, field_name, data, errors, context={})
                except tk.StopOnError:
                    return data, errors

        return data, errors


class HomeItemCreate(HomeItemCreateOrUpdate):
    def get(self) -> str:
        return tk.render(
            "vic_home/add_or_edit.html",
            extra_vars={
                "errors": {},
                "data": {},
                "schema": utils.get_config_schema(),
            },
        )

    def post(self) -> Union[str, Response]:
        data = parse_params(tk.request.form)
        schema = utils.get_config_schema()

        if file := tk.request.files.get("upload"):
            data["upload"] = file

        errors: types.FlattenErrorDict = dict((key, []) for key in data)
        data, errors = self.validate_data(data, schema, errors)

        if any(list(errors.values())):
            return tk.render(
                "vic_home/add_or_edit.html",
                extra_vars={
                    "errors": errors,
                    "data": data,
                    "schema": schema,
                },
            )

        tk.get_action("create_section_item")({}, data)

        tk.h.flash_success("The item has been created")

        return tk.redirect_to("datavic_home.manage")


class HomeItemEdit(HomeItemCreateOrUpdate):
    action = "update_section_item"

    def get(self, item_id: str) -> str:
        try:
            data = tk.get_action("get_section_item")({}, {"id": item_id})
        except tk.ObjectNotFound:
            tk.abort(404)

        return tk.render(
            "vic_home/add_or_edit.html",
            extra_vars={
                "errors": {},
                "data": data,
                "schema": utils.get_config_schema(),
            },
        )

    def post(self, item_id: str) -> Union[str, Response]:
        try:
            tk.get_action("get_section_item")({}, {"id": item_id})
        except tk.ObjectNotFound:
            tk.abort(404)

        data = parse_params(tk.request.form)
        schema = utils.get_config_schema()

        if file := tk.request.files.get("upload"):
            data["upload"] = file

        data["id"] = item_id

        errors: types.FlattenErrorDict = dict((key, []) for key in data)
        data, errors = self.validate_data(data, schema, errors)

        if any(list(errors.values())):
            return tk.render(
                "vic_home/add_or_edit.html",
                extra_vars={
                    "errors": errors,
                    "data": data,
                    "schema": schema,
                },
            )

        tk.get_action("update_section_item")({}, data)

        tk.h.flash_success("The item has been updated")

        return tk.redirect_to("datavic_home.manage")


class HomeItemDelete(MethodView):
    def post(self, item_id: str) -> Union[str, Response]:
        try:
            tk.get_action("get_section_item")({}, {"id": item_id})
        except tk.ObjectNotFound:
            tk.abort(404)

        tk.get_action("delete_section_item")({}, {"id": item_id})

        tk.h.flash_success("The item has been deleted")

        return tk.redirect_to("datavic_home.manage")


def section_autocomplete() -> Response:
    q = tk.request.args.get("incomplete", "")

    if not q:
        return jsonify({"ResultSet": {"Result": []}})

    return jsonify(
        {
            "ResultSet": {
                "Result": [
                    {"Name": section}
                    for section in tk.h.vic_home_get_sections()
                ]
            }
        }
    )


datavic_home.add_url_rule("/manage", view_func=HomeManage.as_view("manage"))
datavic_home.add_url_rule("/new", view_func=HomeItemCreate.as_view("new"))
datavic_home.add_url_rule(
    "/edit/<item_id>", view_func=HomeItemEdit.as_view("edit")
)
datavic_home.add_url_rule(
    "/delete/<item_id>", view_func=HomeItemDelete.as_view("delete")
)
datavic_home.add_url_rule(
    "/section_autocomplete", view_func=section_autocomplete
)
