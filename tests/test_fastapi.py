from __future__ import annotations
from fastapi import FastAPI, Depends, Request
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)

def require_api_login(
    request: Request,
    api_key_header: str | None = Depends(api_key_header),
    api_key_query: str | None = Depends(api_key_query),
) -> int:
    return 1

app = FastAPI()

@app.get("/something", dependencies=[Depends(require_api_login)])
def something():
    pass
