"""Yahoo Finance weekly cup-and-handle screening for TSE common stocks."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET

from mention_info.cli import post_to_slack

JPX_PAGE_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
JPX_XLSX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
JPX_MARKETS = {"プライム（内国株式）", "スタンダード（内国株式）", "グロース（内国株式）"}
STATE_PATH = Path(__file__).resolve().parents[2] / "tasks/japanese-cup-handle/state.json"
MAX_SYMBOLS_PER_RUN = 100
MAX_WORKERS = 5
WEEK_SECONDS = 7 * 24 * 60 * 60

_XLSX_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    market: str


@dataclass(frozen=True)
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


def _fetch(url: str, *, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mention-info/0.1 (cup-handle screening)"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def load_jpx_stocks() -> tuple[list[Stock], str]:
    """Fetch and parse the latest official JPX listed-issues workbook."""
    workbook = _fetch(JPX_XLSX_URL)
    with zipfile.ZipFile(__import__("io").BytesIO(workbook)) as archive:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(node.text or "" for node in item.findall(".//m:t", _XLSX_NS)) for item in root.findall("m:si", _XLSX_NS)]

        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        relation_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relations = {r.attrib["Id"]: r.attrib["Target"] for r in relation_root.findall("p:Relationship", _XLSX_NS)}
        first_sheet = workbook_root.find("m:sheets/m:sheet", _XLSX_NS)
        if first_sheet is None:
            raise ValueError("JPX workbook has no worksheets")
        target = relations[first_sheet.attrib[f"{{{_XLSX_NS['r']}}}id"]]
        sheet_path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        sheet_root = ET.fromstring(archive.read(sheet_path))
        date_as_of = ""
        stocks: list[Stock] = []

        for row in sheet_root.findall(".//m:sheetData/m:row", _XLSX_NS):
            values: dict[str, str] = {}
            for cell in row.findall("m:c", _XLSX_NS):
                column = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
                if not column:
                    continue
                value_node = cell.find("m:v", _XLSX_NS)
                value = value_node.text if value_node is not None else ""
                if cell.attrib.get("t") == "s" and value:
                    value = strings[int(value)]
                values[column.group()] = value
            if values.get("A", "").isdigit() and len(values["A"]) == 8 and not date_as_of:
                date_as_of = values["A"]
            market = values.get("D", "")
            if market in JPX_MARKETS and values.get("B"):
                stocks.append(Stock(values["B"].strip(), values.get("C", "").strip(), market))

    stocks.sort(key=lambda stock: stock.code)
    if not stocks:
        raise ValueError("No TSE domestic common stocks found in JPX workbook")
    return stocks, date_as_of


def fetch_weekly_bars(stock: Stock, *, now: int | None = None) -> list[Bar]:
    """Fetch Yahoo Finance's weekly OHLC data and validate its ticker and freshness."""
    end = int(now if now is not None else time.time())
    start = end - 2 * 366 * 24 * 60 * 60
    symbol = f"{stock.code}.T"
    query = urllib.parse.urlencode({"period1": start, "period2": end, "interval": "1wk", "events": "div,splits"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{query}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            data = json.loads(_fetch(url, timeout=20))
            chart = data.get("chart", {})
            if chart.get("error"):
                raise ValueError(str(chart["error"]))
            result = (chart.get("result") or [None])[0]
            if not result or result.get("meta", {}).get("symbol") != symbol:
                raise ValueError(f"Yahoo Finance symbol mismatch for {symbol}")
            timestamps = result.get("timestamp") or []
            quote = result.get("indicators", {}).get("quote", [{}])[0]
            bars: list[Bar] = []
            for index, stamp in enumerate(timestamps):
                fields = {name: (quote.get(name) or [None] * len(timestamps))[index] for name in ("open", "high", "low", "close", "volume")}
                if any(fields[name] is None or not math.isfinite(float(fields[name])) for name in ("open", "high", "low", "close")):
                    continue
                bars.append(Bar(int(stamp), float(fields["open"]), float(fields["high"]), float(fields["low"]), float(fields["close"]), float(fields["volume"]) if fields["volume"] is not None else None))
            if len(bars) < 40:
                raise ValueError(f"Only {len(bars)} valid weekly bars for {symbol}")
            if end - bars[-1].timestamp > 21 * 24 * 60 * 60:
                raise ValueError(f"Latest weekly bar is stale for {symbol}")
            return bars
        except (ValueError, KeyError, IndexError, TypeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Could not fetch weekly bars for {symbol}: {last_error}")


def _local_peak(bars: list[Bar], index: int) -> bool:
    left, right = max(0, index - 2), min(len(bars), index + 3)
    return bars[index].high >= max(bar.high for bar in bars[left:right])


def detect_cup_and_handle(bars: list[Bar]) -> dict[str, Any] | None:
    """Return the best recent candidate matching the prompt's numeric criteria."""
    count = len(bars)
    candidates: list[dict[str, Any]] = []
    left_start = max(26, count - 53)
    latest_right = count - 2  # Require at least one complete weekly bar after the right rim.
    for left_index in range(left_start, count - 13):
        if not _local_peak(bars, left_index):
            continue
        for right_index in range(max(left_index + 12, count - 9), min(count - 1, left_index + 53)):
            weeks_after_rim = count - 1 - right_index
            if not 1 <= weeks_after_rim <= 8 or right_index > latest_right or not _local_peak(bars, right_index):
                continue
            cup = bars[left_index + 1:right_index]
            if not cup:
                continue
            trough_index = min(range(left_index + 1, right_index), key=lambda index: bars[index].low)
            left_price, right_price = bars[left_index].high, bars[right_index].high
            bottom_price = bars[trough_index].low
            depth = (left_price - bottom_price) / left_price
            if not 0.12 <= depth <= 0.35:
                continue
            if abs(right_price - left_price) / min(right_price, left_price) > 0.05:
                continue
            near_bottom = [index for index in range(left_index + 1, right_index) if bars[index].low <= bottom_price * 1.05]
            if len(near_bottom) < 2 or bars[near_bottom[-1]].timestamp - bars[near_bottom[0]].timestamp < 4 * WEEK_SECONDS:
                continue
            handle_bars = bars[right_index + 1:]
            handle_low = min(bar.low for bar in handle_bars)
            pullback = (right_price - handle_low) / right_price
            if not 0.03 <= pullback <= 0.15:
                continue
            if handle_low <= (left_price + bottom_price) / 2:
                continue
            last = bars[-1]
            if abs(last.close - left_price) / left_price > 0.05:
                continue
            if (last.close - handle_low) / handle_low < 0.02:
                continue
            prior = bars[max(0, left_index - 52):left_index]
            if len(prior) < 26 or min(bar.low for bar in prior) > left_price / 1.30:
                continue
            candidates.append({
                "left_rim": {"date": _date(bars[left_index].timestamp), "price": round(left_price, 4)},
                "right_rim": {"date": _date(bars[right_index].timestamp), "price": round(right_price, 4)},
                "cup_bottom": {"date": _date(bars[trough_index].timestamp), "price": round(bottom_price, 4)},
                "depth_pct": round(depth * 100, 2),
                "handle_low": round(handle_low, 4),
                "handle_pullback_pct": round(pullback * 100, 2),
                "latest_close": round(last.close, 4),
                "latest_week": _date(last.timestamp),
                "status": "candidate" if (last.close >= right_price * 0.97) else "forming",
            })
    return max(candidates, key=lambda item: item["right_rim"]["date"]) if candidates else None


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat()


def _initial_state() -> dict[str, Any]:
    return {"schema_version": 1, "next_index": 0, "next_start_code": None, "universe_source": JPX_PAGE_URL, "universe_retrieved_on": None, "universe_count": None, "last_run_at": None, "cycle": 1, "notified_candidates": []}


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return _initial_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schema_version") != 1 or not isinstance(state.get("next_index"), int) or state["next_index"] < 0 or not isinstance(state.get("notified_candidates"), list):
            raise ValueError("state.json schema is invalid")
        return state
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read state file: {exc}") from exc


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _format_candidate(stock: Stock, pattern: dict[str, Any]) -> str:
    chart_url = f"https://finance.yahoo.co.jp/quote/{stock.code}.T/chart?frm=wkly&trm=2y&scl=stndrd&styl=cndl&evnts=volume&ovrIndctr=sma%2Cmma%2Clma&addIndctr=&compare="
    return (
        f"*{stock.name}（{stock.code}）* — {pattern['status']}\n"
        f"左右リム: {pattern['left_rim']['price']}円（{pattern['left_rim']['date']}） / {pattern['right_rim']['price']}円（{pattern['right_rim']['date']}）\n"
        f"カップ底: {pattern['cup_bottom']['price']}円（{pattern['cup_bottom']['date']}）、深さ {pattern['depth_pct']}%\n"
        f"ハンドル押し幅: {pattern['handle_pullback_pct']}%、安値 {pattern['handle_low']}円\n"
        f"直近週終値: {pattern['latest_close']}円（{pattern['latest_week']}）\n"
        f"条件: 先行上昇30%以上、両リム差5%以内、丸い底、直近8週以内の浅い押しを確認\n"
        f"<{chart_url}|Yahoo!ファイナンスの週足チャート>"
    )


def run_once(*, state_path: Path = STATE_PATH, now: int | None = None, notify: bool = True) -> dict[str, Any]:
    state = load_state(state_path)
    stocks, as_of = load_jpx_stocks()
    start = state["next_index"]
    if start >= len(stocks):
        start = 0
        state["cycle"] = int(state.get("cycle", 1)) + 1
    batch = stocks[start:start + MAX_SYMBOLS_PER_RUN]
    if not batch:
        raise ValueError("JPX universe is empty at the current cursor")

    results: dict[str, tuple[list[Bar] | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_stock = {pool.submit(fetch_weekly_bars, stock, now=now): stock for stock in batch}
        for future in as_completed(future_to_stock):
            stock = future_to_stock[future]
            try:
                results[stock.code] = (future.result(), None)
            except Exception as exc:  # Keep the cursor at the batch start if any ticker fails.
                results[stock.code] = (None, str(exc))

    failures = [stock.code for stock in batch if results[stock.code][1]]
    if failures:
        return {"processed": len(batch) - len(failures), "attempted": len(batch), "failures": failures, "candidates": [], "notified": False, "state_advanced": False, "next_index": start, "next_code": batch[0].code, "universe_count": len(stocks), "universe_as_of": as_of}

    existing = {(item.get("code"), item.get("cycle")) for item in state["notified_candidates"]}
    patterns: list[tuple[Stock, dict[str, Any]]] = []
    for stock in batch:
        pattern = detect_cup_and_handle(results[stock.code][0] or [])
        if pattern and (stock.code, state["cycle"]) not in existing:
            patterns.append((stock, pattern))

    posted = False
    if patterns and notify:
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook:
            raise ValueError("SLACK_WEBHOOK_URL is required to notify about candidates")
        message = ":chart_with_upwards_trend: *カップ・アンド・ハンドル候補（日本株・週足）*\n" + "\n\n".join(_format_candidate(stock, pattern) for stock, pattern in patterns)
        post_to_slack(webhook, message)
        posted = True

    next_index = start + len(batch)
    next_cycle = state["cycle"]
    if next_index >= len(stocks):
        next_index = 0
        next_cycle += 1
    if next_cycle != state["cycle"]:
        state["notified_candidates"] = [item for item in state["notified_candidates"] if item.get("cycle", 0) >= next_cycle - 1]
    run_time = datetime.now(timezone.utc).isoformat()
    if posted:
        state["notified_candidates"].extend({"code": stock.code, "detected_at": run_time, "cycle": state["cycle"]} for stock, _ in patterns)
    state.update({"schema_version": 1, "next_index": next_index, "next_start_code": stocks[next_index].code if next_index < len(stocks) else stocks[0].code, "universe_source": JPX_PAGE_URL, "universe_retrieved_on": datetime.now(timezone.utc).date().isoformat(), "universe_data_as_of": as_of, "universe_count": len(stocks), "last_run_at": run_time, "cycle": next_cycle})
    save_state(state, state_path)
    return {"processed": len(batch), "attempted": len(batch), "failures": [], "candidates": [{"code": stock.code, "name": stock.name, **pattern} for stock, pattern in patterns], "notified": posted, "state_advanced": True, "next_index": next_index, "next_code": state["next_start_code"], "universe_count": len(stocks), "universe_as_of": as_of}


def main() -> int:
    try:
        result = run_once()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["failures"]:
            print("一部銘柄のデータ取得に失敗したため、進捗を更新していません。", file=sys.stderr)
            return 1
        if not result["candidates"]:
            print("条件に合う候補はありません。Slack通知はありません。", file=sys.stderr)
        elif result["notified"]:
            print(f"候補{len(result['candidates'])}件をSlackに通知しました。", file=sys.stderr)
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ET.ParseError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
