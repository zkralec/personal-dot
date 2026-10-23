import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_dot.db import get_db
from personal_dot.models import Memory, MemoryType
from personal_dot.schemas import MemoryCreate, MemoryRead, MemoryUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memories", tags=["memories"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory(request: MemoryCreate, db: DatabaseSession) -> Memory:
    memory = Memory(
        type=request.type,
        content=request.content,
        source=request.source,
        enabled=request.enabled,
        tags=request.tags,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    logger.info(
        "Memory created",
        extra={
            "event": "memory_created",
            "memory_id": str(memory.id),
            "memory_type": memory.type.value,
        },
    )
    return memory


@router.get("", response_model=list[MemoryRead])
def list_memories(
    db: DatabaseSession,
    memory_type: Annotated[MemoryType | None, Query(alias="type")] = None,
    tag: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=50,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9:_-]*$",
        ),
    ] = None,
    enabled: Annotated[bool | None, Query()] = None,
    source: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Memory]:
    conditions = []
    if memory_type is not None:
        conditions.append(Memory.type == memory_type)
    if tag is not None:
        conditions.append(Memory.tags.contains([tag.lower()]))
    if enabled is not None:
        conditions.append(Memory.enabled.is_(enabled))
    if source is not None:
        conditions.append(Memory.source == source)
    statement = (
        select(Memory)
        .where(*conditions)
        .order_by(Memory.updated_at.desc(), Memory.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement))


@router.get("/{memory_id}", response_model=MemoryRead)
def get_memory(memory_id: uuid.UUID, db: DatabaseSession) -> Memory:
    memory = db.get(Memory, memory_id)
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="memory not found"
        )
    return memory


@router.patch("/{memory_id}", response_model=MemoryRead)
def update_memory(
    memory_id: uuid.UUID, request: MemoryUpdate, db: DatabaseSession
) -> Memory:
    memory = db.scalar(
        select(Memory).where(Memory.id == memory_id).with_for_update()
    )
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="memory not found"
        )
    updates = request.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(memory, field, value)
    db.commit()
    db.refresh(memory)
    logger.info(
        "Memory updated",
        extra={
            "event": "memory_updated",
            "memory_id": str(memory.id),
            "memory_type": memory.type.value,
        },
    )
    return memory


@router.post("/{memory_id}/disable", response_model=MemoryRead)
def disable_memory(memory_id: uuid.UUID, db: DatabaseSession) -> Memory:
    memory = db.scalar(
        select(Memory).where(Memory.id == memory_id).with_for_update()
    )
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="memory not found"
        )
    memory.enabled = False
    db.commit()
    db.refresh(memory)
    logger.info(
        "Memory disabled",
        extra={"event": "memory_disabled", "memory_id": str(memory.id)},
    )
    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: uuid.UUID, db: DatabaseSession) -> Response:
    memory = db.scalar(
        select(Memory).where(Memory.id == memory_id).with_for_update()
    )
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="memory not found"
        )
    db.delete(memory)
    db.commit()
    logger.info(
        "Memory deleted",
        extra={"event": "memory_deleted", "memory_id": str(memory_id)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
