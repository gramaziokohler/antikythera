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
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic import Field

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.orchestrator import Orchestrator
from antikythera.orchestrator.storage import BlueprintStorage

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


app = FastAPI(title="Antikythera Orchestrator API")
_sessions_lock = Lock()
_sessions: Dict[str, ActiveSession] = {}
_blueprint_storage: BlueprintStorage = BlueprintStorage()


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


@app.get("/sessions", response_model=list[SessionInfo])
def list_sessions() -> list[SessionInfo]:
    with _sessions_lock:
        infos = [
            SessionInfo(
                session_id=sid,
                blueprint_file=session.blueprint_file,
                broker_host=session.broker_host,
                broker_port=session.broker_port,
                started_at=session.started_at,
            )
            for sid, session in _sessions.items()
        ]
    return infos


@app.get("/blueprints", response_model=list[BlueprintInfo])
def list_blueprints() -> list[BlueprintInfo]:
    try:
        blueprints_metadata = _blueprint_storage.list_blueprints()
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
        LOG.exception("Failed to parse uploaded blueprint file")
        raise HTTPException(status_code=400, detail=f"Failed to parse blueprint file: {exc}")

    global _blueprint_storage
    if _blueprint_storage is None:
        try:
            _blueprint_storage = BlueprintStorage()
        except Exception as exc:
            LOG.exception("Failed to initialize BlueprintStorage")
            raise HTTPException(status_code=500, detail=f"Database not available: {exc}")

    try:
        _blueprint_storage.add_blueprint(blueprint)
    except Exception as exc:
        LOG.exception("Failed to save blueprint to database")
        raise HTTPException(status_code=500, detail=f"Failed to save blueprint: {exc}")

    return UploadBlueprintResponse(blueprint_id=blueprint.id, message="Blueprint uploaded successfully.")


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
