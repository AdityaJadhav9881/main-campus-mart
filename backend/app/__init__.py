"""
CampusMart AI backend application package.

Modules
-------
database : SQLAlchemy engine, session factory, and the FastAPI `get_db`
           dependency.
models   : ORM schema (User, Product, Transaction) registered on `Base`.

Importing the models here (rather than only in main.py) guarantees every table
is registered on `Base.metadata` before any `create_all()` / migration runs.
Note that `create_engine()` is lazy - no network connection is opened until the
first query is executed.
"""

from . import database, models  # noqa: F401  (side effect: register ORM models)
