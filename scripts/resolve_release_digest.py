"""Resolve a GHCR release image digest with bounded eventual-consistency retries."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections.abc import Callable

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def resolve_digest(
    image: str,
    *,
    attempts: int = 6,
    delay_seconds: float = 10.0,
    inspect: Callable[[str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    inspect = inspect or _inspect
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            digest = inspect(image).strip().strip('"')
            if DIGEST.fullmatch(digest):
                return digest
            last_error = f"invalid digest output: {digest!r}"
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            last_error = str(exc)
        if attempt < attempts:
            print(
                f"digest lookup attempt {attempt}/{attempts} failed for {image}: {last_error}; retrying",
                file=sys.stderr,
            )
            sleep(delay_seconds)
    raise RuntimeError(f"digest lookup failed after {attempts} attempts for {image}: {last_error}")


def _inspect(image: str) -> str:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest.Digest}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--delay-seconds", type=float, default=10.0)
    args = parser.parse_args()
    try:
        print(resolve_digest(args.image, attempts=args.attempts, delay_seconds=args.delay_seconds))
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
