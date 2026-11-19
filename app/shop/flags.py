"""Feature flags: defaults from flags.json (in Git, reviewed like code), runtime overrides from the database.

Evaluation order for a signed-in user:
  1. flag disabled (kill switch)  -> off for everyone, including force_on
  2. login in force_off           -> off
  3. login in force_on            -> on   (lets the Tester pin an account to one variant)
  4. stable hash bucket < rollout -> on   (the same user always lands in the same group)
Anonymous visitors never get an experimental variant: the experiments sit behind authentication.
"""
import hashlib
import json
from dataclasses import dataclass, field

from flask import current_app, g
from sqlalchemy import select

from .db import engine, flag_overrides

FLAG_NAMES = ("quick_buy", "stock_badge")


@dataclass(frozen=True)
class Flag:
    name: str
    description: str
    enabled: bool
    rollout: int                      # percent of signed-in users who get the "on" variant
    force_on: frozenset = field(default_factory=frozenset)
    force_off: frozenset = field(default_factory=frozenset)
    params: dict = field(default_factory=dict)
    overridden_by: str | None = None  # set when an admin changed it at runtime


def bucket(flag: str, user_id: int) -> int:
    """0-99, stable per (flag, user). Salting with the flag name keeps the two experiments independent."""
    digest = hashlib.sha256(f"{flag}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def _defaults() -> dict:
    with open(current_app.config["FLAGS_FILE"], encoding="utf-8") as f:
        return json.load(f)


def all_flags() -> dict[str, Flag]:
    """Defaults merged with overrides; cached for the current request so one page sees one state."""
    if "flags" not in g:
        overrides = {}
        with engine().connect() as conn:
            for row in conn.execute(select(flag_overrides)).mappings():
                overrides[row["flag"]] = row
        flags = {}
        for name, cfg in _defaults().items():
            o = overrides.get(name)
            flags[name] = Flag(
                name=name,
                description=cfg["description"],
                enabled=o["enabled"] if o else bool(cfg["enabled"]),
                rollout=o["rollout"] if o else int(cfg["rollout"]),
                force_on=frozenset(s.lower() for s in cfg.get("force_on", [])),
                force_off=frozenset(s.lower() for s in cfg.get("force_off", [])),
                params={k: v for k, v in cfg.items()
                        if k not in ("description", "enabled", "rollout", "force_on", "force_off")},
                overridden_by=o["updated_by"] if o else None,
            )
        g.flags = flags
    return g.flags


def explain(name: str, user) -> tuple[bool, str]:
    """The variant a user gets and the rule that decided it. is_on() and the admin console both use
    this, so the console can never show a different state from the one the user actually gets."""
    if user is None:
        return False, "signed out"
    flag = all_flags()[name]
    login = user["login"].lower()
    b = bucket(name, user["id"])
    if not flag.enabled:
        return False, "killed"
    if login in flag.force_off:
        return False, "force_off"
    if login in flag.force_on:
        return True, "force_on"
    return b < flag.rollout, f"bucket {b} {'<' if b < flag.rollout else '>='} {flag.rollout}"


def is_on(name: str, user) -> bool:
    return explain(name, user)[0]


def variants(user) -> dict[str, bool]:
    return {name: is_on(name, user) for name in FLAG_NAMES}
