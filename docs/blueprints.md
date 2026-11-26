# Writing blueprints

A blueprint describes a process as a list of tasks. You can write it in JSON and upload it
in the web UI, or build it in Python. Read [Concepts](concepts.md) first if the words
*task*, *actor* or *session data* are new to you.

## A first blueprint

This is the [hello world](index.md#hello-world) blueprint in JSON:

```json
{
  "version": "1.0",
  "id": "hello-world",
  "name": "Hello, world",
  "tasks": [
    { "id": "start", "type": "system.start" },
    {
      "id": "hello",
      "type": "greeter.hello",
      "inputs": [{ "name": "name", "value": "world" }],
      "outputs": [{ "name": "greeting" }],
      "depends_on": [{ "id": "start" }]
    },
    { "id": "end", "type": "system.end", "depends_on": [{ "id": "hello" }] }
  ]
}
```

And the same in Python:

```python
from antikythera.models import Blueprint, Task, TaskInput, TaskOutput

start = Task(id="start", type="system.start")
hello = Task(
    id="hello",
    type="greeter.hello",
    inputs=[TaskInput(name="name", value="world")],
    outputs=[TaskOutput(name="greeting")],
)
end = Task(id="end", type="system.end")
start >> hello >> end
blueprint = Blueprint(id="hello-world", name="Hello, world", tasks=[start, hello, end])
```

A blueprint needs exactly one `system.start` task and one `system.end` task. Every other
task must depend on at least one task.

## Order of tasks

`depends_on` lists the tasks that come before. In Python, `a >> b` means "`b` depends on
`a`". A list runs tasks side by side:

```python
start >> [left, right] >> join >> end  # left and right run at the same time
```

By default a task starts when the tasks it depends on have **finished**. Other kinds of
dependency are possible with `"type"`:

| Type | Meaning |
| --- | --- |
| `FS` (default) | Start after the other task finishes |
| `SS` | Start after the other task starts |
| `FF` | Finish only after the other task finishes |

## Passing data between tasks

Tasks share data through the **session data** of their session, a table of named values.

- When a task finishes, each of its **outputs** is saved under the output's name.
- When a task starts, each of its **inputs** is read by the input's name.

So an output named `greeting` and a later input named `greeting` are connected. To use a
different name, set `set_to` on the output or `get_from` on the input:

```json
{ "name": "result", "set_to": "left" }
```

```json
{ "name": "a", "get_from": "left" }
```

The first saves the tool's `result` as `left`. The second gives the tool the value of
`left` as its argument `a`.

An input with a `value` and no `get_from` uses that value when the session data has
nothing by its name. This is how you give a task a fixed input, like `"world"` above.

## Params

**Params** are settings of a task that do not come from other tasks, for example the
duration of `system.sleep`:

```json
{ "id": "wait", "type": "system.sleep", "params": [{ "name": "duration", "value": 5 }], "depends_on": [{ "id": "start" }] }
```

The tool decides which of its arguments are inputs and which are params. See
[Writing actors](actors.md#inputs-params-and-outputs).

## Values

Inputs, outputs and params can hold numbers, text, lists and dictionaries, and also COMPAS
objects such as frames and meshes. In JSON, write a COMPAS object the way COMPAS
serializes it:

```json
{ "name": "frame", "value": { "dtype": "compas.geometry/Frame", "data": { "point": [0, 0, 0], "xaxis": [1, 0, 0], "yaxis": [0, 1, 0] } } }
```

`type_hint` and `description` are optional. They help the people and tools that read the
blueprint.

## Conditions

A task with a `condition` runs only if the condition is true. Otherwise it is skipped, and
the tasks after it still run:

```json
{ "id": "double-check", "type": "user_prompt.confirm", "condition": "answer == 'Yes'", ... }
```

The condition is a Python expression. It can use the task's inputs and params, and any
value in the session data.

## More

- **Scopes** group tasks between a task with `scope_start` and a task with `scope_end`,
  to skip, retry or repeat them together. See `scope_skip.json`, `scope_retry.json` and
  `scope_while.json`.
- **Composite tasks** (`system.composite`) run another blueprint and map data in and out.
  See `toy_problem_4.json`.
- **Dynamic expansion** runs a blueprint once per element of a model. See `toy_problem_6.json`.
- **Competitive execution** sends a task to every actor of its type; the first answer
  wins. Set the param `execution_mode` to `COMPETITIVE`. See `toy_problem_10_competitive.json`.

All of these are in the [examples](examples.md).
