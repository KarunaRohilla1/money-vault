from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.schemas import VaultContext
from api.security import AuthError, ExpiredAuthError, verify_access_token


bearer_scheme = HTTPBearer(auto_error=False)


def auth_error(message="Authentication required."):
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "AUTHENTICATION_REQUIRED",
            "message": message
        },
        headers={"WWW-Authenticate": "Bearer"}
    )


def get_authenticated_vault(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)
) -> VaultContext:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise auth_error()

    try:
        return verify_access_token(credentials.credentials)
    except ExpiredAuthError as error:
        raise auth_error("Authentication token expired.") from error
    except AuthError as error:
        raise auth_error("Invalid authentication token.") from error
