from __future__ import annotations

import ckan.plugins.toolkit as tk

CONFIG_PAGES_BASE_URL = "ckan.pages.base_url"


def get_pages_base_url() -> str:
    return tk.config[CONFIG_PAGES_BASE_URL]

CONFIG_DTV_URL = "ckanext.datavicmain.dtv.url"


def get_dtv_url() -> str:
    return tk.config.get("ckanext.datavicmain.dtv.url", "")
