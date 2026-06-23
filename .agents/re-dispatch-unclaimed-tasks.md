# Re-dispatch unclaimed tasks with orchestrator-side polling

When the orchestrator publishes a `TaskAssignmentMessage`, the message is fire-and-forget over MQTT. If no agent is subscribed at that moment (e.g., the agent process hasn't started yet or is restarting), the message evaporates and the session hangs indefinitely. We decided to solve this with an orchestrator-side re-dispatch polling loop rather than MQTT retained messages.

## Considered Options

**Rejected: MQTT retained messages.** Setting `retain=True` on the `antikythera/task/start` topic would cause the broker to replay the last message to any late-subscribing agent. This solves the race at the transport layer without any timer logic. We rejected it because clearing a retained message must become part of the claim/allocation handshake — a subtle protocol change with non-obvious failure modes if the clear step is missed (stale retained messages could cause agents to claim already-running tasks after a restart).

**Chosen: Orchestrator polling loop.** A single background thread scans all `READY` tasks and re-publishes any whose `first_dispatched_at` timestamp exceeds the re-dispatch interval. After `MAX_REDISPATCHES` attempts with no claim, the task is failed with a `NO_AGENT_CLAIMED` error. The transport stays dumb; all retry policy lives in the orchestrator.

## Consequences

- Tasks that previously hung silently will now fail after ~90s (3 retries × 30s interval, both configurable). This is a visible behaviour change for operators.
- The timeout applies **only while a task is in `READY` state** (dispatched, not yet claimed). Tasks in `RUNNING` state are executing on an agent and are never subject to this timeout, regardless of how long they take.
- `first_dispatched_at` is tracked in an in-memory side dict on the orchestrator, not persisted. If the orchestrator restarts, `_reset_failed_tasks` already resets `READY` tasks to `PENDING`, so the clock resets naturally.
