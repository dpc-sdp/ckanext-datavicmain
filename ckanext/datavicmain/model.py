from ckan.model.meta import metadata, mapper, Session, engine
from ckan.model.domain_object import DomainObject
from ckan.model.types import make_uuid

from sqlalchemy import types, Column, Table
import datetime
import logging    

log = logging.getLogger(__name__)

refresh_dataset_datastore_table = Table(
    'refresh_dataset_datastore',
    metadata,
    Column('id',
        types.UnicodeText,
        primary_key=True,
        default=make_uuid()),
    Column('dataset_id',
        types.UnicodeText,
        nullable=False,
        index=True),
    Column('frequency',
        types.UnicodeText,
        nullable=False),
    Column('created_user_id',
        types.UnicodeText,
        nullable=False),
    Column('created_at',
        types.DateTime,
        nullable=False,
        default=datetime.datetime.utcnow),
    Column('datastore_last_refreshed',
        types.DateTime,
        nullable=True)
)

class RefreshDatasetDatastore(DomainObject):

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.id = make_uuid()
        self.created_at = datetime.datetime.utcnow()

    @classmethod
    def get(cls, id):
        return Session.query(cls).get(id)

    @classmethod
    def delete(cls, id):
        obj = Session.query(cls).get(id)
        if obj:
            Session.delete(obj)
            Session.commit()

    @classmethod
    def get_all(cls):
        return Session.query(cls).all()

mapper(RefreshDatasetDatastore, refresh_dataset_datastore_table)

def setup():
    metadata.create_all(engine)