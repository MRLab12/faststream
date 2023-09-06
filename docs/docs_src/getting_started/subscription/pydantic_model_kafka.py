from faststream import FastStream
from faststream.kafka import KafkaBroker
from pydantic import Field, NonNegativeInt, BaseModel


broker = KafkaBroker("localhost:9092")
app = FastStream(broker)


class UserInfo(BaseModel):
    name: str = Field(..., examples=["john"], description="Registered user name")
    user_id: NonNegativeInt = Field(..., examples=[1], description="Registered user id")


@broker.subscriber("test-topic")
async def handle(user: UserInfo):
    assert user.name == "john"
    assert user.user_id == 1


@app.after_startup
async def test():
    await broker.publish({
        "name": "john",
        "user_id": 1
    }, topic="test-topic")
