"""Issue an API key.

    python scripts/create-api-key.py --name ingest --scope submissions:write

The token is printed once and never stored in recoverable form. If it is lost,
issue another and disable the old one - there is no way to look it up, by
design, including for whoever runs the database.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import get_settings
from app.db.session import create_engine, create_sessionmaker
from app.security.provisioning import create_api_key
from app.security.scopes import Scope


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Who this key is for.")
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        choices=[scope.value for scope in Scope],
        help="May be repeated. At least one is required.",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.scopes:
        print("At least one --scope is required.", file=sys.stderr)
        return 2

    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            token = await create_api_key(
                session, args.name, [Scope(value) for value in args.scopes]
            )
    finally:
        await engine.dispose()

    print(f"name:   {args.name}")
    print(f"scopes: {', '.join(args.scopes)}")
    print(f"key:    {token}")
    print()
    print("Store this now. It cannot be shown again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
