import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import inspect

from app.models.interview import Interview, Candidate
from app.models.user import User
from app.models.workspace import WorkspaceMember, Workspace
from app.services.auth import AuthService
from app.services.calendar import format_time_display, compute_available_slots

def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

async def create_ws_user(db: AsyncSession, email: str, role: str = "owner", name: str = "Test") -> tuple[User, str, uuid.UUID]:
    u = User(email=email, name=name, is_verified=True)
    db.add(u)
    await db.flush()
    ws = Workspace(name="WS", created_by=u.id)
    db.add(ws)
    await db.flush()
    wm = WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=role)
    db.add(wm)
    await db.commit()
    t = await AuthService.create_access_token(u)
    return u, t, ws.id

async def seed_interview(
        db: AsyncSession, 
        u_id: uuid.UUID, 
        ws_id: uuid.UUID, 
        offset_hrs: int = 24, 
        status: str = "scheduled", 
        start_time: datetime | None = None
    ):
    c = Candidate(workspace_id=ws_id, full_name="John Doe", email="john@example.com")
    db.add(c)
    await db.flush()
    start = start_time or datetime.now(timezone.utc) + timedelta(hours=offset_hrs)
    end = start + timedelta(minutes=30)
    
    i = Interview(
        workspace_id=ws_id, 
        candidate_id=c.id, 
        interviewer_id=u_id, 
        role_title="Dev", 
        status=status, 
        scheduled_start=start, 
        scheduled_end=end
    )
    db.add(i)
    await db.commit()
    return i

class TestCalendarCore:
    # ── C1 BEHAVIORS ──
    @pytest.mark.anyio
    async def test_unauth_blocked(self, client: AsyncClient):
        assert (await client.get("/api/v1/calendar/appointments")).status_code == 401
        assert (await client.get("/api/v1/calendar/users")).status_code == 401
        assert (await client.get("/api/v1/calendar/availability?date=2026-01-01")).status_code == 401

    @pytest.mark.anyio
    async def test_rescheduled_at_exists(self, db_session: AsyncSession):
        async with db_session.bind.connect() as conn:
            cols = await conn.run_sync(lambda c: [col['name'] for col in inspect(c).get_columns('interviews')])
            assert "rescheduled_at" in cols

    # ── C2 BEHAVIORS ──
    @pytest.mark.anyio
    async def test_appointments_success_and_scoping(self, client: AsyncClient, db_session: AsyncSession):
        u1, t1, w1 = await create_ws_user(db_session, "a@b.com")
        u2, t2, w2 = await create_ws_user(db_session, "x@y.com")
        await seed_interview(db_session, u1.id, w1, offset_hrs=24) # U1 tomorrow
        await seed_interview(db_session, u2.id, w2, offset_hrs=24) # U2 tomorrow
        
        res = await client.get("/api/v1/calendar/appointments", headers=auth_headers(t1))
        data = res.json()["data"]
        assert len(data["appointments"]) == 1 # Behavior 1 & 2 (Workspace isolation)
        
    @pytest.mark.anyio
    async def test_appointment_filters(self, client: AsyncClient, db_session: AsyncSession):
        u, t, w = await create_ws_user(db_session, "f@b.com")
        await seed_interview(db_session, u.id, w, offset_hrs=1) # Today
        await seed_interview(db_session, u.id, w, offset_hrs=48) # Future
        await seed_interview(db_session, u.id, w, offset_hrs=-24) # Past
        
        res_today = await client.get("/api/v1/calendar/appointments?filter=today", headers=auth_headers(t))
        assert len(res_today.json()["data"]["appointments"]) == 1 # Behavior 3
        
        res_up = await client.get("/api/v1/calendar/appointments?filter=all_upcoming", headers=auth_headers(t))
        assert len(res_up.json()["data"]["appointments"]) == 2 # Behavior 4 (Excludes past)
        
        target = (datetime.now(timezone.utc) + timedelta(hours=48)).strftime("%Y-%m-%d")
        res_date = await client.get(f"/api/v1/calendar/appointments?date={target}", headers=auth_headers(t))
        assert len(res_date.json()["data"]["appointments"]) == 1 # Behavior 5

    @pytest.mark.anyio
    async def test_appointment_empty_state_and_formatter(self, client: AsyncClient, db_session: AsyncSession):
        u, t, w = await create_ws_user(db_session, "e@b.com")
        res = await client.get("/api/v1/calendar/appointments?filter=today", headers=auth_headers(t))
        assert res.json()["data"]["appointments"] == []
        assert "scheduled for this day" in res.json()["data"]["message"] # Behavior 6
        
        now = datetime.now(timezone.utc)
        assert format_time_display(now, now).startswith("Today") # Behavior 7
        assert format_time_display(now+timedelta(days=1), now).startswith("Tomorrow")

    # ── C3 BEHAVIORS ──
    @pytest.mark.anyio
    async def test_users_list(self, client: AsyncClient, db_session: AsyncSession):
        u1, t1, w1 = await create_ws_user(db_session, "1@c.com", role="owner", name="Frank Udoho")
        u2 = User(email="2@c.com", name="Amara Nwosu"); db_session.add(u2); await db_session.flush()
        db_session.add(WorkspaceMember(workspace_id=w1, user_id=u2.id, role="member"))
        await db_session.commit()
        
        res = await client.get("/api/v1/calendar/users", headers=auth_headers(t1))
        users = res.json()["data"]
        assert len(users) == 2 # Behavior 1
        
        res_search = await client.get("/api/v1/calendar/users?search=frank", headers=auth_headers(t1))
        assert len(res_search.json()["data"]) == 1 # Behavior 3
        
        res_role = await client.get("/api/v1/calendar/users?role=member", headers=auth_headers(t1))
        assert res_role.json()["data"][0]["name"] == "Amara Nwosu" # Behavior 4
        
        fu = [x for x in users if x["name"] == "Frank Udoho"][0]
        assert fu["avatar_initials"] == "FU" # Behavior 5
        assert fu["avatar_color"] == users[0]["avatar_color"] # Behavior 6

    # ── C4 BEHAVIORS ──
    def test_availability_pure_function(self):
        date_tmrw = (datetime.now(timezone.utc) + timedelta(days=1)).date()
        date_past = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        
        assert len(compute_available_slots([], date_tmrw)) == 20 # Behavior 1
        assert len(compute_available_slots([], date_past)) == 0  # Behavior 4
        
        start = datetime.combine(date_tmrw, datetime.min.time()).replace(tzinfo=timezone.utc) + timedelta(hours=8)
        slots = compute_available_slots([(start, start+timedelta(minutes=30))], date_tmrw)
        assert len(slots) == 19 # Behavior 2

    @pytest.mark.anyio
    async def test_availability_endpoint(self, client: AsyncClient, db_session: AsyncSession):
        u, t, w = await create_ws_user(db_session, "av@c.com")
        
        # Calculate tomorrow at exactly 10:00 AM UTC
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
        fixed_start = datetime.combine(tomorrow, datetime.min.time()).replace(tzinfo=timezone.utc) + timedelta(hours=10)

        # Seed interviews at exactly 10:00 AM to ensure it falls within the 08:00-18:00 window
        await seed_interview(db_session, u.id, w, start_time=fixed_start) # Active
        await seed_interview(db_session, u.id, w, start_time=fixed_start, status="cancelled") # Cancelled
        
        target = tomorrow.strftime("%Y-%m-%d")
        res = await client.get(f"/api/v1/calendar/availability?date={target}", headers=auth_headers(t))
        
        # Now it will consistently block exactly 1 slot (10:00 - 10:30), leaving 19.
        assert len(res.json()["data"]) == 19