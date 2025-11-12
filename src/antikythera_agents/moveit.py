import time
from typing import Any
from typing import Dict

from antikythera.models import Task

from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from compas.geometry import Frame
from compas_fab.backends.ros import RosClient
from compas_fab.backends.ros import MoveItPlanner

@agent(type="moveit_planner")
class MoveItPlannerAgent(Agent):
    def __init__(self, ros_host: str = "localhost", ros_port: int = 9090):
        super().__init__()
        self.ros_client = RosClient(host=ros_host, port=ros_port)
        self.ros_client.run()
        self.planner = MoveItPlanner(self.ros_client)
        print(f"[MoveItPlannerAgent] Initialized with ROS at {ros_host}:{ros_port}. Connected={self.ros_client.is_connected}")

    @tool(name="plan_pick")
    def plan_pick(self, task: Task) -> Dict[str, Any]:
#     // # Agent: MoveItPlannerAgent, TBD: how to deal with cell state
#     // # params: place_frame (in WCF), approach_vector, pick_frame (in WCF), HARDCODE START CONFIG (CELL STATE)

        
        task.params["element_id"]
        task.params["approach_vector"]
        task.inputs["pickup_location_frame"]

        # calculate grasp frame (wrt to element)
        # calculate pickup frame (using grasp frame and pickup location frame)
        pick_frame = # ..FrameTarget(element["frame"], TargetMode.ROBOT)
        # "calculate approach frame (using pickup frame)",
        approach_frame = # pick_frame - approach_vector

        
        approach_pick_config = # ik for approach pick frame (from start state)
        pick_config = # ik for pick frame (from approach_pick_config)

        approach_place_config = # ik for approach place frame (from approach_pick_config)
        place_config = # ik for place frame (from approach_place_config)

        # PICK:
        # calculate free space trj from start state to approach pick config
        # calculate cartesian trj from approach pick config to pick config

        return None

    @tool(name="generate_pick_location_frame")
    def generate_pick_location_frame(self, task: Task) -> Dict[str, Any]:
        return Frame((3, 5, -3), (1, 0, 0), (0, 1, 0))