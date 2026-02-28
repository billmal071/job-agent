"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Platform(PyEnum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"


class JobStatus(PyEnum):
    DISCOVERED = "discovered"
    MATCHED = "matched"
    QUEUED = "queued"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    APPLY_FAILED = "apply_failed"
    SKIPPED = "skipped"


class ApplicationStatus(PyEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    WITHDRAWN = "withdrawn"


class OutreachStatus(PyEnum):
    PENDING = "pending"
    SENT = "sent"
    ACCEPTED = "accepted"
    REPLIED = "replied"
    FOLLOW_UP_SENT = "follow_up_sent"
    FAILED = "failed"


class RunStatus(PyEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(2048), default="")
    salary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    easy_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.DISCOVERED
    )
    profile_name: Mapped[str] = mapped_column(String(255), default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    match_result: Mapped[MatchResult | None] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    application: Mapped[Application | None] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Job {self.id}: {self.title} @ {self.company}>"


class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    score: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    matched_skills: Mapped[str] = mapped_column(Text, default="")  # JSON list
    missing_skills: Mapped[str] = mapped_column(Text, default="")  # JSON list
    role_fit: Mapped[str] = mapped_column(Text, default="")
    red_flags: Mapped[str] = mapped_column(Text, default="")  # JSON list
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    job: Mapped[Job] = relationship(back_populates="match_result")

    def __repr__(self) -> str:
        return f"<MatchResult job_id={self.job_id} score={self.score}>"


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.PENDING
    )
    resume_path: Mapped[str] = mapped_column(String(1024), default="")
    cover_letter_path: Mapped[str] = mapped_column(String(1024), default="")
    screenshot_path: Mapped[str] = mapped_column(String(1024), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    job: Mapped[Job] = relationship(back_populates="application")

    def __repr__(self) -> str:
        return f"<Application job_id={self.job_id} status={self.status.value}>"


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    recipient_name: Mapped[str] = mapped_column(String(255))
    recipient_title: Mapped[str] = mapped_column(String(255), default="")
    recipient_company: Mapped[str] = mapped_column(String(255), default="")
    recipient_profile_url: Mapped[str] = mapped_column(String(2048), default="")
    message_type: Mapped[str] = mapped_column(String(50))  # connection, inmail
    message_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[OutreachStatus] = mapped_column(
        Enum(OutreachStatus), default=OutreachStatus.PENDING
    )
    related_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    def __repr__(self) -> str:
        return f"<OutreachMessage {self.recipient_name} ({self.status.value})>"


class PlatformCredential(Base):
    __tablename__ = "platform_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform), unique=True)
    username: Mapped[str] = mapped_column(String(255))
    encrypted_password: Mapped[str] = mapped_column(Text)
    extra_data: Mapped[str] = mapped_column(Text, default="")  # JSON encrypted blob
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<PlatformCredential {self.platform.value}>"


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), default=RunStatus.RUNNING
    )
    profile_name: Mapped[str] = mapped_column(String(255), default="")
    platform: Mapped[str] = mapped_column(String(50), default="")
    jobs_discovered: Mapped[int] = mapped_column(Integer, default=0)
    jobs_matched: Mapped[int] = mapped_column(Integer, default=0)
    jobs_applied: Mapped[int] = mapped_column(Integer, default=0)
    jobs_queued: Mapped[int] = mapped_column(Integer, default=0)
    jobs_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<AgentRun {self.id} ({self.status.value})>"
