"""付费授权：群聊白名单、到期时间、激活码与付费查询闸门。

设计目标
--------
* 后台可以手动把某个 AstrBot 会话（群）加入白名单，设置到期时间或立即停用；
* 后台可以批量生成一次性激活码（天数 + 备注）；
* 群里发送 ``激活 <激活码>`` 后，当前会话自动写入白名单，到期时间顺延；
* ``paid_enabled`` 打开时，标记为付费的指令会检查当前会话是否有效；
* 授权和激活码写入同一份 JSON，旧版两个文件只在首次读取时兼容。

时间统一使用 Unix 时间戳存储；展示时转为本地时间。日期只填 ``YYYY-MM-DD``
时按当天 23:59:59 到期。
"""

from __future__ import annotations

import json
import copy
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import Settings
from .storage import write_json as _atomic_write

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LOCK = threading.RLock()


class PaidError(ValueError):
    pass


def _iso(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    try:
        return datetime.fromtimestamp(float(timestamp)).astimezone().isoformat(
            timespec="seconds"
        )
    except (OSError, ValueError, OverflowError):
        return ""


def _parse_time(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise PaidError(f"{label}格式不正确")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        raise PaidError(f"{label}不能为空")
    if len(text) == 10:
        try:
            date = datetime.strptime(text, "%Y-%m-%d")
            return date.replace(hour=23, minute=59, second=59).timestamp()
        except ValueError:
            pass
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError as exc:
        raise PaidError(f"{label}格式应为 YYYY-MM-DD 或 ISO 时间") from exc


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper().replace(" ", "")
    return text


def _code_key(value: Any) -> str:
    """Compare activation codes ignoring hyphens / spaces."""

    return _normalize_code(value).replace("-", "")




class PaidService:
    def __init__(self, settings: Settings, data_dir: str | Path) -> None:
        self.settings = settings
        self.data_dir = Path(data_dir)
        self.groups_path = self.data_dir / "paid_groups.json"
        self.codes_path = self.data_dir / "activation_codes.json"
        self._lock = _CODE_LOCK
        self.state_path = self.data_dir / "paid_state.json"
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not isinstance(state.get("groups"), list) or not isinstance(state.get("codes"), list):
                raise PaidError("授权数据格式异常，请检查 paid_state.json")
            self._groups, self._codes = state["groups"], state["codes"]
        else:
            self._groups, self._codes = self._load_groups(), self._load_codes()
        self._saved_state = copy.deepcopy({"groups": self._groups, "codes": self._codes})

    # ------------------------------------------------------------------ storage
    def _load_groups(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.groups_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise PaidError("授权数据无法读取，请检查原文件。") from exc
        rows = raw.get("groups") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise PaidError("授权数据格式异常，请检查原文件。")
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            session_id = str(row.get("session_id") or "").strip()
            if not session_id:
                continue
            try:
                expires_at = float(row.get("expires_at") or 0)
            except (TypeError, ValueError):
                expires_at = 0.0
            result.append(
                {
                    "session_id": session_id,
                    "note": str(row.get("note") or "")[:200],
                    "expires_at": expires_at,
                    "active": bool(row.get("active", True)),
                    "created_at": float(row.get("created_at") or time.time()),
                    "updated_at": float(row.get("updated_at") or time.time()),
                    "source": str(row.get("source") or ""),
                }
            )
        return result

    def _load_codes(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.codes_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise PaidError("授权数据无法读取，请检查原文件。") from exc
        rows = raw.get("codes") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise PaidError("授权数据格式异常，请检查原文件。")
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = _normalize_code(row.get("code"))
            if not code:
                continue
            try:
                days = max(1, min(3650, int(row.get("days") or 30)))
            except (TypeError, ValueError):
                days = 30
            result.append(
                {
                    "code": code,
                    "days": days,
                    "note": str(row.get("note") or "")[:200],
                    "created_at": float(row.get("created_at") or time.time()),
                    "used_at": float(row.get("used_at") or 0) or None,
                    "used_by": str(row.get("used_by") or ""),
                    "used_session": str(row.get("used_session") or ""),
                }
            )
        return result

    def _save_state(self) -> None:
        state = {"groups": self._groups, "codes": self._codes}
        try:
            _atomic_write(self.state_path, state)
        except OSError as exc:
            self._groups = copy.deepcopy(self._saved_state["groups"])
            self._codes = copy.deepcopy(self._saved_state["codes"])
            raise PaidError("授权保存失败，请稍后再试。") from exc
        self._saved_state = copy.deepcopy(state)

    # ------------------------------------------------------------------ queries
    @property
    def gating_enabled(self) -> bool:
        return self.settings.paid_enabled

    def find_group(self, session_id: str) -> dict[str, Any] | None:
        target = str(session_id or "").strip()
        for group in self._groups:
            if group["session_id"] == target:
                return group
        return None

    def status(self, session_id: str) -> dict[str, Any]:
        group = self.find_group(session_id)
        now = time.time()
        if group is None:
            return {
                "session_id": str(session_id or ""),
                "active": False,
                "exists": False,
                "reason": "not_whitelisted",
                "message": "当前会话尚无付费授权",
                "expires_at": 0,
                "expires": "",
                "remaining_seconds": 0,
                "days": 0,
                "note": "",
            }
        expires_at = float(group["expires_at"])
        expired = expires_at <= now
        active = bool(group["active"]) and not expired
        if expired:
            reason = "expired"
            message = "付费授权已到期"
        elif not group["active"]:
            reason = "disabled"
            message = "付费授权已被管理员关闭"
        else:
            reason = ""
            message = "付费授权有效"
        remaining = max(0, int(expires_at - now))
        return {
            "session_id": group["session_id"],
            "active": active,
            "exists": True,
            "reason": reason,
            "message": message,
            "expires_at": expires_at,
            "expires": _iso(expires_at),
            "remaining_seconds": remaining,
            "days": round(remaining / 86400, 1) if remaining else 0,
            "note": group["note"],
        }

    def can_use_paid(self, session_id: str) -> bool:
        if not self.gating_enabled:
            return True
        return self.status(session_id)["active"]

    def block_message(self, session_id: str, command_name: str = "") -> str:
        status = self.status(session_id)
        prefix = f"「{command_name}」是付费查询。" if command_name else "该功能是付费查询。"
        if status["reason"] == "expired":
            return (
                f"{prefix}\n当前群授权已于 {status['expires']} 到期。"
                "请管理员在后台续期，或发送「激活 <激活码>」。"
            )
        if status["reason"] == "disabled":
            return f"{prefix}\n当前群的付费授权已被管理员关闭。"
        return (
            f"{prefix}\n当前群尚未开通付费查询。"
            "请管理员在后台添加白名单，或发送「激活 <激活码>」。"
        )

    # ---------------------------------------------------------------- activation
    def _new_code(self) -> str:
        existing = {row["code"] for row in self._codes}
        while True:
            parts = [
                "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
                for _ in range(3)
            ]
            code = "JX3-" + "-".join(parts)
            if code not in existing:
                return code

    def generate_codes(
        self, *, days: int, count: int, note: str = ""
    ) -> list[dict[str, Any]]:
        try:
            days = int(days)
            count = int(count)
        except (TypeError, ValueError) as exc:
            raise PaidError("天数和数量必须是整数") from exc
        if days < 1 or days > 3650:
            raise PaidError("授权天数必须在 1 到 3650 之间")
        if count < 1 or count > 100:
            raise PaidError("一次最多生成 100 个激活码")
        note = str(note or "").strip()[:200]
        created: list[dict[str, Any]] = []
        with self._lock:
            for _ in range(count):
                code = self._new_code()
                record = {
                    "code": code,
                    "days": days,
                    "note": note,
                    "created_at": time.time(),
                    "used_at": None,
                    "used_by": "",
                    "used_session": "",
                }
                self._codes.append(record)
                created.append(dict(record))
            self._save_state()
        return created

    def activate(self, session_id: str, code: str) -> dict[str, Any]:
        session_id = str(session_id or "").strip()
        if not session_id:
            raise PaidError("无法识别当前会话，请在群里发送激活码")
        normalized = _normalize_code(code)
        if not normalized:
            raise PaidError("请提供激活码，例如：激活 JX3-XXXX-XXXX-XXXX")
        with self._lock:
            wanted = _code_key(normalized)
            record = next(
                (row for row in self._codes if _code_key(row["code"]) == wanted), None
            )
            if record is None:
                raise PaidError("激活码不存在，请检查是否复制完整")
            if record.get("used_at"):
                raise PaidError("该激活码已经被使用")
            now = time.time()
            group = self.find_group(session_id)
            if group is None:
                base = now
                group = {
                    "session_id": session_id,
                    "note": record.get("note") or "激活码开通",
                    "expires_at": base,
                    "active": True,
                    "created_at": now,
                    "updated_at": now,
                    "source": "activation_code",
                }
                self._groups.append(group)
            else:
                base = max(now, float(group.get("expires_at") or 0))
            group["expires_at"] = base + int(record["days"]) * 86400
            group["active"] = True
            group["updated_at"] = now
            if record.get("note"):
                group["note"] = record["note"]
            group["source"] = "activation_code"
            record["used_at"] = now
            record["used_by"] = session_id
            record["used_session"] = session_id
            self._save_state()
        status = self.status(session_id)
        return {
            "ok": True,
            "message": (
                f"激活成功，当前群付费授权延长至 {status['expires']} "
                f"（剩余 {status['days']} 天）"
            ),
            "status": status,
        }

    # -------------------------------------------------------------------- admin
    def add_group(
        self,
        *,
        session_id: str,
        note: str = "",
        expires_at: Any = None,
        active: bool = True,
    ) -> dict[str, Any]:
        session_id = str(session_id or "").strip()
        if not session_id:
            raise PaidError("会话 ID 不能为空")
        if len(session_id) > 512:
            raise PaidError("会话 ID 不能超过 512 个字符")
        expiry = _parse_time(expires_at, label="到期时间") if expires_at else time.time() + 30 * 86400
        now = time.time()
        with self._lock:
            existing = self.find_group(session_id)
            if existing:
                existing.update(
                    {
                        "note": str(note or existing["note"])[:200],
                        "expires_at": expiry,
                        "active": bool(active),
                        "updated_at": now,
                        "source": "admin",
                    }
                )
                message = "已更新该群的付费授权"
            else:
                self._groups.append(
                    {
                        "session_id": session_id,
                        "note": str(note or "")[:200],
                        "expires_at": expiry,
                        "active": bool(active),
                        "created_at": now,
                        "updated_at": now,
                        "source": "admin",
                    }
                )
                message = "已添加群聊白名单"
            self._save_state()
        return {"ok": True, "message": message, "status": self.status(session_id)}

    def update_group(
        self,
        *,
        session_id: str,
        note: Any = None,
        expires_at: Any = None,
        active: Any = None,
    ) -> dict[str, Any]:
        session_id = str(session_id or "").strip()
        expiry = _parse_time(expires_at, label="到期时间") if expires_at not in (None, "") else None
        with self._lock:
            group = self.find_group(session_id)
            if group is None:
                raise PaidError("该会话不在白名单中")
            if note is not None:
                group["note"] = str(note or "")[:200]
            if expiry is not None:
                group["expires_at"] = expiry
            if active is not None:
                group["active"] = bool(active)
            group["updated_at"] = time.time()
            self._save_state()
        return {"ok": True, "message": "授权已更新", "status": self.status(session_id)}

    def extend_group(self, session_id: str, days: int) -> dict[str, Any]:
        try:
            days = int(days)
        except (TypeError, ValueError) as exc:
            raise PaidError("续期天数必须是整数") from exc
        if days < 1 or days > 3650:
            raise PaidError("续期天数必须在 1 到 3650 之间")
        with self._lock:
            group = self.find_group(session_id)
            if group is None:
                raise PaidError("该会话不在白名单中")
            base = max(time.time(), float(group.get("expires_at") or 0))
            group["expires_at"] = base + days * 86400
            group["active"] = True
            group["updated_at"] = time.time()
            self._save_state()
        return {"ok": True, "message": f"已续期 {days} 天", "status": self.status(session_id)}

    def delete_group(self, session_id: str) -> dict[str, Any]:
        target = str(session_id or "").strip()
        with self._lock:
            before = len(self._groups)
            self._groups = [g for g in self._groups if g["session_id"] != target]
            if len(self._groups) == before:
                raise PaidError("该会话不在白名单中")
            self._save_state()
        return {"ok": True, "message": "已移出白名单"}

    def delete_code(self, code: str) -> dict[str, Any]:
        target = _code_key(code)
        with self._lock:
            before = len(self._codes)
            self._codes = [
                row for row in self._codes if _code_key(row["code"]) != target
            ]
            if len(self._codes) == before:
                raise PaidError("激活码不存在")
            self._save_state()
        return {"ok": True, "message": "激活码已删除"}

    def summary(self) -> dict[str, Any]:
        now = time.time()
        groups: list[dict[str, Any]] = []
        for group in sorted(self._groups, key=lambda item: item["expires_at"], reverse=True):
            status = self.status(group["session_id"])
            groups.append(
                {
                    "session_id": group["session_id"],
                    "note": group["note"],
                    "expires_at": group["expires_at"],
                    "expires": _iso(group["expires_at"]),
                    "active": bool(group["active"]),
                    "valid": status["active"],
                    "reason": status["reason"],
                    "remaining_seconds": max(0, int(group["expires_at"] - now)),
                    "source": group["source"],
                    "updated_at": _iso(group["updated_at"]),
                }
            )
        codes = sorted(self._codes, key=lambda item: item["created_at"], reverse=True)
        code_rows = [
            {
                "code": row["code"],
                "days": row["days"],
                "note": row["note"],
                "created_at": _iso(row["created_at"]),
                "used": bool(row["used_at"]),
                "used_at": _iso(row["used_at"]),
                "used_session": row["used_session"],
            }
            for row in codes
        ]
        return {
            "enabled": self.gating_enabled,
            "groups": groups,
            "codes": code_rows,
            "stats": {
                "groups": len(groups),
                "active_groups": sum(1 for item in groups if item["valid"]),
                "expired_groups": sum(
                    1 for item in groups if item["reason"] == "expired"
                ),
                "codes": len(code_rows),
                "unused_codes": sum(1 for item in code_rows if not item["used"]),
                "used_codes": sum(1 for item in code_rows if item["used"]),
            },
        }
