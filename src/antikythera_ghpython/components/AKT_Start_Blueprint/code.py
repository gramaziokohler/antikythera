"""Grasshopper Script"""

import json
import urllib.request
import urllib.error

import Grasshopper


class StartBlueprintComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, blueprint_path: str, broker_host: str, broker_port: int, orchestrator_api: str, start):
        broker_host = broker_host or "127.0.0.1"
        broker_port = broker_port or 1883
        orchestrator_api = orchestrator_api or "http://localhost:8000"

        if start:
            self.start_blueprint(orchestrator_api, blueprint_path, broker_host, broker_port)
        return

    def start_blueprint(self, orchestrator_api, blueprint_path, broker_host, broker_port):
        endpoint = f"{orchestrator_api}/blueprints/start"

        payload = {"blueprint_file": blueprint_path, "broker_host": broker_host, "broker_port": int(broker_port)}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urllib.request.urlopen(req) as res:
                body = res.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.URLError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}
