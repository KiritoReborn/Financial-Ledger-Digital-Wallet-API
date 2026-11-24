import sqlite3

from fastapi.responses import JSONResponse

from ..http import error_response


def database_error(error: Exception) -> JSONResponse:
    sqlite_code = getattr(error, "sqlite_errorcode", 0) or 0
    if isinstance(error, sqlite3.OperationalError) and sqlite_code & 0xFF == sqlite3.SQLITE_BUSY:
        return error_response(503, "DATABASE_BUSY", "Database is busy. Try again later.")
    return error_response(500, "INTERNAL_ERROR", "An internal error occurred.")
