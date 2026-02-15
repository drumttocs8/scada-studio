"""
Gitea API helper — fetches and commits file content to Gitea repos.
"""

import base64
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


async def get_file_sha(repo: str, file_path: str, ref: str = "main") -> str | None:
    """Get the SHA of an existing file (needed for updates)."""
    settings = get_settings()
    url = f"{settings.gitea_url}/api/v1/repos/{repo}/contents/{file_path}?ref={ref}"
    headers = {}
    if settings.gitea_token:
        headers["Authorization"] = f"token {settings.gitea_token}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("sha")


async def commit_file_to_gitea(
    repo: str,
    file_path: str,
    content: bytes,
    message: str,
    branch: str = "main",
) -> dict:
    """
    Create or update a file in a Gitea repo via API.

    Args:
        repo: "owner/repo" format
        file_path: path inside the repo (e.g. "pointslist/V08_points.json")
        content: file content as bytes
        message: commit message
        branch: target branch
    """
    settings = get_settings()
    url = f"{settings.gitea_url}/api/v1/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"token {settings.gitea_token}",
        "Content-Type": "application/json",
    }

    body = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": branch,
        "committer": {
            "name": "SCADA Studio Bot",
            "email": "scada-bot@verance.ai",
        },
    }

    # Check if file already exists (need SHA for update)
    existing_sha = await get_file_sha(repo, file_path, ref=branch)
    if existing_sha:
        body["sha"] = existing_sha

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()

