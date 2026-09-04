"""Scenarios: named avatar configurations, each served at its own link.

A scenario bundles the rules that scope the conversation, a dataset the model may quote
from, the voice and language it speaks in, and the MCP servers whose tools it may call.

Public endpoints return presentation only. Rules, datasets and tool lists never reach a
browser: they decide what the model does, so a visitor who could read or rewrite them
could make the avatar say anything.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from apps.api.admin import is_protected, require_admin
from apps.api.db import connect, json_column

router = APIRouter(tags=["scenarios"])

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class Scenario(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    language: str = Field(default="en-US", max_length=16)
    voice: str | None = Field(default=None, max_length=128)
    avatar: str | None = Field(default=None, max_length=2000)
    greeting: str = Field(default="", max_length=1000)
    rules: str = Field(default="", max_length=20000)
    data: dict = Field(default_factory=dict)
    mcp: list[str] = Field(default_factory=list)
    tools: list[str] | None = None
    model: str | None = Field(default=None, max_length=128)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    published: bool = True


class ScenarioSummary(BaseModel):
    """What a visitor is allowed to know: presentation, never rules, data, or tools."""

    slug: str
    name: str
    description: str
    language: str
    voice: str | None = None
    avatar: str | None = None
    greeting: str = ""
    speed: float = 1.0


class ScenariosResponse(BaseModel):
    scenarios: list[ScenarioSummary]


class AdminScenariosResponse(BaseModel):
    scenarios: list[Scenario]
    protected: bool


def _row_to_scenario(row) -> Scenario:
    return Scenario(
        slug=row["slug"],
        name=row["name"],
        description=row["description"],
        language=row["language"],
        voice=row["voice"],
        avatar=row["avatar"],
        greeting=row["greeting"],
        rules=row["rules"],
        data=json_column(row, "data", {}),
        mcp=json_column(row, "mcp", []),
        tools=json_column(row, "tools", None),
        model=row["model"],
        speed=row["speed"],
        published=bool(row["published"]),
    )


def load_scenarios(*, include_unpublished: bool = False) -> dict[str, Scenario]:
    query = "SELECT * FROM scenarios"
    if not include_unpublished:
        query += " WHERE published = 1"
    query += " ORDER BY name"

    with connect() as connection:
        rows = connection.execute(query).fetchall()
    return {row["slug"]: _row_to_scenario(row) for row in rows}


def get_scenario(slug: str, *, include_unpublished: bool = True) -> Scenario:
    scenario = load_scenarios(include_unpublished=include_unpublished).get(slug)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{slug}'.")
    return scenario


def save_scenario(scenario: Scenario) -> Scenario:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO scenarios
                (slug, name, description, language, voice, avatar, greeting, rules, data, mcp, tools,
                 model, speed, published)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name, description = excluded.description, language = excluded.language,
                voice = excluded.voice, avatar = excluded.avatar, greeting = excluded.greeting,
                rules = excluded.rules, data = excluded.data, mcp = excluded.mcp, tools = excluded.tools,
                model = excluded.model, speed = excluded.speed, published = excluded.published,
                updated_at = datetime('now')
            """,
            (
                scenario.slug,
                scenario.name,
                scenario.description,
                scenario.language,
                scenario.voice,
                scenario.avatar,
                scenario.greeting,
                scenario.rules,
                json.dumps(scenario.data, ensure_ascii=False),
                json.dumps(scenario.mcp),
                json.dumps(scenario.tools) if scenario.tools is not None else None,
                scenario.model,
                scenario.speed,
                int(scenario.published),
            ),
        )
    return scenario


def _summarize(scenario: Scenario) -> ScenarioSummary:
    return ScenarioSummary(**scenario.model_dump(include=set(ScenarioSummary.model_fields)))


def _check_servers_exist(scenario: Scenario) -> None:
    from apps.api.mcp_registry import load_servers

    known = load_servers()
    missing = [name for name in scenario.mcp if name not in known]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown MCP server(s): {', '.join(missing)}. Register them first.",
        )


@router.get("/scenarios", response_model=ScenariosResponse)
def list_scenarios() -> ScenariosResponse:
    return ScenariosResponse(scenarios=[_summarize(s) for s in load_scenarios().values()])


@router.get("/scenarios/{slug}", response_model=ScenarioSummary)
def read_scenario(slug: str) -> ScenarioSummary:
    return _summarize(get_scenario(slug))


@router.get("/admin/scenarios", response_model=AdminScenariosResponse)
def admin_list_scenarios(_: None = Depends(require_admin)) -> AdminScenariosResponse:
    scenarios = load_scenarios(include_unpublished=True)
    return AdminScenariosResponse(scenarios=list(scenarios.values()), protected=is_protected())


@router.get("/admin/scenarios/{slug}", response_model=Scenario)
def admin_read_scenario(slug: str, _: None = Depends(require_admin)) -> Scenario:
    return get_scenario(slug)


@router.put("/admin/scenarios/{slug}", response_model=Scenario)
def admin_upsert_scenario(slug: str, scenario: Scenario, _: None = Depends(require_admin)) -> Scenario:
    if slug != scenario.slug:
        raise HTTPException(status_code=422, detail="The slug in the path and body must match.")
    _check_servers_exist(scenario)
    return save_scenario(scenario)


@router.delete("/admin/scenarios/{slug}", status_code=204, response_class=Response)
def admin_delete_scenario(slug: str, _: None = Depends(require_admin)) -> Response:
    with connect() as connection:
        deleted = connection.execute("DELETE FROM scenarios WHERE slug = ?", (slug,)).rowcount
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{slug}'.")
    return Response(status_code=204)


@router.post("/admin/scenarios/{slug}/duplicate", response_model=Scenario)
def admin_duplicate_scenario(slug: str, _: None = Depends(require_admin)) -> Scenario:
    """Copy a scenario under a free slug — the fastest way to start from a working one."""
    original = get_scenario(slug)
    existing = load_scenarios(include_unpublished=True)

    suffix = 2
    while f"{slug}-{suffix}" in existing:
        suffix += 1

    copy = original.model_copy(
        update={"slug": f"{slug}-{suffix}", "name": f"{original.name} (copy)", "published": False}
    )
    return save_scenario(copy)


def scenario_from_dict(slug: str, payload: dict[str, Any]) -> Scenario:
    """Build a scenario from a JSON document, used for seeding and import."""
    return Scenario(**{"slug": slug, **payload})
