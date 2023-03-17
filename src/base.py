from dataclasses import dataclass
from email import message
from typing import Optional, List

SEPARATOR_TOKEN = "<|endoftext|>"


@dataclass(frozen=True)
class Message:
    role: str
    content: str
    
    def to_dict(self):
        return {
            "role": self.role, 
            "content": self.content
        }


@dataclass
class Conversation:
    messages: List[Message]

    def prepend(self, message: Message):
        self.messages.insert(0, message)
        return self

    def render(self):
        return [message.to_dict() for message in self.messages]


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