"""特效制作接口：维护特效镜头，覆盖开始制作、提交审核、确认完成等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchActionPayload, BatchActionResult, EntryPayload, PageResult
from app.services.vfx import VfxService

router = APIRouter(prefix="/api/vfx", tags=["特效制作"])

service = VfxService()

LIST_FIELDS = ["镜头编号", "所属集数", "特效类型", "制作供应商", "渲染帧数", "预估工时", "交付版本", "制作状态"]
STATUSES = ["待制作", "制作中", "待审核", "已完成"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按镜头编号检索"),
    status: str | None = Query(default=None, description="待制作、制作中、待审核、已完成"),
    supplier: str | None = Query(default=None, description="按制作供应商过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按镜头编号、状态与制作供应商过滤特效制作列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, supplier=supplier, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats(
    keyword: str | None = Query(default=None, description="按镜头编号检索"),
    status: str | None = Query(default=None, description="待制作、制作中、待审核、已完成"),
    supplier: str | None = Query(default=None, description="按制作供应商过滤"),
) -> dict[str, Any]:
    """概览统计：与列表共用同一套筛选口径，按供应商筛选后整组范围和数量一致。"""
    return service.stats(keyword=keyword, status=status, supplier=supplier)


@router.post("/batch-actions", response_model=BatchActionResult)
def batch_actions(payload: BatchActionPayload) -> BatchActionResult:
    """批量执行动作：逐条返回成功与失败；request_id 相同的重复提交直接回放首次结果，不重复生效。"""
    return BatchActionResult(**service.run_batch(
        action=payload.action,
        entry_ids=payload.ids,
        request_id=payload.request_id,
    ))


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出特效制作清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "vfx", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条特效镜头明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"特效镜头 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条特效镜头，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="特效镜头已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条特效镜头执行开始制作、提交审核、确认完成；状态不满足或动作不允许时会拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
