"""Кэш транскриптов YouTube в SQLite."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from db import SessionLocal
from stores.db_models import YouTubeTranscript


class YouTubeTranscriptsRepository:
    async def get(self, video_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(YouTubeTranscript).where(
                    YouTubeTranscript.video_id == video_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "video_id": row.video_id,
                "url": row.url,
                "title": row.title,
                "channel": row.channel,
                "language": row.language,
                "transcript": row.transcript,
                "source": row.source,
                "created_at": row.created_at,
            }

    async def upsert(
        self,
        video_id: str,
        transcript: str,
        *,
        url: str | None = None,
        title: str | None = None,
        channel: str | None = None,
        language: str | None = None,
        source: str = "apify",
    ) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(YouTubeTranscript).where(
                    YouTubeTranscript.video_id == video_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = YouTubeTranscript(video_id=video_id, transcript=transcript)
                session.add(row)
            row.url = url
            row.title = title
            row.channel = channel
            row.language = language
            row.transcript = transcript
            row.source = source
            await session.commit()

    async def delete(self, video_id: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(
                select(YouTubeTranscript).where(
                    YouTubeTranscript.video_id == video_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


youtube_transcripts = YouTubeTranscriptsRepository()
