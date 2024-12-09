import logging

import click

from ckan.plugins.toolkit import enqueue_job
from ckanext.datavicmain import jobs

from . import maintain, report

log = logging.getLogger(__name__)


@click.group()
def datavic_main():
    """ckanext-datavicmain management commands."""
    pass


@datavic_main.command(u"ckan-job-worker-monitor")
def ckan_worker_job_monitor():
    try:
        enqueue_job(jobs.ckan_worker_job_monitor, title="CKAN job worker monitor")
        click.secho(u"CKAN job worker monitor added to worker queue", fg=u"green")
    except Exception as e:
        log.error(e)


datavic_main.add_command(maintain.maintain)
datavic_main.add_command(report.report)


def get_commands():
    return [datavic_main]
