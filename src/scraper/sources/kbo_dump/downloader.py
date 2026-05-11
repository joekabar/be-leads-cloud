from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from scraper.lib.config import Settings


class KboDumpDownloader:  # pragma: no cover
    """Stub. Real downloader to be implemented when SFTP access is granted.

    Manual download path:
    1. Register at https://kbopub.economie.fgov.be/kbo-open-data/login?lang=en
    2. Verify email and accept the licence.
    3. (For automation) email kbo-bce-webservice@economie.fgov.be requesting SFTP credentials.
    4. Download KboOpenData_<n>_<YYYY>_<MM>_Full.zip to data/kbo_dump/.
    5. Run: uv run be-leads-ingest-kbo --zip data/kbo_dump/KboOpenData_*_Full.zip
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def download_latest_full(self, dest: Path) -> Path:
        raise NotImplementedError(
            "Manual: log in to https://kbopub.economie.fgov.be/kbo-open-data/login, "
            "download the latest Full ZIP, save to data/kbo_dump/. "
            "Once SFTP access is granted, implement async download here."
        )

    async def download_latest_update(self, dest: Path) -> Path:
        raise NotImplementedError(
            "Manual: log in to https://kbopub.economie.fgov.be/kbo-open-data/login, "
            "download the latest Update ZIP, save to data/kbo_dump/. "
            "Once SFTP access is granted, implement async download here."
        )
