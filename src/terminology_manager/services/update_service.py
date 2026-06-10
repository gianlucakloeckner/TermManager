from __future__ import annotations

import json
import platform
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class UpdateCheckResult:
    update_available: bool
    current_version: str
    latest_version: str
    release_url: str
    download_url: str
    release_notes: str


class GitHubUpdateService:
    def __init__(self, owner: str, repo: str) -> None:
        self.owner = owner.strip()
        self.repo = repo.strip()

    def check_for_update(self, current_version: str) -> UpdateCheckResult:
        if not self.owner or not self.repo:
            raise ValueError("GitHub owner/repo not configured")
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "terminology-manager-updater",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            # OSError deckt URLError und Timeouts ab, ValueError den JSON-Parse-Fehler.
            raise RuntimeError(f"Update-Prüfung fehlgeschlagen: {exc}") from exc

        latest_tag = str(payload.get("tag_name", "")).strip() or "v0.0.0"
        latest_version = latest_tag.lstrip("vV")
        release_url = str(payload.get("html_url", "")).strip()
        notes = str(payload.get("body", "") or "")
        download_url = self._select_asset_url(payload.get("assets", []), release_url)
        update_available = self._version_tuple(latest_version) > self._version_tuple(
            current_version
        )
        return UpdateCheckResult(
            update_available=update_available,
            current_version=current_version,
            latest_version=latest_version,
            release_url=release_url,
            download_url=download_url,
            release_notes=notes,
        )

    def _select_asset_url(self, assets: Any, fallback: str) -> str:
        if not isinstance(assets, list):
            return fallback
        system = platform.system().lower()
        preferred_tokens: list[str]
        if "windows" in system:
            preferred_tokens = ["windows", ".exe", ".zip"]
        elif "darwin" in system or "mac" in system:
            preferred_tokens = ["macos", ".dmg", ".zip"]
        else:
            preferred_tokens = [".zip"]

        best_url = fallback
        for token in preferred_tokens:
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                name = str(asset.get("name", "")).lower()
                if token in name:
                    url = str(asset.get("browser_download_url", "")).strip()
                    if url:
                        return url
                if not best_url:
                    url = str(asset.get("browser_download_url", "")).strip()
                    if url:
                        best_url = url
        return best_url

    def _version_tuple(self, raw: str) -> tuple[int, int, int]:
        parts = re.findall(r"\d+", raw)
        nums = [int(p) for p in parts[:3]]
        while len(nums) < 3:
            nums.append(0)
        return (nums[0], nums[1], nums[2])

    def download_asset(
        self,
        url: str,
        target_dir: Path,
        progress_cb: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        parsed = urllib.parse.urlparse(url)
        file_name = Path(parsed.path).name or "update_download.bin"
        out_path = target_dir / file_name
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "terminology-manager-updater",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length", "0") or "0")
            read = 0
            with out_path.open("wb") as out:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Download abgebrochen")
                    chunk = response.read(1024 * 64)
                    if not chunk:
                        break
                    out.write(chunk)
                    read += len(chunk)
                    if progress_cb is not None:
                        progress_cb(read, total)
        return out_path
