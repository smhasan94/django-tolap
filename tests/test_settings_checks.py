import pytest
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_tolap.conf import settings

pytestmark = pytest.mark.django_db  # run_checks() includes database checks once models exist


def _ids() -> set[str]:
    return {m.id for m in run_checks()}


def test_defaults_apply() -> None:
    assert settings.HASH_SALT is None
    assert settings.OBJECT_NAME == "db_table"
    assert settings.CONTEXT_TTL == 3600


def test_signing_key_from_settings() -> None:
    assert settings.SIGNING_KEY == "test-signing-key"


@override_settings(TOLAP={})
def test_missing_signing_key_raises_and_checks_e001() -> None:
    with pytest.raises(ImproperlyConfigured):
        _ = settings.SIGNING_KEY
    assert "django_tolap.E001" in _ids()


@override_settings(TOLAP={"SIGNING_KEY": "k", "IDENTITY_RESOLVER": "nope.Missing"})
def test_bad_identity_resolver_e002() -> None:
    assert "django_tolap.E002" in _ids()


@override_settings(TOLAP={"SIGNING_KEY": "k", "OBJECT_NAME": "nope.missing"})
def test_bad_object_name_e003() -> None:
    assert "django_tolap.E003" in _ids()


@override_settings(TOLAP={"SIGNING_KEY": "k", "OBJECT_NAME": "os.path.basename"})
def test_callable_object_name_ok() -> None:
    assert not _ids() & {"django_tolap.E001", "django_tolap.E002", "django_tolap.E003"}


def test_unknown_setting_attribute() -> None:
    with pytest.raises(AttributeError):
        _ = settings.NOPE
