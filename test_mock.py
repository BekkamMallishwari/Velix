from velix_agent.core.message import Message
from velix_agent.providers.mock import MockProvider

provider = MockProvider()
msgs = [
    Message(role="user", content="My Name is Mallishwari"),
    Message(role="assistant", content="VelixAgent Phase 2 is active..."),
    Message(role="user", content="what is my name"),
]
res = provider.generate(msgs)
print(res.text)
