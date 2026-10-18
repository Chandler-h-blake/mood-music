"""Persistent local profile worker. Start with python -m moodmusic_api.worker."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from .ai_client import DeepSeekModelClient, LocalEmbeddingClient
from .credentials import ModelCredentialStore
from .database import Database
from .profiles import ProfileLeaseLostError, ProfileService

logger = logging.getLogger(__name__)


async def execute_claimed_job(
    profiles: ProfileService, job_id: UUID, credentials: ModelCredentialStore
) -> None:
    def api_key() -> str:
        value = credentials.get_deepseek_api_key()
        if not value:
            raise RuntimeError("请先设置模型密钥。")
        return value

    task = asyncio.create_task(profiles.run_job(job_id, api_key))
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=15)
            if done:
                break
            if not await profiles.renew_lease(job_id):
                raise ProfileLeaseLostError("画像执行器已失去租约。")
        await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def main() -> None:
    database = Database()
    profiles = ProfileService(database, DeepSeekModelClient(), LocalEmbeddingClient())
    credentials = ModelCredentialStore()
    owner = str(uuid4())
    try:
        while True:
            try:
                job_id = await profiles.claim_next_job(owner)
                if job_id:
                    await execute_claimed_job(profiles, job_id, credentials)
                else:
                    await asyncio.sleep(1)
            except Exception:
                # Provider responses and credential errors must never enter worker logs.
                logger.warning("画像执行暂时不可用，将在稍后重新领取任务。")
                await asyncio.sleep(5)
    finally:
        await database.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
