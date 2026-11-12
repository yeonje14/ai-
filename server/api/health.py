"""최소한의 서버 생존 확인. 내부 상태를 노출하지 않는다."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
