# -*- coding: utf-8 -*-


import threading

from compas.datastructures import Graph
from compas_eve import Message
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve.mqtt import MqttTransport

from antikythera.models import BlueprintSession
from antikythera.models import DependencyType
from antikythera.models import Task
from antikythera.models import TaskState


class TaskScheduler:
    """Task scheduler with support for FS and SS task dependencies."""
    def __init__(self, session: BlueprintSession, graph: Graph) -> None:
        self.session = session
        self.graph = graph
        self._lock = threading.Lock()

    def get_pending_tasks(self) -> list[Task]:
        """Returns a list of tasks that are pending execution whose dependencies are satisfied."""
        pending_tasks = []
        dependency_preconditions = []

        for task in self.session.blueprint.tasks:
            if task.state != TaskState.PENDING:
                continue
            for dependency in task.depends_on:
                dep_task = self.graph.node[dependency.id]["task"]
                if dependency.type == DependencyType.FS:
                    dependency_preconditions.append(dep_task.state == TaskState.SUCCEEDED)
                elif dependency.type == DependencyType.SS:
                    dependency_preconditions.append(dep_task.state in (TaskState.RUNNING, TaskState.SUCCEEDED))
                else:
                    raise ValueError(f"Dependency type not yet supported: {dependency.type}")

            if all(dependency_preconditions):
                pending_tasks.append(task)

        return pending_tasks


    def to_mermaid_diagram(self, title="Blueprint") -> str:
        """Generate a mermaid-syntax diagram representation of the blueprint session.

        For more info about Mermaid syntax: https://mermaid.js.org

        Returns
        -------
        str
           Gantt chart representation of the blueprint session.
        """
        import datetime

        from compas.topology import breadth_first_traverse

        if not self.graph:
            return

        fixed_duration = "1d"
        result = list()
        result.append(f"gantt\n  title    {title}")

        def create_label(task: Task):
            if task.state == TaskState.SUCCEEDED:
                task_state = "✅"
            elif task.state == TaskState.FAILED:
                task_state = "❌"
            elif task.state == TaskState.PENDING:
                task_state = "⏳"
            elif task.state == TaskState.READY:
                task_state = "🏁"
            elif task.state == TaskState.RUNNING:
                task_state = "🏃"
            else:
                task_state = "?"
            task_label = f"{task_state} [{task.id}] {task.type}"
            return task_label

        def append_node(previous, current):
            task: Task = self.graph.node[current]["task"]
            task_label = create_label(task)

            dependencies_list = []

            for node_in in self.graph.neighbors_in(current):
                task_in = self.graph.node[node_in]["task"]
                dependencies_list.append(task_in.id)

            if dependencies_list:
                dependencies = "after " + " ".join(dependencies_list)
            else:
                dependencies = ""
            
            milestone = ""
            if task.type in ("system.start", "system.end"):
                milestone = "milestone, "
                duration = "0d"
            else:
                duration = fixed_duration
            if task.type == "system.start" and dependencies == "":
                dependencies = datetime.date.today().isoformat()

            result.append("  {:40}   : {}{}, {}, {}".format(task_label, milestone, task.id, dependencies, duration))

        root_node = None
        for node in self.graph.nodes():
            if self.graph.degree_in(node) == 0:
                root_node = node
                append_node(None, root_node)
                break

        breadth_first_traverse(self.graph.adjacency, root_node, append_node)

        return "\n".join(result)


class Orchestrator:
    """Coordinates the execution of a blueprint.

    The orchestrator is responsible for managing the state of a blueprint session,
    and coordinating the execution of tasks by agents.

    Attributes
    ----------
    session : BlueprintSession
        The blueprint session to execute.

    """

    def __init__(self, session: BlueprintSession, broker_host="127.0.0.1", broker_port=1883) -> None:
        super(Orchestrator, self).__init__()
        self.session: BlueprintSession = session
        self.graph: Graph = None

        self.transport = MqttTransport(host=broker_host, port=broker_port)
        self.task_start = Topic("antikythera/task/start")
        self.task_completed = Topic("antikythera/task/completed")

        self.task_start_publisher = Publisher(self.task_start, transport=self.transport)
        self.task_completion_subscriber = Subscriber(self.task_completed, self.on_task_completed, transport=self.transport)
        self.task_completion_subscriber.subscribe()
        # TODO: This should be replaced with a proper data store
        self.session_data = {}

        self._build_graph()
        self.scheduler = TaskScheduler(self.session, self.graph)

    def start(self) -> None:
        """Starts the orchestrator."""
        self._schedule_tasks()

    def stop(self) -> None:
        """Stops the orchestrator."""
        self.task_completion_subscriber.unsubscribe()

    def _schedule_tasks(self) -> None:
        """Schedules tasks for execution."""
        pending_tasks = self.scheduler.get_pending_tasks()

        for task in pending_tasks:
            try:
                task.state = TaskState.PENDING
                inputs = {}
                for key in task.inputs:
                    inputs[key] = self.session_data.get(key)
                self.task_start_publisher.publish(Message({"id": task.id, "type": task.type, "inputs": inputs, "outputs": task.outputs, "params": task.params}))
                # TODO: Verify if they actually started
                task.state = TaskState.RUNNING
            except Exception as e:
                print(f"Failed to start task {task.id}: {e}")
                task.state = TaskState.FAILED
    
    def on_task_completed(self, message: Message) -> None:
        """Handles incoming task completion messages."""
        task_id = message["id"]
        task = self.graph.node[task_id]["task"]

        # TODO: Handle task failure properly
        if message["state"] == "succeeded":
            task.state = TaskState.SUCCEEDED
        elif message["state"] == "failed":
            task.state = TaskState.FAILED
        else:
            raise ValueError(f"Invalid task state: {message['state']}")

        if task.outputs:
            task.outputs = message["outputs"]
            self.session_data.update(task.outputs)
        else:
            task.outputs = {}
    
        # Ready to schedule new tasks
        self._schedule_tasks()

    def _build_graph(self) -> None:
        """Builds a dependency graph from the loaded blueprint."""
        if not self.session:
            return

        self.graph = Graph()
        for task in self.session.blueprint.tasks:
            self.graph.add_node(task.id, task=task)

        for task in self.session.blueprint.tasks:
            for dep in task.depends_on:
                self.graph.add_edge(dep.id, task.id, type=dep.type)

        # NOTE: Perhaps we need to do transitive_reduction here
