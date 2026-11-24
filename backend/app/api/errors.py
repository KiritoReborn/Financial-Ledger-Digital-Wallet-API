import sqlite3

from fastapi.responses import JSONResponse


def error_response(status: int, code: str, message: str, headers=None) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if status != 500:
        error["details"] = None
    return JSONResponse(status_code=status, content={"error": error}, headers=headers)


def database_error(error: Exception) -> JSONResponse:
    sqlite_code = getattr(error, "sqlite_errorcode", 0) or 0
    if isinstance(error, sqlite3.OperationalError) and sqlite_code & 0xFF == sqlite3.SQLITE_BUSY:
        return error_response(503, "DATABASE_BUSY", "Database is busy. Try again later.")
    return error_response(500, "INTERNAL_ERROR", "An internal error occurred.")
