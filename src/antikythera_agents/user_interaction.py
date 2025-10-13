"""User interaction agent implementation."""

from typing import Any
from typing import Dict

from antikythera.models import Task

from antikythera_agents.cli import Colors
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool


@agent(type="user_interaction")
class UserInteractionAgent(Agent):
    @tool(name="user_input")
    def get_user_input(self, task: Task) -> Dict[str, Any]:
        print(f"{Colors.HEADER}✍️ [{task.id}][{task.type}] Awaiting user input...{Colors.ENDC}")
        result = {}
        for key in task.outputs:
            result[key] = input(f"    [{task.id}][{task.type}] > Enter {key}: ")
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Input received.{Colors.ENDC}")
        return result

    @tool(name="user_output")
    def show_user_output(self, task: Task) -> Dict[str, Any]:
        print(f"{Colors.OKCYAN}💬 [{task.id}][{task.type}] Displaying output:{Colors.ENDC}")
        for key, value in task.inputs.items():
            print(f"    [{task.id}][{task.type}] > {key}: {value}")
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished displaying output.{Colors.ENDC}")
        return None
