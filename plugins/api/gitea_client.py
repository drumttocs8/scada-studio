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


async def list_repo_files(
    repo: str,
    path_prefix: str = "",
    ref: str = "main",
    extensions: tuple[str, ...] = (".xml",),
) -> list[dict]:
    """
    List files under `path_prefix` (recursively) in a Gitea repo.

    Returns a list of {"path": str, "sha": str, "size": int} entries
    filtered to the given extensions.

    Uses Gitea's git tree API for recursive listing.
    """
    settings = get_settings()
    # Resolve branch to commit SHA first (git/trees needs a SHA)
    branch_url = f"{settings.gitea_url}/api/v1/repos/{repo}/branches/{ref}"
    headers = {}
    if settings.gitea_token:
        headers["Authorization"] = f"token {settings.gitea_token}"

    async with httpx.AsyncClient(timeout=30) as client:
        br = await client.get(branch_url, headers=headers)
        if br.status_code == 404:
            # ref may already be a commit sha
            commit_sha = ref
        else:
            br.raise_for_status()
            commit_sha = br.json().get("commit", {}).get("id", ref)

        tree_url = (
            f"{settings.gitea_url}/api/v1/repos/{repo}/git/trees/"
            f"{commit_sha}?recursive=true&per_page=1000"
        )
        tr = await client.get(tree_url, headers=headers)
        tr.raise_for_status()
        data = tr.json()

    out: list[dict] = []
    prefix = (path_prefix or "").lstrip("/")
    for entry in data.get("tree", []):
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if prefix and not path.startswith(prefix):
            continue
        if extensions and not path.lower().endswith(extensions):
            continue
        out.append({"path": path, "sha": entry.get("sha", ""), "size": entry.get("size", 0)})
    return out


async def list_repos(owner: str | None = None, limit: int = 50) -> list[dict]:
    """
    List Gitea repositories.

    If `owner` is provided, returns repos for that user or organization
    (each repo is treated as one substation in SCADA Mapping). Otherwise
    returns all repos visible to the configured token.

    Returns list of {"full_name", "name", "owner", "default_branch",
                     "description", "updated_at"}.
    """
    settings = get_settings()
    headers = {}
    if settings.gitea_token:
        headers["Authorization"] = f"token {settings.gitea_token}"

    params: dict = {"limit": limit, "page": 1}
    if owner:
        # repos/search handles both users and orgs
        params["owner"] = owner
    url = f"{settings.gitea_url}/api/v1/repos/search"

    out: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data", []) if isinstance(payload, dict) else payload
            for r in data:
                out.append({
                    "full_name": r.get("full_name"),
                    "name": r.get("name"),
                    "owner": (r.get("owner") or {}).get("login"),
                    "default_branch": r.get("default_branch") or "main",
                    "description": r.get("description") or "",
                    "updated_at": r.get("updated_at"),
                    "html_url": r.get("html_url"),
                })
            if len(data) < limit:
                break
            params["page"] += 1
            if params["page"] > 20:  # hard safety
                break
    return out

