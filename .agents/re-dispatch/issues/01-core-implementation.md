## What to build

Add an orchestrator-side re-dispatch loop that detects unclaimed READY tasks and re-publishes them with exponential backoff, failing them with a `NO_AGENT_CLAIMED` error after a configurable number of attempts.

When `_schedule_tasks` sets a task to READY and publishes a `TaskAssignmentMessage`, two new in-memory dicts record the dispatch state for that task: one tracking the timestamp of the most recent dispatch, and one tracking the attempt count. When a task is claimed (in `on_task_claim`) or reset to PENDING (in `_reset_failed_tasks` and `reset_task_state`), its entries are removed from both dicts.

A background polling thread (`_poll_for_stale_tasks`) starts in `start()` and stops cleanly in `stop()`. On each wake-up it scans all READY tasks and checks whether enough time has elapsed since the last dispatch:

```
base_delay = 2        # seconds
max_delay  = 90       # seconds
delay      = min(base_delay * 2 ** attempts, max_delay)
```

Attempt 0 re-dispatches after 2 s, attempt 1 after 4 s, attempt 2 after 8 s, … capped at 90 s per interval.

If `attempts < MAX_REDISPATCHES`, the orchestrator re-publishes the original `TaskAssignmentMessage` and increments the attempt counter. If `attempts >= MAX_REDISPATCHES`, it synthesizes a `TaskCompletionMessage(state=FAILED)` with error code `NO_AGENT_CLAIMED` and calls `on_task_completed()` directly, which propagates the failure through the normal path (session → FAILED, `_completion_event` set).

`REDISPATCH_BASE_DELAY`, `REDISPATCH_MAX_DELAY`, and `MAX_REDISPATCHES` are added to `config.py` with env-var overrides (defaults: 2, 90, 5).

The polling thread wakes on a short tick (e.g. 1 s) rather than sleeping for the full backoff interval, so that `stop()` can interrupt it promptly.

## Acceptance criteria

- [ ] `config.py` exposes `REDISPATCH_BASE_DELAY`, `REDISPATCH_MAX_DELAY`, `MAX_REDISPATCHES` with env overrides
- [ ] `Orchestrator._dispatch_times` and `Orchestrator._dispatch_counts` are populated when a task goes READY, and cleared on claim and on any reset path
- [ ] Re-dispatch polling thread is started by `start()` and stops within ~1 s of `stop()` being called
- [ ] A READY task that goes unclaimed is re-published after `min(base * 2^attempts, max)` seconds, with attempt count incrementing each time
- [ ] After `MAX_REDISPATCHES` re-dispatches without a claim, the task fails with error code `NO_AGENT_CLAIMED` via `on_task_completed()`
- [ ] Session transitions to FAILED state when a task hits `NO_AGENT_CLAIMED`
- [ ] The TODO comment in `_schedule_tasks` (line 866 of orchestrator.py) is removed

## Blocked by

None — can start immediately.
