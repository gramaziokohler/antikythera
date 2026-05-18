"""Antikythera MCP Server.

Exposes Antikythera's orchestrator over the Model Context Protocol so that
LLMs can author blueprints and control sessions.

Usage (stdio, default – for Claude Desktop / VS Code agents):
    python -m antikythera_orchestrator.mcp_server

Usage (SSE, for network clients):
    python -m antikythera_orchestrator.mcp_server --transport sse --port 8001

The server talks to the Antikythera REST API. Set ANTIKYTHERA_API_BASE (default:
http://localhost:8000) or pass --api-base on the command line.
"""

import json
import os
from typing import Any
from typing import List
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Global configuration – can be overridden via env var or CLI flag
# ---------------------------------------------------------------------------

_api_base: str = os.getenv("ANTIKYTHERA_API_BASE", "http://localhost:8000")


def _client() -> httpx.Client:
    return httpx.Client(base_url=_api_base, timeout=30.0)


# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "antikythera",
    instructions=(
        "You are connected to an Antikythera orchestrator — a distributed task-graph "
        "execution engine for robotic and automated processes.\n\n"
        "KEY CONCEPTS:\n"
        "• Blueprint: a JSON workflow definition — a DAG of typed Tasks.\n"
        "• Task: a unit of work with a 'type' (e.g. 'system.start', 'system.sleep', "
        "'user_interaction.user_output'). Every blueprint needs exactly one 'system.start' "
        "and one 'system.end' task.\n"
        "• depends_on: declares ordering. Tasks run only after their dependencies succeed.\n"
        "• Wiring: task inputs can reference upstream outputs via get_from / set_to keys. "
        "A task input with get_from='my_key' will receive the value from an upstream task "
        "output whose set_to (or name, if set_to is absent) equals 'my_key'.\n"
        "• Session: an execution instance of a blueprint. It can be started, paused, "
        "stopped, and resumed. Use get_session_diagram to monitor progress.\n\n"
        "WORKFLOW:\n"
        "1. Call list_blueprints to see what exists.\n"
        "2. Author a new blueprint JSON, call validate_blueprint to check it, then "
        "create_blueprint to upload.\n"
        "3. Call start_session to execute it.\n"
        "4. Use get_session_diagram repeatedly to monitor task states.\n"
        "5. Use reset_task / skip_task / reset_scope for intervention."
    ),
)


# ===========================================================================
# Blueprint authoring tools
# ===========================================================================


@mcp.tool()
def list_blueprints() -> List[dict]:
    """List all uploaded blueprints with their metadata (id, name, version, task_count)."""
    with _client() as client:
        response = client.get("/blueprints")
        response.raise_for_status()
        return response.json()


@mcp.tool()
def get_blueprint(blueprint_id: str) -> str:
    """Return the full JSON definition of a blueprint.

    Parameters
    ----------
    blueprint_id:
        The blueprint ID to retrieve.
    """
    with _client() as client:
        response = client.get(f"/blueprints/{blueprint_id}")
        response.raise_for_status()
        return response.text


@mcp.tool()
def validate_blueprint(blueprint_json: str) -> dict:
    """Validate a blueprint JSON string without uploading it.

    Checks:
    • Required top-level fields (id, name, version, tasks)
    • Every task has id and type
    • depends_on references exist
    • No dependency cycles
    • Input get_from keys resolve to an upstream task output (set_to or name)

    Parameters
    ----------
    blueprint_json:
        The blueprint as a JSON string.
    """
    try:
        data = json.loads(blueprint_json)
    except json.JSONDecodeError as exc:
        return {"valid": False, "issues": [f"Invalid JSON: {exc}"]}

    issues = _validate_blueprint_dict(data)
    return {"valid": len(issues) == 0, "issues": issues}


@mcp.tool()
def create_blueprint(blueprint_json: str) -> dict:
    """Author and upload a new blueprint.

    The blueprint must be a JSON string conforming to the Antikythera v1 schema.

    REQUIRED TOP-LEVEL FIELDS:
    • id       – unique slug, e.g. "my-workflow-v1"
    • name     – human-readable name
    • version  – schema version string, use "1.0"
    • tasks    – list of task objects (see below)

    TASK FIELDS:
    • id          – unique within the blueprint
    • type        – agent task type (see common types below)
    • description – optional human-readable label
    • depends_on  – list of {id: "<task_id>"} objects
    • inputs      – list of {name, get_from?, type?, description?}
    • outputs     – list of {name, set_to?, type?, description?}
    • params      – list of {name, value}

    WIRING:
    A task input with get_from="my_key" will receive the value produced by any upstream
    task output where set_to="my_key" (or name="my_key" if set_to is absent).

    COMMON TASK TYPES:
    • system.start  – must be the first task; outputs process_start_time
    • system.end    – must be the last task
    • system.sleep  – sleeps for param 'duration' seconds
    • system.composite – nested blueprint execution
    • user_interaction.user_output – print/display a value
    • user_interaction.user_input  – prompt the user for a JSON value

    MINIMAL EXAMPLE:
    {
      "id": "hello-world", "name": "Hello World", "version": "1.0",
      "tasks": [
        {"id": "start", "type": "system.start"},
        {"id": "wait",  "type": "system.sleep", "params": [{"name": "duration", "value": 2}],
         "depends_on": [{"id": "start"}]},
        {"id": "end",   "type": "system.end", "depends_on": [{"id": "wait"}]}
      ]
    }

    Parameters
    ----------
    blueprint_json:
        The complete blueprint as a JSON string.
    """
    try:
        data = json.loads(blueprint_json)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON: {exc}"}

    issues = _validate_blueprint_dict(data)
    if issues:
        return {"error": "Blueprint validation failed — fix these issues first.", "issues": issues}

    with _client() as client:
        response = client.post(
            "/blueprints/upload",
            files={"file": (f"{data['id']}.json", blueprint_json.encode(), "application/json")},
        )
        response.raise_for_status()
        return response.json()


@mcp.tool()
def delete_blueprint(blueprint_id: str) -> dict:
    """Delete a blueprint from the orchestrator.

    Parameters
    ----------
    blueprint_id:
        The blueprint ID to delete.
    """
    with _client() as client:
        response = client.delete(f"/blueprints/{blueprint_id}")
        response.raise_for_status()
        return response.json()


# ===========================================================================
# Session control tools
# ===========================================================================


@mcp.tool()
def list_sessions(limit: int = 20, offset: int = 0) -> List[dict]:
    """List all sessions (active and historical).

    Parameters
    ----------
    limit:
        Maximum number of sessions to return. Default 20.
    offset:
        Pagination offset. Default 0.
    """
    with _client() as client:
        response = client.get("/sessions", params={"limit": limit, "offset": offset})
        response.raise_for_status()
        return response.json()


@mcp.tool()
def start_session(
    blueprint_id: str,
    session_name: Optional[str] = None,
    params: Optional[dict] = None,
) -> dict:
    """Create and immediately start a session from a blueprint.

    Parameters
    ----------
    blueprint_id:
        ID of the blueprint to execute.
    session_name:
        Optional human-readable name used as the session ID (slugified).
        A unique UUID is auto-generated if omitted.
    params:
        Arbitrary string key-value pairs passed into the session context
        (accessible by tasks via their inputs).
    """
    payload: dict[str, Any] = {"blueprint_id": blueprint_id}
    if session_name:
        payload["session_name"] = session_name
    if params:
        payload["params"] = params

    with _client() as client:
        create_resp = client.post("/blueprints/start", json=payload)
        create_resp.raise_for_status()
        session_id = create_resp.json()["session_id"]

        start_resp = client.post(f"/sessions/{session_id}/start", json={})
        start_resp.raise_for_status()

    return {"session_id": session_id, "message": "Session created and started."}


@mcp.tool()
def get_session_diagram(session_id: str) -> str:
    """Get a Mermaid diagram showing the current state of every task in a session.

    Task states: PENDING, READY, RUNNING, SUCCEEDED, FAILED, SKIPPED.
    This is the best tool to monitor session progress.

    Parameters
    ----------
    session_id:
        The session ID.
    """
    with _client() as client:
        response = client.get(f"/sessions/{session_id}/diagram")
        response.raise_for_status()
        data = response.json()
    return f"Session state: {data['state']}\n\n{data['diagram']}"


@mcp.tool()
def get_session_data(session_id: str) -> str:
    """Get all data values stored in a session's context (task outputs, parameters).

    Returns a JSON string with keys per blueprint and their stored values.

    Parameters
    ----------
    session_id:
        The session ID.
    """
    with _client() as client:
        response = client.get(f"/sessions/{session_id}/data")
        response.raise_for_status()
        data = response.json()
    return data["data"]


@mcp.tool()
def get_session_details(session_id: str) -> str:
    """Get the full serialised session object (blueprint definitions + task states).

    Parameters
    ----------
    session_id:
        The session ID.
    """
    with _client() as client:
        response = client.get(f"/sessions/{session_id}")
        response.raise_for_status()
    return response.text


@mcp.tool()
def pause_session(session_id: str) -> dict:
    """Pause a running session. Resume it later with resume_session.

    Parameters
    ----------
    session_id:
        The session ID to pause.
    """
    with _client() as client:
        response = client.post(f"/sessions/{session_id}/pause")
        response.raise_for_status()
        return response.json()


@mcp.tool()
def resume_session(session_id: str) -> dict:
    """Resume a paused or stopped session.

    Parameters
    ----------
    session_id:
        The session ID to resume.
    """
    with _client() as client:
        response = client.post(f"/sessions/{session_id}/start", json={})
        response.raise_for_status()
        return response.json()


@mcp.tool()
def stop_session(session_id: str) -> dict:
    """Stop a session and persist its final state to storage.

    The session can be resumed later with resume_session.

    Parameters
    ----------
    session_id:
        The session ID to stop.
    """
    with _client() as client:
        response = client.post(f"/sessions/{session_id}/stop")
        response.raise_for_status()
        return response.json()


@mcp.tool()
def delete_session(session_id: str) -> dict:
    """Delete a session and all its data from storage.

    The session must not be in RUNNING state — pause or stop it first.

    Parameters
    ----------
    session_id:
        The session ID to delete.
    """
    with _client() as client:
        response = client.delete(f"/sessions/{session_id}")
        response.raise_for_status()
        return response.json()


@mcp.tool()
def reset_task(
    session_id: str,
    blueprint_id: str,
    task_id: str,
    include_downstream: bool = True,
    clear_outputs: bool = True,
) -> dict:
    """Reset a task (and optionally its downstream tasks) to PENDING state.

    The session must be paused or stopped first.

    Parameters
    ----------
    session_id:
        The session containing the task.
    blueprint_id:
        The blueprint ID containing the task.
    task_id:
        The task ID to reset.
    include_downstream:
        Also reset tasks that depend on this one. Default True.
    clear_outputs:
        Clear stored output values for all reset tasks. Default True.
    """
    with _client() as client:
        response = client.post(
            f"/sessions/{session_id}/tasks/reset",
            json={
                "blueprint_id": blueprint_id,
                "task_id": task_id,
                "include_downstream": include_downstream,
                "clear_outputs": clear_outputs,
            },
        )
        response.raise_for_status()
        return response.json()


@mcp.tool()
def skip_task(session_id: str, blueprint_id: str, task_id: str) -> dict:
    """Mark a task to be skipped during execution.

    The session must be paused or stopped first.

    Parameters
    ----------
    session_id:
        The session containing the task.
    blueprint_id:
        The blueprint ID containing the task.
    task_id:
        The task ID to skip.
    """
    with _client() as client:
        response = client.post(
            f"/sessions/{session_id}/tasks/skip",
            json={"blueprint_id": blueprint_id, "task_id": task_id},
        )
        response.raise_for_status()
        return response.json()


@mcp.tool()
def reset_scope(session_id: str, scope_name: str) -> dict:
    """Reset all tasks in a named scope back to PENDING (e.g. for loop / while scopes).

    The session must be paused or stopped first.

    Parameters
    ----------
    session_id:
        The session containing the scope.
    scope_name:
        The scope name / id to reset.
    """
    with _client() as client:
        response = client.post(f"/sessions/{session_id}/scopes/{scope_name}/reset")
        response.raise_for_status()
        return response.json()


# ===========================================================================
# Model management tools
# ===========================================================================


@mcp.tool()
def list_models() -> List[str]:
    """List all available model IDs stored in the orchestrator."""
    with _client() as client:
        response = client.get("/models")
        response.raise_for_status()
        return response.json()


@mcp.tool()
def delete_model(model_id: str) -> dict:
    """Delete a model from the orchestrator's storage.

    Parameters
    ----------
    model_id:
        The model ID to delete.
    """
    with _client() as client:
        response = client.delete(f"/models/{model_id}")
        response.raise_for_status()
        return response.json()


# ===========================================================================
# MCP Resources
# ===========================================================================


@mcp.resource("blueprint://{blueprint_id}")
def blueprint_resource(blueprint_id: str) -> str:
    """Full JSON definition of a blueprint."""
    with _client() as client:
        response = client.get(f"/blueprints/{blueprint_id}")
        response.raise_for_status()
    return response.text


@mcp.resource("session://{session_id}/diagram")
def session_diagram_resource(session_id: str) -> str:
    """Mermaid diagram of the current session task state."""
    with _client() as client:
        response = client.get(f"/sessions/{session_id}/diagram")
        response.raise_for_status()
        data = response.json()
    return f"Session state: {data['state']}\n\n{data['diagram']}"


# ===========================================================================
# Internal validation helpers
# ===========================================================================


def _validate_blueprint_dict(data: dict) -> List[str]:
    issues: List[str] = []

    for field_name in ("id", "name", "version"):
        if not data.get(field_name):
            issues.append(f"Missing required field: '{field_name}'")

    tasks = data.get("tasks")
    if not tasks or not isinstance(tasks, list):
        issues.append("Blueprint must have a non-empty 'tasks' list.")
        return issues

    task_ids = {t.get("id") for t in tasks if t.get("id")}
    output_keys_by_task: dict[str, set] = {}
    dep_map: dict[str, List[str]] = {}

    for task in tasks:
        tid = task.get("id")
        if not tid:
            issues.append("A task is missing a required 'id' field.")
            continue
        if not task.get("type"):
            issues.append(f"Task '{tid}': missing required 'type' field.")

        # Collect output storage keys (set_to takes priority over name)
        output_keys_by_task[tid] = {out.get("set_to") or out.get("name") for out in task.get("outputs", []) if out.get("set_to") or out.get("name")}

        # Collect and validate dependencies
        dep_map[tid] = []
        for dep in task.get("depends_on", []):
            dep_id = dep.get("id")
            if not dep_id:
                continue
            if dep_id not in task_ids:
                issues.append(f"Task '{tid}': depends_on unknown task '{dep_id}'.")
            else:
                dep_map[tid].append(dep_id)

    # Validate input wiring
    for task in tasks:
        tid = task.get("id")
        if not tid:
            continue
        for inp in task.get("inputs", []):
            get_from = inp.get("get_from")
            if not get_from:
                continue
            upstream_ids = _collect_upstream(tid, dep_map)
            if not any(get_from in output_keys_by_task.get(uid, set()) for uid in upstream_ids):
                issues.append(
                    f"Task '{tid}' input '{inp.get('name')}': get_from='{get_from}' does not "
                    f"match any upstream task output (set_to / name). "
                    f"Upstream tasks: {sorted(upstream_ids)}"
                )

    for cycle in _find_cycles(dep_map):
        issues.append(f"Dependency cycle detected: {' -> '.join(cycle)}")

    return issues


def _collect_upstream(task_id: str, dep_map: dict[str, List[str]]) -> set:
    visited: set = set()
    queue = list(dep_map.get(task_id, []))
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        queue.extend(dep_map.get(current, []))
    return visited


def _find_cycles(dep_map: dict[str, List[str]]) -> List[List[str]]:
    visited: set = set()
    rec_stack: set = set()
    cycles: List[List[str]] = []

    def dfs(node: str, path: List[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in dep_map.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path + [neighbor])
            elif neighbor in rec_stack:
                start = path.index(neighbor) if neighbor in path else 0
                cycles.append(path[start:] + [neighbor])
        rec_stack.discard(node)

    for node in dep_map:
        if node not in visited:
            dfs(node, [node])

    return cycles


# ===========================================================================
# Entrypoint
# ===========================================================================


def main() -> None:
    import argparse

    global _api_base

    parser = argparse.ArgumentParser(description="Antikythera MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host for SSE transport (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8001, help="Port for SSE transport (default: 8001)")
    parser.add_argument(
        "--api-base",
        default=None,
        help="Antikythera API base URL (overrides ANTIKYTHERA_API_BASE env var)",
    )
    args = parser.parse_args()

    if args.api_base:
        _api_base = args.api_base

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
