from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunStatusEnum(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    webhook_slug: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    graph_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    runs: Mapped[list["Run"]] = relationship("Run", back_populates="workflow")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[RunStatusEnum] = mapped_column(Enum(RunStatusEnum), default=RunStatusEnum.pending, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    trigger_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trigger_payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    outputs_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="runs")
    node_runs: Mapped[list["NodeRun"]] = relationship("NodeRun", back_populates="run")
    logs: Mapped[list["Log"]] = relationship("Log", back_populates="run")


class NodeRun(Base):
    __tablename__ = "node_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    input_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    output_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    run: Mapped[Run] = relationship("Run", back_populates="node_runs")

    __table_args__ = (
        Index("ix_node_runs_run_id_node_id", "run_id", "node_id", unique=False),
    )


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    run: Mapped[Run] = relationship("Run", back_populates="logs")

    __table_args__ = (
        Index("ix_logs_run_id_ts", "run_id", "ts"),
    )
