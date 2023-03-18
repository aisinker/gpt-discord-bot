from enum import Enum
from dataclasses import dataclass
import openai
from typing import Optional, List
from src.utils import logger


class CompletionResult(Enum):
    OK = 0
    TOO_LONG = 1
    INVALID_REQUEST = 2
    OTHER_ERROR = 3


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content
        }


@dataclass
class CompletionData:
    status: CompletionResult
    reply_text: Optional[ChatMessage]
    status_text: Optional[str]


async def chat_completion(
    messages: List[ChatMessage]
) -> CompletionData:
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[message.to_dict() for message in messages],
            temperature=1.0,
            top_p=0.9,
            max_tokens=2048,
            stop=["<|endoftext|>"],
        )
        reply = response.choices[0].message.content.strip()
        return CompletionData(
            status=CompletionResult.OK, reply_text=ChatMessage(role="assistant", content=reply), status_text=None
        )
    except openai.error.InvalidRequestError as e:
        if "This model's maximum context length" in e.user_message:
            return CompletionData(
                status=CompletionResult.TOO_LONG, reply_text=None, status_text=str(e)
            )
        else:
            logger.exception(e)
            return CompletionData(
                status=CompletionResult.INVALID_REQUEST,
                reply_text=None,
                status_text=str(e),
            )
    except Exception as e:
        logger.exception(e)
        return CompletionData(
            status=CompletionResult.OTHER_ERROR, reply_text=None, status_text=str(e)
        )
