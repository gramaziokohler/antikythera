import argparse
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from threading import Lock
from typing import Dict
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

from compas.data import json_dumps

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.orchestrator import Orchestrator

LOG = logging.getLogger(__name__)


@dataclass
class ActiveSession:
    orchestrator: Orchestrator
    blueprint_file: str
    broker_host: str
    broker_port: int
    started_at: datetime


class StartBlueprintRequest(BaseModel):
    blueprint_file: str = Field(..., description="Path to the blueprint JSON file.")
    broker_host: str = Field("127.0.0.1", description="MQTT broker host.")
    broker_port: int = Field(1883, ge=1, le=65535, description="MQTT broker port.")


class StartBlueprintResponse(BaseModel):
    session_id: str
    message: str


class SessionInfo(BaseModel):
    session_id: str
    blueprint_file: str
    broker_host: str
    broker_port: int
    started_at: datetime
    state: str


class BlueprintDiagramResponse(BaseModel):
    session_id: str
    diagram: str
    state: str


class SessionDataResponse(BaseModel):
    session_id: str
    data: str
    state: str


app = FastAPI(title="Antikythera Orchestrator API")
_sessions_lock = Lock()
_sessions: Dict[str, ActiveSession] = {}


def _start_blueprint_session(payload: StartBlueprintRequest) -> str:
    blueprint_path = Path(payload.blueprint_file).expanduser()
    if not blueprint_path.is_file():
        raise HTTPException(status_code=400, detail=f"Blueprint file '{blueprint_path}' does not exist.")

    try:
        blueprint = Blueprint.from_file(str(blueprint_path))
    except Exception as exc:  # pragma: no cover - runtime safety
        LOG.exception("Failed to load blueprint from %s", blueprint_path)
        raise HTTPException(status_code=400, detail=f"Failed to load blueprint: {exc}")

    session_id = uuid.uuid4().hex
    session = BlueprintSession(bsid=session_id, blueprint=blueprint)
    orchestrator = Orchestrator(session, broker_host=payload.broker_host, broker_port=payload.broker_port)

    try:
        orchestrator.start()
    except Exception as exc:  # pragma: no cover - runtime safety
        LOG.exception("Failed to start orchestrator for session %s", session_id)
        raise HTTPException(status_code=500, detail=f"Unable to start orchestrator: {exc}")

    started_at = datetime.now(timezone.utc)
    with _sessions_lock:
        _sessions[session_id] = ActiveSession(
            orchestrator=orchestrator,
            blueprint_file=str(blueprint_path),
            broker_host=payload.broker_host,
            broker_port=payload.broker_port,
            started_at=started_at,
        )

    return session_id


@app.post("/blueprints/start", response_model=StartBlueprintResponse, status_code=202)
def start_blueprint(payload: StartBlueprintRequest) -> StartBlueprintResponse:
    session_id = _start_blueprint_session(payload)
    return StartBlueprintResponse(session_id=session_id, message="Blueprint execution started.")


@app.get("/blueprints", response_model=list[SessionInfo])
def list_sessions() -> list[SessionInfo]:
    with _sessions_lock:
        infos = [
            SessionInfo(
                session_id=sid,
                blueprint_file=session.blueprint_file,
                broker_host=session.broker_host,
                broker_port=session.broker_port,
                started_at=session.started_at,
                state=session.orchestrator.session.state,
            )
            for sid, session in _sessions.items()
        ]
    return infos


@app.get("/sessions/{session_id}/diagram", response_model=BlueprintDiagramResponse)
def get_session_diagram(session_id: str) -> BlueprintDiagramResponse:
    with _sessions_lock:
        session = _sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    diagram = session.orchestrator.to_mermaid_diagram()
    return BlueprintDiagramResponse(session_id=session_id, diagram=diagram, state=session.orchestrator.session.state)


@app.get("/sessions/{session_id}/data", response_model=SessionDataResponse)
def get_session_data(session_id: str) -> SessionDataResponse:
    with _sessions_lock:
        session = _sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Retrieve data for the main blueprint of the session
    blueprint_id = session.orchestrator.session.blueprint.id
    data = session.orchestrator.session_storage.get_all(blueprint_id)

    return SessionDataResponse(session_id=session_id, data=json_dumps(data), state=session.orchestrator.session.state)


@app.on_event("shutdown")
def shutdown() -> None:
    with _sessions_lock:
        for session in _sessions.values():
            try:
                session.orchestrator.stop()
            except Exception:  # pragma: no cover - best-effort shutdown
                LOG.exception("Failed to stop orchestrator for blueprint %s", session.blueprint_file)
        _sessions.clear()


def main() -> None:
    """Entrypoint that launches the FastAPI server."""
    parser = argparse.ArgumentParser(description="Antikythera Orchestrator API")
    parser.add_argument("--host", default="0.0.0.0", help="API host.")
    parser.add_argument("--port", type=int, default=8000, help="API port.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, filename="orchestrator.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
