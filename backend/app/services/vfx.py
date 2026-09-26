"""特效制作业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "vfx"
REQUIRED_FIELDS = ["镜头编号", "所属集数", "特效类型"]
STATUS_ORDER = ["待制作", "制作中", "待审核", "已完成"]
ACTION_RULES = {"开始制作": "制作中", "提交审核": "待审核", "确认完成": "已完成"}
# 每个动作只允许从特定前置状态发起，避免重复提交或跨状态硬跳
ALLOWED_SOURCES = {"开始制作": {"待制作"}, "提交审核": {"制作中"}, "确认完成": {"待审核"}}
NEGATIVE_ACTIONS = []
BATCH_SIZE_LIMIT = 200
BATCH_LOG_LIMIT = 500


class VfxService:
    def __init__(self) -> None:
        # 幂等日志：request_id -> 批次结果快照，重复提交直接重放不再生效
        self._batch_log: dict[str, dict[str, Any]] = {}

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        vendor: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter_rows(keyword=keyword, status=status, vendor=vendor)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        vendor: str | None = None,
    ) -> dict[str, Any]:
        """与列表完全同口径的状态统计，保证筛选后的整组范围与概览数量一致。"""
        rows = self._filter_rows(keyword=keyword, status=status, vendor=vendor)
        counts = {name: 0 for name in STATUS_ORDER}
        for row in rows:
            current = str(row.get("status") or "")
            if current in counts:
                counts[current] += 1
        return {"total": len(rows), "statuses": counts}

    def _filter_rows(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        vendor: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("镜头编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if vendor:
            rows = [row for row in rows if vendor in str(row.get("制作供应商", ""))]
        return rows

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"特效镜头 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于特效制作可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        current = str(entry.get("status") or "")
        allowed = ALLOWED_SOURCES.get(action, set())
        if current not in allowed:
            expect = "、".join(sorted(allowed)) or "无"
            return None, f"特效镜头当前状态为「{current}」，仅「{expect}」可执行{action}"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"特效镜头已{action}"

    def run_batch_action(self, *, action: str, ids: list[int], request_id: str) -> dict[str, Any]:
        """批量执行动作：逐条记录成败，同一 request_id 重放不重复生效。"""
        cached = self._batch_log.get(request_id)
        if cached is not None:
            return {**cached, "replayed": True}
        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        for entry_id in ids:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            entry, message = self.run_action(entry_id, action)
            current = entry if entry is not None else store.find(MODULE, entry_id)
            results.append({
                "id": entry_id,
                "ok": entry is not None,
                "message": message,
                "label": (current or {}).get("镜头编号"),
                "status": (current or {}).get("status"),
            })
        succeeded = sum(1 for item in results if item["ok"])
        failed = len(results) - succeeded
        summary = {
            "ok": failed == 0,
            "message": f"批量{action}完成：成功 {succeeded} 条，失败 {failed} 条",
            "action": action,
            "request_id": request_id,
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "replayed": False,
            "results": results,
        }
        if len(self._batch_log) >= BATCH_LOG_LIMIT:
            self._batch_log.pop(next(iter(self._batch_log)))
        self._batch_log[request_id] = summary
        return summary
