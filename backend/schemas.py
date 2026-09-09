from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class FeedbackAction(str, Enum):
    upvote = "upvote"
    downvote = "downvote"


class FeedbackRequest(BaseModel):
    action: FeedbackAction


class UserCreateRequest(BaseModel):
    """Create a care-recipient record for one browser session."""
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip()


class UserResponse(BaseModel):
    id: UUID
    name: str


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)
    assistant_reply: str | None = Field(default=None, max_length=8_000)
    intervention_id: UUID | None = None  # supplied only when the UI knows the suggestion being evaluated
    share_successful_intervention: bool = False

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text cannot be blank")
        return value.strip()


class ContextRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)
    limit: int = Field(default=5, ge=1, le=20)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)
    # Consent is separate from saying an idea worked.  Without this flag the
    # observation remains in that user's private long-term memory only.
    share_successful_intervention: bool = False

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text cannot be blank")
        return value.strip()


class FeedbackResponse(BaseModel):
    intervention_id: UUID
    upvotes: int
    downvotes: int
    source: str
