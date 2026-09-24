#!/usr/bin/env python3
"""Private iconfont session storage and API-first automation helpers.

The CLI never prints cookie values. Import browser storage state from a file,
then use authenticated API commands without passing credentials on argv.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional


BASE_URL = "https://www.iconfont.cn"
AUTH_COOKIE_NAME = "EGG_SESS_ICONFONT"
CSRF_COOKIE_NAME = "ctoken"
PERSISTED_COOKIE_NAMES = {AUTH_COOKIE_NAME, CSRF_COOKIE_NAME}
DEFAULT_SESSION_PATH = (
    Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    / "private"
    / "files"
    / "iconfont"
    / "session.json"
)

FALLBACK_ENDPOINTS: Dict[str, Dict[str, str]] = {
    "add_icons": {"url": "/api/project/addIcons.json", "method": "POST"},
    "project_lists": {"url": "/api/user/myprojects.json", "method": "GET"},
    "project_detail": {"url": "/api/project/detail.json", "method": "GET"},
    "search_icons": {"url": "/api/icon/search.json", "method": "POST"},
    "refresh_code": {"url": "/api/project/cdn.json", "method": "POST"},
}


class IconfontError(RuntimeError):
    pass


def _json_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _atomic_private_write(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_private_directory(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=".iconfont-session-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _extract_cookies(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        cookies = raw
    elif isinstance(raw, dict) and isinstance(raw.get("cookies"), list):
        cookies = raw["cookies"]
    else:
        raise IconfontError("Storage state must contain a cookies array")

    normalized: List[Dict[str, Any]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name", "")).strip()
        value = str(cookie.get("value", ""))
        domain = str(cookie.get("domain", "")).strip()
        if not name or not domain:
            continue
        if name not in PERSISTED_COOKIE_NAMES:
            continue
        normalized_domain = domain.lstrip(".").lower()
        if normalized_domain != "iconfont.cn" and not normalized_domain.endswith(".iconfont.cn"):
            continue
        normalized.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": str(cookie.get("path") or "/"),
                "expires": cookie.get("expires", -1),
                "httpOnly": bool(cookie.get("httpOnly", False)),
                "secure": bool(cookie.get("secure", False)),
                "sameSite": str(cookie.get("sameSite") or "Lax"),
            }
        )
    if not normalized:
        raise IconfontError("No valid cookies were found in storage state")
    return normalized


def import_storage_state(source: Path, target: Path = DEFAULT_SESSION_PATH) -> Dict[str, Any]:
    raw = _json_load(source)
    cookies = _extract_cookies(raw)
    payload = {
        "version": 1,
        "service": "iconfont",
        "base_url": BASE_URL,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cookies": cookies,
    }
    _atomic_private_write(target, payload)
    return {
        "path": str(target),
        "cookie_count": len(cookies),
        "authenticated_cookie_present": any(c["name"] == AUTH_COOKIE_NAME for c in cookies),
    }


def load_session(path: Path = DEFAULT_SESSION_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise IconfontError(f"Session file does not exist: {path}")
    raw = _json_load(path)
    if not isinstance(raw, dict) or not isinstance(raw.get("cookies"), list):
        raise IconfontError("Session file has an invalid schema")
    return raw


def _cookie_expired(cookie: Mapping[str, Any], now: Optional[float] = None) -> bool:
    expires = cookie.get("expires", -1)
    try:
        expires_float = float(expires)
    except (TypeError, ValueError):
        return False
    if expires_float <= 0:
        return False
    return expires_float <= (time.time() if now is None else now)


def session_status(path: Path = DEFAULT_SESSION_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "authenticated_cookie_present": False,
            "authenticated_cookie_expired": None,
            "cookie_names": [],
        }
    session = load_session(path)
    cookies = session["cookies"]
    auth = next((c for c in cookies if c.get("name") == AUTH_COOKIE_NAME), None)
    return {
        "exists": True,
        "path": str(path),
        "saved_at": session.get("saved_at"),
        "authenticated_cookie_present": auth is not None,
        "authenticated_cookie_expired": _cookie_expired(auth) if auth else None,
        "cookie_names": sorted({str(c.get("name")) for c in cookies if c.get("name")}),
        "file_mode": oct(stat.S_IMODE(path.stat().st_mode)),
    }


def _domain_matches(hostname: str, cookie_domain: str) -> bool:
    domain = cookie_domain.lstrip(".").lower()
    hostname = hostname.lower()
    return hostname == domain or hostname.endswith("." + domain)


def build_cookie_header(cookies: Iterable[Mapping[str, Any]], url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""
    path = parsed.path or "/"
    secure = parsed.scheme == "https"
    values: List[str] = []
    for cookie in cookies:
        if _cookie_expired(cookie):
            continue
        if not _domain_matches(hostname, str(cookie.get("domain", ""))):
            continue
        cookie_path = str(cookie.get("path") or "/")
        if not path.startswith(cookie_path):
            continue
        if cookie.get("secure") and not secure:
            continue
        name = str(cookie.get("name", ""))
        if name:
            values.append(f"{name}={cookie.get('value', '')}")
    return "; ".join(values)


def find_csrf_token(cookies: Iterable[Mapping[str, Any]]) -> str:
    for cookie in cookies:
        if cookie.get("name") == CSRF_COOKIE_NAME and not _cookie_expired(cookie):
            return str(cookie.get("value", ""))
    return ""


def build_add_icons_payload(
    project_id: str,
    icons: Iterable[Mapping[str, Any]],
    csrf_token: str,
    now_ms: Optional[int] = None,
) -> Dict[str, str]:
    pairs = []
    for icon in icons:
        icon_id = str(icon.get("id") or icon.get("icon_id") or "").strip()
        source_project_id = str(icon.get("project_id") or icon.get("projectId") or "-1").strip()
        if not icon_id:
            raise IconfontError("Every icon requires an id")
        pairs.append(f"{icon_id}|{source_project_id}")
    if not pairs:
        raise IconfontError("At least one icon is required")
    return {
        "pid": str(project_id),
        "ids": ",".join(pairs),
        "ctoken": csrf_token,
        "t": str(now_ms if now_ms is not None else int(time.time() * 1000)),
    }


_ENDPOINT_PATTERN = re.compile(
    r'name:["\'](?P<name>[^"\']+)["\']\s*,\s*'
    r'url:["\'](?P<url>[^"\']+)["\']'
    r'(?:\s*,\s*method:["\'](?P<method>[^"\']+)["\'])?'
)


def parse_endpoint_map(source: str) -> Dict[str, Dict[str, str]]:
    endpoints: Dict[str, Dict[str, str]] = {}
    for match in _ENDPOINT_PATTERN.finditer(source):
        endpoints[match.group("name")] = {
            "url": match.group("url"),
            "method": (match.group("method") or "GET").upper(),
        }
    return endpoints


def _fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36",
            "Accept": "text/html,application/javascript,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def discover_current_endpoints() -> Dict[str, Any]:
    home = _fetch_text(BASE_URL + "/")
    match = re.search(
        r'(?://|https://)g\.alicdn\.com/mm/iconfont-plus-bp/([^/]+)/app/boot\.js', home
    )
    if not match:
        raise IconfontError("Could not locate the current iconfont frontend version")
    version = match.group(1)
    manager_url = f"https://g.alicdn.com/mm/iconfont-plus-bp/{version}/app/models/manager.js"
    endpoint_map = parse_endpoint_map(_fetch_text(manager_url))
    required = ["add_icons", "project_lists", "project_detail", "search_icons", "refresh_code"]
    missing = [name for name in required if name not in endpoint_map]
    if missing:
        raise IconfontError("Current frontend bundle is missing expected endpoints: " + ", ".join(missing))
    return {
        "frontend_version": version,
        "manager_url": manager_url,
        "endpoints": {name: endpoint_map[name] for name in required},
    }


class IconfontClient:
    def __init__(self, session_path: Path = DEFAULT_SESSION_PATH):
        self.session_path = session_path
        self.session = load_session(session_path)
        self.cookies = self.session["cookies"]
        auth = next((c for c in self.cookies if c.get("name") == AUTH_COOKIE_NAME), None)
        if not auth or _cookie_expired(auth):
            raise IconfontError("Iconfont login is missing or expired; refresh the browser session")

    def _request(
        self,
        endpoint: Mapping[str, str],
        params: Optional[MutableMapping[str, Any]] = None,
    ) -> Any:
        method = endpoint.get("method", "GET").upper()
        values: MutableMapping[str, Any] = dict(params or {})
        values.setdefault("t", str(int(time.time() * 1000)))
        csrf_token = find_csrf_token(self.cookies)
        if csrf_token:
            values.setdefault("ctoken", csrf_token)
        encoded = urllib.parse.urlencode(values).encode("utf-8")
        url = urllib.parse.urljoin(BASE_URL, endpoint["url"])
        data = encoded if method != "GET" else None
        if method == "GET":
            url += ("&" if "?" in url else "?") + encoded.decode("utf-8")
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": build_cookie_header(self.cookies, url),
            "Origin": BASE_URL,
            "Referer": BASE_URL + "/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
        }
        if csrf_token and method != "GET":
            headers["x-csrf-token"] = csrf_token
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise IconfontError("Iconfont authentication was rejected; refresh the browser session") from exc
            raise IconfontError(f"Iconfont request failed with HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise IconfontError(f"Iconfont request failed: {exc.reason}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IconfontError("Iconfont returned a non-JSON response; rediscover the browser request") from exc
        if isinstance(payload, dict) and payload.get("code") not in (None, 200):
            message = str(payload.get("message") or payload.get("error_code") or "unknown error")
            if "LOGIN REQUIRED" in message.upper():
                raise IconfontError("Iconfont login expired; refresh the browser session")
            raise IconfontError(f"Iconfont API rejected the request: {message}")
        return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    def projects(self) -> List[Dict[str, Any]]:
        data = self._request(FALLBACK_ENDPOINTS["project_lists"], {"page": 1}) or {}
        projects = list(data.get("ownProjects") or []) + list(data.get("corpProjects") or [])
        return [
            {
                "id": str(project.get("id", "")),
                "name": project.get("name", ""),
                "icon_count": project.get("icon_count", 0),
                "updated_at": project.get("updated_at", ""),
            }
            for project in projects
        ]

    def search(self, query: str, page: int = 1, page_size: int = 54) -> Dict[str, Any]:
        data = self._request(
            FALLBACK_ENDPOINTS["search_icons"],
            {
                "q": query,
                "sortType": "updated_at",
                "page": page,
                "pageSize": page_size,
                "fromCollection": "-1",
                "fills": "",
            },
        ) or {}
        icons = []
        for icon in data.get("icons") or []:
            icons.append(
                {
                    "id": str(icon.get("id") or icon.get("icon_id") or ""),
                    "name": icon.get("name", ""),
                    "project_id": str(icon.get("projectId") or icon.get("project_id") or "-1"),
                    "font_class": icon.get("font_class"),
                    "unicode": icon.get("unicode"),
                    "tags": icon.get("tags") or [],
                    "show_svg": icon.get("show_svg") or icon.get("svg") or "",
                }
            )
        return {"total": data.get("total", len(icons)), "page": page, "icons": icons}

    def project_detail(self, project_id: str) -> Dict[str, Any]:
        return self._request(FALLBACK_ENDPOINTS["project_detail"], {"pid": project_id}) or {}

    def project_icons(self, project_id: str) -> List[Dict[str, Any]]:
        data = self.project_detail(project_id)
        return list(data.get("icons") or [])

    def add_icons(self, project_id: str, icons: List[Dict[str, str]]) -> Dict[str, Any]:
        existing = {
            str(icon.get("id") or icon.get("icon_id") or "") for icon in self.project_icons(project_id)
        }
        missing = [icon for icon in icons if str(icon.get("id")) not in existing]
        if not missing:
            return {"added": [], "already_present": sorted(existing.intersection({i["id"] for i in icons}))}
        payload = build_add_icons_payload(project_id, missing, find_csrf_token(self.cookies))
        self._request(FALLBACK_ENDPOINTS["add_icons"], payload)
        after = {
            str(icon.get("id") or icon.get("icon_id") or "") for icon in self.project_icons(project_id)
        }
        added_ids = [str(icon["id"]) for icon in missing]
        unverified = [icon_id for icon_id in added_ids if icon_id not in after]
        if unverified:
            raise IconfontError("Add request returned but verification failed for icon ids: " + ", ".join(unverified))
        return {
            "added": added_ids,
            "already_present": sorted(existing.intersection({i["id"] for i in icons})),
        }

    def refresh_code(self, project_id: str) -> Any:
        return self._request(FALLBACK_ENDPOINTS["refresh_code"], {"pid": project_id})


def _parse_icon_spec(value: str) -> Dict[str, str]:
    icon_id, separator, project_id = value.partition("|")
    if not icon_id.strip():
        raise argparse.ArgumentTypeError("Icon spec must be ID or ID|SOURCE_PROJECT_ID")
    return {"id": icon_id.strip(), "project_id": project_id.strip() if separator else "-1"}


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private iconfont session and API helper")
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION_PATH)
    commands = parser.add_subparsers(dest="command", required=True)

    import_cmd = commands.add_parser("import-storage-state")
    import_cmd.add_argument("source", type=Path)
    import_cmd.add_argument("--delete-source", action="store_true")

    commands.add_parser("status")
    commands.add_parser("discover")
    commands.add_parser("projects")

    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--page-size", type=int, default=54)

    detail = commands.add_parser("project-detail")
    detail.add_argument("project_id")

    add = commands.add_parser("add")
    add.add_argument("project_id")
    add.add_argument("icons", nargs="+", type=_parse_icon_spec)

    refresh = commands.add_parser("refresh-code")
    refresh.add_argument("project_id")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import-storage-state":
            result = import_storage_state(args.source, args.session)
            if args.delete_source:
                args.source.unlink(missing_ok=True)
            _print_json(result)
            return 0
        if args.command == "status":
            _print_json(session_status(args.session))
            return 0
        if args.command == "discover":
            _print_json(discover_current_endpoints())
            return 0
        client = IconfontClient(args.session)
        if args.command == "projects":
            _print_json(client.projects())
        elif args.command == "search":
            _print_json(client.search(args.query, args.page, args.page_size))
        elif args.command == "project-detail":
            _print_json(client.project_detail(args.project_id))
        elif args.command == "add":
            _print_json(client.add_icons(args.project_id, args.icons))
        elif args.command == "refresh-code":
            _print_json(client.refresh_code(args.project_id))
        return 0
    except (IconfontError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
