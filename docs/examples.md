# Examples

The [`examples`](https://github.com/gramaziokohler/antikythera/tree/main/examples) folder
has one example per feature. They all run with the actors that come with Antikythera, and
the tests run every one of them.

## Python

| File | Shows |
| --- | --- |
| [`hello_world.py`][hello_world] | The smallest complete program: one actor, one blueprint, one process |
| [`embedded.py`][embedded] | Tasks running side by side, and passing data from task to task |
| [`greeter_actor.py`][greeter_actor] | An actor in a single file, started with `uv run` or `uvx` |

Run them with `python examples/hello_world.py`. They need no broker and no database.

## Blueprints

To try a blueprint, [start the system](deployment/docker.md), upload the JSON file in the
web UI, and start it. For a composite example, upload the inner blueprint first.

| Blueprint | Shows | Needs |
| --- | --- | --- |
| [`toy_problem_0.json`][tp0] | The smallest useful blueprint | |
| [`toy_problem_1.json`][tp1] | Branches that run side by side and then join, and a COMPAS frame as a value | An answer in the terminal of the actors |
| [`toy_problem_4.json`][tp4] + [`toy_problem_4_inner.json`][tp4i] | A composite task: one blueprint running another | An answer in the terminal |
| [`toy_problem_6.json`][tp6] + [`toy_problem_6_inner.json`][tp6i] | Dynamic expansion: the inner blueprint runs once per element of a model | An uploaded model, and `{"model_id": "<id>"}` when starting |
| [`toy_problem_7.json`][tp7] | A question answered in the web UI | Web UI |
| [`toy_problem_8.json`][tp8] | A task that runs only if a condition is true | Web UI |
| [`toy_problem_10_competitive.json`][tp10] | Competitive execution: the first actor to answer wins | Web UI, open twice |
| [`toy_problem_12_notification.json`][tp12] | Notifications, in the terminal and in the web UI | Web UI |
| [`toy_problem_13_test_skipping.json`][tp13] | Skipping tasks by hand | Web UI |
| [`scope_skip.json`][skip] | A group of tasks skipped together when a condition is false | |
| [`scope_retry.json`][retry] | A group of tasks tried again | |
| [`scope_while.json`][while] | A group of tasks repeated while a condition is true | |
| [`reference_actor_demo.json`][ref] | Every tool of the reference actor | |

[hello_world]: https://github.com/gramaziokohler/antikythera/blob/main/examples/hello_world.py
[embedded]: https://github.com/gramaziokohler/antikythera/blob/main/examples/embedded.py
[greeter_actor]: https://github.com/gramaziokohler/antikythera/blob/main/examples/greeter_actor.py
[tp0]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_0.json
[tp1]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_1.json
[tp4]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_4.json
[tp4i]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_4_inner.json
[tp6]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_6.json
[tp6i]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_6_inner.json
[tp7]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_7.json
[tp8]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_8.json
[tp10]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_10_competitive.json
[tp12]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_12_notification.json
[tp13]: https://github.com/gramaziokohler/antikythera/blob/main/examples/toy_problem_13_test_skipping.json
[skip]: https://github.com/gramaziokohler/antikythera/blob/main/examples/scope_skip.json
[retry]: https://github.com/gramaziokohler/antikythera/blob/main/examples/scope_retry.json
[while]: https://github.com/gramaziokohler/antikythera/blob/main/examples/scope_while.json
[ref]: https://github.com/gramaziokohler/antikythera/blob/main/examples/reference_actor_demo.json
