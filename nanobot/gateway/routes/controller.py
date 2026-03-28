"""Controller API routes — speed, rotation, movement, actions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from sqlmodel import func, select

from nanobot.gateway.database import SessionDep
from nanobot.gateway.unitree_g1 import loco
from nanobot.gateway.models import (
    Action,
    ActionLog,
    BaseResponse,
    ExternalRequest,
    ExternalResponse,
    MoveRequest,
    PerformRequest,
    RotateRequest,
    SpeedRequest,
    SpeedResponse,
)

router = APIRouter(prefix="/api/controller", tags=["controller"])

_speed: float = 0.5
_safe: bool = True
_unsafe_side: str | None = None

VALID_ROTATE_DIRECTIONS = {"left", "right"}
VALID_MOVE_DIRECTIONS = {"forward", "backward", "left", "right"}


@router.get("/speed", response_model=BaseResponse[SpeedResponse])
async def get_speed() -> BaseResponse[SpeedResponse]:
    """Get the current speed."""
    return BaseResponse(data=SpeedResponse(speed=_speed))


@router.post("/speed", response_model=BaseResponse[SpeedResponse])
async def set_speed(body: SpeedRequest) -> BaseResponse[SpeedResponse]:
    """Set the speed (0.0 ~ 1.0)."""
    global _speed
    _speed = body.speed
    return BaseResponse(data=SpeedResponse(speed=_speed))


@router.post("/rotate", response_model=BaseResponse[None])
async def rotate(body: RotateRequest) -> BaseResponse[None]:
    """Rotate in the given direction for the specified duration."""
    if body.direction not in VALID_ROTATE_DIRECTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid direction: {body.direction}, must be one of {VALID_ROTATE_DIRECTIONS}")
    await loco.rotate(body.direction, body.duration, _speed)
    return BaseResponse(message="rotate successful")


@router.post("/move", response_model=BaseResponse[None])
async def move(body: MoveRequest) -> BaseResponse[None]:
    """Move in the given direction for the specified duration."""
    if body.direction == "forward" and not _safe: # Only block forward movement when unsafe
        logger.warning("move blocked: system is not in safe state")
        return BaseResponse(code=2004, message="not safe to move")
    if body.direction not in VALID_MOVE_DIRECTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid direction: {body.direction}, must be one of {VALID_MOVE_DIRECTIONS}")
    await loco.move(body.direction, body.duration, _speed)
    return BaseResponse(message="move successful")


@router.post("/external", response_model=BaseResponse[ExternalResponse])
async def set_external(body: ExternalRequest) -> BaseResponse[ExternalResponse]:
    """Set the global safe flag. Motion commands are only allowed when safe=true."""
    global _safe, _unsafe_side
    _safe = body.safe
    _unsafe_side = body.unsafe_side
    return BaseResponse(data=ExternalResponse(safe=_safe, unsafe_side=_unsafe_side))

@router.get("/external", response_model=BaseResponse[ExternalResponse])
async def get_external() -> BaseResponse[ExternalResponse]:
    """Get the current state of the global safe flag."""
    return BaseResponse(data=ExternalResponse(safe=_safe, unsafe_side=_unsafe_side))

@router.post("/stop", response_model=BaseResponse[None])
async def stop() -> BaseResponse[None]:
    """Emergency stop — halt all movement immediately."""
    await loco.stop()
    return BaseResponse(message="stop successful")


@router.get("/actions", response_model=BaseResponse[list[Action]])
async def actions(
    session: SessionDep,
    recent: bool = Query(default=False),
    limit: int = Query(default=10, ge=1, le=50),
) -> BaseResponse[list[Action]]:
    """Return available actions. If recent=true, return most frequently used actions."""
    if not recent:
        return BaseResponse(data=list(loco.all_actions.values()))

    # Most frequent action_ids, ordered by count desc
    rows = session.exec(
        select(ActionLog.action_id, func.count())
        .group_by(ActionLog.action_id)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()

    result = []
    for action_id, _ in rows:
        action = loco.all_actions.get(action_id)
        if action:
            result.append(action)
    return BaseResponse(data=result)


@router.post("/perform", response_model=BaseResponse[dict])
async def perform(body: PerformRequest, session: SessionDep) -> BaseResponse[dict]:
    """Perform an action by action_id."""
    if body.action_id not in loco.all_actions:
        raise HTTPException(status_code=422, detail=f"Unknown action_id: {body.action_id}")

    # Log the action
    session.add(ActionLog(action_id=body.action_id))
    session.commit()

    await loco.perform(body.action_id)
    return BaseResponse(data={"action_id": body.action_id, "action_name": loco.all_actions[body.action_id].action_name})
