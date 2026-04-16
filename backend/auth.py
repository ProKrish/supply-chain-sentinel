"""
Supply Chain Sentinel - Authentication Module

Handles JWT token verification using Auth0.
Provides dependency functions for protecting API endpoints
with role-based access control (RBAC).
"""

from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import HTTPException, Security, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import os
import json
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Auth0 configuration
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE")

# JWKS endpoint for public key discovery
JWKS_URL = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"

# Token issuer URL for validation
ISSUER = f"https://{AUTH0_DOMAIN}/"

# Custom namespace for role claims in JWT tokens
ROLES_NAMESPACE = "https://supply-chain-sentinel/roles"

# HTTP Bearer security scheme
security = HTTPBearer()

# Module-level cache for JWKS to avoid repeated network calls
_jwks_cache = None


def get_jwks() -> dict:
    """
    Fetch and cache the JSON Web Key Set (JWKS) from Auth0.

    The JWKS contains public keys used to verify JWT signatures.
    Results are cached in a module-level variable to avoid
    redundant network requests.

    Returns:
        dict: The JWKS containing public keys.

    Raises:
        HTTPException: 500 if unable to fetch JWKS.
    """
    global _jwks_cache

    if _jwks_cache is not None:
        return _jwks_cache

    try:
        with httpx.Client() as client:
            response = client.get(JWKS_URL, timeout=10.0)
            response.raise_for_status()
            _jwks_cache = response.json()
            return _jwks_cache
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to fetch JWKS: {str(e)}"
        )


def get_rsa_key(token: str) -> dict | None:
    """
    Extract the RSA public key from JWKS matching the token's key ID.

    Parses the token header to get the 'kid' (key ID), then finds
    the corresponding key in the JWKS and converts it to an RSA key.

    Args:
        token: The raw JWT string.

    Returns:
        dict: RSA key in JWK format for jose, or None if no match.
    """
    try:
        unverified_header = jwt.get_unverified_headers(token)
    except JWTError:
        return None

    kid = unverified_header.get("kid")
    if not kid:
        return None

    jwks = get_jwks()
    keys = jwks.get("keys", [])

    for key in keys:
        if key.get("kid") == kid:
            return {
                "kty": key.get("kty"),
                "kid": key.get("kid"),
                "use": key.get("use"),
                "alg": key.get("alg"),
                "n": key.get("n"),
                "e": key.get("e"),
            }

    return None


def verify_token(token: str) -> dict:
    """
    Verify and decode a JWT token.

    Validates the token signature using the RSA public key,
    checks expiration, audience, and issuer claims.

    Args:
        token: The raw JWT string.

    Returns:
        dict: The decoded token payload.

    Raises:
        HTTPException: 401 if token is invalid or expired.
    """
    rsa_key = get_rsa_key(token)

    if rsa_key is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=AUTH0_AUDIENCE,
            issuer=ISSUER,
        )
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token expired"
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> dict:
    """
    Extract and verify the JWT token from request credentials.

    FastAPI dependency for protected endpoints that require
    authentication.

    Args:
        credentials: HTTP Bearer credentials from the request.

    Returns:
        dict: The decoded token payload.

    Raises:
        HTTPException: 401 if authentication fails.
    """
    token = credentials.credentials
    return verify_token(token)


def require_manager(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Verify that the authenticated user has the logistics_manager role.

    FastAPI dependency for endpoints restricted to logistics managers.

    Args:
        current_user: The decoded token payload from get_current_user.

    Returns:
        dict: The current user payload if authorized.

    Raises:
        HTTPException: 403 if user lacks the manager role.
    """
    roles = current_user.get(ROLES_NAMESPACE, [])

    if "logistics_manager" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Manager role required"
        )

    return current_user


def require_analyst(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Verify that the authenticated user has analyst or manager role.

    FastAPI dependency for endpoints accessible to logistics managers
    or read-only analysts.

    Args:
        current_user: The decoded token payload from get_current_user.

    Returns:
        dict: The current user payload if authorized.

    Raises:
        HTTPException: 403 if user lacks required role.
    """
    roles = current_user.get(ROLES_NAMESPACE, [])

    allowed_roles = {"logistics_manager", "read_only_analyst"}

    if not any(role in allowed_roles for role in roles):
        raise HTTPException(
            status_code=403,
            detail="Analyst role required"
        )

    return current_user


def get_optional_user(request: Request) -> dict | None:
    """
    Attempt to extract and verify a JWT token from the request.

    Unlike get_current_user, this function never raises exceptions.
    It returns the decoded payload if a valid token is present,
    or None if no token or an invalid token is provided.

    Useful for endpoints that optionally enhance responses for
    authenticated users.

    Args:
        request: The FastAPI request object.

    Returns:
        dict | None: The decoded token payload if valid, else None.
    """
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]

    try:
        return verify_token(token)
    except HTTPException:
        return None
