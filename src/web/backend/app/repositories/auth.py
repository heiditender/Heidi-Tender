from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from ..models import AuditLog, AuthProvider, MagicLinkToken, User, UserIdentity, UserSession


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_user(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.primary_email == email)
        return self.db.scalars(stmt).first()

    def get_identity(self, provider: AuthProvider, provider_subject: str) -> UserIdentity | None:
        stmt = (
            select(UserIdentity)
            .options(joinedload(UserIdentity.user))
            .where(UserIdentity.provider == provider, UserIdentity.provider_subject == provider_subject)
        )
        return self.db.scalars(stmt).first()

    def create_user(
        self,
        *,
        email: str,
        display_name: str | None,
        avatar_url: str | None,
        email_verified: bool,
    ) -> User:
        user = User(
            primary_email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            email_verified=email_verified,
            last_login_at=utc_now(),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def create_or_link_identity(
        self,
        *,
        provider: AuthProvider,
        provider_subject: str,
        email: str,
        email_verified: bool,
        display_name: str | None,
        avatar_url: str | None,
    ) -> tuple[User, UserIdentity, bool]:
        identity = self.get_identity(provider, provider_subject)
        linked_existing = False
        if identity is not None:
            user = identity.user
        else:
            user = self.get_user_by_email(email)
            if user is None:
                user = User(
                    primary_email=email,
                    display_name=display_name,
                    avatar_url=avatar_url,
                    email_verified=email_verified,
                    last_login_at=utc_now(),
                )
                self.db.add(user)
                self.db.flush()
            else:
                linked_existing = True

            identity = UserIdentity(
                user_id=user.id,
                provider=provider,
                provider_subject=provider_subject,
            )

        user.primary_email = email
        user.display_name = display_name or user.display_name
        user.avatar_url = avatar_url or user.avatar_url
        user.email_verified = email_verified
        user.last_login_at = utc_now()

        identity.email = email
        identity.email_verified = email_verified
        identity.display_name = display_name
        identity.avatar_url = avatar_url
        identity.last_login_at = utc_now()
        self.db.add(user)
        self.db.add(identity)
        self.db.commit()
        self.db.refresh(user)
        self.db.refresh(identity)
        return user, identity, linked_existing

    def create_session(
        self,
        *,
        user_id: str,
        token_hash_value: str,
        idle_timeout_seconds: int,
        absolute_timeout_seconds: int,
        created_ip: str | None,
        user_agent: str | None,
    ) -> UserSession:
        now = utc_now()
        session = UserSession(
            user_id=user_id,
            token_hash=token_hash_value,
            last_used_at=now,
            idle_expires_at=now + timedelta(seconds=idle_timeout_seconds),
            absolute_expires_at=now + timedelta(seconds=absolute_timeout_seconds),
            created_ip=created_ip,
            user_agent=user_agent,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session_by_token_hash(self, token_hash_value: str) -> UserSession | None:
        stmt = (
            select(UserSession)
            .options(joinedload(UserSession.user))
            .where(UserSession.token_hash == token_hash_value)
        )
        return self.db.scalars(stmt).first()

    def is_session_expired(self, session: UserSession) -> bool:
        now = utc_now()
        if session.revoked_at is not None:
            return True
        return session.idle_expires_at <= now or session.absolute_expires_at <= now

    def touch_session(self, session: UserSession, *, idle_timeout_seconds: int) -> UserSession:
        now = utc_now()
        session.last_used_at = now
        next_idle_expiry = now + timedelta(seconds=idle_timeout_seconds)
        if next_idle_expiry < session.absolute_expires_at:
            session.idle_expires_at = next_idle_expiry
        else:
            session.idle_expires_at = session.absolute_expires_at
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def revoke_session(self, session: UserSession) -> UserSession:
        if session.revoked_at is None:
            session.revoked_at = utc_now()
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)
        return session

    def create_magic_link_token(
        self,
        *,
        email: str,
        token_hash_value: str,
        next_path: str | None,
        requested_ip: str | None,
        ttl_seconds: int,
    ) -> MagicLinkToken:
        row = MagicLinkToken(
            email=email,
            token_hash=token_hash_value,
            next_path=next_path,
            requested_ip=requested_ip,
            expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_magic_link_by_hash(self, token_hash_value: str) -> MagicLinkToken | None:
        stmt = select(MagicLinkToken).where(MagicLinkToken.token_hash == token_hash_value)
        return self.db.scalars(stmt).first()

    def consume_magic_link(self, token_hash_value: str) -> MagicLinkToken | None:
        row = self.get_magic_link_by_hash(token_hash_value)
        if row is None:
            return None
        now = utc_now()
        if row.used_at is not None or row.expires_at <= now:
            return None
        row.used_at = now
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def log_event(
        self,
        *,
        event_type: str,
        actor_user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        email: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        payload: dict | None = None,
    ) -> AuditLog:
        row = AuditLog(
            actor_user_id=actor_user_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            email=email,
            ip_address=ip_address,
            user_agent=user_agent,
            payload=payload or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def count_recent_events(
        self,
        *,
        event_type: str,
        email: str | None = None,
        ip_address: str | None = None,
        since: datetime,
    ) -> int:
        stmt: Select[tuple[int]] = select(func.count(AuditLog.id)).where(
            AuditLog.event_type == event_type,
            AuditLog.created_at >= since,
        )
        if email is not None:
            stmt = stmt.where(AuditLog.email == email)
        if ip_address is not None:
            stmt = stmt.where(AuditLog.ip_address == ip_address)
        return int(self.db.scalar(stmt) or 0)
