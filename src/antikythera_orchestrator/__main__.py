import argparse
import logging
import copy

import uvicorn
from uvicorn.config import LOGGING_CONFIG


def main() -> None:
    """Entrypoint that launches the FastAPI server."""
    parser = argparse.ArgumentParser(description="Antikythera Orchestrator API")
    parser.add_argument("--host", default="0.0.0.0", help="API host.")
    parser.add_argument("--port", type=int, default=8000, help="API port.")
    parser.add_argument("--dev", action="store_true", help="Enable auto-reload.")
    args = parser.parse_args()

    # Configure file logging for the main process
    logging.basicConfig(level=logging.DEBUG, filename="orchestrator.log", filemode="a", format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    # Configure uvicorn logging to match requested style and persist across reloads
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["formatters"]["default"]["fmt"] = "%(levelname)s:\t%(message)s"
    log_config["formatters"]["access"]["fmt"] = "%(levelname)s:\t%(message)s"
    
    # Ensure antikythera_orchestrator logs are shown
    log_config["loggers"]["antikythera_orchestrator"] = {
        "handlers": ["default"],
        "level": "DEBUG" if args.dev else "INFO",
        "propagate": False
    }

    uvicorn.run(
        "antikythera_orchestrator.api:app", 
        host=args.host, 
        port=args.port, 
        log_level="debug" if args.dev else "info", 
        reload=args.dev,
        log_config=log_config
    )


if __name__ == "__main__":
    main()
