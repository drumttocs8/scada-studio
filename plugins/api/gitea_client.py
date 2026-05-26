"""
Gitea API helper — fetches and commits file content to Gitea repos.
"""

import base64
import httpx
from config import get_settings


# ── Effective Gitea connection config ──────────────────────────────────────
# A small module-level cache lets every helper read the current Gitea
# URL/token/owner without threading a DB session through every call.
# Cache is populated by `refresh_gitea_cache()` at startup and after each
# config write via /api/gitea/config.
_runtime: dict = {"url": None, "token": None, "owner": None}


def get_effective_gitea() -> dict:
    """Return the effective Gitea connection settings, preferring the
    runtime cache (DB-backed) over env defaults."""
    s = get_settings()
    return {
        "url": (_runtime.get("url") or s.gitea_url or "").rstrip("/"),
        "token": _runtime.get("token") if _runtime.get("token") is not None else s.gitea_token,
        "owner": _runtime.get("owner") or s.gitea_owner,
    }


async def refresh_gitea_cache() -> dict:
    """Reload the runtime config from the database. Safe to call any time."""
    try:
        from database import get_db
        from models import GiteaConnection
        from sqlalchemy import select

        async for db in get_db():
            row = (await db.execute(select(GiteaConnection).where(GiteaConnection.id == 1))).scalar_one_or_none()
            if row:
                _runtime["url"] = row.url
                _runtime["token"] = row.token
                _runtime["owner"] = row.default_owner
            else:
                _runtime["url"] = None
                _runtime["token"] = None
                _runtime["owner"] = None
            break
    except Exception:
        # Table may not exist yet on first boot; fall back to env.
        _runtime["url"] = None
        _runtime["token"] = None
        _runtime["owner"] = None
    return get_effective_gitea()


def _auth_headers(cfg: dict | None = None) -> dict:
    cfg = cfg or get_effective_gitea()
    return {"Authorization": f"token {cfg['token']}"} if cfg.get("token") else {}


async def fetch_file_from_gitea(
    repo: str, file_path: str, ref: str = "main"
) -> bytes:
    """Download raw file content from Gitea."""
    cfg = get_effective_gitea()
    url = f"{cfg['url']}/api/v1/repos/{repo}/raw/{file_path}?ref={ref}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_auth_headers(cfg))
        resp.raise_for_status()
        return resp.content


async def get_file_sha(repo: str, file_path: str, ref: str = "main") -> str | None:
    """Get the SHA of an existing file (needed for updates)."""
    cfg = get_effective_gitea()
    url = f"{cfg['url']}/api/v1/repos/{repo}/contents/{file_path}?ref={ref}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_auth_headers(cfg))
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
    """Create or update a file in a Gitea repo via API."""
    cfg = get_effective_gitea()
    url = f"{cfg['url']}/api/v1/repos/{repo}/contents/{file_path}"
    headers = {**_auth_headers(cfg), "Content-Type": "application/json"}

    body = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": branch,
        "committer": {
            "name": "SCADA Studio Bot",
            "email": "scada-bot@verance.ai",
        },
    }

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
    """List files under `path_prefix` (recursively) in a Gitea repo."""
    cfg = get_effective_gitea()
    headers = _auth_headers(cfg)
    branch_url = f"{cfg['url']}/api/v1/repos/{repo}/branches/{ref}"

    async with httpx.AsyncClient(timeout=30) as client:
        br = await client.get(branch_url, headers=headers)
        if br.status_code == 404:
            commit_sha = ref
        else:
            br.raise_for_status()
            commit_sha = br.json().get("commit", {}).get("id", ref)

        tree_url = (
            f"{cfg['url']}/api/v1/repos/{repo}/git/trees/"
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


async def list_repos(owner: str | None = None, limit: int = 50, cfg: dict | None = None) -> list[dict]:
    """
    List Gitea repositories visible to the configured token.

    - If `owner` is empty/None, returns all repos accessible to the token
      (via /repos/search).
    - If `owner` is set, tries /users/{owner}/repos then /orgs/{owner}/repos.

    `cfg` lets the connection-test endpoint probe with unsaved values
    without affecting the runtime cache.
    """
    cfg = cfg or get_effective_gitea()
    if not cfg.get("url"):
        raise RuntimeError("Gitea URL not configured")
    headers = _auth_headers(cfg)
    base = cfg["url"]

    if owner:
        candidate_urls = [
            f"{base}/api/v1/users/{owner}/repos",
            f"{base}/api/v1/orgs/{owner}/repos",
        ]
    else:
        candidate_urls = [f"{base}/api/v1/repos/search"]

    out: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        url = None
        last_probe = None
        for u in candidate_urls:
            probe = await client.get(u, headers=headers, params={"limit": 1, "page": 1})
            last_probe = probe
            if probe.status_code == 200:
                url = u
                break
        if url is None:
            # Surface a helpful error
            status = last_probe.status_code if last_probe is not None else 0
            detail = ""
            try:
                detail = last_probe.text[:200] if last_probe is not None else ""
            except Exception:
                pass
            raise RuntimeError(
                f"No repos found for owner={owner!r}: last probe {status} {detail}"
            )

        params: dict = {"limit": limit, "page": 1}
        while True:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and "data" in payload:
                data = payload.get("data", [])
            else:
                data = payload if isinstance(payload, list) else []
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


async def test_connection(cfg: dict | None = None) -> dict:
    """
    Probe a Gitea instance for reachability and auth status. Returns:

        {
          "ok": bool,
          "url": str,
          "version": str | None,
          "authenticated_user": str | None,
          "error": str | None,
        }
    """
    cfg = cfg or get_effective_gitea()
    base = (cfg.get("url") or "").rstrip("/")
    result: dict = {
        "ok": False,
        "url": base,
        "version": None,
        "authenticated_user": None,
        "error": None,
    }
    if not base:
        result["error"] = "Gitea URL is empty"
        return result
    headers = _auth_headers(cfg)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            v = await client.get(f"{base}/api/v1/version")
            if v.status_code != 200:
                result["error"] = f"/version returned {v.status_code}: {v.text[:200]}"
                return result
            try:
                result["version"] = v.json().get("version")
            except Exception:
                pass

            if headers:
                u = await client.get(f"{base}/api/v1/user", headers=headers)
                if u.status_code == 200:
                    try:
                        result["authenticated_user"] = u.json().get("login")
                    except Exception:
                        pass
                elif u.status_code == 401:
                    result["error"] = "Token rejected (401 Unauthorized)"
                    return result
                else:
                    result["error"] = f"/user returned {u.status_code}: {u.text[:200]}"
                    return result

            result["ok"] = True
            return result
    except httpx.RequestError as e:
        result["error"] = f"Unreachable: {e}"
        return result

