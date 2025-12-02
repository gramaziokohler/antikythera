import argparse
import logging
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from threading import Lock
from typing import Dict
from typing import Optional

import uvicorn
from compas.data import json_dumps
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic import Field

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.orchestrator import Orchestrator
from antikythera.orchestrator.storage import BlueprintStorage
from antikythera.orchestrator.storage import RequestedBlueprintNotFound
from antikythera.orchestrator.storage import SessionStorage

LOG = logging.getLogger(__name__)


@dataclass
class ActiveSession:
    orchestrator: Orchestrator
    blueprint_id: str
    broker_host: str
    broker_port: int
    started_at: datetime


class StartBlueprintRequest(BaseModel):
    blueprint_id: str = Field(..., description="ID of the blueprint to start.")
    broker_host: str = Field("127.0.0.1", description="MQTT broker host.")
    broker_port: int = Field(1883, ge=1, le=65535, description="MQTT broker port.")


class StartBlueprintResponse(BaseModel):
    session_id: str
    message: str


class SessionInfo(BaseModel):
    session_id: str
    blueprint_id: str
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


class BlueprintInfo(BaseModel):
    id: str
    name: str
    version: str
    description: Optional[str]
    task_count: int
    uploaded_at: datetime


class UploadBlueprintResponse(BaseModel):
    blueprint_id: str
    message: str


class DeleteBlueprintResponse(BaseModel):
    blueprint_id: str
    message: str


app = FastAPI(title="Antikythera Orchestrator API")
_sessions_lock = Lock()
_sessions: Dict[str, ActiveSession] = {}


def _start_blueprint_session(request: StartBlueprintRequest) -> str:
    try:
        with BlueprintStorage() as storage:
            blueprint = storage.get_blueprint(request.blueprint_id)

    except Exception as exc:  # pragma: no cover - runtime safety
        LOG.exception(f"Failed to load blueprint with id {request.blueprint_id}")
        raise HTTPException(status_code=400, detail=f"Failed to load blueprint: {exc}")

    session_id = uuid.uuid4().hex
    session = BlueprintSession(bsid=session_id, blueprint=blueprint)
    orchestrator = Orchestrator(session, broker_host=request.broker_host, broker_port=request.broker_port)

    try:
        orchestrator.start()
    except Exception as exc:  # pragma: no cover - runtime safety
        LOG.exception("Failed to start orchestrator for session %s", session_id)
        raise HTTPException(status_code=500, detail=f"Unable to start orchestrator: {exc}")

    started_at = datetime.now(timezone.utc)
    with _sessions_lock:
        _sessions[session_id] = ActiveSession(
            orchestrator=orchestrator,
            blueprint_id=request.blueprint_id,
            broker_host=request.broker_host,
            broker_port=request.broker_port,
            started_at=started_at,
        )

    return session_id


@app.post("/blueprints/start", response_model=StartBlueprintResponse, status_code=202)
def start_blueprint(payload: StartBlueprintRequest) -> StartBlueprintResponse:
    session_id = _start_blueprint_session(payload)
    return StartBlueprintResponse(session_id=session_id, message="Blueprint execution started.")


@app.get("/sessions", response_model=list[SessionInfo])
def list_sessions() -> list[SessionInfo]:
    with _sessions_lock:
        infos = [
            SessionInfo(
                session_id=sid,
                blueprint_id=session.blueprint_id,
                broker_host=session.broker_host,
                broker_port=session.broker_port,
                started_at=session.started_at,
                state=session.orchestrator.session.state,
            )
            for sid, session in _sessions.items()
        ]
    return infos


@app.get("/blueprints", response_model=list[BlueprintInfo])
def list_blueprints() -> list[BlueprintInfo]:
    try:
        with BlueprintStorage() as storage:
            blueprints_metadata = storage.list_blueprints()
    except Exception as exc:
        LOG.exception("Failed to fetch blueprints from database")
        raise HTTPException(status_code=500, detail=f"Failed to fetch blueprints: {exc}")

    blueprint_infos = [
        BlueprintInfo(
            id=metadata["id"],
            name=metadata["name"],
            version=metadata["version"],
            description=metadata.get("description"),
            task_count=metadata["task_count"],
            uploaded_at=datetime.fromisoformat(metadata["uploaded_at"]),
        )
        for metadata in blueprints_metadata
    ]

    return blueprint_infos


@app.post("/blueprints/upload", response_model=UploadBlueprintResponse, status_code=201)
async def upload_blueprint(file: UploadFile) -> UploadBlueprintResponse:
    """Upload a blueprint JSON file to the database.

    Parameters
    ----------
    file : UploadFile
        The blueprint JSON file to upload.

    Returns
    -------
    UploadBlueprintResponse
        Response containing the blueprint ID and success message.

    Raises
    ------
    HTTPException
        If the file is not a JSON file or cannot be parsed.
    """
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are accepted.")

    try:
        content = await file.read()

        # Create a temporary file to use Blueprint.from_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp_file:
            tmp_file.write(content.decode())
            tmp_file_path = tmp_file.name

        try:
            blueprint = Blueprint.from_file(tmp_file_path)
        finally:
            # Clean up temp file
            Path(tmp_file_path).unlink(missing_ok=True)

    except Exception as exc:
        LOG.exception("Failed to parse uploaded blueprint file. Make sure it's a valid JSON blueprint.")
        raise HTTPException(status_code=400, detail=f"Failed to parse blueprint file: {exc}")

    try:
        with BlueprintStorage() as storage:
            storage.add_blueprint(blueprint)
    except Exception as exc:
        LOG.exception("Failed to save blueprint to database")
        raise HTTPException(status_code=500, detail=f"Failed to save blueprint: {exc}")

    return UploadBlueprintResponse(blueprint_id=blueprint.id, message="Blueprint uploaded successfully.")


@app.delete("/blueprints/{blueprint_id}", response_model=DeleteBlueprintResponse)
def delete_blueprint(blueprint_id: str) -> DeleteBlueprintResponse:
    try:
        with BlueprintStorage() as storage:
            storage.remove_blueprint(blueprint_id)
    except RequestedBlueprintNotFound as exc:
        LOG.warning(f"Blueprint {blueprint_id} not found: {exc}")
        raise HTTPException(status_code=404, detail=f"Blueprint {blueprint_id} not found")
    except Exception as exc:
        LOG.exception(f"Failed to delete blueprint {blueprint_id}")
        raise HTTPException(status_code=500, detail=f"Failed to delete blueprint: {exc}")

    return DeleteBlueprintResponse(blueprint_id=blueprint_id, message="Blueprint deleted successfully.")


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

    if session:
        # Retrieve data for the main blueprint of the session
        blueprint_id = session.orchestrator.session.blueprint.id
        data = session.orchestrator.session_storage.get_all(blueprint_id)
        state = session.orchestrator.session.state
        return SessionDataResponse(session_id=session_id, data=json_dumps(data), state=state)

    # If session is not in memory, try to load from storage
    with SessionStorage() as storage:
        session_info = storage.get_session_info(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="Session not found")

        blueprint_id = session_info["blueprint_id"]
        state = session_info["state"]
        data = storage.get_all(blueprint_id)

        return SessionDataResponse(session_id=session_id, data=json_dumps(data), state=state)



@app.on_event("shutdown")
def shutdown() -> None:
    with _sessions_lock:
        for session in _sessions.values():
            try:
                session.orchestrator.stop()
            except Exception:  # pragma: no cover - best-effort shutdown
                LOG.exception(f"Failed to stop orchestrator for blueprint {session.blueprint_id}")
        _sessions.clear()


def main() -> None:
    """Entrypoint that launches the FastAPI server."""
    parser = argparse.ArgumentParser(description="Antikythera Orchestrator API")
    parser.add_argument("--host", default="0.0.0.0", help="API host.")
    parser.add_argument("--port", type=int, default=8000, help="API port.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, filename="orchestrator.log", filemode="a", format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
