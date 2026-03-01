"""CRUD operations for database models."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_agent.db.models import (
    AgentRun,
    Application,
    ApplicationStatus,
    Job,
    JobStatus,
    MatchResult,
    OutreachMessage,
    OutreachStatus,
    Platform,
    PlatformCredential,
    RunStatus,
)


class JobRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> Job:
        job = Job(**kwargs)
        self.session.add(job)
        self.session.flush()
        return job

    def get_by_id(self, job_id: int) -> Job | None:
        return self.session.get(Job, job_id)

    def get_by_external_id(self, external_id: str, platform: Platform) -> Job | None:
        stmt = select(Job).where(
            Job.external_id == external_id, Job.platform == platform
        )
        return self.session.scalars(stmt).first()

    def exists(self, external_id: str, platform: Platform) -> bool:
        return self.get_by_external_id(external_id, platform) is not None

    def list_by_status(
        self, status: JobStatus, limit: int = 100, offset: int = 0
    ) -> list[Job]:
        stmt = (
            select(Job)
            .where(Job.status == status)
            .order_by(Job.discovered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all())

    def list_queued(self, limit: int = 50) -> list[Job]:
        return self.list_by_status(JobStatus.QUEUED, limit=limit)

    def list_all(
        self,
        platform: Platform | None = None,
        status: JobStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Job]:
        stmt = select(Job)
        if platform:
            stmt = stmt.where(Job.platform == platform)
        if status:
            stmt = stmt.where(Job.status == status)
        stmt = stmt.order_by(Job.discovered_at.desc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt).all())

    def update_status(self, job_id: int, status: JobStatus) -> Job | None:
        job = self.get_by_id(job_id)
        if job:
            job.status = status
            self.session.flush()
        return job

    def count_by_status(self) -> dict[str, int]:
        stmt = select(Job.status, func.count(Job.id)).group_by(Job.status)
        return {status.value: count for status, count in self.session.execute(stmt)}


class MatchResultRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        job_id: int,
        score: float,
        reasoning: str = "",
        matched_skills: list[str] | None = None,
        missing_skills: list[str] | None = None,
        role_fit: str = "",
        red_flags: list[str] | None = None,
    ) -> MatchResult:
        result = MatchResult(
            job_id=job_id,
            score=score,
            reasoning=reasoning,
            matched_skills=json.dumps(matched_skills or []),
            missing_skills=json.dumps(missing_skills or []),
            role_fit=role_fit,
            red_flags=json.dumps(red_flags or []),
        )
        self.session.add(result)
        self.session.flush()
        return result

    def get_by_job_id(self, job_id: int) -> MatchResult | None:
        stmt = select(MatchResult).where(MatchResult.job_id == job_id)
        return self.session.scalars(stmt).first()


class ApplicationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, job_id: int, **kwargs) -> Application:
        app = Application(job_id=job_id, **kwargs)
        self.session.add(app)
        self.session.flush()
        return app

    def get_by_job_id(self, job_id: int) -> Application | None:
        stmt = select(Application).where(Application.job_id == job_id)
        return self.session.scalars(stmt).first()

    def update_status(
        self, app_id: int, status: ApplicationStatus, **kwargs
    ) -> Application | None:
        app = self.session.get(Application, app_id)
        if app:
            app.status = status
            for key, value in kwargs.items():
                setattr(app, key, value)
            self.session.flush()
        return app

    def list_all(self, status: ApplicationStatus | None = None, limit: int = 100) -> list[Application]:
        stmt = select(Application)
        if status:
            stmt = stmt.where(Application.status == status)
        stmt = stmt.order_by(Application.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def count_today(self, platform: Platform) -> int:
        today = datetime.now(timezone.utc).date()
        stmt = (
            select(func.count(Application.id))
            .join(Job)
            .where(
                Job.platform == platform,
                Application.applied_at >= datetime(
                    today.year, today.month, today.day, tzinfo=timezone.utc
                ),
            )
        )
        return self.session.scalar(stmt) or 0


class OutreachRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> OutreachMessage:
        msg = OutreachMessage(**kwargs)
        self.session.add(msg)
        self.session.flush()
        return msg

    def exists_for_recipient(self, recipient_profile_url: str) -> bool:
        stmt = select(OutreachMessage).where(
            OutreachMessage.recipient_profile_url == recipient_profile_url
        )
        return self.session.scalars(stmt).first() is not None

    def list_pending_follow_ups(self) -> list[OutreachMessage]:
        now = datetime.now(timezone.utc)
        stmt = select(OutreachMessage).where(
            OutreachMessage.status == OutreachStatus.ACCEPTED,
            OutreachMessage.follow_up_at <= now,
        )
        return list(self.session.scalars(stmt).all())

    def get_by_id(self, message_id: int) -> OutreachMessage | None:
        return self.session.get(OutreachMessage, message_id)

    def list_drafted_emails(self, limit: int = 100) -> list[OutreachMessage]:
        stmt = (
            select(OutreachMessage)
            .where(
                OutreachMessage.message_type == "email",
                OutreachMessage.status == OutreachStatus.DRAFTED,
            )
            .order_by(OutreachMessage.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def mark_as_sent(self, message_id: int) -> OutreachMessage | None:
        msg = self.get_by_id(message_id)
        if msg:
            msg.status = OutreachStatus.SENT
            msg.sent_at = datetime.now(timezone.utc)
            self.session.flush()
        return msg

    def exists_email_for_job(self, job_id: int, recipient_name: str) -> bool:
        stmt = select(OutreachMessage).where(
            OutreachMessage.related_job_id == job_id,
            OutreachMessage.recipient_name == recipient_name,
            OutreachMessage.message_type == "email",
        )
        return self.session.scalars(stmt).first() is not None

    def delete(self, message_id: int) -> bool:
        msg = self.get_by_id(message_id)
        if msg:
            self.session.delete(msg)
            self.session.flush()
            return True
        return False

    def list_all(self, limit: int = 100) -> list[OutreachMessage]:
        stmt = (
            select(OutreachMessage)
            .order_by(OutreachMessage.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def count_today(self, platform: Platform) -> int:
        today = datetime.now(timezone.utc).date()
        stmt = (
            select(func.count(OutreachMessage.id))
            .where(
                OutreachMessage.platform == platform,
                OutreachMessage.sent_at >= datetime(
                    today.year, today.month, today.day, tzinfo=timezone.utc
                ),
            )
        )
        return self.session.scalar(stmt) or 0


class CredentialRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(
        self, platform: Platform, username: str, encrypted_password: str
    ) -> PlatformCredential:
        stmt = select(PlatformCredential).where(
            PlatformCredential.platform == platform
        )
        cred = self.session.scalars(stmt).first()
        if cred:
            cred.username = username
            cred.encrypted_password = encrypted_password
        else:
            cred = PlatformCredential(
                platform=platform,
                username=username,
                encrypted_password=encrypted_password,
            )
            self.session.add(cred)
        self.session.flush()
        return cred

    def get(self, platform: Platform) -> PlatformCredential | None:
        stmt = select(PlatformCredential).where(
            PlatformCredential.platform == platform
        )
        return self.session.scalars(stmt).first()


class AgentRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, **kwargs) -> AgentRun:
        run = AgentRun(**kwargs)
        self.session.add(run)
        self.session.flush()
        return run

    def finish(
        self, run_id: int, status: RunStatus = RunStatus.COMPLETED, **kwargs
    ) -> AgentRun | None:
        run = self.session.get(AgentRun, run_id)
        if run:
            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            for key, value in kwargs.items():
                setattr(run, key, value)
            self.session.flush()
        return run

    def get_latest(self, limit: int = 10) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .order_by(AgentRun.started_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
