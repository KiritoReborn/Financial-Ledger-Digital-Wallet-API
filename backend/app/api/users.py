"""User registration (FR-1.1 and FR-1.2)."""

import sqlite3
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from email_validator import validate_email
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth import issue_user_token
from .errors import database_error, error_response

router = APIRouter()


class UserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)
    name: Annotated[str, Field(min_length=1, max_length=100)]
    email: Annotated[str, Field(max_length=254, json_schema_extra={"format": "email"})]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        # Syntax only. Reserved .test domains are valid inputs in the shared API contract.
        normalized = validate_email(
            value.lower(), check_deliverability=False, test_environment=True
        )
        if len(normalized.normalized) > 254:
            raise ValueError("Email is too long")
        return normalized.normalized


class UserCreated(BaseModel):
    id: UUID
    name: str
    email: str
    token: str
    created_at: datetime


@router.post(
    "/users",
    status_code=201,
    response_model=UserCreated,
    operation_id="createUser",
    tags=["users"],
    responses={409: {"description": "Email already registered."}},
)
def create_user(body: UserRequest, request: Request) -> UserCreated | JSONResponse:
    token, digest = issue_user_token()
    user = UserCreated(
        id=uuid4(), name=body.name, email=body.email, token=token, created_at=datetime.now(UTC)
    )
    try:
        with request.app.state.database.transaction() as conn:
            inserted = conn.execute(
                """INSERT INTO users (id, name, email, token_hash, created_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(email) DO NOTHING""",
                (
                    str(user.id),
                    user.name,
                    user.email,
                    digest,
                    user.created_at.isoformat().replace("+00:00", "Z"),
                ),
            ).rowcount
    except sqlite3.Error as error:
        return database_error(error)
    if not inserted:
        return error_response(409, "EMAIL_ALREADY_EXISTS", "Email is already registered.")
    return user
