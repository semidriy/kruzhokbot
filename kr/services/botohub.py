import asyncio
import aiohttp
import logging
from typing import Optional, List, Dict


class BotoHubAPI:
    BASE_URL = "https://botohub.me"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None
        if not api_key:
            logging.warning("[BotoHub] API ключ не задан.")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post(self, endpoint: str, payload: dict) -> Optional[Dict]:
        if not self.api_key:
            return None
        url = f"{self.BASE_URL}{endpoint}"
        headers = {"Auth": self.api_key, "Content-Type": "application/json"}
        try:
            session = await self._get_session()
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json(content_type=None)
                logging.info(f"[BotoHub] {endpoint} → {data}")
                if resp.ok:
                    return data
                logging.error(f"[BotoHub] Error {resp.status}: {data}")
                return None
        except asyncio.TimeoutError:
            logging.error(f"[BotoHub] Timeout on {endpoint}")
            return None
        except Exception as e:
            logging.error(f"[BotoHub] Exception on {endpoint}: {e}")
            return None


    async def get_op_links(self, user_id: int, limit: int = 5) -> List[str]:
        """Получить список ссылок для ОП. Возвращает до `limit` URL."""
        data = await self._post("/get-tasks", {"chat_id": user_id})
        if not data or data.get("completed") or data.get("skip"):
            return []
        return (data.get("tasks") or [])[:limit]

    @staticmethod
    def _norm(url: str) -> str:
        return url.lower().rstrip('/')

    async def check_op_completion(self, user_id: int, given_links: List[str]) -> bool:
        """
        Проверить, выполнены ли ОП-ссылки для данного этапа.
        BotoHub при повторном запросе возвращает только невыполненные.
        Если ни одна из наших given_links не осталась в remaining — пройдено.
        При ошибке API / skip / completed — fail-open (не блокируем).
        """
        logging.info(f"[BotoHub] check_op user={user_id}, given={len(given_links)} ссылок: {given_links}")

        data = await self._post("/get-tasks", {"chat_id": user_id})
        if not data:
            logging.info(f"[BotoHub] check_op user={user_id} — API ошибка, пропускаем (fail-open)")
            return True
        if data.get("completed"):
            logging.info(f"[BotoHub] check_op user={user_id} — completed=True ✓")
            return True
        if data.get("skip"):
            logging.info(f"[BotoHub] check_op user={user_id} — skip=True ✓")
            return True

        remaining_raw = data.get("tasks") or []
        remaining_norm = {self._norm(r) for r in remaining_raw}
        still_pending = [l for l in given_links if self._norm(l) in remaining_norm]

        logging.info(
            f"[BotoHub] check_op user={user_id}: "
            f"remaining={len(remaining_raw)}, still_pending={len(still_pending)}/{len(given_links)}: {still_pending}"
        )

        if not still_pending:
            logging.info(f"[BotoHub] check_op user={user_id} — наши ссылки выполнены ✓")
            return True

        return False


    async def get_task_link(self, user_id: int, skip: bool = False) -> Optional[str]:
        """Получить одну ссылку задания. Возвращает URL или None."""
        data = await self._post("/get-tasks", {"chat_id": user_id, "is_task": True, "skip": skip})
        if not data or data.get("completed") or data.get("skip"):
            return None
        tasks = data.get("tasks") or []
        return tasks[0] if tasks else None

    async def check_task_done(self, user_id: int) -> bool:
        """
        Проверить, выполнено ли текущее задание.
        prev_success=True → пользователь подписался на предыдущую ссылку.
        """
        data = await self._post("/get-tasks", {"chat_id": user_id, "is_task": True})
        if not data:
            return False
        if data.get("completed"):
            return True
        return bool(data.get("prev_success"))
