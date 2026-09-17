"""按需取得一份披露原文；保存实际响应，供写作与 record 回读核对。"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import json
import gzip
from pathlib import Path
import re
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse
import shutil


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("p", "div", "br", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "div", "tr", "td", "th"):
            self.parts.append("\n" if tag != "td" else " | ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract_original(raw: bytes, content_type: str) -> tuple[str, str]:
    if not raw:
        raise ValueError("官方原文为空")
    if raw.startswith(b"%PDF-"):
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise ValueError("读取官方 PDF 需要 pypdf；请安装项目 documents 依赖后重试") from error
        try:
            reader = PdfReader(BytesIO(raw))
            text = "\n\n".join(f"[第{i+1}页]\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages))
        except Exception as error:
            raise ValueError("官方 PDF 无法读取") from error
        visible = re.sub(r"\[第\d+页\]|\s", "", text)
        if len(visible) < 20:
            raise ValueError("PDF 没有可回读正文；须另取可读原文，不能填写已核实数据")
        return "pdf", text
    if "pdf" in content_type.lower():
        raise ValueError("返回内容不是 PDF，不能将错误页作为官方原文")
    if "html" not in content_type.lower():
        raise ValueError("仅支持可回读 PDF/HTML 官方原文")
    if not re.search(br"<\s*(?:!doctype|html|head|body|div|p)[\s>]", raw[:4096], re.I):
        raise ValueError("官方 HTML 响应不是可读网页正文")
    charset = re.search(r"charset=[\"']?([\w-]+)", content_type, re.I)
    if not charset:
        charset = re.search(r"charset=[\"']?([\w-]+)", raw[:4096].decode("ascii", errors="ignore"), re.I)
    html = raw.decode(charset.group(1) if charset else "utf-8", errors="replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if re.search(r"403|404|forbidden|access denied|captcha|访问受限|访问拒绝|验证码", title.group(1) if title else html[:250], re.I):
        raise ValueError("官方入口返回错误页或访问验证页")
    parser = _Text(); parser.feed(html)
    text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
    if len(re.sub(r"\s", "", text)) < 20:
        raise ValueError("官方 HTML 没有可回读正文")
    return "html", text


def fetch_evidence(url: str, directory: Path, *, connection: str = "direct") -> Path:
    if not url.startswith(("https://", "http://")):
        raise ValueError("官方资料 URL 必须是 HTTP(S)")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    if connection not in {"direct", "environment"}:
        raise ValueError("connection 必须是 direct 或 environment")
    # 只限定本份官方原件的连接；不修改进程环境或模型供应商网络。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if connection == "direct" else urllib.request.build_opener()
    with opener.open(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"官方入口返回 HTTP {response.status}")
        raw = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip" or raw.startswith(b"\x1f\x8b"):
            raw = gzip.decompress(raw)
        content_type = response.headers.get("Content-Type", "")
        final_url = response.url
    kind, text = extract_original(raw, content_type)
    # 检查成功才生成证据；不允许覆盖另一份取证结果。
    directory.mkdir(parents=True, exist_ok=False)
    (directory / f"original.{kind}").write_bytes(raw)
    (directory / "text.txt").write_text(text, encoding="utf-8")
    receipt = {"schema": "official-evidence-v1", "url": url, "final_url": final_url,
               "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "http_status": 200, "connection": connection,
               "content_type": content_type, "original": f"original.{kind}", "text": "text.txt"}
    path = directory / "receipt.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_evidence(path: Path, url: str, retrieved_at: datetime) -> dict:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "official-evidence-v1" or url not in (receipt.get("url"), receipt.get("final_url")):
        raise ValueError("官方来源 URL 与实际取得原文不一致")
    stamp = datetime.fromisoformat(receipt["retrieved_at"])
    if stamp.tzinfo is None or stamp != retrieved_at:
        raise ValueError("官方来源 retrieved_at 必须使用实际取证时间")
    name = receipt.get("original")
    if name not in ("original.pdf", "original.html") or receipt.get("text") != "text.txt":
        raise ValueError("官方取证结果文件不完整")
    kind, text = extract_original((path.parent / name).read_bytes(), receipt.get("content_type", ""))
    if name != f"original.{kind}" or text != (path.parent / "text.txt").read_text(encoding="utf-8"):
        raise ValueError("官方原件与保存的提取正文不一致")
    return receipt


def announcement_url(announcement: dict) -> str:
    url = announcement.get("url") or announcement.get("announcement_url")
    pdf = announcement.get("pdf_path")
    if pdf:
        # A relative cninfo pdf_path is rooted at the static host, never the detail page.
        return urljoin("https://static.cninfo.com.cn/", str(pdf))
    if not url:
        raise ValueError("已知公告缺少原文入口")
    return str(url)


def fetch_announcement(announcement: dict, directory: Path, *, as_of: datetime,
                       existing_receipts=(), alternative_urls=()) -> Path:
    """Retrieve only one known announcement; no search or new permanent full-text store.

    Caller supplies official alternative URLs already matched to the same document.
    Reuse preserves original retrieved_at. Historical availability comes only from
    the known announcement metadata, never the current download time.
    """
    stamp = datetime.fromisoformat(str(announcement["available_at"]).replace("Z", "+00:00"))
    if as_of.tzinfo is None or stamp.tzinfo is None or stamp > as_of:
        raise ValueError("公告公开时点晚于截止或缺少时区")
    url = announcement_url(announcement)
    identity = {k: announcement.get(k) for k in ("ts_code", "announcement_id", "title", "available_at", "version")}
    attempts = []
    diagnostics = directory.with_name(directory.name + "-attempts.json")

    def record():
        diagnostics.parent.mkdir(parents=True, exist_ok=True)
        diagnostics.write_text(json.dumps({"announcement": identity, "attempts": attempts}, ensure_ascii=False, indent=2))

    def reuse(path):
        receipt = json.loads(path.read_text())
        read_evidence(path, receipt["url"], datetime.fromisoformat(receipt["retrieved_at"]))
        prior = receipt.get("announcement")
        if prior and prior != identity:
            raise ValueError("已有原件的公告身份/版本/公开时间不同")
        if not prior and url not in (receipt.get("url"), receipt.get("final_url")):
            raise ValueError("已有原件缺少可核对的同版公告身份")
        if path.parent.resolve() != directory.resolve():
            shutil.copytree(path.parent, directory)
        return directory / "receipt.json"

    if directory.exists():
        # The task's own previously fetched original is reused between stages.
        return reuse(directory / "receipt.json")
    for path in existing_receipts:
        try:
            result = reuse(Path(path))
            attempts.append({"source": str(path), "status": "reused"}); record()
            return result
        except (OSError, ValueError, KeyError) as error:
            attempts.append({"source": str(path), "status": "reuse_rejected", "detail": str(error)[:300]})
    urls = [url]
    if urlparse(url).hostname == "www.cninfo.com.cn" and "/finalpage/" in url:
        urls.append(url.replace("www.cninfo.com.cn", "static.cninfo.com.cn", 1))
    urls += list(alternative_urls)
    for candidate in dict.fromkeys(urls):
        try:
            receipt_path = fetch_evidence(candidate, directory)
            receipt = json.loads(receipt_path.read_text())
            if candidate != url and candidate in alternative_urls:
                # Same-title and issuer checks catch accidental alternative documents.
                text = re.sub(r"\s|[，,。:：（）()]", "", (directory / "text.txt").read_text())
                title = re.sub(r"\s|[，,。:：（）()]", "", str(identity.get("title") or ""))
                code = str(identity.get("ts_code") or "").split(".")[0]
                if not title or title not in text or not code or code not in text:
                    # Keep the rejected download for diagnosis, never adopt it.
                    directory.rename(directory.with_name(directory.name + f"-rejected-{len(attempts)}"))
                    raise ValueError("备用原件不能核对同一发行人及公告标题")
            receipt["announcement"] = identity
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
            attempts.append({"url": candidate, "final_url": receipt["final_url"], "http_status": 200, "status": "readable"})
            record()
            return receipt_path
        except (OSError, ValueError, urllib.error.URLError) as error:
            attempts.append({"url": candidate, "http_status": getattr(error, "code", None),
                             "status": "failed", "detail": f"{type(error).__name__}: {error}"[:300]})
            record()
    raise ValueError(f"同份公告原文仍不可取得；条款未知，诊断见 {diagnostics}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--announcement", type=Path, required=True, help="本份已知公告元数据 JSON")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--existing-receipt", action="append", default=[])
    parser.add_argument("--alternative-url", action="append", default=[])
    args = parser.parse_args()
    path = fetch_announcement(json.loads(args.announcement.read_text()), args.output_dir,
                              as_of=datetime.fromisoformat(args.as_of),
                              existing_receipts=args.existing_receipt, alternative_urls=args.alternative_url)
    print(f"evidence_path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
