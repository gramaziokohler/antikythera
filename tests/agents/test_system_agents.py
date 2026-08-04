from compas.datastructures import Mesh

from antikythera.models import Task
from antikythera_orchestrator.system_agents import SystemAgent


def test_start_end_and_demo_mesh_are_not_opaque_and_declare_outputs():
    """issue-td-11: these three tools take no inputs and gain a `TypedDict` return, so
    they're migrated (non-opaque) and their outputs appear in the catalog.
    """
    assert SystemAgent.start_process._descriptor.opaque is False
    assert SystemAgent.end_process._descriptor.opaque is False
    assert SystemAgent.demo_mesh._descriptor.opaque is False

    start_entry = SystemAgent.start_process._descriptor.to_dict("system")
    assert start_entry["outputs"] == [{"name": "process_start_time", "type_hint": "float", "optional": False, "description": start_entry["outputs"][0]["description"]}]
    assert "inputs" not in start_entry
    assert "params" not in start_entry

    end_entry = SystemAgent.end_process._descriptor.to_dict("system")
    assert end_entry["outputs"][0]["name"] == "process_end_time"

    mesh_entry = SystemAgent.demo_mesh._descriptor.to_dict("system")
    assert mesh_entry["outputs"][0]["name"] == "mesh"
    assert mesh_entry["outputs"][0]["type_hint"] == "compas.datastructures.mesh.mesh.Mesh"


def test_start_end_and_demo_mesh_run_and_satisfy_their_declared_outputs():
    agent = SystemAgent()

    start_result = agent.execute_task(Task(id="start_task", type="system.start"))
    assert isinstance(start_result["process_start_time"], float)

    end_result = agent.execute_task(Task(id="end_task", type="system.end"))
    assert isinstance(end_result["process_end_time"], float)

    mesh_result = agent.execute_task(Task(id="mesh_task", type="system.demo_mesh"))
    assert isinstance(mesh_result["mesh"], Mesh)


def test_sleep_and_composite_stay_opaque():
    """`sleep` keeps `task: Task` to log the sleeping task's id/type alongside its one real
    argument (`duration`); `composite` keeps it because its output shape is decided entirely
    by the blueprint. Both document why in their docstrings (issue-td-11).
    """
    assert SystemAgent.sleep_process._descriptor.opaque is True
    assert SystemAgent.composite._descriptor.opaque is True
    assert "opaque" in (SystemAgent.sleep_process.__doc__ or "")
    assert "opaque" in (SystemAgent.composite.__doc__ or "")
