"""
SQLAlchemy models for SCADA Studio.
"""

from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime, timezone


class Base(DeclarativeBase):
    pass


class RtacConfig(Base):
    __tablename__ = "rtac_configs"

    id = Column(Integer, primary_key=True)
    repo = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    commit_sha = Column(Text, nullable=False)
    device_name = Column(Text)
    parsed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    metadata_ = Column("metadata", JSONB, default=dict)

    points = relationship("Point", back_populates="config", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("repo", "file_path", "commit_sha", name="uq_config_version"),
    )


class Point(Base):
    __tablename__ = "points"

    id = Column(Integer, primary_key=True)
    config_id = Column(Integer, ForeignKey("rtac_configs.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    address = Column(Text)
    point_type = Column(Text)
    data_type = Column(Text)
    description = Column(Text)
    source_tag = Column(Text)
    destination_tag = Column(Text)
    extra = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    config = relationship("RtacConfig", back_populates="points")
