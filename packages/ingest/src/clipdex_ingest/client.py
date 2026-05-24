from datetime import datetime
from typing import Any

import httpx

from clipdex_ingest.settings import settings

YT = "https://www.googleapis.com/youtube/v3"


class QuotaExceeded(Exception):
    pass


def _raise_for_quota(resp: httpx.Response) -> None:
    if resp.status_code == 403:
        body = resp.json()
        for err in body.get("error", {}).get("errors", []):
            if err.get("reason") == "quotaExceeded":
                raise QuotaExceeded(body["error"]["message"])
    resp.raise_for_status()


async def resolve_uploads_playlist(channel_id: str) -> str:
    """Return the channel's UU... uploads playlist id."""
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(
            f"{YT}/channels",
            params={"part": "contentDetails", "id": channel_id, "key": settings.youtube_api_key},
        )
        _raise_for_quota(r)
        items = r.json().get("items", [])
        if not items:
            raise RuntimeError(f"channel not found: {channel_id}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


async def list_uploads(
    playlist_id: str, since: datetime | None = None
) -> list[dict[str, Any]]:
    """Return videos in the uploads playlist newer than `since` (most recent first)."""
    out: list[dict[str, Any]] = []
    page_token: str | None = None
    async with httpx.AsyncClient(timeout=15) as http:
        while True:
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": 50,
                "key": settings.youtube_api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            r = await http.get(f"{YT}/playlistItems", params=params)
            _raise_for_quota(r)
            data = r.json()

            stop = False
            for item in data["items"]:
                published = datetime.fromisoformat(
                    item["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00")
                )
                if since and published <= since:
                    stop = True
                    break
                out.append(
                    {
                        "video_id": item["contentDetails"]["videoId"],
                        "title": item["snippet"]["title"],
                        "published_at": published,
                    }
                )
            page_token = data.get("nextPageToken")
            if stop or not page_token:
                break
    return out
