"""Request / Response models for the gateway API."""

from datetime import datetime
from typing import Any, TypeVar, Generic

from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField
from sqlalchemy import Column, JSON


D = TypeVar("D")
class BaseResponse(BaseModel, Generic[D]):
    code: int = 200
    message: str = "Success"
    data: D | None = None


# ── Home API models ──────────────────────────────────────────────────────────

class CurrentTask(BaseModel):
    name: str = Field(description="Task name / description")
    progress: int = Field(description="Progress percentage 0-100")


class RecentTask(BaseModel):
    id: int = Field(description="Task ID")
    name: str = Field(description="Task name")
    created_at: datetime = Field(description="ISO timestamp")


class StatusResponse(BaseModel):
    battery: int = Field(description="Battery level percentage 0-100")
    available: list[str] = Field(description="Available features")
    unavailable: list[str] = Field(description="Features not ready yet")
    weather: str = Field(description="Current weather condition, e.g. sunny, rainy")
    air_quality: str = Field(description="Air quality index, e.g. good, moderate, unhealthy")
    calendar_summary: str = Field(description="Today's calendar events, if any")
    mail_summary: str = Field(description="Recent email subjects, if any")


# ── Controller API models ────────────────────────────────────────────────────

class SpeedRequest(BaseModel):
    speed: float = Field(ge=0, le=1, description="Speed value 0.0 ~ 1.0")


class SpeedResponse(BaseModel):
    speed: float = Field(description="Current speed value")


class RotateRequest(BaseModel):
    direction: str = Field(description="Rotation direction: left or right")
    duration: float = Field(default=1.0, gt=0, description="Duration in seconds")


class MoveRequest(BaseModel):
    direction: str = Field(description="Move direction: forward, backward, left, right")
    duration: float = Field(default=1.0, gt=0, description="Duration in seconds")

class ExternalRequest(BaseModel):
    safe: bool = Field(description="Whether the system is in a safe state for movement")
    unsafe_side: str | None = Field(default=None, description="If unsafe, which side is the obstacle on: left or right")

class ExternalResponse(ExternalRequest):
    pass

class Action(BaseModel):
    action_id: str = Field(description="Unique action identifier")
    action_name: str = Field(description="Display name of the action")
    action_params: dict[str, Any] = Field(default_factory=dict, description="Optional parameters for the action")


class Ability(BaseModel):
    id: int = Field(description="id in database")
    name: str = Field(description="Display name of the ability")
    duration: float = Field(description="Duration in seconds")
    actions: list[Action] = Field(description="List of actions that comprise this ability")


class PerformRequest(BaseModel):
    action_id: str = Field(description="Action to perform")


class AbilityCreateRequest(BaseModel):
    name: str = Field(description="Ability name")
    actions: list[Action] = Field(description="Ordered list of actions")


class AbilityUpdateRequest(BaseModel):
    name: str | None = Field(default=None, description="New name")
    actions: list[Action] | None = Field(default=None, description="New action list")


# ── Skills API models ────────────────────────────────────────────────────────

class SkillSummary(BaseModel):
    id: str = Field(description="Unique skill identifier")
    name: str = Field(description="Display name")
    description: str = Field(description="Short description")
    category: str = Field(description="Skill category")
    installed: bool = Field(description="Whether the skill is installed")
    enabled: bool = Field(description="Whether the skill is enabled")


class SkillDetail(SkillSummary):
    enabled: bool = Field(description="Whether the skill is enabled")
    installed: bool = Field(description="Whether the skill is installed")
    version: str = Field(default="1.0.0", description="Skill version")
    created_at: datetime = Field(description="When the skill was created")
    updated_at: datetime = Field(description="When the skill was last updated")
    installed_at: datetime | None = Field(default=None, description="When the skill was installed")


class SkillPatchRequest(BaseModel):
    enabled: bool = Field(description="Enable or disable the skill")


# ── Chat API models ─────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    chat_id: str = Field(default="main", description="Conversation identifier")
    sender_id: str = Field(default="user", description="Sender identifier")
    content: str = Field(description="Message text")


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    label: str = Field(default="text", description="Message type, e.g. text, audio, file")
    media: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class ChatResponse(BaseModel):
    channel: str
    chat_id: str
    messages: list[Message] = Field(description="List of messages in the response")
    is_final: bool = Field(default=False, description="Whether this is the final response (not a progress update)")


class PageResponse(BaseModel):
    messages: list[Message]
    page: int
    size: int
    total: int


class ChatCommand(BaseModel):
    name: str = Field(description="Command name, e.g. /new")
    description: str = Field(description="What this command does")


# ── Database models ──────────────────────────────────────────────────────────

class ActionLog(SQLModel, table=True):
    """Log of performed actions, used to derive recent/frequent actions."""

    id: int | None = SQLField(default=None, primary_key=True)
    action_id: str = SQLField(index=True)
    created_at: datetime = SQLField(default_factory=datetime.now)


class Task(SQLModel, table=True):
    """A user-initiated task."""

    id: int | None = SQLField(default=None, primary_key=True)
    name: str
    created_at: datetime = SQLField(default_factory=datetime.now)


class MessageStore(SQLModel, table=True):
    """Persisted chat message (both user and assistant)."""

    id: int | None = SQLField(default=None, primary_key=True)
    channel: str = SQLField(index=True)
    chat_id: str = SQLField(index=True)
    role: str  # "user" or "assistant"
    content: str
    label: str = SQLField(default="text") # "text", "audio", "file"
    media: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))
    meta: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = SQLField(default_factory=datetime.now)


class AbilityStore(SQLModel, table=True):
    """Store for defined abilities."""

    id: int | None = SQLField(default=None, primary_key=True)
    name: str
    duration: float
    actions: list[dict[str, Any]] = SQLField(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = SQLField(default_factory=datetime.now)
