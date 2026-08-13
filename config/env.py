"""Environment variable helpers backed by python-dotenv."""

from typing import TypeVar

from dotenv import load_dotenv
import os


T = TypeVar("T")


# Load .env automatically
load_dotenv()


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def env(name: str, default: T | None = None) -> str | T | None:
    """Read an environment variable with an optional default."""
    return os.getenv(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    """Read an environment variable as a boolean."""
    value = os.getenv(name)

    if value is None:
        return default

    normalized = value.strip().lower()

    if normalized in TRUE_VALUES:
        return True

    if normalized in FALSE_VALUES:
        return False

    raise ValueError(f"{name} must be a boolean value")


def env_int(name: str, default: int) -> int:
    """Read an environment variable as an integer."""
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def env_list(name: str, default: str = "") -> list[str]:
    """Read a comma-separated environment variable as a list."""
    value = os.getenv(name, default)

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]