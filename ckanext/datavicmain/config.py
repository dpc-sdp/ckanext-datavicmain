from __future__ import annotations

import ckan.plugins.toolkit as tk

CONFIG_PAGES_BASE_URL = "ckan.pages.base_url"
CONFIG_DTV_URL = "ckanext.datavicmain.dtv.url"
CONFIG_DTV_MAX_SIZE_LIMIT = "ckanext.datavicmain.dtv.max_size_limit"
CONFIG_DTV_EXTERNAL_LINK = "ckanext.datavicmain.dtv.external_link"


def get_pages_base_url() -> str:
    return tk.config[CONFIG_PAGES_BASE_URL]


def get_dtv_url() -> str:
    return tk.config.get(CONFIG_DTV_URL, "")


def get_dtv_max_size_limit() -> int:
    return tk.config.get(CONFIG_DTV_MAX_SIZE_LIMIT, "157286400")


def get_dtv_external_link() -> str:
    return tk.config.get(CONFIG_DTV_EXTERNAL_LINK, "")
