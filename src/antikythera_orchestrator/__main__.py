import argparse
import logging

import uvicorn



def main() -> None:
    """Entrypoint that launches the FastAPI server."""
    parser = argparse.ArgumentParser(description="Antikythera Orchestrator API")
    parser.add_argument("--host", default="0.0.0.0", help="API host.")
    parser.add_argument("--port", type=int, default=8000, help="API port.")
    parser.add_argument("--dev", action="store_true", help="Enable auto-reload.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, filename="orchestrator.log", filemode="a", format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    uvicorn.run("antikythera_orchestrator.api:app", host=args.host, port=args.port, log_level="info", reload=args.dev)


if __name__ == "__main__":
    main()
