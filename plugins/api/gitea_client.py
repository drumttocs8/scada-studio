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
    base = f"{cfg['url']}/api/v1/repos/{repo}"

    async with httpx.AsyncClient(timeout=30) as client:
        # Check repo metadata first so we can return a clear error for empty repos
        meta = await client.get(base, headers=headers)
        if meta.status_code == 404:
            raise RuntimeError(f"Repo not found: {repo}")
        meta.raise_for_status()
        meta_json = meta.json()
        if meta_json.get("empty"):
            raise RuntimeError(
                f"Repo {repo} is empty — push at least one commit before syncing."
            )
        default_branch = meta_json.get("default_branch") or ref

        # Resolve commit SHA via branch; fall back to using the branch name
        # directly as the tree ref if Gitea's branches endpoint misbehaves
        # (older Gitea versions return 500 on empty/just-initialized branches).
        commit_sha = ref or default_branch
        try:
            br = await client.get(f"{base}/branches/{ref or default_branch}", headers=headers)
            if br.status_code == 200:
                commit_sha = br.json().get("commit", {}).get("id") or commit_sha
            elif br.status_code != 404:
                # Non-404 failure: log via exception text in caller, but keep going with branch name
                pass
        except httpx.HTTPError:
            pass

        tree_url = f"{base}/git/trees/{commit_sha}?recursive=true&per_page=1000"
        tr = await client.get(tree_url, headers=headers)
        if tr.status_code >= 400:
            raise RuntimeError(
                f"Tree fetch failed ({tr.status_code}) for {repo}@{commit_sha}: {tr.text[:200]}"
            )
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


class GiteaAuthError(RuntimeError):
    """The Gitea token was missing or rejected."""


async def list_repos(owner: str | None = None, limit: int = 50, cfg: dict | None = None) -> list[dict]:
    """
    List Gitea repositories visible to the configured token.

    Every repo on the instance is one substation's RTAC, and configs are pushed
    by whoever did the engineering, so the default is to list *everything* the
    token can see rather than one account's repos. `owner` is an optional
    narrowing filter, not the normal path.

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
        # /repos/search returns everything the token can read, across all owners.
        candidate_urls = [f"{base}/api/v1/repos/search"]

    out: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        url = None
        last_probe = None
        for u in candidate_urls:
            probe = await client.get(u, headers=headers, params={"limit": 1, "page": 1})
            last_probe = probe
            # An auth failure is never "no repos here" — say so plainly rather
            # than letting it read as a bad owner filter.
            if probe.status_code in (401, 403):
                raise GiteaAuthError(
                    f"Gitea rejected the access token ({probe.status_code}). "
                    f"Check the token in Settings - it may be expired, revoked, "
                    f"or missing the 'repo' scope."
                )
            if probe.status_code == 200:
                url = u
                break
        if url is None:
            status = last_probe.status_code if last_probe is not None else 0
            detail = ""
            try:
                detail = last_probe.text[:200] if last_probe is not None else ""
            except Exception:
                pass
            if owner:
                raise RuntimeError(
                    f"No Gitea user or organisation named {owner!r} "
                    f"(probe returned {status}). Clear the Default Owner field to "
                    f"list every repo the token can see. {detail}"
                )
            raise RuntimeError(f"Gitea repo search failed ({status}). {detail}")

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

