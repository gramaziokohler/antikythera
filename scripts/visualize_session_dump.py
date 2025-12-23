"""
This script reads in a session dump (i.e. `json_dump(PATH, orchestrator.session)`)
and visualizes the entire session bluprint structure as an interactive HTML graph using pyvis.

make sure to dump the session after the pre-processing step to include all dynamically expanded blueprints
"""

import json
import sys
import os
from pyvis.network import Network


def unwrap(obj):
    if isinstance(obj, dict) and "data" in obj and "dtype" in obj:
        return unwrap(obj["data"])
    return obj


def visualize(dump_path, output_path):
    print(f"Loading dump from {dump_path}...")
    with open(dump_path, "r") as f:
        raw_data = json.load(f)

    session_data = unwrap(raw_data)

    net = Network(height="90vh", width="100%", directed=True, layout=True)
    # Use force atlas 2 based layout for better clustering
    net.force_atlas_2based(gravity=-50, central_gravity=0.01, spring_length=100, spring_strength=0.08, damping=0.4, overlap=0)

    # Process main blueprint
    main_blueprint = unwrap(session_data["blueprint"])
    main_bp_id = main_blueprint["id"]
    print(f"Processing main blueprint: {main_bp_id}")

    # Map composite tasks to their inner blueprints if possible
    composite_task_map = {}

    process_blueprint(net, main_blueprint, namespace=main_bp_id, composite_map=composite_task_map)

    # Process inner blueprints
    inner_blueprints = session_data.get("inner_blueprints", {})
    print(f"Found {len(inner_blueprints)} inner blueprints.")

    for inner_bp_id, inner_bp_wrapper in inner_blueprints.items():
        inner_bp = unwrap(inner_bp_wrapper)
        print(f"Processing inner blueprint: {inner_bp_id}")
        process_blueprint(net, inner_bp, namespace=inner_bp_id, composite_map=composite_task_map)

        # Link composite task to inner blueprint using blueprint_id param
        for full_task_id, task_data in composite_task_map.items():
            params = task_data.get("params", {})
            blueprint_params = params.get("blueprint", {})
            dynamic_params = blueprint_params.get("dynamic", {})
            referenced_bp_id = dynamic_params.get("blueprint_id")

            if referenced_bp_id == inner_bp_id:
                # Link composite task to the start of the inner blueprint
                inner_start_node = f"{inner_bp_id}:start"
                # Add edge from composite task to inner start
                net.add_edge(full_task_id, inner_start_node, title="expands to", color="orange", dashes=True)
                print(f"  Linked {full_task_id} -> {inner_start_node}")
                break

    print(f"Saving visualization to {output_path}...")
    net.show(output_path, notebook=False)
    print("Done.")


def process_blueprint(net, blueprint, namespace, composite_map):
    tasks = blueprint.get("tasks", [])

    for task_wrapper in tasks:
        task = unwrap(task_wrapper)
        task_id = task["id"]
        full_task_id = f"{namespace}:{task_id}"

        label = f"{task_id}\n({task.get('type', 'unknown')})"
        title = f"ID: {task_id}\nType: {task.get('type')}\nDesc: {task.get('description')}"

        color = "#97c2fc"  # Default blue
        shape = "box"

        task_type = task.get("type")
        if task_type == "system.start":
            color = "#7BE141"  # Green
            shape = "ellipse"
        elif task_type == "system.end":
            color = "#E14141"  # Red
            shape = "ellipse"
        elif task_type == "system.composite":
            color = "#FB7E81"  # Light red/orange
            shape = "hexagon"
            composite_map[full_task_id] = task

        net.add_node(full_task_id, label=label, title=title, color=color, shape=shape, group=namespace)

        # Dependencies
        depends_on = task.get("depends_on", [])
        for dep_wrapper in depends_on:
            dep = unwrap(dep_wrapper)
            dep_id = dep["id"]
            full_dep_id = f"{namespace}:{dep_id}"
            net.add_edge(full_dep_id, full_task_id)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python visualize_session_dump.py <dump_file> [output_file]")
        sys.exit(1)

    dump_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "blueprint_graph.html"

    visualize(dump_file, output_file)
