"""
SQLAlchemy models for SCADA Studio.
"""

from sqlalchemy import Column, Integer, Text, Float, DateTime, ForeignKey, UniqueConstraint
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
    mappings = relationship("DeviceMapping", back_populates="config", cascade="all, delete-orphan")

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


class DeviceMapping(Base):
    """Cross-profile device association: EQ  SC  PE."""
    __tablename__ = "device_mappings"

    id = Column(Integer, primary_key=True)
    substation = Column(Text, nullable=False)
    # EQ profile
    eq_uri = Column(Text)
    eq_name = Column(Text)
    eq_type = Column(Text)
    # SC profile
    sc_device_uri = Column(Text)
    sc_device_name = Column(Text)
    sc_map_name = Column(Text)
    # PE profile
    pe_relay_uri = Column(Text)
    pe_relay_name = Column(Text)
    # Tag matching
    tag_pattern = Column(Text)
    # Provenance
    confidence = Column(Float, default=1.0)
    source = Column(Text, default="manual")
    model_name = Column(Text)
    config_id = Column(Integer, ForeignKey("rtac_configs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    config = relationship("RtacConfig", back_populates="mappings")

    __table_args__ = (
        UniqueConstraint("substation", "eq_uri", "sc_device_uri", name="uq_device_mapping"),
    )
