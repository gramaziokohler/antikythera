import argparse
import sys
import time
import uuid

from antikythera.models import BlueprintSession
from antikythera.models import load_blueprint_from_file
from antikythera.orchestrator import Orchestrator


def main():
    """Main entry point for the Antikythera orchestrator."""
    parser = argparse.ArgumentParser(description="Antikythera")
    parser.add_argument("blueprint_file", help="Path to the blueprint JSON file.")
    parser.add_argument("--broker-host", default="127.0.0.1", help="MQTT broker host.")
    parser.add_argument("--broker-port", type=int, default=1883, help="MQTT broker port.")
    args = parser.parse_args()

    print(f"Loading blueprint: {args.blueprint_file}")
    blueprint = load_blueprint_from_file(args.blueprint_file)
    bsid = uuid.uuid4().hex
    session = BlueprintSession(bsid=bsid, blueprint=blueprint)

    print()
    print("Loaded successfully! Starting execution...")
    print("-------------------------------------------")

    orchestrator = Orchestrator(session, broker_host=args.broker_host, broker_port=args.broker_port)
    orchestrator.start()

    t0 = time.time()
    diagram = orchestrator.scheduler.to_mermaid_diagram()

    while True:
        diagram = orchestrator.scheduler.to_mermaid_diagram()
        lines = len(diagram.split("\n")) - 1
        sys.stdout.write(diagram)
        sys.stdout.write(f"\033[{lines}A")
        sys.stdout.write("\r")
        sys.stdout.flush()
        time.sleep(1)

        if time.time() - t0 > 30:
            break

    orchestrator.stop()


if __name__ == "__main__":
    main()
