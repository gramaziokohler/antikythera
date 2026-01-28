import time
from typing import Any
from typing import Dict
from typing import List

from antikythera.models import Task
from antikythera.models import TaskOutput
from antikythera_agents.base_agent import Agent
from antikythera_agents.cli import Colors
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool


@agent(type="system")
class SystemAgent(Agent):
    @tool(name="composite")
    def composite(self, task: Task) -> Dict[str, Any]:
        print(f"{Colors.OKBLUE}✅ [{task.id}][{task.type}] Composite trigger {Colors.ENDC}")

        # Composite tasks need to return a clean list of expected outputs.
        # Since they are virtual, they don't produce values, so we return keys with None values.
        return {o.name: None for o in task.outputs}

    @tool(name="start")
    def start_process(self, task: Task) -> Dict[str, Any]:
        print(f"{Colors.OKBLUE}🏃 [{task.id}][{task.type}] Starting...{Colors.ENDC}")
        time.sleep(1)
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished.{Colors.ENDC}")
        return {"process_start_time": time.time()}

    @tool(name="end")
    def end_process(self, task: Task) -> Dict[str, Any]:
        print(f"{Colors.OKBLUE}🏃 [{task.id}][{task.type}] Starting...{Colors.ENDC}")
        time.sleep(1)
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished.{Colors.ENDC}")
        return {"process_end_time": time.time()}

    @tool(name="sleep")
    def sleep_process(self, task: Task) -> Dict[str, Any]:
        duration = task.get_param_value("duration", 1)
        print(f"{Colors.OKBLUE}😴 [{task.id}][{task.type}] Sleeping for {duration}s...{Colors.ENDC}")
        time.sleep(duration)
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished sleeping.{Colors.ENDC}")
        return {}
