"""Operational CLI: ``python -m app.cli <command>`` (P0-T12).

Commands exist so that every background job is usable without Redis and without
a worker process — the whole point of the no-Docker path (D-34).

  python -m app.cli migrate [--revision head|base]
  python -m app.cli seed
  python -m app.cli job list
  python -m app.cli job run <name>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]


def _alembic_config() -> object:
    from alembic.config import Config

    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


def cmd_migrate(revision: str) -> int:
    from alembic import command

    config = _alembic_config()
    if revision == "base":
        command.downgrade(config, "base")
    else:
        command.upgrade(config, revision)
    print(json.dumps({"status": "ok", "migrated_to": revision}))
    return 0


def cmd_seed() -> int:
    asyncio.run(_seed())
    return 0


async def _seed() -> None:
    from sqlalchemy import text

    from app.core.db import get_sessionmaker

    maker = get_sessionmaker()
    async with maker() as session:
        await session.execute(
            text(
                """
                INSERT INTO app_meta (key, value)
                VALUES ('seed_version', :value)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                                               updated_at = now()
                """
            ),
            {"value": "phase-0"},
        )
        await session.commit()
    print(json.dumps({"status": "ok", "seed": "phase-0"}))


def cmd_job_list() -> int:
    from app.jobs.registry import TASKS

    print(json.dumps({"tasks": sorted(TASKS)}))
    return 0


def cmd_job_run(name: str) -> int:
    from app.jobs.registry import run_task

    result = asyncio.run(run_task(name, {}))
    print(json.dumps({"status": "ok", "task": name, "result": result}, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="run Alembic migrations")
    migrate.add_argument("--revision", default="head", choices=["head", "base"])

    sub.add_parser("seed", help="seed baseline data")

    job = sub.add_parser("job", help="inspect and run background jobs")
    job_sub = job.add_subparsers(dest="job_command", required=True)
    job_sub.add_parser("list", help="list registered tasks")
    run = job_sub.add_parser("run", help="run one task synchronously")
    run.add_argument("name")

    args = parser.parse_args(argv)

    if args.command == "migrate":
        return cmd_migrate(args.revision)
    if args.command == "seed":
        return cmd_seed()
    if args.command == "job":
        if args.job_command == "list":
            return cmd_job_list()
        return cmd_job_run(args.name)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
