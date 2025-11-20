from __future__ import annotations

from pathlib import Path
from typing import Optional


def run(output_path: Optional[str] = None) -> Path:
    """
    Create a minimal Python script that prints 'goodbye world'.
    Returns the path to the created file.
    """
    target_path = Path(output_path) if output_path else Path("scripts/goodbye_world.py")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    script_contents = (
        'def main() -> None:\n'
        '    print("goodbye world")\n'
        "\n"
        'if __name__ == "__main__":\n'
        "    main()\n"
    )
    target_path.write_text(script_contents, encoding="utf-8")
    return target_path

