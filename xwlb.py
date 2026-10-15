#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻联播文字版 T+1 抓取器与静态页生成器。

数据链路（全部为央视网公开页面与公开接口，低频访问）：
  1. 单日节目单   https://tv.cctv.com/lm/xwlb/day/YYYYMMDD.shtml
  2. 每条新闻详情页（提取 var guid 与 content_area 正文文字）
  3. 视频信息接口 https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid=<完整版guid>

用法：
  python xwlb.py fetch                          # 抓取前一日（T+1）
  python xwlb.py fetch --date 2026-10-14        # 抓取指定日期
  python xwlb.py backfill --days 7              # 回补最近 7 天（已存在则跳过）
  python xwlb.py backfill --from 2026-10-01 --to 2026-10-14
  python xwlb.py schedule                       # 内置定时器：每天 08:00 抓前一日

仅依赖 Python 3.8+ 标准库，无需 pip install。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import time
import html as htmllib
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "template"
LOG_FILE = BASE_DIR / "xwlb.log"

DEFAULT_CONFIG = {
    "output_dir": "site",            # 静态站点输出目录（相对脚本目录或绝对路径）
    "schedule_time": "08:00",        # schedule 模式每天执行时间
    "retries": 8,                    # schedule 模式失败重试次数
    "retry_wait_minutes": 10,        # schedule 模式重试间隔（分钟）
    "request_delay_seconds": 0.6,    # 相邻两次请求间隔（礼貌抓取）
    "http_timeout_seconds": 20,
}

DAY_PAGE_URL = "https://tv.cctv.com/lm/xwlb/day/{yyyymmdd}.shtml"
VIDEO_INFO_URL = "https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid={pid}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 xwlb-t1/1.0"
    ),
    "Referer": "https://tv.cctv.com/",
}

A_TAG_RE = re.compile(r'<a\s[^>]*href="(https?://tv\.cctv\.com/[^"]+\.shtml)"[^>]*>', re.I)
ALT_RE = re.compile(r'alt="([^"]*)"')
TITLE_ATTR_RE = re.compile(r'title="([^"]*)"')
DUR_RE = re.compile(r"<span>(\d{2}:\d{2}:\d{2})</span>")
SQL_RE = re.compile(r'class="sql(\d)"')
GUID_RE = re.compile(r'var\s+guid\s*=\s*"([0-9a-fA-F]{8,})"')
CONTENT_RE = re.compile(
    r'<div\s+class="content_area"\s+id="content_area"[^>]*>(.*?)</div>', re.S
)
P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
TAG_RE = re.compile(r"<[^>]+>")

log = logging.getLogger("xwlb")


# ---------------------------------------------------------------- 基础工具

def setup_logging(verbose: bool = False, to_file: bool = False) -> None:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    handlers = [logging.StreamHandler(sys.stderr)]
    if to_file:
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for h in handlers:
        h.setFormatter(fmt)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = BASE_DIR / "config.json"
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning("config.json 解析失败，使用默认配置：%s", e)
    return cfg


def resolve_output(cfg: dict, override: str | None) -> Path:
    out = Path(override) if override else Path(cfg["output_dir"])
    if not out.is_absolute():
        out = BASE_DIR / out
    return out


def parse_date_arg(s: str) -> date:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"无法识别的日期：{s}（支持 2026-10-14 或 20261014）")


def http_get(url: str, cfg: dict, retries: int = 3) -> str:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=cfg["http_timeout_seconds"]) as resp:
                raw = resp.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("gbk", errors="replace")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"请求失败 {url}：{last_err}")


# ---------------------------------------------------------------- 页面解析

def parse_day_page(page: str) -> list[dict]:
    """解析单日节目单片段，按播出顺序返回条目列表。"""
    items = []
    for chunk in re.split(r"<li[^>]*>", page)[1:]:
        m = A_TAG_RE.search(chunk)
        if not m:
            continue
        tag = m.group(0)
        am = ALT_RE.search(tag) or TITLE_ATTR_RE.search(tag)
        title = htmllib.unescape(am.group(1)).strip() if am else ""
        dur = DUR_RE.search(chunk)
        sql = SQL_RE.search(chunk)
        items.append(
            {
                "url": m.group(1),
                "title": title,
                "duration_text": dur.group(1) if dur else "",
                "is_full": bool(sql and sql.group(1) == "0"),
            }
        )
    seen, out = set(), []
    for it in items:  # 每个条目在页面中出现两次链接（图片+文字），按 URL 去重
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
    return out


def clean_title(t: str) -> str:
    return re.sub(r"^\[视频\]\s*", "", t).strip()


def extract_paragraphs(page: str) -> list[str]:
    """从详情页提取 content_area 正文，返回纯文本段落列表。"""
    m = CONTENT_RE.search(page)
    if not m:
        return []
    box = m.group(1)
    pieces = [pm.group(1) for pm in P_RE.finditer(box)]
    if not pieces:
        pieces = [box]
    result = []
    for p in pieces:
        text = TAG_RE.sub("", p)
        text = htmllib.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            result.append(text)
    return result


# ---------------------------------------------------------------- 抓取

def enrich_with_video_info(doc: dict, cfg: dict) -> None:
    """调用 getHttpVideoInfo.do 补充完整版元数据；失败不影响文字版。"""
    try:
        raw = http_get(VIDEO_INFO_URL.format(pid=doc["guid"]), cfg)
        info = json.loads(raw)
        doc["title"] = info.get("title") or doc["title"]
        doc["column"] = info.get("column") or ""
        doc["air_time"] = info.get("f_pgmtime") or ""
        doc["hls_url"] = info.get("hls_url") or ""
        total = (info.get("video") or {}).get("totalLength")
        try:
            doc["duration_seconds"] = round(float(total), 1)
        except (TypeError, ValueError):
            pass
    except Exception as e:
        log.warning("视频信息接口调用失败（不影响文字内容）：%s", e)


def fetch_day(day: date, cfg: dict) -> dict:
    yyyymmdd = day.strftime("%Y%m%d")
    day_url = DAY_PAGE_URL.format(yyyymmdd=yyyymmdd)
    log.info("抓取节目单 %s", day_url)
    items = parse_day_page(http_get(day_url, cfg))
    if not items:
        raise RuntimeError("节目单解析结果为空（页面可能尚未发布或日期无节目）")
    full = next((it for it in items if it["is_full"]), None)
    seg_items = [it for it in items if not it["is_full"]]
    log.info("节目单共 %d 项：完整版 %s，正文条目 %d 条",
             len(items), "有" if full else "无", len(seg_items))

    doc = {
        "date": day.isoformat(),
        "day_page_url": day_url,
        "title": full["title"] if full else f"《新闻联播》{yyyymmdd}",
        "episode_url": full["url"] if full else "",
        "guid": "",
        "column": "",
        "air_time": "",
        "duration_seconds": None,
        "duration_text": full["duration_text"] if full else "",
        "hls_url": "",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "segments": [],
    }

    if full:
        g = GUID_RE.search(http_get(full["url"], cfg))
        doc["guid"] = g.group(1) if g else ""
        if doc["guid"]:
            enrich_with_video_info(doc, cfg)

    for i, it in enumerate(seg_items, 1):
        seg = {
            "no": i,
            "title": clean_title(it["title"]),
            "duration_text": it["duration_text"],
            "url": it["url"],
            "guid": "",
            "paragraphs": [],
        }
        try:
            page = http_get(it["url"], cfg)
            gm = GUID_RE.search(page)
            seg["guid"] = gm.group(1) if gm else ""
            seg["paragraphs"] = extract_paragraphs(page)
        except Exception as e:
            log.warning("  第 %02d 条正文抓取失败（保留标题）：%s", i, e)
        doc["segments"].append(seg)
        log.info("  [%02d] %s（文字 %d 段，时长 %s）",
                 i, seg["title"], len(seg["paragraphs"]), seg["duration_text"])
        time.sleep(cfg["request_delay_seconds"])

    doc["segment_count"] = len(doc["segments"])
    return doc


# ---------------------------------------------------------------- 发布

def ensure_site(output: Path) -> None:
    if not TEMPLATE_DIR.exists():
        sys.exit(f"缺少模板目录：{TEMPLATE_DIR}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "data").mkdir(exist_ok=True)
    shutil.copy2(TEMPLATE_DIR / "index.html", output / "index.html")
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    for f in (TEMPLATE_DIR / "assets").iterdir():
        if f.is_file():
            shutil.copy2(f, assets / f.name)


def build_index(data_dir: Path) -> dict:
    files = [p for p in data_dir.glob("????-??-??.json")]
    dates = sorted((p.stem for p in files), reverse=True)
    newest = max((p.stat().st_mtime for p in files), default=time.time())
    idx = {
        "updated_at": datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M:%S"),
        "dates": dates,
    }
    (data_dir / "index.json").write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return idx


def publish(cfg: dict, doc: dict, output: Path) -> Path:
    ensure_site(output)
    path = output / "data" / f"{doc['date']}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    build_index(output / "data")
    return path


def run_with_retry(cfg: dict, day: date, retries: int, wait_seconds: int,
                   output: Path) -> bool:
    for attempt in range(1, retries + 1):
        try:
            doc = fetch_day(day, cfg)
            if not doc["segments"]:
                raise RuntimeError("本期没有正文条目")
            path = publish(cfg, doc, output)
            log.info("完成 %s：共 %d 条 → %s", doc["date"], doc["segment_count"], path)
            return True
        except Exception as e:
            log.warning("抓取 %s 第 %d/%d 次失败：%s", day, attempt, retries, e)
            if attempt < retries:
                time.sleep(wait_seconds)
    log.error("放弃 %s：连续 %d 次失败", day, retries)
    return False


# ---------------------------------------------------------------- 命令

def next_run_at(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def cmd_fetch(cfg: dict, args) -> int:
    day = parse_date_arg(args.date) if args.date else date.today() - timedelta(days=1)
    output = resolve_output(cfg, args.output)
    ok = run_with_retry(cfg, day, retries=args.retries, wait_seconds=5, output=output)
    return 0 if ok else 1


def cmd_backfill(cfg: dict, args) -> int:
    today = date.today()
    if args.date_from and args.date_to:
        start, end = parse_date_arg(args.date_from), parse_date_arg(args.date_to)
    else:
        days = args.days if args.days else 7
        start, end = today - timedelta(days=days), today - timedelta(days=1)
    if start > end:
        start, end = end, start
    output = resolve_output(cfg, args.output)
    days_list = []
    d = end
    while d >= start:
        days_list.append(d)
        d -= timedelta(days=1)
    ok = 0
    for day in days_list:
        if (output / "data" / f"{day.isoformat()}.json").exists() and not args.force:
            log.info("跳过 %s（数据已存在）", day)
            ok += 1
            continue
        if run_with_retry(cfg, day, retries=2, wait_seconds=5, output=output):
            ok += 1
        time.sleep(2)  # 逐日回补，保持低频
    log.info("回补结束：%d/%d 天成功（范围 %s ~ %s）", ok, len(days_list), start, end)
    return 0 if ok == len(days_list) else 1


def cmd_schedule(cfg: dict, args) -> int:
    if args.time:
        cfg["schedule_time"] = args.time
    log.info("进入定时模式：每天 %s 抓取前一日内容，日志同时写入 %s（Ctrl+C 退出）",
             cfg["schedule_time"], LOG_FILE)
    while True:
        target = next_run_at(cfg["schedule_time"])
        wait_s = (target - datetime.now()).total_seconds()
        log.info("下次执行：%s（约 %.1f 小时后）", target.strftime("%Y-%m-%d %H:%M"), wait_s / 3600)
        try:
            time.sleep(max(wait_s, 1))
        except KeyboardInterrupt:
            log.info("已手动停止")
            return 0
        yesterday = date.today() - timedelta(days=1)
        output = resolve_output(cfg, None)
        run_with_retry(cfg, yesterday,
                       retries=int(cfg["retries"]),
                       wait_seconds=int(cfg["retry_wait_minutes"]) * 60,
                       output=output)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # 保证 Windows GBK 控制台下中文日志不乱码
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="新闻联播文字版 T+1 抓取与静态页生成")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="抓取前一日（或指定日期）内容")
    p.add_argument("--date", help="指定日期，如 2026-10-14 或 20261014；默认前一日")
    p.add_argument("--retries", type=int, default=3, help="失败重试次数（默认 3）")
    p.add_argument("--output", help="覆盖输出目录")

    p = sub.add_parser("backfill", help="批量回补历史日期（已存在的跳过）")
    p.add_argument("--days", type=int, help="回补最近 N 天（不含今天），默认 7")
    p.add_argument("--from", dest="date_from", help="起始日期 2026-10-01")
    p.add_argument("--to", dest="date_to", help="结束日期 2026-10-14")
    p.add_argument("--force", action="store_true", help="已存在的也重新抓取")
    p.add_argument("--output", help="覆盖输出目录")

    p = sub.add_parser("schedule", help="内置定时器：每天定时抓取前一日")
    p.add_argument("--time", help="每天执行时间 HH:MM，覆盖 config.json")

    args = parser.parse_args()
    setup_logging(verbose=args.verbose, to_file=(args.cmd == "schedule"))
    cfg = load_config()

    if args.cmd == "fetch":
        sys.exit(cmd_fetch(cfg, args))
    elif args.cmd == "backfill":
        sys.exit(cmd_backfill(cfg, args))
    elif args.cmd == "schedule":
        sys.exit(cmd_schedule(cfg, args))


if __name__ == "__main__":
    main()
