"""Quick CLI: validate a KBO enterprise number via stdnum.be.vat."""

from __future__ import annotations

import sys

from stdnum.be import vat


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: validate_kbo.py <kbo_number>", file=sys.stderr)
        sys.exit(1)
    number = sys.argv[1]
    if vat.is_valid(number):
        print(f"valid: {vat.compact(number)}")
    else:
        print(f"invalid: {number!r}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
