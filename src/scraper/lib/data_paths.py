"""Paths to bundled data files (rate limits, sectors, postcodes).

These files live next to this module so they are always available when the
package is installed as a wheel (no reliance on the project-root layout).
"""

from pathlib import Path

_LIB = Path(__file__).parent

PER_HOST_TOML = _LIB / "per-host.toml"
SECTORS_TOML = _LIB / "sectors.toml"
POSTCODES_TOML = _LIB / "postcodes.toml"
