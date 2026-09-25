import django_tolap


def test_version_is_set() -> None:
    assert django_tolap.__version__


def test_versions_match_installed_metadata() -> None:
    from importlib.metadata import version

    import sqlalchemy_tolap

    assert django_tolap.__version__ == version("django-tolap")
    assert sqlalchemy_tolap.__version__ == version("sqlalchemy-tolap")
