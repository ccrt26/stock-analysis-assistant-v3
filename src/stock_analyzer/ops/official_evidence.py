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


def fetch_evidence(url: str, directory: Path) -> Path:
    if not url.startswith(("https://", "http://")):
        raise ValueError("官方资料 URL 必须是 HTTP(S)")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
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
