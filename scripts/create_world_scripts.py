from __future__ import annotations

from agents import (
    create_goodbye_world_script,
    create_hello_world_script,
)


def main() -> None:
    create_hello_world_script()
    create_goodbye_world_script()


if __name__ == "__main__":
    main()

