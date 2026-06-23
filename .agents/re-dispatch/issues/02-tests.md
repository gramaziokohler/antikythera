## What to build

Test coverage for the re-dispatch polling loop added in issue 01.

Three test cases, all in `tests/orchestrator/`:

**Test 1 — dispatch tracking lifecycle.**
Verify that `_dispatch_times` and `_dispatch_counts` are populated when `_schedule_tasks` publishes a READY task, and cleared when the task is claimed via `on_task_claim`. Also verify they are cleared by `_reset_failed_tasks` and `reset_task_state`. Use a mock publisher; no real MQTT connection needed.

**Test 2 — re-dispatch re-publishes with backoff.**
Freeze time (or inject a fake clock). After the first dispatch (attempt 0), advance time by `base_delay * 2^0 = 2 s` and tick the polling loop manually. Assert that `task_start_publisher.publish` is called a second time with the same `TaskAssignmentMessage`. Repeat for attempt 1 (advance 4 s), assert a third publish call. Assert that advancing time by less than the current backoff window does NOT trigger a re-publish.

**Test 3 — NO_AGENT_CLAIMED failure after MAX_REDISPATCHES.**
Configure `MAX_REDISPATCHES=2` for the test. Dispatch a task, exhaust all re-dispatch attempts by advancing time past each backoff window, and tick the polling loop each time. After the final attempt, assert that `on_task_completed` was called with `state=FAILED` and error code `NO_AGENT_CLAIMED`, and that `session.state == BlueprintSessionState.FAILED`.

## Acceptance criteria

- [ ] Test 1 passes: tracking dicts are populated on dispatch and cleared on claim and reset
- [ ] Test 2 passes: re-publishes occur at the correct exponential intervals and not before
- [ ] Test 3 passes: session fails with `NO_AGENT_CLAIMED` after MAX_REDISPATCHES

## Blocked by

- Issue 01: core implementation
