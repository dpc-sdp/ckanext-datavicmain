from . import (
    datavic_dataset,
    datavic_main,
    datavic_member,
    datavic_organization,
    datavic_pages,
    datavic_user,
)


def get_blueprints():
    return [
        datavic_dataset.datavic_dataset,
        datavic_main.datavicmain,
        datavic_user.datavicuser,
        datavic_member.datavic_member,
        datavic_organization.bp,
        datavic_pages.datavicpages,
    ]
