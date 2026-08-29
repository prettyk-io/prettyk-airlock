"""COS-065: Notification webhook config CRUD API — per domain."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

# In-memory configs — placeholder until notification service is built
_configs: dict[str, list[dict]] = {}


class WebhookConfig(BaseModel):
    id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    channels: list[str] = Field(default_factory=lambda: ["email"])
    enabled: bool = True


@router.get("", response_model=list[WebhookConfig])
async def list_configs(domain_id: str | None = None):
    if domain_id:
        return [WebhookConfig(**c) for c in _configs.get(domain_id, [])]
    result = []
    for cfgs in _configs.values():
        for c in cfgs:
            result.append(WebhookConfig(**c))
    return result


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WebhookConfig)
async def create_config(domain_id: str, body: WebhookConfig):
    _configs.setdefault(domain_id, []).append(body.model_dump())
    return body


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(config_id: str, domain_id: str):
    cfgs = _configs.get(domain_id, [])
    for i, c in enumerate(cfgs):
        if c["id"] == config_id:
            cfgs.pop(i)
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")