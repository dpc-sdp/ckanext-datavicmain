from __future__ import annotations

import ckan.plugins.toolkit as tk

CONFIG_PAGES_BASE_URL = "ckan.pages.base_url"
CONFIG_DTV_URL = "ckanext.datavicmain.dtv.url"
CONFIG_DTV_EXTERNAL_LINK = "ckanext.datavicmain.dtv.external_link"


def get_pages_base_url() -> str:
    return tk.config[CONFIG_PAGES_BASE_URL]


def get_dtv_url() -> str:
    return tk.config.get(CONFIG_DTV_URL, "")


def get_dtv_external_link() -> str:
    return tk.config.get(CONFIG_DTV_EXTERNAL_LINK, "")
