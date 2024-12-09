from __future__ import annotations

import logging
import csv
from io import StringIO

import click

import ckan.model as model

log = logging.getLogger(__name__)


@click.group()
def report():
    """Generate reports"""
    pass


@report.command()
def package_authors():
    """Generate a CSV of package authors"""
    click.echo(get_package_authors())


def get_package_authors():
    headers = ["ID", "Name", "Email", "Packages"]
    dict_data = []
    output = StringIO()

    for user in model.Session.query(model.User).all():
        if user.state != model.State.ACTIVE:
            continue

        number_of_packages = user.number_created_packages(
            include_private_and_draft=True
        )

        if not number_of_packages:
            continue

        dict_data.append(
            {
                "ID": user.id,
                "Name": user.name,
                "Email": user.email,
                "Packages": number_of_packages,
            }
        )

    writer = csv.DictWriter(output, fieldnames=headers, quoting=csv.QUOTE_ALL)

    writer.writeheader()
    writer.writerows(dict_data)

    return output.getvalue()
