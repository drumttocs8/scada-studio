"""
Gitea API helper — fetches file content from Gitea repos.
"""

import httpx
from config import get_settings


async def fetch_file_from_gitea(
    repo: str, file_path: str, ref: str = "main"
) -> bytes:
    """
    Download raw file content from Gitea.

    Args:
        repo: "owner/repo" format
        file_path: path inside the repo
        ref: branch or commit SHA
    """
    settings = get_settings()
    url = f"{settings.gitea_url}/api/v1/repos/{repo}/raw/{file_path}?ref={ref}"
    headers = {}
    if settings.gitea_token:
        headers["Authorization"] = f"token {settings.gitea_token}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content
