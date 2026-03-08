---
mode: fileMatch
patterns:
  - "src/beacon/api/**/*.py"
---

# API Standards — Beacon

## API Design Principles

1. **RESTful**: Use HTTP methods correctly (GET, POST, PUT, DELETE)
2. **Versioned**: All endpoints under `/v1/` prefix
3. **Typed**: Pydantic models for all requests/responses
4. **Documented**: OpenAPI docs auto-generated from FastAPI
5. **Consistent**: Standard error format, status codes, naming

## Endpoint Structure

### URL Patterns

```
/v1/packs                    # List available packs
/v1/packs/{pack_id}          # Get pack details
/v1/packs/{pack_id}/execute  # Execute pack
/v1/evidence                 # List evidence packs
/v1/evidence/{evidence_id}   # Get evidence pack
/v1/telemetry/metrics        # Query telemetry metrics
/v1/telemetry/status         # Get telemetry status
/v1/health                   # Health check
```

### HTTP Methods

- **GET**: Retrieve data (idempotent, no side effects)
- **POST**: Create resource or trigger action
- **PUT**: Update entire resource
- **PATCH**: Update partial resource
- **DELETE**: Remove resource

### Status Codes

- **200 OK**: Successful GET/PUT/PATCH
- **201 Created**: Successful POST creating resource
- **202 Accepted**: Async operation started
- **204 No Content**: Successful DELETE
- **400 Bad Request**: Invalid input
- **404 Not Found**: Resource doesn't exist
- **422 Unprocessable Entity**: Validation error
- **500 Internal Server Error**: Server failure
- **503 Service Unavailable**: Dependency unavailable

## Request/Response Models

### Use Pydantic Models

```python
from pydantic import BaseModel, Field
from typing import Optional

class PackExecuteRequest(BaseModel):
    """Request to execute a diagnostic pack."""
    pack_id: str = Field(..., description="Pack identifier")
    privacy_mode: Optional[str] = Field("hashed", description="Privacy mode: hashed, redacted, plaintext")
    timeout_seconds: Optional[int] = Field(300, ge=1, le=3600, description="Execution timeout")

class PackExecuteResponse(BaseModel):
    """Response from pack execution."""
    execution_id: str = Field(..., description="Unique execution ID")
    status: str = Field(..., description="Status: running, completed, failed")
    evidence_id: Optional[str] = Field(None, description="Evidence pack ID if completed")
    error: Optional[str] = Field(None, description="Error message if failed")
```

### Field Validation

```python
from pydantic import validator, Field

class TelemetryQueryRequest(BaseModel):
    start_time: datetime = Field(..., description="Query start time")
    end_time: datetime = Field(..., description="Query end time")
    metric: str = Field(..., description="Metric name")

    @validator("end_time")
    def end_after_start(cls, v, values):
        if "start_time" in values and v <= values["start_time"]:
            raise ValueError("end_time must be after start_time")
        return v

    @validator("metric")
    def valid_metric(cls, v):
        allowed = ["wifi_rssi", "latency", "throughput"]
        if v not in allowed:
            raise ValueError(f"metric must be one of {allowed}")
        return v
```

## Error Handling

### Standard Error Response

```python
class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Machine-readable error code")
    details: Optional[dict] = Field(None, description="Additional error context")

# Example usage
@app.get("/v1/evidence/{evidence_id}")
async def get_evidence(evidence_id: str):
    try:
        evidence = load_evidence(evidence_id)
        return evidence
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=f"Evidence pack {evidence_id} not found",
                error_code="EVIDENCE_NOT_FOUND",
                details={"evidence_id": evidence_id}
            ).dict()
        )
```

### Error Codes

Use consistent error codes:

- `PACK_NOT_FOUND`: Diagnostic pack doesn't exist
- `EVIDENCE_NOT_FOUND`: Evidence pack doesn't exist
- `EXECUTION_FAILED`: Pack execution failed
- `VALIDATION_ERROR`: Input validation failed
- `INFLUXDB_UNAVAILABLE`: InfluxDB connection failed
- `TIMEOUT`: Operation timed out

## Endpoint Implementation

### Basic Endpoint

```python
from fastapi import APIRouter, HTTPException, Depends
from typing import List

router = APIRouter(prefix="/v1/packs", tags=["packs"])

@router.get("/", response_model=List[PackInfo])
async def list_packs():
    """
    List all available diagnostic packs.

    Returns:
        List of pack metadata (id, name, description, collectors, runners)
    """
    packs = load_all_packs()
    return [PackInfo.from_pack(p) for p in packs]

@router.get("/{pack_id}", response_model=PackDetail)
async def get_pack(pack_id: str):
    """
    Get detailed information about a diagnostic pack.

    Args:
        pack_id: Pack identifier

    Returns:
        Full pack definition including YAML content

    Raises:
        404: Pack not found
    """
    try:
        pack = load_pack(pack_id)
        return PackDetail.from_pack(pack)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Pack {pack_id} not found"
        )
```

### Async Endpoint

```python
@router.post("/{pack_id}/execute", response_model=PackExecuteResponse, status_code=202)
async def execute_pack(pack_id: str, request: PackExecuteRequest):
    """
    Execute a diagnostic pack asynchronously.

    Args:
        pack_id: Pack identifier
        request: Execution parameters

    Returns:
        Execution ID and status (202 Accepted)

    Raises:
        404: Pack not found
        400: Invalid parameters
    """
    try:
        pack = load_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Pack {pack_id} not found")

    # Start async execution
    execution_id = str(uuid.uuid4())
    asyncio.create_task(run_pack_async(execution_id, pack, request))

    return PackExecuteResponse(
        execution_id=execution_id,
        status="running"
    )
```

### Dependency Injection

```python
from fastapi import Depends

def get_config() -> BeaconConfig:
    """Dependency: Load Beacon configuration."""
    return load_config()

def get_influxdb_client(config: BeaconConfig = Depends(get_config)):
    """Dependency: Get InfluxDB client."""
    return InfluxDBClient(url=config.influxdb_url, token=config.influxdb_token)

@router.get("/v1/telemetry/metrics")
async def query_metrics(
    request: TelemetryQueryRequest,
    client = Depends(get_influxdb_client)
):
    """Query telemetry metrics from InfluxDB."""
    results = client.query(
        measurement=request.metric,
        start=request.start_time,
        end=request.end_time
    )
    return results
```

## Query Parameters

### Pagination

```python
from fastapi import Query

@router.get("/v1/evidence")
async def list_evidence(
    limit: int = Query(50, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Skip N results"),
    sort_by: str = Query("timestamp", description="Sort field"),
    order: str = Query("desc", regex="^(asc|desc)$", description="Sort order")
):
    """List evidence packs with pagination."""
    evidence = load_evidence_list(limit=limit, offset=offset, sort_by=sort_by, order=order)
    return evidence
```

### Filtering

```python
@router.get("/v1/telemetry/metrics")
async def query_metrics(
    metric: str = Query(..., description="Metric name"),
    start_time: datetime = Query(..., description="Start time"),
    end_time: datetime = Query(..., description="End time"),
    device_id: Optional[str] = Query(None, description="Filter by device"),
    ssid_hash: Optional[str] = Query(None, description="Filter by SSID hash")
):
    """Query telemetry metrics with filters."""
    filters = {}
    if device_id:
        filters["device_id"] = device_id
    if ssid_hash:
        filters["ssid_hash"] = ssid_hash

    results = query_influxdb(metric, start_time, end_time, filters)
    return results
```

## Response Formatting

### Success Response

```python
class SuccessResponse(BaseModel):
    """Generic success response."""
    success: bool = True
    message: str
    data: Optional[dict] = None

@router.delete("/v1/evidence/{evidence_id}", status_code=204)
async def delete_evidence(evidence_id: str):
    """Delete an evidence pack."""
    try:
        delete_evidence_file(evidence_id)
        return  # 204 No Content
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Evidence not found")
```

### List Response

```python
class ListResponse(BaseModel):
    """Generic list response with pagination."""
    items: List[dict]
    total: int
    limit: int
    offset: int

@router.get("/v1/evidence", response_model=ListResponse)
async def list_evidence(limit: int = 50, offset: int = 0):
    """List evidence packs."""
    items, total = load_evidence_list(limit=limit, offset=offset)
    return ListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset
    )
```

## Authentication (Future)

Placeholder for future authentication:

```python
from fastapi import Security, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Verify JWT token (future implementation)."""
    # TODO: Implement JWT verification
    return {"user_id": "placeholder"}

@router.get("/v1/protected")
async def protected_endpoint(user = Depends(verify_token)):
    """Protected endpoint requiring authentication."""
    return {"message": f"Hello {user['user_id']}"}
```

## CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Health Check

```python
@router.get("/v1/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        Service status and dependency health
    """
    influxdb_ok = check_influxdb_connection()

    return {
        "status": "healthy" if influxdb_ok else "degraded",
        "version": "1.0.0",
        "dependencies": {
            "influxdb": "healthy" if influxdb_ok else "unavailable"
        }
    }
```

## OpenAPI Documentation

FastAPI auto-generates docs at `/docs` (Swagger UI) and `/redoc` (ReDoc).

### Customize Metadata

```python
app = FastAPI(
    title="Beacon API",
    description="Network diagnostics and observability platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "packs", "description": "Diagnostic pack operations"},
        {"name": "evidence", "description": "Evidence pack management"},
        {"name": "telemetry", "description": "Telemetry data queries"},
    ]
)
```

### Add Examples

```python
class PackExecuteRequest(BaseModel):
    pack_id: str
    privacy_mode: str = "hashed"

    class Config:
        schema_extra = {
            "example": {
                "pack_id": "full_diagnostic",
                "privacy_mode": "hashed"
            }
        }
```

## Testing APIs

```python
from fastapi.testclient import TestClient

client = TestClient(app)

def test_list_packs():
    """Should return list of available packs."""
    response = client.get("/v1/packs")
    assert response.status_code == 200
    assert len(response.json()) > 0

def test_execute_pack():
    """Should start pack execution and return execution ID."""
    response = client.post(
        "/v1/packs/full_diagnostic/execute",
        json={"privacy_mode": "hashed"}
    )
    assert response.status_code == 202
    assert "execution_id" in response.json()

def test_get_nonexistent_evidence():
    """Should return 404 for nonexistent evidence."""
    response = client.get("/v1/evidence/nonexistent")
    assert response.status_code == 404
```

## Versioning Strategy

### Current: URL Versioning

All endpoints under `/v1/` prefix.

### Future: Breaking Changes

When introducing breaking changes:
1. Create `/v2/` endpoints
2. Maintain `/v1/` for 6 months
3. Add deprecation warnings to `/v1/` responses
4. Remove `/v1/` after deprecation period

### Non-Breaking Changes

Allowed without version bump:
- Adding new endpoints
- Adding optional fields to requests
- Adding fields to responses
- Relaxing validation

Not allowed:
- Removing endpoints
- Removing fields from responses
- Changing field types
- Stricter validation
