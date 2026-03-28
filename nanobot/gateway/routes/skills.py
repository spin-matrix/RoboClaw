"""Skills API routes — dynamically loaded from nanobot/skills."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from nanobot.gateway.models import BaseResponse, SkillDetail, SkillPatchRequest, SkillSummary

router = APIRouter(prefix="/api/skills", tags=["skills"])

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
_ENABLED_OVERRIDES: dict[str, bool] = {}
_GROUPED_SKILL_PREFIXES: dict[str, tuple[str, ...]] = {
    "gws-calendar": ("gws-calendar", "gws-calendar-agenda", "gws-calendar-insert"),
    "gws-gmail": (
        "gws-gmail",
        "gws-gmail-forward",
        "gws-gmail-read",
        "gws-gmail-reply",
        "gws-gmail-reply-all",
        "gws-gmail-send",
        "gws-gmail-triage",
        "gws-gmail-watch",
    ),
}


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _read_skill_frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    frontmatter: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = _strip_wrapping_quotes(value.strip())
    return frontmatter


def _display_name(skill_id: str, metadata: dict[str, str]) -> str:
    if name := metadata.get("name"):
        if name == "gws-gmail":
            return "Gmail"
        if name == "gws-calendar":
            return "Google Calendar"
        if name == "gws-shared":
            return "Google Workspace Shared"
        return name.replace("-", " ").title()
    return skill_id.replace("-", " ").title()


def _category_for_skill(skill_id: str) -> str:
    if skill_id.startswith("robot-"):
        return "机器人"
    if skill_id in {"cron", "memory"}:
        return "系统"
    if skill_id in {"github", "skill-creator", "tmux"}:
        return "开发工具"
    if skill_id == "clawhub":
        return "技能市场"
    if skill_id in {"weather"}:
        return "生活"
    return "效率工具"


def _group_skill_id(raw_skill_id: str) -> str:
    for grouped_skill_id, members in _GROUPED_SKILL_PREFIXES.items():
        if raw_skill_id in members:
            return grouped_skill_id
    return raw_skill_id


def _skill_paths() -> list[Path]:
    return sorted(path for path in _SKILLS_DIR.iterdir() if path.is_dir() and (path / "SKILL.md").exists())


def _build_skill_detail(skill_id: str, paths: list[Path]) -> SkillDetail:
    primary_path = next((path for path in paths if path.name == skill_id), paths[0])
    metadata = _read_skill_frontmatter(primary_path / "SKILL.md")
    timestamps = [path.stat().st_mtime for path in paths]
    created_at = datetime.fromtimestamp(min(timestamps))
    updated_at = datetime.fromtimestamp(max(timestamps))

    return SkillDetail(
        id=skill_id,
        name=_display_name(skill_id, metadata),
        description=metadata.get("description", f"{skill_id} skill"),
        category=_category_for_skill(skill_id),
        installed=True,
        enabled=_ENABLED_OVERRIDES.get(skill_id, True),
        version=metadata.get("version", "1.0.0"),
        created_at=created_at,
        updated_at=updated_at,
        installed_at=created_at,
    )


def _load_skills() -> dict[str, SkillDetail]:
    grouped_paths: dict[str, list[Path]] = {}
    for path in _skill_paths():
        grouped_paths.setdefault(_group_skill_id(path.name), []).append(path)

    return {
        skill_id: _build_skill_detail(skill_id, paths)
        for skill_id, paths in sorted(grouped_paths.items())
    }


def _get_skill(skill_id: str) -> SkillDetail:
    skill = _load_skills().get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return skill


@router.get("/all", response_model=BaseResponse[list[SkillSummary]])
async def list_all() -> BaseResponse[list[SkillSummary]]:
    """List all available skills from nanobot/skills."""
    skills = _load_skills().values()
    return BaseResponse[list[SkillSummary]](data=[SkillSummary(**skill.model_dump()) for skill in skills])


@router.get("/installed", response_model=BaseResponse[list[SkillSummary]])
async def list_installed() -> BaseResponse[list[SkillSummary]]:
    """List installed skills only."""
    skills = _load_skills().values()
    return BaseResponse[list[SkillSummary]](data=[SkillSummary(**skill.model_dump()) for skill in skills if skill.installed])


@router.get("/{skill_id}", response_model=BaseResponse[SkillDetail])
async def get_detail(skill_id: str) -> BaseResponse[SkillDetail]:
    """Get dynamically loaded skill detail by id."""
    return BaseResponse[SkillDetail](data=_get_skill(skill_id))


@router.post("/{skill_id}/install")
async def install(skill_id: str) -> BaseResponse[dict]:
    """Built-in skills are loaded from disk and are already installed."""
    _get_skill(skill_id)
    raise HTTPException(status_code=409, detail="Skill already installed")


@router.post("/{skill_id}/uninstall")
async def uninstall(skill_id: str) -> BaseResponse[dict]:
    """Built-in skills cannot be uninstalled through the gateway."""
    _get_skill(skill_id)
    raise HTTPException(status_code=409, detail="Built-in skills cannot be uninstalled")


@router.patch("/{skill_id}", response_model=BaseResponse[SkillDetail])
async def patch_skill(skill_id: str, body: SkillPatchRequest) -> BaseResponse[SkillDetail]:
    """Enable or disable an installed skill."""
    _get_skill(skill_id)
    _ENABLED_OVERRIDES[skill_id] = body.enabled
    return BaseResponse[SkillDetail](data=_get_skill(skill_id))
