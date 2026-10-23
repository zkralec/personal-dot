from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select

from personal_dot.db import SessionLocal
from personal_dot.models import Memory
from personal_dot.schemas import MemorySelection


@dataclass(frozen=True)
class RetrievedMemoryContext:
    text: str | None
    metadata: dict[str, Any]


class MemoryService:
    """Deterministic explicit-memory retrieval with no semantic search."""

    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def retrieve(self, selection: MemorySelection) -> RetrievedMemoryContext:
        selected: list[Memory] = []
        selected_ids: set[uuid.UUID] = set()
        missing_ids: list[str] = []

        with self.session_factory() as session:
            if selection.ids:
                explicit = list(
                    session.scalars(
                        select(Memory).where(
                            Memory.id.in_(selection.ids),
                            Memory.enabled.is_(True),
                        )
                    )
                )
                by_id = {memory.id: memory for memory in explicit}
                for memory_id in selection.ids:
                    memory = by_id.get(memory_id)
                    if memory is None:
                        missing_ids.append(str(memory_id))
                        continue
                    selected.append(memory)
                    selected_ids.add(memory.id)

            if selection.types or selection.tags:
                conditions = [Memory.enabled.is_(True)]
                if selection.types:
                    conditions.append(Memory.type.in_(selection.types))
                if selection.tags:
                    conditions.append(
                        or_(
                            *(
                                Memory.tags.contains([tag])
                                for tag in selection.tags
                            )
                        )
                    )
                if selected_ids:
                    conditions.append(Memory.id.not_in(selected_ids))
                statement = (
                    select(Memory)
                    .where(*conditions)
                    .order_by(Memory.updated_at.desc(), Memory.id)
                    .limit(selection.limit)
                )
                for memory in session.scalars(statement):
                    selected.append(memory)
                    selected_ids.add(memory.id)

        metadata = {
            "strategy": "explicit_v1",
            "selected_ids": [str(memory.id) for memory in selected],
            "selected_types": [memory.type.value for memory in selected],
            "missing_or_disabled_ids": missing_ids,
            "count": len(selected),
        }
        if not selected:
            return RetrievedMemoryContext(text=None, metadata=metadata)

        blocks = [
            (
                f"Memory {index} (id={memory.id}, type={memory.type.value}, "
                f"source={memory.source}):\n{memory.content}"
            )
            for index, memory in enumerate(selected, start=1)
        ]
        return RetrievedMemoryContext(text="\n\n".join(blocks), metadata=metadata)


def get_memory_service() -> MemoryService:
    return MemoryService()
