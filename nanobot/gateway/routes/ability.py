"""Ability API routes — CRUD and execution of named action sequences."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from nanobot.gateway.database import SessionDep
from nanobot.gateway.unitree_g1 import loco, _ALL_ACTIONS as _LOCO_ACTIONS
from nanobot.gateway.models import (
    Ability,
    AbilityCreateRequest,
    AbilityStore,
    AbilityUpdateRequest,
    Action,
    BaseResponse,
)

router = APIRouter(prefix="/api/ability", tags=["ability"])

# All available action templates (move + rotate)
ALL_ABILITY_ACTIONS: list[Action] = [
    Action(action_id="move_forward", action_name="向前进", action_params={"speed": 0.5, "duration": 1.0}),
    Action(action_id="move_backward", action_name="向后退", action_params={"speed": 0.5, "duration": 1.0}),
    Action(action_id="move_left", action_name="向左移", action_params={"speed": 0.5, "duration": 1.0}),
    Action(action_id="move_right", action_name="向右移", action_params={"speed": 0.5, "duration": 1.0}),
    Action(action_id="rotate_left", action_name="向左转", action_params={"speed": 0.5, "duration": 1.0}),
    Action(action_id="rotate_right", action_name="向右转", action_params={"speed": 0.5, "duration": 1.0}),
]

ALL_ABILITY_ACTIONS.extend(_LOCO_ACTIONS.values())


def _calc_duration(actions: list[Action]) -> float:
    return sum(a.action_params.get("duration", 0.0) for a in actions)


def _to_ability(store: AbilityStore) -> Ability:
    actions = [Action(**a) if isinstance(a, dict) else a for a in store.actions]
    return Ability(id=store.id, name=store.name, duration=store.duration, actions=actions)


@router.get("/actions", response_model=BaseResponse[list[Action]])
async def list_actions() -> BaseResponse[list[Action]]:
    """Return all available action types for building abilities."""
    return BaseResponse(data=ALL_ABILITY_ACTIONS)


@router.get("/all", response_model=BaseResponse[list[Ability]])
async def list_abilities(session: SessionDep) -> BaseResponse[list[Ability]]:
    """List all saved abilities."""
    stores = session.exec(select(AbilityStore).order_by(AbilityStore.created_at.desc())).all()
    return BaseResponse(data=[_to_ability(s) for s in stores])


@router.get("/{ability_id}", response_model=BaseResponse[Ability])
async def get_ability(ability_id: int, session: SessionDep) -> BaseResponse[Ability]:
    """Get a single ability by ID."""
    store = session.get(AbilityStore, ability_id)
    if not store:
        raise HTTPException(status_code=404, detail=f"Ability {ability_id} not found")
    return BaseResponse(data=_to_ability(store))


@router.post("/", response_model=BaseResponse[Ability])
async def create_ability(body: AbilityCreateRequest, session: SessionDep) -> BaseResponse[Ability]:
    """Create a new ability."""
    store = AbilityStore(
        name=body.name,
        duration=_calc_duration(body.actions),
        actions=[a.model_dump() for a in body.actions],
    )
    session.add(store)
    session.commit()
    session.refresh(store)
    return BaseResponse(data=_to_ability(store))


@router.put("/{ability_id}", response_model=BaseResponse[Ability])
async def update_ability(ability_id: int, body: AbilityUpdateRequest, session: SessionDep) -> BaseResponse[Ability]:
    """Update an existing ability."""
    store = session.get(AbilityStore, ability_id)
    if not store:
        raise HTTPException(status_code=404, detail=f"Ability {ability_id} not found")
    if body.name is not None:
        store.name = body.name
    if body.actions is not None:
        store.actions = [a.model_dump() for a in body.actions]
        store.duration = _calc_duration(body.actions)
    session.add(store)
    session.commit()
    session.refresh(store)
    return BaseResponse(data=_to_ability(store))


@router.delete("/{ability_id}", response_model=BaseResponse[None])
async def delete_ability(ability_id: int, session: SessionDep) -> BaseResponse[None]:
    """Delete an ability."""
    store = session.get(AbilityStore, ability_id)
    if not store:
        raise HTTPException(status_code=404, detail=f"Ability {ability_id} not found")
    session.delete(store)
    session.commit()
    return BaseResponse(message="ability deleted")


@router.post("/{ability_id}/execute", response_model=BaseResponse[dict])
async def execute_ability(ability_id: int, session: SessionDep) -> BaseResponse[dict]:
    """Execute an ability by running its action sequence."""
    store = session.get(AbilityStore, ability_id)
    if not store:
        raise HTTPException(status_code=404, detail=f"Ability {ability_id} not found")
    await loco.execute_ability(store.actions)
    return BaseResponse(data={"ability_id": ability_id, "ability_name": store.name, "total_duration": store.duration})
