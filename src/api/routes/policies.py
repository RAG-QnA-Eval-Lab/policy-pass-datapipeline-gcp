"""정책 메타데이터 엔드포인트."""

import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src.api.deps import get_mongo
from src.api.schemas import PoliciesResponse, PolicyItem
from src.ingestion.mongo_client import PolicyMetadataStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["policies"])


class CategoryEnum(str, Enum):
    housing = "housing"
    employment = "employment"
    startup = "startup"
    education = "education"
    welfare = "welfare"
    finance = "finance"
    participation = "participation"


def _require_mongo(mongo: PolicyMetadataStore | None = Depends(get_mongo)) -> PolicyMetadataStore:
    if mongo is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")
    return mongo


@router.get("/policies", response_model=PoliciesResponse)
def list_policies(
    category: CategoryEnum | None = Query(None, description="카테고리 필터"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지 크기"),
    mongo: PolicyMetadataStore = Depends(_require_mongo),
) -> PoliciesResponse:
    skip = (page - 1) * limit

    if category:
        docs = mongo.find_by_category(category.value, skip=skip, limit=limit)
        total = mongo.count({"category": category.value})
    else:
        docs = mongo.list_all(skip=skip, limit=limit)
        total = mongo.count()

    items = [PolicyItem(**{k: v for k, v in d.items() if k in PolicyItem.model_fields}) for d in docs]
    return PoliciesResponse(policies=items, total=total, page=page, limit=limit)


@router.get("/policies/{policy_id}", response_model=PolicyItem)
def get_policy(
    policy_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$"),
    mongo: PolicyMetadataStore = Depends(_require_mongo),
) -> PolicyItem:
    doc = mongo.find_by_id(policy_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")
    return PolicyItem(**{k: v for k, v in doc.items() if k in PolicyItem.model_fields})
