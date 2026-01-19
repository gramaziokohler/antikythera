import logging
from typing import Any
from typing import Dict

from antikythera.models import Task
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool

LOG = logging.getLogger(__name__)


@agent(type="trajectory_planner")
class TrajectoryPlanner(Agent):
    @tool(name="plan_stock_pnp")
    def pick_and_place_stock(self, task: Task) -> Dict[str, Any]:
        element_id = task.inputs.get("element_id")
        LOG.info(f"Planning stock PnP for element: {element_id}")
        return {"trajectory": f"trajectory_for_stock_{element_id}"}

    @tool(name="plan_element_pnp")
    def pick_and_place_element(self, task: Task) -> Dict[str, Any]:
        element_id = task.inputs.get("element_id")
        LOG.info(f"Planning element PnP for element: {element_id}")
        return {"trajectory": f"trajectory_for_element_{element_id}"}


@agent(type="fall_demonstrator_rrc")
class RRCAgent(Agent):
    @tool(name="execute_pnp_stock")
    def execute_pnp_stock(self, task: Task) -> Dict[str, Any]:
        element_id = task.inputs.get("element_id")
        LOG.info(f"Executing stock PnP for element: {element_id}")
        return {"status": "success", "element_id": element_id}

    @tool(name="execute_pnp_element")
    def execute_pnp_element(self, task: Task) -> Dict[str, Any]:
        element_id = task.inputs.get("element_id")
        LOG.info(f"Executing element PnP for element: {element_id}")
        return {"status": "success", "element_id": element_id}


def test_trajectory_planner_stock_pnp():
    planner = TrajectoryPlanner()
    task = Task(id="test_task", type="trajectory_planner.plan_stock_pnp", inputs={"element_id": "123"})
    result = planner.pick_and_place_stock(task)
    assert result == {"trajectory": "trajectory_for_stock_123"}


def test_trajectory_planner_element_pnp():
    planner = TrajectoryPlanner()
    task = Task(id="test_task", type="trajectory_planner.plan_element_pnp", inputs={"element_id": "456"})
    result = planner.pick_and_place_element(task)
    assert result == {"trajectory": "trajectory_for_element_456"}


def test_rrc_agent_stock_pnp():
    rrc = RRCAgent()
    task = Task(id="test_task", type="fall_demonstrator_rrc.execute_pnp_stock", inputs={"element_id": "789"})
    result = rrc.execute_pnp_stock(task)
    assert result == {"status": "success", "element_id": "789"}


def test_rrc_agent_element_pnp():
    rrc = RRCAgent()
    task = Task(id="test_task", type="fall_demonstrator_rrc.execute_pnp_element", inputs={"element_id": "000"})
    result = rrc.execute_pnp_element(task)
    assert result == {"status": "success", "element_id": "000"}
