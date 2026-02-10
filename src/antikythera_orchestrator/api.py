import logging
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from threading import Lock
from typing import Dict
from typing import Optional
from typing import cast

from compas.data import json_dumps
from compas.data import json_loads
from compas_model.models import Model
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi import Response
from fastapi import UploadFile
from fastapi.concurrency import asynccontextmanager
from pydantic import BaseModel
from pydantic import Field

from antikythera.io import BlueprintJsonSerializer
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.storage import BlueprintStorage
from antikythera_orchestrator.storage import ModelStorage
from antikythera_orchestrator.storage import RequestedBlueprintNotFound
from antikythera_orchestrator.storage import RequestedModelNotFound
from antikythera_orchestrator.storage import RequestedSessionNotFound
from antikythera_orchestrator.storage import SessionStorage

LOG = logging.getLogger(__name__)


@dataclass
class ActiveSession:
    """Runtime wrapper for a currently active blueprint session."""

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


class RestartSessionRequest(BaseModel):
    broker_host: str = Field("127.0.0.1", description="MQTT broker host.")
    broker_port: int = Field(1883, ge=1, le=65535, description="MQTT broker port.")


class StartBlueprintResponse(BaseModel):
    session_id: str
    message: str


class SessionInfo(BaseModel):
    """Response model for listing sessions."""

    session_id: str
    blueprint_id: str
    broker_host: str
    broker_port: int
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
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


class UploadModelsResponse(BaseModel):
    model_ids: list[str] = Field(default_factory=list, description="Model IDs of the uploaded models.")
    message: str


class DeleteModelResponse(BaseModel):
    model_id: str
    message: str


class SessionActionResponse(BaseModel):
    session_id: str
    message: str


_sessions_lock = Lock()
_sessions: Dict[str, ActiveSession] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # before running
    LOG.info("Antikythera Orchestrator API starting up...")

    # app is running
    yield

    # on shutdown
    LOG.info("Shutting down all active sessions...")
    with _sessions_lock:
        for session in _sessions.values():
            try:
                session.orchestrator.stop()
            except Exception:  # pragma: no cover - best-effort shutdown
                LOG.exception(f"Failed to stop orchestrator for blueprint {session.blueprint_id}")
        _sessions.clear()


app = FastAPI(title="Antikythera Orchestrator API", lifespan=lifespan)


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

    # Not starting the orchestrator yet, just creating the session and storing it
    # The user can now inspect the session in "preview" mode and hit resume when it's time to run.

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
def list_sessions(
    limit: int = Query(10, ge=1, le=1000, description="Number of sessions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[SessionInfo]:
    sessions_in_storage = SessionStorage.list_sessions(limit=limit, offset=offset)

    session_infos = []
    for session_id in sessions_in_storage:
        with SessionStorage(session_id) as storage:
            session_data = storage.load_session_with_metadata()
            if not session_data:
                continue

            session = session_data["session"]
            started_at = session_data.get("started_at")
            ended_at = session_data.get("ended_at")

            # stored times are ISO format UTC
            if started_at:
                started_at = datetime.fromisoformat(started_at)
            if ended_at:
                ended_at = datetime.fromisoformat(ended_at)

            broker_host = "unavailable"
            broker_port = 0

            if session_id in _sessions:
                # only active sessions have useful broker info
                with _sessions_lock:
                    active_session = _sessions[session_id]
                    broker_host = active_session.broker_host
                    broker_port = active_session.broker_port

            session_infos.append(
                SessionInfo(
                    session_id=session_id,
                    blueprint_id=session.blueprint.id,
                    broker_host=broker_host,
                    broker_port=broker_port,
                    started_at=started_at,
                    ended_at=ended_at,
                    state=session.state,
                )
            )
    return session_infos


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

        # Create a temporary file to use BlueprintJsonSerializer.from_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp_file:
            tmp_file.write(content.decode())
            tmp_file_path = tmp_file.name

        try:
            blueprint = BlueprintJsonSerializer.from_file(tmp_file_path)
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


def _enrich_data_with_types(data_dict: Dict) -> Dict:
    """Enrich data values with type information for frontend."""
    enriched = {}
    for key, value in data_dict.items():
        val_type = "json"

        # Determine type
        if isinstance(value, (int, float)):
            val_type = "number"
        elif isinstance(value, str):
            val_type = "text"
        elif isinstance(value, dict) and "dtype" in value:
            # Check for COMPAS geometry
            dtype = value["dtype"]
            if dtype.startswith("compas.geometry") or dtype.startswith("compas.datastructures") or dtype.startswith("antikythera.models"):
                val_type = "geometry"

        enriched[key] = {"value": value, "type": val_type}
    return enriched


@app.get("/sessions/{session_id}/data", response_model=SessionDataResponse)
def get_session_data(session_id: str) -> SessionDataResponse:
    # Always load from storage to ensure consistency
    with SessionStorage(session_id) as storage:
        session = storage.load_session()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        blueprint_id = session.blueprint.id
        state = session.state
        inner_blueprint_ids = list(session.inner_blueprints.keys())

        data = {
            "main_blueprint": _enrich_data_with_types(storage.get_all(blueprint_id)),
            "inner_blueprints": {inner_id: _enrich_data_with_types(storage.get_all(inner_id)) for inner_id in inner_blueprint_ids},
        }

        return SessionDataResponse(session_id=session_id, data=json_dumps(data), state=state)


@app.post("/sessions/{session_id}/pause", response_model=SessionActionResponse)
def pause_session(session_id: str) -> SessionActionResponse:
    with _sessions_lock:
        session = _sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        session.orchestrator.pause()
    except Exception as exc:
        LOG.exception(f"Failed to pause session {session_id}")
        raise HTTPException(status_code=500, detail=f"Failed to pause session: {exc}")

    return SessionActionResponse(session_id=session_id, message="Session paused.")


@app.post("/sessions/{session_id}/stop", response_model=SessionActionResponse)
def stop_session(session_id: str) -> SessionActionResponse:
    with _sessions_lock:
        session = _sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # the difference between pause and stop is that when stopping the orchestrator will unsubscribe
        # from all topics, message queue will be flushed and serialize final state to storage
        session.orchestrator.stop()
    except Exception as exc:
        LOG.exception(f"Failed to stop session {session_id}")
        raise HTTPException(status_code=500, detail=f"Failed to stop session: {exc}")

    return SessionActionResponse(session_id=session_id, message="Session stopped.")


def _get_bp_session_from_storage(session_id: str) -> BlueprintSession:
    with SessionStorage(session_id) as session_storage:
        session = session_storage.load_session()
        if not session:
            raise RequestedSessionNotFound(f"session id: {session_id}")
        return session


def _revive_session(session_id: str, broker_host: str, broker_port: int) -> ActiveSession:
    """Revive a session from storage if it is not currently active in memory."""

    session = _get_bp_session_from_storage(session_id)

    if session.state == BlueprintSessionState.COMPLETED:
        # NOTE: not sure if we actually want this restriction
        raise ValueError("Cannot revive a completed session. Just start a new one.")

    orchestrator = Orchestrator(session, broker_host=broker_host, broker_port=broker_port)

    active_session = ActiveSession(
        orchestrator=orchestrator,
        blueprint_id=session.blueprint.id,
        broker_host=broker_host,
        broker_port=broker_port,
        started_at=datetime.now(timezone.utc),
    )

    with _sessions_lock:
        _sessions[session_id] = active_session

    LOG.info(f"Revived session {session_id} from storage.")
    return active_session


@app.post("/sessions/{session_id}/start", response_model=SessionActionResponse)
def start_session(session_id: str, request: RestartSessionRequest) -> SessionActionResponse:
    with _sessions_lock:
        session = _sessions.get(session_id)

    if not session:
        # Check if it exists in storage and revive it
        session = _revive_session(session_id, request.broker_host, request.broker_port)

    try:
        session.orchestrator.start()
    except RequestedSessionNotFound as snf:
        raise HTTPException(status_code=404, detail=f"Session not found: {snf}")
    except Exception as exc:
        LOG.exception(f"Failed to start session {session_id}")
        raise HTTPException(status_code=500, detail=f"Failed to start session: {exc}")

    return SessionActionResponse(session_id=session_id, message="Session started.")


async def _handle_upload_json_file(file: UploadFile) -> list[str]:
    assert file.filename

    content = await file.read()

    # Parse JSON to ensure validity and extract ID
    model_data: Model = cast(Model, json_loads(content.decode()))

    model_id = f"{Path(file.filename).stem}_{str(model_data.guid)[0:8]}"
    try:
        with ModelStorage() as storage:
            storage.add_model(model_id, model_data)
    except Exception as exc:
        LOG.exception("Failed to save model to database")
        raise HTTPException(status_code=500, detail=f"Failed to save model: {exc}")

    return [model_id]


async def _handle_upload_cog_file(file: UploadFile) -> list[str]:
    assert file.filename
    content = await file.read()
    uploaded_ids = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        cog_path = Path(tmp_dir) / file.filename
        cog_path.write_bytes(content)

        try:
            with zipfile.ZipFile(cog_path, "r") as zip_ref:
                zip_ref.extractall(tmp_dir)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid .cog file (not a valid zip archive).")

        manifest_path = Path(tmp_dir) / "manifest.json"
        if not manifest_path.exists():
            raise HTTPException(status_code=400, detail="Manifest file missing in .cog archive.")

        try:
            manifest = json_loads(manifest_path.read_text())
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid manifest file.")

        items = manifest.get("items", [])

        with ModelStorage() as storage:
            for item in items:
                model_file = item.get("model")
                nesting_file = item.get("nesting")

                # Default to looking in model/ directory using the filename
                model_path = Path(tmp_dir) / "model" / Path(model_file).name

                if not model_path.exists():
                    LOG.warning(f"Model file {model_file} listed in manifest but not found in archive.")
                    continue

                try:
                    model_data = cast(Model, json_loads(model_path.read_text()))
                    model_id = f"{Path(model_file).stem}_{str(model_data.guid)[0:8]}"

                    storage.add_model(model_id, model_data)
                    uploaded_ids.append(model_id)

                    if nesting_file:
                        nesting_path = Path(tmp_dir) / "nesting" / Path(nesting_file).name

                        if nesting_path.exists():
                            nesting_data = json_loads(nesting_path.read_text())
                            storage.add_nesting(model_id, nesting_data)
                        else:
                            LOG.warning(f"Nesting file {nesting_file} listed in manifest but not found in archive.")

                except Exception as e:
                    LOG.error(f"Failed to process model {model_file}: {e}")
                    raise HTTPException(status_code=400, detail=f"Failed to process model {model_file}: {e}")

    return uploaded_ids


@app.post("/models/upload", response_model=UploadModelsResponse, status_code=201)
async def upload_model(file: UploadFile) -> UploadModelsResponse:
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
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename must be provided.")

    if file.filename.endswith(".json"):
        uploaded_ids = await _handle_upload_json_file(file)
    elif file.filename.endswith(".cog"):
        uploaded_ids = await _handle_upload_cog_file(file)
    else:
        raise HTTPException(status_code=400, detail="Only JSON and COG files are accepted.")

    return UploadModelsResponse(model_ids=uploaded_ids, message="Model uploaded successfully.")


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
    try:
        with BlueprintStorage() as storage:
            blueprint = storage.get_blueprint(blueprint_id)
        return Response(content=json_dumps(blueprint), media_type="application/json")
    except RequestedBlueprintNotFound:
        raise HTTPException(status_code=404, detail=f"Blueprint {blueprint_id} not found")
    except Exception as exc:
        LOG.exception(f"Failed to retrieve blueprint {blueprint_id}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve blueprint: {exc}")


@app.get("/sessions/{session_id}/blueprint")
def get_session_root_blueprint(session_id: str):
    with SessionStorage(session_id) as session_storage:
        session = session_storage.load_session()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return Response(
            content=json_dumps(session.blueprint),
            media_type="application/json",
        )


@app.get("/sessions/{session_id}/blueprint/{blueprint_id}")
def get_session_blueprint(session_id: str, blueprint_id: str):
    with SessionStorage(session_id) as session_storage:
        session = session_storage.load_session()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        try:
            blueprint = session.get_blueprint(blueprint_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Blueprint {blueprint_id} not found in session")
        else:
            return Response(
                content=json_dumps(blueprint),
                media_type="application/json",
            )


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
    # Always load from storage
    with SessionStorage(session_id) as session_storage:
        session = session_storage.load_session()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return Response(content=json_dumps(session), media_type="application/json")
