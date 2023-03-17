from dataclasses import dataclass
from email import message
from typing import Optional, List

SEPARATOR_TOKEN = "<|endoftext|>"


@dataclass(frozen=True)
class Message:
    user: str
    text: Optional[str] = None
    
    def render(self):
        return {
            "role": self.user, 
            "content": self.text
        }


@dataclass
class Conversation:
    messages: List[Message]

    def prepend(self, message: Message):
        self.messages.insert(0, message)
        return self

    def render(self):
        return [message.render() for message in self.messages]


@dataclass(frozen=True)
class Config:
    name: str
    instructions: str


@dataclass(frozen=True)
class Prompt:
    header: Message
    convo: Conversation

    def render(self):
        message_list = []
        message_list.append(self.header.render())
        for message in self.convo.render():
            message_list.append(message)

        return message_list