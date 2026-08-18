"""Declarative base and metadata conventions.

The naming convention is set here, before any table exists. Alembic arrives in
v3 and generates migrations by comparing the database against this metadata; if
constraint names are left to the database to invent, that comparison produces
noisy and sometimes wrong migrations. Deciding the names up front costs nothing
now and avoids churn later.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
