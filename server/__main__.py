from pathlib import Path

from .app import ApiApplication, create_server
from .assumptions import AssumptionsEvaluator
from .calculator import PobCalculator

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    calculator = PobCalculator(ROOT)
    app = ApiApplication(
        calculator,
        AssumptionsEvaluator(ROOT / "assumptions"),
    )
    server = create_server(app)
    print(
        "server listening on "
        f"http://{server.server_address[0]}:{server.server_address[1]}/api/v0"
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        calculator.close()


if __name__ == "__main__":
    main()
