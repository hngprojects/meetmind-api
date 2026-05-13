"""v1 API router — composes domain routers under their canonical prefixes/tags."""

from fastapi import APIRouter

from app.api.v1.routes import (
    ask_mind,
    auth,
    candidates,
    dashboard,
    health,
    integrations,
    interviews,
    meetings,
    subscription,
    support,
    users,
    waitlist,
    workspaces,
)

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["Meetings"])
api_router.include_router(interviews.router, prefix="/interviews", tags=["Interviews"])
api_router.include_router(
    integrations.router, prefix="/integrations", tags=["Integrations"]
)
api_router.include_router(ask_mind.router, prefix="/ask-mind", tags=["Ask Mind"])
api_router.include_router(
    subscription.router, prefix="/subscriptions", tags=["Subscriptions"]
)
api_router.include_router(support.router, prefix="/support", tags=["Support"])
api_router.include_router(candidates.router, prefix="/candidates", tags=["Candidates"])
api_router.include_router(waitlist.router, prefix="/waitlist", tags=["Waitlist"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
