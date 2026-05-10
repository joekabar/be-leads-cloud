import scraper


def test_package_metadata() -> None:
    assert scraper.__version__ == "0.1.0"
