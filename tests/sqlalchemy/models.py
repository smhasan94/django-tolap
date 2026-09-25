"""SQLAlchemy tables mirroring ``tests/testapp/models.py`` (same names as upstream ``schema.sql``).

On PostgreSQL the tables live in schema ``tolap_sa`` inside Django's throwaway test database
so they never collide with the Django tables or touch a real database. ``Table.name`` (the
TOLAP object name) is unaffected by the schema.
"""

from __future__ import annotations

import os

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, MetaData, String, Table, Text
from sqlalchemy.orm import DeclarativeBase

_URL = os.environ.get("DATABASE_URL", "")
# PostgreSQL: a schema inside Django's throwaway test database. MySQL has no schemas below a
# database, so it is a second throwaway database created and dropped by the engine fixture.
if _URL.startswith("postgres"):
    SCHEMA: str | None = "tolap_sa"
elif _URL.startswith("mysql"):
    SCHEMA = "test_tolap_sa"
else:
    SCHEMA = None
metadata = MetaData(schema=SCHEMA)


class Base(DeclarativeBase):
    metadata = metadata


patients = Table(
    "patients",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("full_name", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("ssn", Text, nullable=False),
    Column("date_of_birth", Date, nullable=False),
    Column("region", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("score", Integer, nullable=True),
)
encounters = Table(
    "encounters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("patient_id", Integer, ForeignKey(patients.c.id), nullable=False),
    Column("occurred_at", DateTime, nullable=False),
    Column("region", Text, nullable=False),
    Column("status", Text, nullable=False),
)
billing_internal = Table(
    "billing_internal",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("patient_id", Integer, nullable=True),
    Column("amount_cents", Integer, nullable=False),
    Column("region", Text, nullable=False),
)
audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("occurred_at", DateTime, nullable=False),
)
pharmacy_orders = Table(
    "pharmacy_orders", metadata, Column("id", Integer, primary_key=True), Column("drug", Text)
)
records = Table(
    "records",
    metadata,
    Column("id", String(16), primary_key=True),
    Column("score", Integer, nullable=True),
    Column("region", Text, nullable=True),
    Column("name", Text, nullable=True),
)


class Patient(Base):
    __table__ = patients


class Encounter(Base):
    __table__ = encounters


TABLES = {t.name: t for t in metadata.tables.values()}
