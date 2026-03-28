# Exploration: arq Job Context and Custom Metadata Passing

Date: 2026-03-27

## Research question

1. When calling `arq_pool.enqueue_job("task_name", arg1, arg2, _job_id="xxx", _custom_key="value")`, does `_custom_key` get passed to the task function's `ctx` dict?
2. How does arq handle extra keyword arguments with underscore prefix?
3. What is the correct way to pass custom metadata through an arq job to the worker task?

## Scope

Analysis of arq v0.27.0 source code as installed in the project's backend virtualenv. Focused on the `enqueue_job` method, job serialization, and worker-side job execution. Out of scope: Redis internals, custom serializers, cron jobs.

## Findings

### How `enqueue_job` handles keyword arguments

The `enqueue_job` method signature (in `connections.py`, line 119) is:

```python
async def enqueue_job(
    self,
    function: str,
    *args: Any,
    _job_id: Optional[str] = None,
    _queue_name: Optional[str] = None,
    _defer_until: Optional[datetime] = None,
    _defer_by: Union[None, int, float, timedelta] = None,
    _expires: Union[None, int, float, timedelta] = None,
    _job_try: Optional[int] = None,
    **kwargs: Any,
) -> Optional[Job]:
```

The method accepts `**kwargs: Any` as a catch-all for additional keyword arguments. These kwargs are passed directly to `serialize_job()` on line 172:

```python
job = serialize_job(function, args, kwargs, _job_try, enqueue_time_ms, serializer=self.job_serializer)
```

The `serialize_job` function (in `jobs.py`, line 211) stores `kwargs` in the serialized payload under key `'k'`:

```python
data = {'t': job_try, 'f': function_name, 'a': args, 'k': kwargs, 'et': enqueue_time_ms}
```

This means **any keyword argument that does not match one of the reserved underscore-prefixed parameters** (`_job_id`, `_queue_name`, `_defer_until`, `_defer_by`, `_expires`, `_job_try`) flows into `**kwargs` and is serialized with the job.

**Confidence:** Corroborated (verified directly in source code)

### What happens with `_custom_key="value"`

If you call `enqueue_job("task_name", _custom_key="value")`, the `_custom_key` parameter does **not** match any of the six reserved parameters. Python's `**kwargs` catch-all captures it. The kwargs dict becomes `{"_custom_key": "value"}`, which is serialized and stored in Redis.

On the worker side, `run_job` (in `worker.py`, line 474) deserializes the job and calls the function as:

```python
function.coroutine(ctx, *args, **kwargs)
```

(line 591). So `_custom_key="value"` is passed as a **regular keyword argument** to the task function -- it is **not** injected into the `ctx` dict.

**Confidence:** Corroborated (verified directly in source code)

### The `ctx` dict: what it contains and where it comes from

The `ctx` dict passed to task functions is constructed in `run_job` (worker.py, lines 572-578):

```python
job_ctx = {
    'job_id': job_id,
    'job_try': job_try,
    'enqueue_time': ms_to_datetime(enqueue_time_ms),
    'score': score,
}
ctx = {**self.ctx, **job_ctx}
```

It merges two sources:
1. `self.ctx` -- the Worker-level context dict, initialized at worker startup. It always contains `'redis'` (the pool), and whatever the `on_startup` callback adds.
2. `job_ctx` -- per-job metadata with `job_id`, `job_try`, `enqueue_time`, and `score`.

The `ctx` dict has **no mechanism** to receive values from the enqueue side. It is entirely constructed by the worker from its own state plus Redis-derived job metadata.

**Confidence:** Corroborated (verified directly in source code)

### How to pass custom metadata from enqueue to task

There are three approaches:

**Approach A: Regular keyword arguments.** Pass metadata as normal kwargs to `enqueue_job`. They arrive as keyword arguments to the task function, not in `ctx`.

```python
# Enqueue side
await pool.enqueue_job("my_task", source_id, _job_id="xxx", user_id="u-123")

# Worker side -- user_id arrives as a kwarg, not in ctx
async def my_task(ctx, source_id, user_id=None):
    ...
```

Trade-offs: Simple and direct. The task function signature must accept these kwargs explicitly (or use `**kwargs`). Metadata is serialized into the job payload in Redis.

**Approach B: Regular positional arguments.** Pass metadata as positional args.

```python
await pool.enqueue_job("my_task", source_id, "u-123")

async def my_task(ctx, source_id, user_id):
    ...
```

Trade-offs: Tightly coupled to argument order. Less readable at the enqueue site.

**Approach C: Pack metadata into a single dict argument.** Pass a metadata dict as one of the arguments.

```python
await pool.enqueue_job("my_task", source_id, {"user_id": "u-123", "trace_id": "t-456"})

async def my_task(ctx, source_id, metadata):
    user_id = metadata["user_id"]
```

Trade-offs: Flexible for variable metadata. Slightly less explicit at the function signature level.

**Confidence:** Substantiated (derived from source code analysis)

### What the reserved underscore parameters do

The six reserved parameters are consumed by `enqueue_job` itself and **never** reach the serialized job payload or the task function:

| Parameter | Purpose | Used on line |
|-----------|---------|-------------|
| `_job_id` | Sets the Redis key for job deduplication | 148 |
| `_queue_name` | Overrides the default queue name | 146-147 |
| `_defer_until` | Schedules the job for a future datetime | 163 |
| `_defer_by` | Delays the job by a duration | 153, 165-166 |
| `_expires` | Sets job TTL (expiration) | 154, 170 |
| `_job_try` | Sets the initial try counter | 172 |

Any kwargs not matching these six names flow into the serialized payload.

**Confidence:** Corroborated (verified directly in source code)

## Key takeaways

- Underscore-prefixed kwargs that do not match arq's six reserved names (`_job_id`, `_queue_name`, `_defer_until`, `_defer_by`, `_expires`, `_job_try`) are treated as regular kwargs and serialized into the job payload. They are passed to the task function as keyword arguments, not injected into `ctx`. (Corroborated)
- The `ctx` dict is constructed entirely by the worker -- it contains `redis`, `job_id`, `job_try`, `enqueue_time`, `score`, and anything added by `on_startup`. There is no enqueue-to-ctx pipeline. (Corroborated)
- Passing `_custom_key="value"` to `enqueue_job` results in the task function receiving `_custom_key="value"` as a keyword argument. The task function must accept it in its signature. (Corroborated)
- The correct way to pass custom metadata is through regular args or kwargs to `enqueue_job` -- they serialize and arrive at the task function alongside `ctx`. (Substantiated)

## Open questions

- None. The source code is unambiguous on all three research questions.

## Sources

1. arq v0.27.0 source: `backend/.venv/lib/python3.14/site-packages/arq/connections.py` -- `enqueue_job` method definition and kwargs handling
2. arq v0.27.0 source: `backend/.venv/lib/python3.14/site-packages/arq/jobs.py` -- `serialize_job` and `deserialize_job_raw` showing how args/kwargs are stored
3. arq v0.27.0 source: `backend/.venv/lib/python3.14/site-packages/arq/worker.py` -- `run_job` method showing `ctx` construction and `function.coroutine(ctx, *args, **kwargs)` invocation
