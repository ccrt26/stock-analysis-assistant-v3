"""本机显式启用的既有静态发布；默认只更新本地页面。"""
import json
import os
from pathlib import Path
import subprocess


def publish_fixed_page(root: Path, page: Path) -> tuple[bool, str]:
    path = root / ".stock-ai.local.json"
    config = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    setting = config.get("web_publish") or {}
    if not setting.get("enabled"):
        return True, "public=disabled（本地模式）"
    directory = setting.get("site_dir")
    if not directory:
        return False, "public=failed（未配置既有发布仓库）"
    env = os.environ.copy()
    env["PRISM_SITE_DIR"] = str(Path(directory).expanduser())
    try:
        result = subprocess.run(["bash", str(root / "tools/publish_prism_a2.sh"), str(page)],
                                cwd=root, env=env, text=True, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"public=failed（{type(error).__name__}）；本地页面已保留"
    if result.returncode:
        return False, "public=failed；本地页面已保留；" + (result.stderr or result.stdout).strip()[-700:]
    return True, result.stdout.strip() or "public=pushed"
