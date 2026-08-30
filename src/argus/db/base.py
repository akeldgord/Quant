"""Shared SQLAlchemy declarative base for all ARGUS ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base. All domain ORM models inherit from this."""
