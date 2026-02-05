"""Grasshopper Script"""

import json
import urllib.error
import urllib.request

import Grasshopper


class GetSessionDataComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, session_id: str, orchestrator_api: str, refresh: bool):
        orchestrator_api = orchestrator_api or "http://localhost:8000"

        # If accessing via frontend proxy (e.g. port 5174), ensure /api prefix if needed.
        # But standard usage is direct backend access.

        if refresh and session_id:
            return self.get_session_data(orchestrator_api, session_id)
        return

    def get_session_data(self, orchestrator_api, session_id):
        endpoint = f"{orchestrator_api}/sessions/{session_id}/data"

        try:
            req = urllib.request.Request(endpoint, headers={"Content-Type": "application/json"}, method="GET")
            with urllib.request.urlopen(req) as res:
                body = res.read().decode("utf-8")
                response_json = json.loads(body)

                # The actual session data structure is serialized in the 'data' field
                inner_data_str = response_json.get("data")
                if inner_data_str:
                    return json.loads(inner_data_str)
                return response_json

        except urllib.error.URLError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}
