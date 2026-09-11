"""Data models for the AI Ship Design Debugger scene."""
from __future__ import annotations

from pydantic import BaseModel, Field


Vec3 = list[float]  # [x, y, z] in meters, Z-up


class Box(BaseModel):
    """Axis-aligned bounding box."""
    min: Vec3
    max: Vec3


class RoomMeta(BaseModel):
    name: str
    units: str = "m"
    up_axis: str = "z"
    room: Box


class Rules(BaseModel):
    min_pipe_clearance_mm: float = 300
    min_pipe_to_pipe_clearance_mm: float = 50
    default_maintenance_clearance_mm: float = 800


class Structure(BaseModel):
    id: str
    name: str
    type: str  # deck | frame | bulkhead ...
    box: Box


class Equipment(BaseModel):
    id: str
    name: str
    type: str  # pump | engine | heat_exchanger | generator ...
    box: Box
    maintenance_clearance_mm: float | None = None


class Pipe(BaseModel):
    id: str
    name: str
    system: str
    diameter_mm: float
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    path: list[Vec3]  # centerline waypoints

    model_config = {"populate_by_name": True}


class Scene(BaseModel):
    meta: RoomMeta
    rules: Rules
    structures: list[Structure]
    equipment: list[Equipment]
    pipes: list[Pipe]
