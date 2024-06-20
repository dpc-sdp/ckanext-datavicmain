# encoding: utf-8
from __future__ import annotations

import logging
from typing import Union

from flask.views import MethodView
from flask import Blueprint

from ckan.plugins import toolkit as tk
from ckan.types import Response


log = logging.getLogger(__name__)

datavic_home = Blueprint("datavic_home", __name__)


class HomeManage(MethodView):
    def get(self) -> str:
        return tk.render(
            "vic_home/manage.html",
            extra_vars={"test": "hello world", "errors": {}, "data": {}},
        )

    def post(self) -> Union[str, Response]:
        tk.h.flash_success("Hello world")

        return tk.redirect_to("datavic_home.manage")


datavic_home.add_url_rule(
    "/vic/home-manage", view_func=HomeManage.as_view("manage")
)
# datavic_home.manage
