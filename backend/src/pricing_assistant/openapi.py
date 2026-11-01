"""Print the OpenAPI schema of the API as stable, sorted JSON (used by `make openapi`)."""

import json
import sys

from pricing_assistant.app import create_app


def main() -> None:
    schema = create_app().openapi()
    sys.stdout.write(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
