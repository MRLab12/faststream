# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/002_ConfluentKafka.ipynb.

# %% auto 0
__all__ = ['logger', 'create_missing_topics', 'create_testing_topic', 'AIOProducer']

# %% ../nbs/002_ConfluentKafka.ipynb 1
from typing import List, Dict, Any, Optional, Callable, Tuple, Generator
from os import environ
import string
from contextlib import contextmanager

import asyncio
from asyncio import BaseEventLoop
from inspect import iscoroutinefunction

import numpy as np
import confluent_kafka
from confluent_kafka import KafkaException, Consumer, Producer, Message, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import time
from threading import Thread
from asyncer import syncify

import fast_kafka_api.logger

fast_kafka_api.logger.should_supress_timestamps = True

from .logger import get_logger

# %% ../nbs/002_ConfluentKafka.ipynb 2
logger = get_logger(__name__)

# %% ../nbs/002_ConfluentKafka.ipynb 6
def create_missing_topics(
    admin: AdminClient,
    topic_names: List[str],
    *,
    num_partitions: Optional[int] = None,
    replication_factor: Optional[int] = None,
    **kwargs,
) -> None:
    if not replication_factor:
        replication_factor = len(admin.list_topics().brokers)
    if not num_partitions:
        num_partitions = replication_factor
    existing_topics = list(admin.list_topics().topics.keys())
    logger.debug(
        f"create_missing_topics({topic_names}): existing_topics={existing_topics}, num_partitions={num_partitions}, replication_factor={replication_factor}"
    )
    new_topics = [
        NewTopic(
            topic,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
            **kwargs,
        )
        for topic in topic_names
        if topic not in existing_topics
    ]
    if len(new_topics):
        logger.info(f"create_missing_topics({topic_names}): new_topics = {new_topics}")
        #         nlsep = "\n - "
        #         logger.info(f"create_missing_topics({topic_names}): creating topics:{nlsep}{nlsep.join([str(t) for t in new_topics])}")
        fs = admin.create_topics(new_topics)
        results = {k: f.result() for k, f in fs.items()}
        time.sleep(1)

# %% ../nbs/002_ConfluentKafka.ipynb 9
def _consume_all_messages(c: Consumer, timeout=0.1, no_retries: int = 25):
    while True:
        for i in range(no_retries):
            msg = c.poll(timeout=timeout)
            if msg:
                if msg.error():
                    logger.warning(f"Error while consuming message: {msg.error()}")
                break
        break


@contextmanager
def create_testing_topic(
    kafka_config: Dict[str, Any], topic_prefix: str, seed: int
) -> Generator[Tuple[str, Consumer, Producer], None, None]:
    # create random topic name
    rng = np.random.default_rng(seed)
    topic = topic_prefix + "".join(rng.choice(list(string.ascii_lowercase), size=10))

    # delete topic if it already exists
    admin = AdminClient(kafka_config)
    existing_topics = admin.list_topics().topics.keys()
    if topic in existing_topics:
        logger.warning(f"topic {topic} exists, deleting it...")
        fs = admin.delete_topics(topics=[topic])
        results = {k: f.result() for k, f in fs.items()}
        time.sleep(1)

    try:
        # create topic if needed
        create_missing_topics(admin, [topic])

        # create consumer and producer for the topic
        c = Consumer(kafka_config)
        c.subscribe([topic])
        p = Producer(kafka_config)

        yield topic, c, p

    finally:
        pass
        # cleanup if needed again
        #         _consume_all_messages(c)
        fs = admin.delete_topics(topics=[topic])
        results = {k: f.result() for k, f in fs.items()}
        time.sleep(1)

# %% ../nbs/002_ConfluentKafka.ipynb 11
class AIOProducer:
    """Async producer

    Adapted companion code of the blog post "Integrating Kafka With Python Asyncio Web Applications"
    https://www.confluent.io/blog/kafka-python-asyncio-integration/

    https://github.com/confluentinc/confluent-kafka-python/blob/master/examples/asyncio_example.py

    """

    def __init__(
        self, config: Dict[str, Any], loop: Optional[BaseEventLoop] = None
    ) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._producer = Producer(config)
        self._cancelled = False
        self._poll_thread = Thread(target=self._poll_loop)
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._cancelled:
            self._producer.poll(0.1)

    def close(self) -> None:
        """Shutdowns the pooling thread pool"""
        self._cancelled = True
        self._poll_thread.join()

    def produce(
        self,
        topic: str,
        value: bytes,
        on_delivery: Optional[Callable[[KafkaError, Message], Any]] = None,
    ) -> "asyncio.Future[Any]":
        """An awaitable produce method

        Params:
            topic: name of the topic
            value: encoded message
            on_delivery: callback function to be called on delivery from a separate thread

        Returns:
            Awaitable future

        Raises:
            ValueError: if a coroutine passed as on_delivery
        """
        if on_delivery and iscoroutinefunction(on_delivery):
            raise ValueError("can only call synchronous code for now")

        result = self._loop.create_future()

        def ack(
            err: KafkaError,
            msg: Message,
            self: "AIOProducer" = self,
            result: "asyncio.Future[Any]" = result,
            on_delivery: Optional[Callable[[KafkaError, Message], Any]] = on_delivery,
        ) -> None:
            if err:
                self._loop.call_soon_threadsafe(
                    result.set_exception, KafkaException(err)
                )
            else:
                self._loop.call_soon_threadsafe(result.set_result, msg)

            if on_delivery:
                self._loop.call_soon_threadsafe(on_delivery, err, msg)

        self._producer.produce(topic, value, on_delivery=ack)

        return result