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

from compas.data import json_dumps
from compas.data import json_loads
from compas_model.models import Model

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Response
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic import Field

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.storage import BlueprintStorage
from antikythera_orchestrator.storage import ModelStorage
from antikythera_orchestrator.storage import RequestedBlueprintNotFound
from antikythera_orchestrator.storage import RequestedModelNotFound
from antikythera_orchestrator.storage import SessionStorage

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
    params: Dict[str, str] = Field(default_factory=dict, description="Arbitrary parameters for the session.")


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


class UploadModelResponse(BaseModel):
    model_id: str
    message: str


class DeleteModelResponse(BaseModel):
    model_id: str
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
    session = BlueprintSession(bsid=session_id, blueprint=blueprint, params=request.params)
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
        storage = session.orchestrator.session_storage
        # Retrieve data for all blueprints of the session
        blueprint_id = session.orchestrator.session.blueprint.id
        inner_blueprint_ids = session.orchestrator.session.inner_blueprints.keys()
        data = {"main_blueprint": storage.get_all(blueprint_id), "inner_blueprints": {blueprint_id: storage.get_all(blueprint_id) for blueprint_id in inner_blueprint_ids}}
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


@app.post("/models/upload", response_model=UploadModelResponse, status_code=201)
async def upload_model(file: UploadFile) -> UploadModelResponse:
    """Upload a model JSON file to the database.

    Parameters
    ----------
    file : UploadFile
        The model JSON file to upload.

    Returns
    -------
    UploadModelResponse
        Response containing the model ID and success message.

    Raises
    ------
    HTTPException
        If the file is not a JSON file or cannot be parsed.
    """
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are accepted.")

    try:
        content = await file.read()

        # Parse JSON to ensure validity and extract ID
        model_data: Model = json_loads(content.decode())

        model_id = f"{Path(file.filename).stem}_{str(model_data.guid)[0:8]}"

    except Exception as exc:
        LOG.exception("Failed to parse uploaded model file.")
        raise HTTPException(status_code=400, detail=f"Failed to parse model file: {exc}")

    try:
        with ModelStorage() as storage:
            storage.add_model(model_id, model_data)
    except Exception as exc:
        LOG.exception("Failed to save model to database")
        raise HTTPException(status_code=500, detail=f"Failed to save model: {exc}")

    return UploadModelResponse(model_id=model_id, message="Model uploaded successfully.")


@app.get("/models", response_model=list[str])
def list_models() -> list[str]:
    """List all available model IDs.

    Returns
    -------
    list[str]
        A list of model IDs.
    """
    try:
        with ModelStorage() as storage:
            return storage.list_models()
    except Exception as exc:
        LOG.exception("Failed to fetch models from database")
        raise HTTPException(status_code=500, detail=f"Failed to fetch models: {exc}")


@app.delete("/models/{model_id}", response_model=DeleteModelResponse)
def delete_model(model_id: str) -> DeleteModelResponse:
    """Delete a model from the database.

    Parameters
    ----------
    model_id : str
        The ID of the model to delete.

    Returns
    -------
    DeleteModelResponse
        Response containing the model ID and success message.

    Raises
    ------
    HTTPException
        If the model is not found or cannot be deleted.
    """
    try:
        with ModelStorage() as storage:
            storage.remove_model(model_id)
    except RequestedModelNotFound as exc:
        LOG.warning(f"Model {model_id} not found: {exc}")
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
    except Exception as exc:
        LOG.exception(f"Failed to delete model {model_id}")
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {exc}")

    return DeleteModelResponse(model_id=model_id, message="Model deleted successfully.")


@app.get("/models/{model_id}")
def get_model(model_id: str):
    """Retrieve a model by its ID.

    Parameters
    ----------
    model_id : str
        The ID of the model to retrieve.

    Returns
    -------
    Response
        The model data as a JSON response.

    Raises
    ------
    HTTPException
        If the model is not found.
    """
    try:
        with ModelStorage() as storage:
            model = storage.get_model(model_id)
    except RequestedModelNotFound:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
    except Exception as exc:
        LOG.exception(f"Failed to retrieve model {model_id}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve model: {exc}")

    return Response(content=json_dumps(model), media_type="application/json")


@app.get("/blueprints/{blueprint_id}")
def get_blueprint(blueprint_id: str):
    """Retrieve a blueprint by its ID.

    If the blueprint is currently active in a session, the active (possibly expanded)
    version is returned. Otherwise, the stored version is returned.

    Parameters
    ----------
    blueprint_id : str
        The ID of the blueprint to retrieve.

    Returns
    -------
    Response
        The blueprint data as a JSON response.

    Raises
    ------
    HTTPException
        If the blueprint is not found.
    """
    blueprint = None

    # First check active sessions
    with _sessions_lock:
        for session in _sessions.values():
            if session.blueprint_id == blueprint_id:
                # Found active session with this blueprint
                # NOTE: this is tricky since if there's several sessions with the same blueprint (from previous runs) which are finished
                # thie finised one will be returned, potentially ignoring the currently active one.
                # TODO: made get_session_blueprint instead, maybe remove this section and always get from storage?
                blueprint = session.orchestrator.session.blueprint
                break

    if not blueprint:
        # If not found in active sessions, check storage
        try:
            with BlueprintStorage() as storage:
                blueprint = storage.get_blueprint(blueprint_id)
        except RequestedBlueprintNotFound:
            raise HTTPException(status_code=404, detail=f"Blueprint {blueprint_id} not found")
        except Exception as exc:
            LOG.exception(f"Failed to retrieve blueprint {blueprint_id}")
            raise HTTPException(status_code=500, detail=f"Failed to retrieve blueprint: {exc}")

    return Response(content=json_dumps(blueprint), media_type="application/json")


@app.get("/sessions/{session_id}/blueprint")
def get_session_blueprint(session_id: str):
    # Check active sessions
    with _sessions_lock:
        session_wrapper = _sessions.get(session_id)
        if session_wrapper:
            return Response(
                content=json_dumps(session_wrapper.orchestrator.session.blueprint),
                media_type="application/json",
            )

    # Check storage
    with SessionStorage() as session_storage:
        session_info = session_storage.get_session_info(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="Session not found")

        blueprint_id = session_info["blueprint_id"]

        try:
            with BlueprintStorage() as bp_storage:
                blueprint = bp_storage.get_blueprint(blueprint_id)
        except RequestedBlueprintNotFound:
            raise HTTPException(status_code=404, detail=f"Blueprint {blueprint_id} for session {session_id} not found")
        except Exception as exc:
            LOG.exception(f"Failed to retrieve blueprint {blueprint_id} for session {session_id}")
            raise HTTPException(status_code=500, detail=f"Failed to retrieve session blueprint: {exc}")

        return Response(content=json_dumps(blueprint), media_type="application/json")


@app.get("/sessions/{session_id}")
def get_session_details(session_id: str):
    """Retrieve full details of a session including blueprints and parameters.

    Parameters
    ----------
    session_id : str
        The ID of the session to retrieve.

    Returns
    -------
    Response
        The session data as a JSON response.

    Raises
    ------
    HTTPException
        If the session is not found.
    """
    # Check active sessions
    with _sessions_lock:
        session_wrapper = _sessions.get(session_id)
        if session_wrapper:
            return Response(
                content=json_dumps(session_wrapper.orchestrator.session),
                media_type="application/json",
            )

    # Check storage
    with SessionStorage() as session_storage:
        session_info = session_storage.get_session_info(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="Session not found")

        blueprint_id = session_info["blueprint_id"]
        state = session_info["state"]

        try:
            with BlueprintStorage() as bp_storage:
                blueprint = bp_storage.get_blueprint(blueprint_id)
        except Exception as exc:
            LOG.exception(f"Failed to retrieve blueprint {blueprint_id} for session {session_id}")
            raise HTTPException(status_code=500, detail=f"Failed to retrieve session blueprint: {exc}")

        # Reconstruct a partial session object
        # Note: params and inner_blueprints are not currently persisted, so they will be empty
        session = BlueprintSession(
            bsid=session_id,
            blueprint=blueprint,
            state=state,
        )

        return Response(content=json_dumps(session), media_type="application/json")


@app.on_event("shutdown")
def shutdown() -> None:
    with _sessions_lock:
        for session in _sessions.values():
            try:
                session.orchestrator.stop()
            except Exception:  # pragma: no cover - best-effort shutdown
                LOG.exception(f"Failed to stop orchestrator for blueprint {session.blueprint_id}")
        _sessions.clear()
