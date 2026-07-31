import os

from compas_model.elements import Element
from compas_model.models import Model

from antikythera.io import BlueprintJsonSerializer
from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskOutput
from antikythera.models import TaskParam
from antikythera.models.blueprints import BlueprintSessionState
from antikythera_agents.launcher import AgentLauncher
from antikythera_agents.reference_agent import ReferenceAgent  # noqa: F401 (registers "reference" for AgentLauncher)
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.storage import BlueprintStorage
from antikythera_orchestrator.storage import ModelStorage

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "../../examples")


def test_reference_agent_context_binds_per_element_in_dynamic_expansion(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, fast_system_agents, cleanup_manager):
    """The reference agent's `assemble` tool, run inside a genuinely dynamically-expanded
    inner blueprint (a sequencer over a model's elements), binds a distinct `element_id` per
    element via its `Context[str]` parameter — the same shape proven in
    `test_orchestrator_dynamic.py::test_dynamic_expansion_context_annotation_binds_per_element`,
    but against the real reference agent rather than a throwaway test agent (issue-td-10).
    """
    model = Model()
    element1 = Element()
    element2 = Element()
    model.add_element(element1)
    model.add_element(element2)

    model_id = "test_model_reference_agent_context"

    with ModelStorage() as storage:
        storage.add_model(model_id, model)

    inner_start = Task(id="inner_start", type="system.start")
    inner_assemble = Task(
        id="assemble",
        type="reference.assemble",
        inputs=[TaskInput(name="title", value="Element"), TaskInput(name="subtitle", value="Report")],
        params=[TaskParam(name="tag", value="fabrication")],
        outputs=[TaskOutput(name="message")],
    )
    inner_end = Task(id="inner_end", type="system.end")
    inner_start >> inner_assemble >> inner_end

    inner_blueprint = Blueprint(id="test_inner_bp_reference", name="Test Inner Blueprint Reference", tasks=[inner_start, inner_assemble, inner_end])

    with BlueprintStorage() as bp_storage:
        bp_storage.add_blueprint(inner_blueprint)

    outer_start = Task(id="start", type="system.start")
    dynamic_task = Task(
        id="dynamic_process",
        type="system.composite",
        params=[TaskParam(name="blueprint", value={"dynamic": {"blueprint_id": "test_inner_bp_reference", "sequencer": "basic_sequencer"}})],
    )
    outer_end = Task(id="end", type="system.end")
    outer_start >> dynamic_task >> outer_end

    outer_blueprint = Blueprint(id="test_outer_bp_reference", name="Test Outer Dynamic Blueprint Reference", tasks=[outer_start, dynamic_task, outer_end])

    session = BlueprintSession(
        bsid="test_session_reference_agent_context",
        blueprint=outer_blueprint,
        params={"model_id": model_id},
    )

    orchestrator = cleanup_manager.register(Orchestrator(session))
    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()

    orchestrator.start()

    assert orchestrator.await_completion(timeout=12)
    assert session.state == BlueprintSessionState.COMPLETED

    graph_tasks = [data["task"] for _, data in orchestrator.graph.nodes(data=True)]
    subtasks = [t for t in graph_tasks if t.id == "assemble"]
    assert len(subtasks) == 2

    messages = {subtask.get_output_value("message") for subtask in subtasks}
    assert messages == {
        f"Element — Report [fabrication/{str(element1.guid)}]",
        f"Element — Report [fabrication/{str(element2.guid)}]",
    }


def test_reference_agent_example_blueprint_runs_end_to_end(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, fast_system_agents, cleanup_manager):
    """`examples/reference_agent_demo.json` (issue-td-10) drives every tool of the reference
    agent through a real orchestrator/launcher run and completes successfully.
    """
    blueprint = BlueprintJsonSerializer.from_file(os.path.join(EXAMPLES_DIR, "reference_agent_demo.json"))
    session = BlueprintSession(bsid="test_session_reference_agent_demo", blueprint=blueprint)

    orchestrator = cleanup_manager.register(Orchestrator(session))
    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()

    orchestrator.start()

    assert orchestrator.await_completion(timeout=12)
    assert session.state == BlueprintSessionState.COMPLETED

    graph_tasks = {data["task"].id: data["task"] for _, data in orchestrator.graph.nodes(data=True)}

    assemble_message = graph_tasks["assemble"].get_output_value("message")
    assert assemble_message.count("Antikythera — Reference Agent Demo") == 2
    assert graph_tasks["assemble"].get_output_value("detail") == "Generated by the reference agent demo blueprint."

    assert graph_tasks["wait"].get_output_value("cancelled") is False

    assert graph_tasks["passthrough"].get_output_value("message") == assemble_message
    assert graph_tasks["passthrough"].get_output_value("detail") == "Generated by the reference agent demo blueprint."
