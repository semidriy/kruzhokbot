import asyncio
import aiohttp
import logging
from typing import Optional, Tuple, List, Dict
from aiogram.types import User


class SubgramAPI:
    BASE_URL = "https://api.subgram.ru"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache_check: Dict[int, Tuple[float, Tuple[bool, List[Dict]]]] = {}
        self._cache_ttl_seconds: int = 30
        if not api_key:
            logging.warning("[Subgram API] Ключ не предоставлен. Функционал будет недоступен.")

    async def _get_session(self, timeout_sec: int = 8) -> aiohttp.ClientSession:
        """Получить или создать переиспользуемую сессию"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout_sec)
            )
        return self._session

    async def close(self):
        """Закрыть сессию"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _make_request(self, endpoint: str, payload: dict,
                            timeout_sec: int = 8) -> Optional[Dict]:
        if not self.api_key:
            return None

        url = f"{self.BASE_URL}/{endpoint}"
        headers = {'Auth': self.api_key, 'Content-Type': 'application/json'}

        try:
            session = await self._get_session()
            async with session.post(
                url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as response:
                if response.ok:
                    data = await response.json()
                    logging.info(f"[Subgram API] ПОЛУЧЕН ОТВЕТ от {endpoint}: {data}")
                    return data
                else:
                    logging.error(f"[Subgram API] Ошибка от {endpoint}. Статус: {response.status}")
                    return None
        except asyncio.TimeoutError:
            logging.error(f"[Subgram API] Таймаут ({timeout_sec}с) при запросе к {endpoint}")
            return None
        except aiohttp.ClientError as e:
            logging.error(f"[Subgram API] Критическая ошибка сети: {e}")
            return None
        except Exception as e:
            logging.error(f"[Subgram API] Неожиданная ошибка: {e}")
            return None

    async def check_subscription(self, user: User) -> Tuple[bool, List[Dict]]:
        cached = self._cache_check.get(user.id)
        if cached:
            ts, value = cached
            if (asyncio.get_event_loop().time() - ts) < self._cache_ttl_seconds:
                return value

        payload = {
            "UserId": str(user.id), "ChatId": str(user.id),
            "first_name": user.first_name, "language_code": user.language_code,
            "Premium": bool(user.is_premium), "action": "subscribe",
        }
        data = await self._make_request('request-op', payload)
        result: Tuple[bool, List[Dict]] = (False, [])
        if data:
            status = data.get("status")
            if status == "ok":
                result = (True, [])
            elif status == "warning":
                sponsors = data.get("additional", {}).get("sponsors")
                if sponsors is not None:
                    unsubscribed = [s for s in sponsors if s.get("status") == "unsubscribed"]
                else:
                    links = data.get("links") or []
                    unsubscribed = [{"link": link, "status": "unsubscribed"} for link in links]
                result = (len(unsubscribed) == 0, unsubscribed)
            elif status == "gender":
                logging.info("[Subgram API] Требуется передать пол пользователя (status=gender).")

        self._cache_check[user.id] = (asyncio.get_event_loop().time(), result)
        return result

    async def get_subgram_tasks(self, user: User) -> List[Dict]:
        payload = {
            "UserId": str(user.id), "ChatId": str(user.id),
            "first_name": user.first_name, "language_code": user.language_code,
            "Premium": bool(user.is_premium), "action": "newtask",
        }
        data = await self._make_request('request-op', payload)
        if not data:
            return []
        if data.get("status") == "warning":
            sponsors = data.get("additional", {}).get("sponsors")
            if sponsors is not None:
                return [s for s in sponsors if s.get("status") == "unsubscribed"]
            links = data.get("links") or []
            return [{"link": link, "status": "unsubscribed", "resource_name": ""} for link in links]
        return []

    async def check_task_completion(self, user_id: int, link: str) -> bool:
        """Проверить выполнение одного задания. При таймауте — пропускаем (fail-open)."""
        return await self.check_op_links_batch(user_id, [link])

    async def check_op_links_batch(self, user_id: int, links: List[str]) -> bool:
        """
        Проверить список subgram-ссылок одним запросом.
        Возвращает True если ВСЕ ссылки подписаны (или notgetted).
        При ошибке/таймауте возвращает True (fail-open — не блокируем пользователя).
        """
        if not links:
            return True
        payload = {"user_id": user_id, "links": links}
        data = await self._make_request('get-user-subscriptions', payload, timeout_sec=15)
        if data is None:
            logging.warning(f"[Subgram API] check_op_links_batch: нет ответа для user={user_id}, пропускаем")
            return True
        if data.get("code") == 404:
            return False
        if data.get("status") != "ok":
            logging.warning(f"[Subgram API] check_op_links_batch: неожиданный статус={data.get('status')}, пропускаем")
            return True
        sponsors = data.get("additional", {}).get("sponsors", [])
        link_set = set(links)
        for s in sponsors:
            if s.get("link") in link_set and s.get("status") == "unsubscribed":
                return False
        return True