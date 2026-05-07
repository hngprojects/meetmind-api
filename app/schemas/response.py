from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class APIResponse(BaseModel, Generic[T]):
    status_code: int
    message: str
    data: T | None = None


class PaginatedResponse(APIResponse[list[T]], Generic[T]):
    pagination: PaginationMeta | None = None