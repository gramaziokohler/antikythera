import Grasshopper
import System

from dataclasses import dataclass
from typing import Dict

from antikythera.models import Blueprint
from antikythera.models import Task
from antikythera.models import Dependency


class BlueprintComposer:
    def __init__(self):
        self.tasks = {}
    
    def __str__(self):
        return f"BlueprintComposer with {len(self.tasks)} tasks (ids={[k for k in self.tasks.keys()]})"

    def add_task(self, task: Task):
        self.tasks[task.id] = task
    
    def get_blueprint(self, blueprint_id: str, name: str, description: str) -> Blueprint:
        blueprint = Blueprint(
            id=blueprint_id,
            name=name,
            description=description,
            tasks=list(self.tasks.values()),
        )
        return blueprint



@dataclass
class TaskDefinition:
    composer: BlueprintComposer
    task: Task


###########################################
# Sample agents
###########################################

class SystemAgent:
    agent_type = "system"
    tools = ["start", "end", "sleep"]


class UserInteractionAgent:
    agent_type = "user_interaction"
    tools = ["user_input", "user_output"]


def get_agent_classes():
    return [SystemAgent, UserInteractionAgent]


def get_full_tool_name(agent_class, tool_name):
    if agent_class is None:
        return None

    agent_type = agent_class.agent_type
    return f"{agent_type}.{tool_name}"


###########################################
# Grasshopper stuff
###########################################

class GrasshopperNodeCreator:
    def __init__(self):
        pass

    def convert_node_to_task_definition(self, ghenv, agent_class, tool_name) -> TaskDefinition:
        composer = None
        task_definitions = self.get_task_definition_inputs(ghenv)

        dependencies = []
        for task_definition in task_definitions:
            # if not isinstance(task_definition, TaskDefinition):
            #     raise Exception(f"Task dependencies must be of type `TaskDefinition`! Found {type(task_definition)}")

            dependencies.append(Dependency(task_definition.task.id))
            if task_definition.composer:
                if composer is None:
                    composer = task_definition.composer
                else:
                    if task_definition.composer != composer:
                        raise Exception("Something is off, you have two different composers in the dependencies")

        if composer is None:
            composer = BlueprintComposer()

        task = Task(
            id=ghenv.Component.NickName,
            type=get_full_tool_name(agent_class, tool_name) or "Undefined",
            description="TODO!",
            inputs=self.collect_input_params(ghenv),
            outputs=self.collect_output_params(ghenv),
            depends_on=dependencies,
            # params={},
            # argument_mapping={},
            # state=None,
        )

        task_def = TaskDefinition(
            composer=composer,
            task=task,
        )
        composer.add_task(task)

        print("task", task)
        print(composer)

        return task_def

    def get_task_definition_inputs(self, ghenv) -> list[TaskDefinition]:
        for param in ghenv.Component.Params.Input:
            if param.Name.lower() == "depends_on":
                data = param.VolatileData
        
                if data.DataCount == 0:
                    return []
        

                if param.Access != Grasshopper.Kernel.GH_ParamAccess.list:
                    raise Exception("depends_on must be set to `list access`")

                values = []
                for goo in data.get_Branch(0):
                    values.append(goo.ScriptVariable())
                return values
        
        return []

    def collect_input_params(self, ghenv) -> Dict[str, str]:
        inputs = {}

        for p in ghenv.Component.Params.Input:
            if p.Name.lower() == "depends_on":
                continue

            inputs[p.NickName] = p.Type.Name

        return inputs

    def collect_output_params(self, ghenv) -> Dict[str, str]:
        outputs = {}
        for p in ghenv.Component.Params.Output:
            if p.Name.lower() == "out" or p.Name.lower() == "task":
                continue

            outputs[p.NickName] = p.Type.Name

        return outputs