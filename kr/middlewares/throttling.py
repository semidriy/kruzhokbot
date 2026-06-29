import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    """Анти-спам: не чаще одного действия раз в throttle_time секунд."""

    def __init__(self, throttle_time: float = 0.5):
        super().__init__()
        self.throttle_time = throttle_time
        self.user_last_action: Dict[int, float] = {}
        self._cleanup_counter = 0

    def _cleanup_old_records(self):
        self._cleanup_counter += 1
        if self._cleanup_counter >= 1000:
            current_time = time.time()
            self.user_last_action = {
                uid: last_time
                for uid, last_time in self.user_last_action.items()
                if current_time - last_time < 600
            }
            self._cleanup_counter = 0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message) and event.successful_payment is not None:
            return await handler(event, data)

        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if not user:
            return await handler(event, data)

        user_id = user.id
        current_time = time.time()

        last_action_time = self.user_last_action.get(user_id, 0)
        time_passed = current_time - last_action_time

        if time_passed < self.throttle_time:
            if isinstance(event, CallbackQuery):
                await event.answer("⏱ Подождите немного", show_alert=False)
            return

        self.user_last_action[user_id] = current_time
        self._cleanup_old_records()

        return await handler(event, data)
