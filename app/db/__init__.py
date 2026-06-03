"""Couche base de données."""
from .database import get_connection, init_database

__all__ = ["get_connection", "init_database"]
