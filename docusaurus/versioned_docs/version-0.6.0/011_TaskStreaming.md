Streaming
================

<!-- WARNING: THIS FILE WAS AUTOGENERATED! DO NOT EDIT! -->

``` python
from datetime import datetime, timedelta

from anyio import create_task_group, create_memory_object_stream, ExceptionGroup
from unittest.mock import Mock, MagicMock, AsyncMock

import asyncer
import pytest
from aiokafka import ConsumerRecord, TopicPartition
from pydantic import BaseModel, Field, HttpUrl, NonNegativeInt
from tqdm.notebook import tqdm
from types import CoroutineType

from fastkafka._components.logger import supress_timestamps
```

``` python
supress_timestamps()
logger = get_logger(__name__, level=20)
logger.info("ok")
```

    [INFO] __main__: ok

## anyio stream is not running tasks in parallel

> Memory object stream is buffering the messages but the messages are
> consumed one by one and a new one is consumed only after the last one
> is finished

``` python
num_msgs = 5
latency = 0.2

receive_pbar = tqdm(total=num_msgs*2)

async def latency_task():
    receive_pbar.update(1)
    await asyncio.sleep(latency)
    receive_pbar.update(1)

async def process_message_callback(
        receive_stream,
) -> None:
    async with receive_stream:
        async for task in receive_stream:
            await task

send_stream, receive_stream = anyio.create_memory_object_stream(
    max_buffer_size=num_msgs
)

t0 = datetime.now()
async with anyio.create_task_group() as tg:
    tg.start_soon(process_message_callback, receive_stream)
    async with send_stream:
        for i in tqdm(range(num_msgs)):
            await send_stream.send(latency_task())
            
assert datetime.now() - t0 >= timedelta(seconds=latency*num_msgs)
```

      0%|          | 0/10 [00:00<?, ?it/s]

      0%|          | 0/5 [00:00<?, ?it/s]

To solve this, we can create tasks from coroutines and let them run in
background while the receive_stream is spawning new tasks whithout being
blocked by previous ones.

``` python
num_msgs = 10_000
latency = 4.0

receive_pbar = tqdm(total=num_msgs*2)

async def latency_task():
    receive_pbar.update(1)
    await asyncio.sleep(latency)
    receive_pbar.update(1)

tasks = set()

async def process_message_callback(
        receive_stream,
) -> None:
    async with receive_stream:
        async for f in receive_stream:
            task: asyncio.Task = asyncio.create_task(f())
            tasks.add(task)
            task.add_done_callback(lambda task=task, tasks=tasks: tasks.remove(task))

send_stream, receive_stream = anyio.create_memory_object_stream(
    max_buffer_size=num_msgs
)

t0 = datetime.now()
async with anyio.create_task_group() as tg:
    tg.start_soon(process_message_callback, receive_stream)
    async with send_stream:
        for i in tqdm(range(num_msgs)):
            await send_stream.send(latency_task)

await asyncio.sleep(latency/2)
receive_pbar.refresh()
assert receive_pbar.n == num_msgs, receive_pbar.n

while len(tasks) > 0:
    await asyncio.sleep(0)
await send_stream.aclose()
    
receive_pbar.close()
assert datetime.now() - t0 <= timedelta(seconds=latency+5.0)
assert receive_pbar.n == num_msgs*2, receive_pbar.n

print("ok")
```

      0%|          | 0/20000 [00:00<?, ?it/s]

      0%|          | 0/10000 [00:00<?, ?it/s]

    ok

## Keeping track of tasks

------------------------------------------------------------------------

<a
href="https://github.com/airtai/fastkafka/blob/main/fastkafka/_components/task_streaming.py#L26"
target="_blank" style={{float: 'right', fontSize: 'smaller'}}>source</a>

### TaskPool

>      TaskPool (size:int=100000,
>                on_error:Optional[Callable[[BaseException],NoneType]]=None)

Initialize self. See help(type(self)) for accurate signature.

``` python
async with TaskPool() as tp:
    pass
```

``` python
async def f():
    await asyncio.sleep(2)

pool = TaskPool()
assert len(pool) == 0

async with pool:
    task = asyncio.create_task(f())
    await pool.add(task)
    assert len(pool) == 1

assert len(pool) == 0, len(pool)
```

``` python
async def f():
    raise RuntimeError("funny error")

        
    return _log_error
    
pool = TaskPool(on_error=TaskPool.log_error(logger))

async with pool:
    task = asyncio.create_task(f())
    await pool.add(task)
```

    [WARNING] __main__: e=RuntimeError('funny error')

------------------------------------------------------------------------

<a
href="https://github.com/airtai/fastkafka/blob/main/fastkafka/_components/task_streaming.py#L75"
target="_blank" style={{float: 'right', fontSize: 'smaller'}}>source</a>

### ExceptionMonitor

>      ExceptionMonitor ()

Initialize self. See help(type(self)) for accurate signature.

``` python
no_tasks = 1

async def f():
    raise RuntimeError(f"very funny error.")


exception_monitor = ExceptionMonitor()
pool = TaskPool(on_error=exception_monitor.on_error)

async def create_tasks():
    for _ in range(no_tasks):
        task = asyncio.create_task(f())
        await pool.add(task)
        await asyncio.sleep(0.1) # otherwise the tasks get created before any of them throws an exception
        if exception_monitor.exception_found:
            break
        
with pytest.raises(RuntimeError) as e:
    async with exception_monitor, pool:
        async with asyncer.create_task_group() as tg:
            tg.soonify(create_tasks)()
            
print(f"{e=}")
assert exception_monitor.exceptions == [], len(exception_monitor.exceptions)
```

    e=<ExceptionInfo RuntimeError('very funny error.') tblen=4>

------------------------------------------------------------------------

<a
href="https://github.com/airtai/fastkafka/blob/main/fastkafka/_components/task_streaming.py#L98"
target="_blank" style={{float: 'right', fontSize: 'smaller'}}>source</a>

### StreamExecutor

>      StreamExecutor ()

Helper class that provides a standard way to create an ABC using
inheritance.

## Streaming tasks

``` python
mock = Mock()
async_mock = asyncer.asyncify(mock)

async def process_items(receive_stream):
    async with receive_stream:
        async for item in receive_stream:
            task = asyncio.create_task(async_mock(item))
            await pool.add(task)

send_stream, receive_stream = create_memory_object_stream()
pool = TaskPool()

async with pool:
    async with create_task_group() as tg:
        tg.start_soon(process_items, receive_stream)
        async with send_stream:
            await send_stream.send(f"hi")

mock.assert_called()
```

------------------------------------------------------------------------

<a
href="https://github.com/airtai/fastkafka/blob/main/fastkafka/_components/task_streaming.py#L132"
target="_blank" style={{float: 'right', fontSize: 'smaller'}}>source</a>

### DynamicTaskExecutor

>      DynamicTaskExecutor (throw_exceptions:bool=False, max_buffer_size=100000,
>                           size=100000)

Helper class that provides a standard way to create an ABC using
inheritance.

``` python
def is_shutting_down_f(call_count:int = 1) -> Callable[[], bool]:
    count = {"count": 0}
    
    def _is_shutting_down_f(count=count, call_count:int = call_count):
        if count["count"]>=call_count:
            return True
        else:
            count["count"] = count["count"] + 1
            return False
        
    return _is_shutting_down_f
```

``` python
f = is_shutting_down_f()
assert f() == False
assert f() == True
```

``` python
async def produce():
    return ["msg"]


async def consume(msg):
    print(msg)


stream = DynamicTaskExecutor()

await stream.run(
    is_shutting_down_f(),
    produce_func=produce,
    consume_func=consume,
)
```

    msg

``` python
mock_produce = AsyncMock(spec=CoroutineType, return_value=["msg"])
mock_consume = AsyncMock(spec=CoroutineType)

stream = DynamicTaskExecutor()

await stream.run(
    is_shutting_down_f(),
    produce_func=mock_produce,
    consume_func=mock_consume,
)

mock_produce.assert_awaited()
mock_consume.assert_awaited_with("msg")
```

``` python
mock_produce = AsyncMock(spec=CoroutineType, return_value=["msg"])
mock_consume = AsyncMock(spec=CoroutineType)

stream = DynamicTaskExecutor()

await stream.run(
    is_shutting_down_f(),
    produce_func=mock_produce,
    consume_func=mock_consume,
)

mock_produce.assert_called()
mock_consume.assert_called_with("msg")
```

``` python
num_msgs = 13

mock_produce = AsyncMock(spec=CoroutineType, return_value=["msg"])
mock_consume = AsyncMock(spec=CoroutineType)
mock_consume.side_effect = RuntimeError()

stream = DynamicTaskExecutor(throw_exceptions=True)

with pytest.raises(RuntimeError) as e:
    await stream.run(
        is_shutting_down_f(num_msgs),
        produce_func=mock_produce,
        consume_func=mock_consume,
    )

mock_produce.assert_called()
mock_consume.assert_awaited_with("msg")
```

``` python
num_msgs = 13

mock_produce = AsyncMock(spec=CoroutineType, return_value=["msg"])
mock_consume = AsyncMock(spec=CoroutineType)
mock_consume.side_effect = RuntimeError()

stream = DynamicTaskExecutor()

await stream.run(
    is_shutting_down_f(num_msgs),
    produce_func=mock_produce,
    consume_func=mock_consume,
)

mock_produce.assert_called()
mock_consume.assert_awaited_with("msg")
```

    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()
    [WARNING] __main__: e=RuntimeError()

## Awaiting coroutines

------------------------------------------------------------------------

<a
href="https://github.com/airtai/fastkafka/blob/main/fastkafka/_components/task_streaming.py#L205"
target="_blank" style={{float: 'right', fontSize: 'smaller'}}>source</a>

### SequentialExecutor

>      SequentialExecutor (throw_exceptions:bool=False, max_buffer_size=100000)

Helper class that provides a standard way to create an ABC using
inheritance.

``` python
num_msgs = 13

mock_produce = AsyncMock(spec=CoroutineType, return_value=["msg"])
mock_consume = AsyncMock(spec=CoroutineType)
mock_consume.side_effect = RuntimeError("Funny error")

stream = SequentialExecutor(throw_exceptions=True)

with pytest.raises(ExceptionGroup) as e:
    await stream.run(is_shutting_down_f(num_msgs), produce_func=mock_produce, consume_func=mock_consume)

mock_produce.assert_called()
mock_consume.assert_awaited_with("msg")
```

``` python
num_msgs = 13

mock_produce = AsyncMock(spec=CoroutineType, return_value=["msg"])
mock_consume = AsyncMock(spec=CoroutineType)
mock_consume.side_effect = RuntimeError("Funny error")

stream = SequentialExecutor()

await stream.run(
    is_shutting_down_f(num_msgs),
    mock_produce,
    mock_consume,
)

mock_produce.assert_called()
mock_consume.assert_awaited_with("msg")
```

    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')
    [WARNING] __main__: e=RuntimeError('Funny error')

------------------------------------------------------------------------

<a
href="https://github.com/airtai/fastkafka/blob/main/fastkafka/_components/task_streaming.py#L235"
target="_blank" style={{float: 'right', fontSize: 'smaller'}}>source</a>

### get_executor

>      get_executor (executor:Union[str,__main__.StreamExecutor,NoneType]=None)

``` python
for executor in [None, "SequentialExecutor", SequentialExecutor()]:
    actual = get_executor(executor)
    assert actual.__class__.__qualname__ == "SequentialExecutor"
```

``` python
for executor in ["DynamicTaskExecutor", DynamicTaskExecutor()]:
    actual = get_executor(executor)
    assert actual.__class__.__qualname__ == "DynamicTaskExecutor"
```