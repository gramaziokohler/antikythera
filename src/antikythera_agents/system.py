import time
from typing import Any
from typing import Dict

from antikythera.models import Task

from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from antikythera_agents.cli import Colors


@agent(type="system")
class SystemAgent(Agent):
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
        duration = task.params.get("duration", 1)
        print(f"{Colors.OKBLUE}😴 [{task.id}][{task.type}] Sleeping for {duration}s...{Colors.ENDC}")
        time.sleep(duration)
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished sleeping.{Colors.ENDC}")
        return None
