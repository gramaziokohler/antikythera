from typing import Any
from typing import Dict

from compas.geometry import Frame
from compas_fab.backends import MoveItPlanner
from compas_fab.backends import RosClient
from compas_fab.robots import FrameWaypoints
from compas_fab.robots import TargetMode

from antikythera.models import Task

from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from antikythera_agents.cli import Colors


@agent(type="fall_demonstrator")
class FallDemonstratorAgent(Agent):
    def __init__(self):
        super().__init__()
        self.client = RosClient()
        self.client.run()
        print("Connected to ROS")

        self.planner = MoveItPlanner(self.client)
        self.robot_cell = self.client.load_robot_cell()

    def dispose(self):
        self.client.close()
        print("Disconnected from ROS")
        super().dispose()

    @tool(name="select_frames")
    def select_frames(self, task: Task) -> Dict[str, Any]:
        frames = []
        frames.append(Frame([0.3, 0.3, 0.5], [0, -1, 0], [0, 0, -1]))
        return {"frames": frames}

    @tool(name="plan_trajectory")
    def plan_trajectory(self, task: Task) -> Dict[str, Any]:
        frames = task.inputs.get("frames", [])
        if not frames:
            raise ValueError("No frames provided for trajectory planning")

        waypoints = FrameWaypoints(frames, TargetMode.ROBOT)

        robot_cell_state = self.robot_cell.default_cell_state()
        robot_cell_state.robot_configuration.joint_values = (-0.042, 0.033, -2.174, 5.282, -1.528, 0.000)

        options = {"max_step": 0.001}  # Units in meters
        trajectory = self.planner.plan_cartesian_motion(waypoints, robot_cell_state, options=options)
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Planned trajectory with {len(trajectory.points)} points.{Colors.ENDC}")
        return {"trajectory": trajectory}
