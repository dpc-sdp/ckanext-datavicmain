from __future__ import annotations

import ckan.plugins.toolkit as tk


CONFIG_DTV_URL = "ckanext.datavicmain.dtv.url"


def get_dtv_url() -> str:
    return tk.config.get("ckanext.datavicmain.dtv.url", "")
