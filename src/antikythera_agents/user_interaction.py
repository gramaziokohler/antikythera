"""User interaction agent implementation."""

from typing import Any
from typing import Dict

from antikythera.models import Task
from antikythera_agents.base_agent import Agent
from antikythera_agents.cli import Colors
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool


@agent(type="user_interaction")
class UserInteractionAgent(Agent):
    @tool(name="user_input")
    def get_user_input(self, task: Task) -> Dict[str, Any]:
        print(f"{Colors.HEADER}✍️ [{task.id}][{task.type}] Awaiting user input...{Colors.ENDC}")
        result = {}
        for task_output in task.outputs:
            key = task_output.name
            result[key] = input(f"    [{task.id}][{task.type}] > Enter {key}: ")
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Input received.{Colors.ENDC}")
        return result

    # Deprecated in favor of `notify`
    @tool(name="user_output")
    def show_user_output(self, task: Task) -> Dict[str, Any]:
        print(f"{Colors.OKCYAN}💬 [{task.id}][{task.type}] Displaying output:{Colors.ENDC}")
        for task_input in task.inputs:
            print(f"    [{task.id}][{task.type}] > {task_input.name}: {task_input.value}")
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished displaying output.{Colors.ENDC}")
        return None

    @tool(name="notify")
    def notify(self, task: Task) -> Dict[str, Any]:
        inputs = {i.name: i.value for i in task.inputs}
        params = {p.name: p.value for p in task.params}

        # Value resolution: Inputs > Params > Default
        title = inputs.get("title", params.get("title", "Notification"))
        message = inputs.get("message", params.get("message", ""))
        level = inputs.get("level", params.get("level", "info"))

        # String interpolation using inputs and context
        # Inputs override context if keys match
        interpolation_data = {**task.context, **inputs}

        try:
            title = title.format(**interpolation_data)
        except Exception:
            pass

        try:
            message = message.format(**interpolation_data)
        except Exception:
            pass

        color = Colors.OKBLUE
        prefix = "ℹ️"

        if level == "success":
            color = Colors.OKGREEN
            prefix = "✅"
        elif level == "warning":
            color = Colors.WARNING
            prefix = "⚠️"
        elif level == "error":
            color = Colors.FAIL
            prefix = "❌"

        print(f"{color}{prefix} [{task.id}] {title}: {message}{Colors.ENDC}")
        return {"status": "displayed"}
