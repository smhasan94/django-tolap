"""sqlalchemy-tolap: TOLAP policies enforced on SQLAlchemy Select statements."""

from importlib.metadata import version

from sqlalchemy_tolap.enforce import enforce
from sqlalchemy_tolap.exceptions import TolapDenied, Uninspectable
from sqlalchemy_tolap.pushdown import EnforcementMode

__version__ = version("sqlalchemy-tolap")

__all__ = ["EnforcementMode", "TolapDenied", "Uninspectable", "enforce"]
