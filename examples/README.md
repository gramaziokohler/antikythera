# Examples

Every example here runs to completion with the actors that ship with Antikythera;
`tests/test_examples.py` runs all of them on every build.

## Python

| File | Shows |
| --- | --- |
| `hello_world.py` | The smallest complete program: one actor, one blueprint, one process: `python examples/hello_world.py` |
| `embedded.py` | The orchestrator and actors in one Python process, no broker and no Redis: `python examples/embedded.py` |
| `greeter_actor.py` | An actor in a single file, started with `uv run examples/greeter_actor.py` or `uvx --from antikythera-sdk antikythera-actors run --actor examples/greeter_actor.py` |

## Blueprints

Upload them through the web UI or `POST /blueprints/upload`, then start them. Upload the
inner blueprint of a composite example before the outer one.

| Blueprint | Shows | Needs |
| --- | --- | --- |
| `toy_problem_0.json` | The smallest useful blueprint | |
| `toy_problem_1.json` | Parallel branches joining, a literal COMPAS frame as input | Terminal input for the `user_interaction` actor |
| `toy_problem_4.json` + `toy_problem_4_inner.json` | A composite task running an inner blueprint, mapping data in and out | Terminal input |
| `toy_problem_6.json` + `toy_problem_6_inner.json` | Dynamic expansion: one inner run per element of a model | An uploaded `compas_model` model, started with `{"model_id": "<id>"}` |
| `toy_problem_7.json` | A prompt answered in the web UI | Web UI |
| `toy_problem_8.json` | A task that runs only if a condition holds, and a fallback value when it did not | Web UI |
| `toy_problem_10_competitive.json` | Competitive execution: the first actor to finish wins | Web UI, open twice |
| `toy_problem_12_notification.json` | Notifications shown by the Python actor and the web UI at once | Web UI |
| `toy_problem_13_test_skipping.json` | Skipping tasks by hand | Web UI |
| `scope_skip.json` | A scope that is skipped as a whole when its condition is false | |
| `scope_retry.json` | A scope with a retry policy | |
| `scope_while.json` | A scope that loops while a condition holds, capped by `max_iterations` | |
| `reference_actor_demo.json` | Every tool of the reference actor, the template for writing actors | |
