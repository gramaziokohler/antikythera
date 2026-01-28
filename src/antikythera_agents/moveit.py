# ruff: noqa
import math
from typing import Any
from typing import Dict
from typing import Optional

from compas.data import json_dump
from compas.data import json_load
from compas.datastructures import Mesh
from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Scale
from compas.geometry import Shape
from compas.geometry import Transformation
from compas.geometry import Vector
from compas_fab.backends import MoveItPlanner
from compas_fab.backends import RosClient
from compas_fab.robots import FrameTarget
from compas_fab.robots import RigidBody
from compas_fab.robots import RobotCellState
from compas_fab.robots import TargetMode
from compas_timber.model import TimberModel

from antikythera.models import Task
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import tool

CONNECTION_TIMEOUT = 5
DISCONNECTION_TIMEOUT = 2


# @agent(type="moveit_planner")
class MoveItPlannerAgent(Agent):
    def __init__(self, ros_host: str = "localhost", ros_port: int = 9090):
        super().__init__()
        self.ros_client = RosClient(host=ros_host, port=ros_port)
        self.ros_client.run(CONNECTION_TIMEOUT)
        self.robot_cell = self.ros_client.load_robot_cell(load_geometry=False)
        self.planner = MoveItPlanner(self.ros_client)
        self.model = None

        # HACK: Yes, we did this.
        self.ensure_hardcoded_model()

        self.logger.info(f"[MoveItPlannerAgent] Initialized with ROS at {ros_host}:{ros_port}. Connected={self.ros_client.is_connected}")

    def dispose(self):
        self.ros_client.close(DISCONNECTION_TIMEOUT)
        return super().dispose()

    def ensure_hardcoded_model(self):
        if self.model is None:
            model_path = "/Users/gcasas/eth/projects/gramaziokohler/fall_demo_2025/data/models/production/251202_model/251202_model.json"
            nesting_path = "/Users/gcasas/eth/projects/gramaziokohler/fall_demo_2025/data/models/production/251202_model/251202_model_nesting.json"
            self.model: TimberModel = json_load(model_path)  # type: ignore
            self.nesting = json_load(nesting_path)

            # Hardcoded frames for now, these geometries will be loaded from a config file of the agent
            assembly_table_frame = Frame(point=Point(x=7.764, y=5.889, z=0.184), xaxis=Vector(x=1.000, y=0.000, z=0.000), yaxis=Vector(x=0.000, y=1.000, z=0.000))
            cnc_table_frame = Frame(point=Point(x=9.556, y=0.801, z=1.815), xaxis=Vector(x=1.000, y=0.000, z=0.000), yaxis=Vector(x=0.000, y=1.000, z=0.000))

            height = 0.15
            assembly_table = Box.from_corner_corner_height(assembly_table_frame.point, assembly_table_frame.point + (4, 4, 0), height)
            assembly_table.frame.point.x -= 0.5
            assembly_table.frame.point.y -= 0.5
            assembly_table.frame.point.z -= height

            cnc_table = Box.from_corner_corner_height(cnc_table_frame.point, cnc_table_frame.point + (3, 0.5, 0), height)
            cnc_table.frame.point.x -= 0.5
            cnc_table.frame.point.y -= 0.2
            cnc_table.frame.point.z -= height

            self.static_objects = []
            self.static_objects.append(cnc_table)
            self.static_objects.append(assembly_table)

    def _calculate_ik_for_frame_target(self, frame: Frame, start_state: Optional[RobotCellState] = None, group=None):
        start_state = start_state.copy()

        target = FrameTarget(frame, TargetMode.ROBOT)

        configuration = self.planner.inverse_kinematics(target, start_state, group=group, options={"allow_collision": False})
        start_state.robot_configuration.merge(configuration)
        return start_state

    @tool(name="pnp.calculate_ik")
    def calculate_ik(self, task: Task) -> Dict[str, Any]:
        element_id = task.get_param_value("element_id")
        element = self.model.element_by_guid(element_id)

        # # Check if element is inside a slab (parent)
        # found_slabs = [slab for slab in self.model.slabs if element in self.model.get_elements_in_group(slab)]
        # if len(found_slabs) > 0:
        #     slab = found_slabs[0]
        # else:
        #     slab = None

        # Setup scene rigid bodies
        for i, static_object in enumerate(self.static_objects):
            mesh = static_object
            if isinstance(static_object, Shape):
                mesh = Mesh.from_shape(static_object)
            self.robot_cell.rigid_body_models[f"static_objects_{i}"] = RigidBody.from_mesh(mesh)

        # if slab:
        #     align_to_world_origin = element.transformation.inverse() * slab.transformation.inverse()
        # else:
        #     align_to_world_origin = element.transformation.inverse()

        tx_to_pickup_location = Transformation.from_frame(task.get_input_value("pickup_location_frame"))
        tx_to_placement_location = Transformation.from_frame(task.get_input_value("placement_location_frame"))

        sx = Scale.from_factors([0.001] * 3)

        # Grasp frame in local space -> then transform to pick frame (this includes the centerline adjustment)
        grasp_frame_in_local = Frame(Point(element.blank_length / 1000 * 0.5, element.width / 1000 * 0.5, element.height / 1000), Vector.Yaxis(), Vector.Xaxis())
        grasp_frame = grasp_frame_in_local.transformed(tx_to_pickup_location)

        # Grasp frame in local space at centerline -> transform to assembly table excluding the centerline adjustment
        grasp_frame_midbeam_centerline = Frame(Point(element.blank_length * 0.5, 0, element.height / 2), Vector.Yaxis(), Vector.Xaxis())
        place_frame = grasp_frame_midbeam_centerline.transformed(tx_to_placement_location * sx * element.transformation)

        # Create approach frames
        grasp_frame_approach = grasp_frame.copy()
        grasp_frame_approach.point += grasp_frame_approach.to_world_coordinates(task.get_param_value("approach_vector"))

        place_frame_approach = place_frame.copy()
        place_frame_approach.point += place_frame_approach.to_world_coordinates(task.get_param_value("approach_vector"))

        # Reset planner cell with the assembly table
        self.planner.set_robot_cell(self.robot_cell)

        start_state = self.robot_cell.default_cell_state()
        assert start_state.robot_configuration is not None

        robot_config = start_state.robot_configuration
        robot_config["robot12_joint_EA_Y"] = -12
        robot_config["robot12_joint_EA_Z"] = -4.5
        robot_config["robot12_joint_2"] = math.pi / 2

        # start_state = task.inputs["start_state"]
        try:
            self.logger.debug("[MoveItPlannerAgent] 1...")
            place_state = self._calculate_ik_for_frame_target(place_frame, start_state, task.get_param_value("group"))
            self.logger.debug("[MoveItPlannerAgent] 2...")
            place_state_approach = self._calculate_ik_for_frame_target(place_frame_approach, place_state, task.get_param_value("group"))
            json_dump(
                {"place_state": place_state, "place_state_approach": place_state_approach},
                "/Users/gcasas/eth/projects/gramaziokohler/antikythera/toy_problem_5_inner_pnp_ik_solutions_up_to_step_2.json",
            )
            self.logger.debug("[MoveItPlannerAgent] 3...")
            grasp_state_approach = self._calculate_ik_for_frame_target(grasp_frame_approach, place_state_approach, task.get_param_value("group"))
            self.logger.debug("[MoveItPlannerAgent] 4...")
            grasp_state = self._calculate_ik_for_frame_target(grasp_frame, grasp_state_approach, task.get_param_value("group"))
            json_dump(
                {"place_state": place_state, "place_state_approach": place_state_approach, "grasp_state": grasp_state, "grasp_state_approach": grasp_state_approach},
                "/Users/gcasas/eth/projects/gramaziokohler/antikythera/toy_problem_5_inner_pnp_ik_solutions_up_to_step_4.json",
            )
            self.logger.debug("[MoveItPlannerAgent] 5...")
        except Exception as e:
            print(f"[MoveItPlannerAgent] IK calculation failed: {e}")
            raise e

        # Return output params
        ik_solutions = {}

        ik_solutions["grasp_state_approach"] = grasp_state_approach
        ik_solutions["grasp_state"] = grasp_state
        ik_solutions["place_state_approach"] = place_state_approach
        ik_solutions["place_state"] = place_state

        return ik_solutions

    @tool(name="generate_pickup_inputs")
    def generate_pickup_inputs(self, task: Task) -> Dict[str, Any]:
        placement_location_frame = Frame(point=Point(x=7.764, y=5.889, z=0.184), xaxis=Vector(x=1.000, y=0.000, z=0.000), yaxis=Vector(x=0.000, y=1.000, z=0.000))
        pickup_location_frame = Frame(point=Point(x=9.556, y=0.801, z=1.815), xaxis=Vector(x=1.000, y=0.000, z=0.000), yaxis=Vector(x=0.000, y=1.000, z=0.000))

        data = {
            # "start_state": self.robot_cell.default_cell_state(),
            # CNC pick origin
            "pickup_location_frame": pickup_location_frame,
            # assembly table origin
            "placement_location_frame": placement_location_frame,
        }

        # # HACK: Move robot12 out of the way
        # data["start_state"].robot_configuration["robot12_joint_EA_Y"] = -12
        # data["start_state"].robot_configuration["robot12_joint_EA_Z"] = -4.5
        # data["start_state"].robot_configuration["robot12_joint_2"] = math.pi / 2

        print(f"[MoveItPlannerAgent] Generated pickup inputs for task {task.id}: {data}")
        return data

    @tool(name="plan_pick")
    def plan_pick(self, task: Task) -> Dict[str, Any]:
        element_id = task.get_param_value("element_id")
        element = self.model.element_by_guid(element_id)

        # Check if element is inside a slab (parent)
        found_slabs = [slab for slab in self.model.slabs if element in self.model.get_elements_in_group(slab)]
        if len(found_slabs) > 0:
            slab = found_slabs[0]
        else:
            slab = None

        if slab:
            align_to_world_origin = element.transformation.inverse() * slab.transformation.inverse()
        else:
            align_to_world_origin = element.transformation.inverse()

        # tx_to_assembly_table = Transformation.from_frame(assembly_table_frame)
        # tx_to_stock_table = Transformation.from_frame(stock_table_frame)
        tx_to_pick_location = Transformation.from_frame(task.get_input_value("pickup_location_frame"))

        # element_at_stock_table = element.geometry.transformed(sx * stock_table_transform * align_to_world_origin)
        element_at_cnc_pick = element.geometry.transformed(tx_to_cnc_pick * sx * align_to_world_origin)
        # element_at_assembly = element.geometry.transformed(tx_to_assembly_table * sx * slab.transformation.inverse())
        element_at_assembly = element.geometry.transformed(tx_to_assembly_table * sx * element.transformation * align_to_world_origin)

        # HACK to align to stock beam & CNC table
        adjust_from_centerline = Translation.from_vector((0, element.width / 1000 / 2, element.height / 1000 / 2))
        element_at_stock_table = element_at_stock_table.transformed(adjust_from_centerline)
        element_at_cnc_pick = element_at_cnc_pick.transformed(adjust_from_centerline)
        # NOTE: The element at assembly does not need this adjustment because it's all aligned to the frame of the slab
        # and the slab's frame is not the center line, it's the corner of the slab's "bounding box"
        # element_at_assembly = element_at_assembly.transformed(adjust_from_centerline)

        tx_align_beam_to_origin.append(adjust_from_centerline * sx * align_to_world_origin)
        tx_align_slab_to_origin.append(sx * slab.transformation.inverse())

        #     // # Agent: MoveItPlannerAgent, TBD: how to deal with cell state
        #     // # params: place_frame (in WCF), approach_vector, pick_frame (in WCF), HARDCODE START CONFIG (CELL STATE)

        # 1. Figure out the ONLY possible grasp frame based on how it can be gripped at the assembly table (only one side if free of collisions)
        #    -> IK for assembly placement ready
        # 2. Transform grasp frame to CNC pickup_location_frame -> pickup frame for the robot
        # 3. If there are collisions, it means the beam needs to be flipped

        # beam_mesh = Mesh.from_shape(beam)
        # robot_cell.rigid_body_models["beam"] = RigidBody.from_mesh(beam_mesh)

        # Attach the beam to the gripper or to link
        # robot_cell_state.set_rigid_body_attached_to_tool("beam", "gripper")
        # robot_cell_state.set_rigid_body_attached_to_link("beam", "link_6")

        # task.params["element_id"]
        # task.inputs["approach_vector"]
        # task.inputs["pickup_location_frame"]

        # # calculate grasp frame (wrt to element)
        # # calculate pickup frame (using grasp frame and pickup location frame)
        # pick_frame = # ..FrameTarget(element["frame"], TargetMode.ROBOT)
        # # "calculate approach frame (using pickup frame)",
        # approach_frame = # pick_frame - approach_vector

        # approach_pick_config = # ik for approach pick frame (from start state)
        # pick_config = # ik for pick frame (from approach_pick_config)

        # approach_place_config = # ik for approach place frame (from approach_pick_config)
        # place_config = # ik for place frame (from approach_place_config)

        # PICK:
        # "plan trajectory safe config to approach frame - trajectory1",
        # calculate free space trj from start state to approach pick config

        # "plan trajectory approach config to pickup frame  - trajectory2",
        # calculate cartesian trj from approach pick config to pick config

        return {}

    @tool(name="plan_place")
    def plan_place(self, task: Task) -> Dict[str, Any]:
        return {}
