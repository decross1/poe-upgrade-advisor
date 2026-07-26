from pathlib import Path

from .app import ApiApplication, create_server
from .assumptions import AssumptionsEvaluator
from .calculator import FixtureCalculator

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app = ApiApplication(
        FixtureCalculator(ROOT / "contracts/fixtures"),
        AssumptionsEvaluator(ROOT / "assumptions"),
    )
    server = create_server(app)
    print(f"server listening on http://{server.server_address[0]}:{server.server_address[1]}/api/v0")
    server.serve_forever()


if __name__ == "__main__":
    main()
