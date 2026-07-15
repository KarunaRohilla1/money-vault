from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.accounts import router as accounts_router
from api.auth import router as auth_router
from api.categories import router as categories_router
from api.config import ApiConfigError, get_config
from api.dashboard import router as dashboard_router
from api.planning import router as planning_router
from api.reports import router as reports_router
from api.transactions import router as transactions_router
from api.transfers import router as transfers_router
from api.wishlist import router as wishlist_router
from api.schemas import HealthResponse


def error_response(status_code, code, message):
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message
        }
    )


def create_app():
    app = FastAPI(
        title="Money Vault API",
        version="1.0.0"
    )

    try:
        config = get_config()
    except ApiConfigError:
        config = None

    if config and config.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"]
        )

    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(accounts_router)
    app.include_router(categories_router)
    app.include_router(planning_router)
    app.include_router(reports_router)
    app.include_router(transactions_router)
    app.include_router(transfers_router)
    app.include_router(wishlist_router)

    @app.get("/health", response_model=HealthResponse)
    def health():
        return HealthResponse(status="ok")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, _exc: RequestValidationError):
        return error_response(422, "VALIDATION_ERROR", "Request validation failed.")

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "message" in exc.detail:
            content = {
                "code": exc.detail.get("code", "REQUEST_FAILED"),
                "message": exc.detail["message"]
            }
        else:
            content = {
                "code": "REQUEST_FAILED",
                "message": "Request failed."
            }
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(_request: Request, _exc: Exception):
        return error_response(500, "SERVER_ERROR", "Unexpected server error.")

    return app


app = create_app()
