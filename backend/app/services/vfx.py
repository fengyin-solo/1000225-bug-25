"""特效制作业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "vfx"
REQUIRED_FIELDS = ["镜头编号", "所属集数", "特效类型"]
STATUS_ORDER = ["待制作", "制作中", "待审核", "已完成"]
# 动作 -> (允许的来源状态, 目标状态)：来源状态不匹配就拒绝流转，
# 已经在目标状态的镜头会被拦下，避免重复提交审核再次“生效”。
TRANSITION_RULES = {
    "开始制作": (["待制作"], "制作中"),
    "提交审核": (["制作中"], "待审核"),
    "确认完成": (["待审核"], "已完成"),
}
ACTION_RULES = {action: target for action, (_, target) in TRANSITION_RULES.items()}
NEGATIVE_ACTIONS = []
STATUS_FIELD = "制作状态"
SUPPLIER_FIELD = "制作供应商"


class VfxService:
    def __init__(self) -> None:
        # 幂等台账：request_id -> 批量处理结果。同一个 request_id 再次提交时
        # 直接回放首次结果，不再触碰镜头状态，保证一次提交只生效一次。
        self._batch_log: dict[str, dict[str, Any]] = {}

    def _filter_rows(
        self,
        keyword: str | None = None,
        status: str | None = None,
        supplier: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("镜头编号", ""))]
        if supplier:
            rows = [row for row in rows if supplier in str(row.get(SUPPLIER_FIELD, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        supplier: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter_rows(keyword, status, supplier)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        supplier: str | None = None,
    ) -> dict[str, Any]:
        """概览统计：与列表共用同一套筛选口径，保证整组范围和数量对得上。"""
        rows = self._filter_rows(keyword, status, supplier)
        by_status = {name: 0 for name in STATUS_ORDER}
        for row in rows:
            current = str(row.get("status", ""))
            if current in by_status:
                by_status[current] += 1
        return {
            "total": len(rows),
            "by_status": by_status,
            "pending": sum(1 for row in rows if row.get("pending")),
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
        }

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
        entry[STATUS_FIELD] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def _apply_action(self, entry: dict[str, Any], action: str) -> tuple[bool, str]:
        """单条流转：来源状态不匹配时说明原因，不静默改状态。"""
        sources, target = TRANSITION_RULES[action]
        current = str(entry.get("status", ""))
        if current == target:
            return False, f"已处于「{target}」，无需重复{action}"
        if current not in sources:
            return False, f"当前状态为「{current}」，不能{action}（需先处于{'、'.join(sources)}）"
        entry["status"] = target
        # 列表与详情展示的是 STATUS_FIELD，必须和内部状态同步，否则会出现
        # “提示成功但状态没变”的假象。
        entry[STATUS_FIELD] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return True, f"特效镜头已{action}"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"特效镜头 {entry_id} 不存在或已归档"
        if action not in TRANSITION_RULES:
            return None, f"动作「{action}」不属于特效制作可执行范围"
        ok, message = self._apply_action(entry, action)
        if not ok:
            return None, message
        return entry, message

    def run_batch(
        self,
        *,
        action: str,
        entry_ids: list[int],
        request_id: str,
    ) -> dict[str, Any]:
        """批量执行动作：逐条返回成功/失败；同一 request_id 只生效一次。"""
        request_id = (request_id or "").strip()
        if action not in TRANSITION_RULES:
            return self._batch_error(action, request_id, f"动作「{action}」不属于特效制作可执行范围")
        if not request_id:
            return self._batch_error(action, request_id, "缺少 request_id：批量提交需要幂等键，防止重试导致重复生效")
        if not entry_ids:
            return self._batch_error(action, request_id, "未选择任何特效镜头")
        replay = self._batch_log.get(request_id)
        if replay is not None:
            # 同一批次重复提交：回放首次结果，状态不二次变更
            return {
                **replay,
                "deduplicated": True,
                "message": f"{replay['message']}（重复提交已忽略，未重复生效）",
            }
        # 同一请求内的重复 id 只处理一次，避免结果显示成重复处理
        unique_ids = list(dict.fromkeys(entry_ids))
        duplicates_ignored = len(entry_ids) - len(unique_ids)
        results: list[dict[str, Any]] = []
        for entry_id in unique_ids:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                results.append({
                    "id": entry_id,
                    "label": f"#{entry_id}",
                    "ok": False,
                    "message": f"特效镜头 {entry_id} 不存在或已归档",
                    "status": None,
                })
                continue
            ok, message = self._apply_action(entry, action)
            results.append({
                "id": entry_id,
                "label": str(entry.get("镜头编号") or f"#{entry_id}"),
                "ok": ok,
                "message": message,
                "status": entry.get("status"),
            })
        succeeded = sum(1 for item in results if item["ok"])
        failed = len(results) - succeeded
        message = f"批量{action}完成：成功 {succeeded} 条、失败 {failed} 条"
        if duplicates_ignored:
            message += f"，已忽略 {duplicates_ignored} 个重复镜头"
        record = {
            "ok": failed == 0,
            "action": action,
            "request_id": request_id,
            "deduplicated": False,
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "duplicates_ignored": duplicates_ignored,
            "message": message,
            "results": results,
        }
        self._batch_log[request_id] = record
        return record

    @staticmethod
    def _batch_error(action: str, request_id: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "request_id": request_id,
            "deduplicated": False,
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "duplicates_ignored": 0,
            "message": message,
            "results": [],
        }
