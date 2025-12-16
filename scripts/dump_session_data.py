import argparse
import json
import logging
import sys
from typing import Any
from typing import Dict

from compas.data import json_loads
from immudb import ImmudbClient

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("dump_session_data")

DB_NAME = "orchestrator_session"
DEFAULT_USERNAME = "immudb"
DEFAULT_PASSWORD = "immudb"


def create_immudb_client(db_name: str) -> ImmudbClient:
    client = ImmudbClient()
    try:
        client.login(DEFAULT_USERNAME, DEFAULT_PASSWORD)
    except Exception as e:
        LOG.error(f"Failed to connect to immudb: {e}")
        sys.exit(1)

    existing_dbs = client.databaseList()
    if db_name not in existing_dbs:
        LOG.error(f"Database '{db_name}' does not exist.")
        sys.exit(1)

    client.useDatabase(db_name.encode())
    LOG.info(f"Connected to immudb database '{db_name}'")
    return client


def scan_all_keys(client: ImmudbClient) -> Dict[str, Any]:
    all_data = {}
    # Start with empty key
    last_key = b""

    while True:
        # Scan returns a dictionary of key(bytes) -> value(bytes)
        # We scan in batches of 1000
        results = client.scan(last_key, b"", False, 1000)

        if not results:
            break

        for key, value in results.items():
            decoded_key = key.decode("utf-8")
            try:
                # Values in SessionStorage are stored as json strings using compas.data.json_dumps
                # We decode them back to python objects
                decoded_value = json_loads(value.decode("utf-8"))
            except Exception:
                # Fallback for non-json values
                decoded_value = value.decode("utf-8")

            all_data[decoded_key] = decoded_value
            last_key = key

        if len(results) < 1000:
            break

    return all_data


def main():
    parser = argparse.ArgumentParser(description="Dump entire session data from Immudb to a JSON file.")
    parser.add_argument("--output", "-o", default="session_dump.json", help="Output JSON file path")
    args = parser.parse_args()

    client = create_immudb_client(DB_NAME)

    try:
        LOG.info("Scanning all keys...")
        data = scan_all_keys(client)
        LOG.info(f"Found {len(data)} keys.")

        with open(args.output, "w") as f:
            json.dump(data, f, indent=2, default=str)

        LOG.info(f"Successfully dumped data to {args.output}")

    except Exception as e:
        LOG.exception("An error occurred during dump")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
