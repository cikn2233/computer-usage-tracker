from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.config import WEB_DIR, AppConfig
from app.database import Database
from app.ui.plotly_charts import (
    donut_figure,
    hbar_figure,
    pie_figure,
    usage_figure,
)
from app.utils import event_type_label, human_duration, human_size

_PIE_COLORS = ["#4080FF", "#57B894", "#F0A868", "#5AA9E6", "#A0A8B8", "#E0655A"]


def _bounds(start: date, end: date) -> tuple[str, str]:
    return f"{start.isoformat()} 00:00:00", f"{(end + timedelta(days=1)).isoformat()} 00:00:00"


def _clean_row(values: list) -> list:
    return [ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v for v in values]


def _clean(text: str) -> str:
    return ILLEGAL_CHARACTERS_RE.sub("", str(text))


def _summary(db: Database, config: AppConfig, start: date, end: date) -> dict:
    a, i, l = db.usage_totals(start.isoformat(), end.isoformat())
    start_iso, end_iso = _bounds(start, end)
    groups = db.group_counts_between(start_iso, end_iso, config.office_extensions)
    bin_, bout_ = db.network_host_totals(start.isoformat(), end.isoformat())
    return {
        "active": a, "idle": i, "lock": l, "total": a + i + l,
        "office": groups.get("office", 0), "other": groups.get("other", 0),
        "all_files": groups.get("all", 0), "bytes_in": bin_, "bytes_out": bout_,
    }


def export_excel(db: Database, config: AppConfig, path: str, start: date, end: date) -> int:
    start_iso, end_iso = _bounds(start, end)
    summary = _summary(db, config, start, end)
    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="4080FF")
    header_font = Font(color="FFFFFF", bold=True, name="Microsoft YaHei")
    body_font = Font(name="Microsoft YaHei", size=10)

    def style_header(ws, ncols):
        for col in range(1, ncols + 1):
            cell = ws.cell(row=1, column=col)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center")
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "概览"
    ws.append(["指标", "数值"])
    rows = [
        ("统计范围", f"{start.isoformat()} ~ {end.isoformat()}"),
        ("总使用时长", human_duration(summary["total"])),
        ("活跃时长", human_duration(summary["active"])),
        ("闲置时长", human_duration(summary["idle"])),
        ("锁屏时长", human_duration(summary["lock"])),
        ("办公文档变动", summary["office"]),
        ("其他文件变动", summary["other"]),
        ("文件变动总数", summary["all_files"]),
        ("整机下载流量", human_size(summary["bytes_in"])),
        ("整机上传流量", human_size(summary["bytes_out"])),
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    for r in rows:
        ws.append(list(r))
    style_header(ws, 2)
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 34

    ws2 = wb.create_sheet("文件事件")
    ws2.append(["发生时间", "类型", "文件名", "后缀", "大小(字节)", "操作软件(推测)", "完整路径", "原路径", "监测目录"])
    events, _ = db.query_file_events(start_iso=start_iso, end_iso=end_iso, limit=200000, offset=0)
    for e in events:
        ws2.append(_clean_row([
            e["event_time"], event_type_label(e["event_type"]), e["name"], e["ext"],
            e["size"], e.get("process_name", ""), e["path"], e.get("old_path", ""), e["root"],
        ]))
    style_header(ws2, 9)
    for col, width in zip("ABCDEFGHI", (20, 8, 28, 8, 12, 18, 50, 50, 30)):
        ws2.column_dimensions[col].width = width

    ws3 = wb.create_sheet("软件时长")
    ws3.append(["软件", "前台时长(分钟)", "后台时长(分钟)", "可执行文件"])
    for app in db.app_ranking(start.isoformat(), end.isoformat(), limit=500):
        ws3.append(_clean_row([app["name"], round(int(app["fg"]) / 60, 1), round(int(app["bg"]) / 60, 1), app["exe"]]))
    style_header(ws3, 4)
    for col, width in zip("ABCD", (30, 16, 16, 60)):
        ws3.column_dimensions[col].width = width

    ws4 = wb.create_sheet("网络流量")
    ws4.append(["软件", "下载(字节)", "上传(字节)", "合计"])
    for net in db.network_ranking(start.isoformat(), end.isoformat(), limit=500):
        total = int(net["bin"]) + int(net["bout"])
        ws4.append(_clean_row([net["name"], int(net["bin"]), int(net["bout"]), human_size(total)]))
    style_header(ws4, 4)
    for col, width in zip("ABCD", (30, 16, 16, 16)):
        ws4.column_dimensions[col].width = width

    for sheet in wb.worksheets:
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.font = body_font
    wb.save(path)
    return len(events)


def export_html(db: Database, config: AppConfig, path: str, start: date, end: date) -> int:
    start_iso, end_iso = _bounds(start, end)
    summary = _summary(db, config, start, end)
    js_path = Path(WEB_DIR) / "plotly.min.js"
    plotly_js = js_path.read_text(encoding="utf-8") if js_path.exists() else ""

    days = [start + timedelta(days=o) for o in range((end - start).days + 1)]
    usage = db.usage_daily_map(start.isoformat(), end.isoformat())
    if len(days) == 1:
        a_h, i_h, l_h = db.usage_hour_map(start.isoformat())
        labels = [f"{h}时" for h in range(24)]
        a = [v / 3600 for v in a_h]
        i = [v / 3600 for v in i_h]
        l = [v / 3600 for v in l_h]
    else:
        labels = [f"{d.month}/{d.day}" for d in days]
        a = [usage.get(d.isoformat(), (0, 0, 0))[0] / 3600 for d in days]
        i = [usage.get(d.isoformat(), (0, 0, 0))[1] / 3600 for d in days]
        l = [usage.get(d.isoformat(), (0, 0, 0))[2] / 3600 for d in days]
    trend = usage_figure(labels, a, i, l).to_plotly_json()

    apps = [x for x in db.app_ranking(start.isoformat(), end.isoformat(), limit=8) if int(x["fg"]) > 0]
    software = donut_figure(
        [_clean(x["name"]) for x in apps], [round(int(x["fg"]) / 60, 1) for x in apps], _PIE_COLORS, "分钟"
    ).to_plotly_json()
    types = db.office_type_counts(start_iso, end_iso, config.office_extensions)
    tl = [k for k, v in types.items() if v > 0]
    office = pie_figure(tl, [types[k] for k in tl], _PIE_COLORS).to_plotly_json()
    nets = db.network_ranking(start.isoformat(), end.isoformat(), limit=8)
    traffic = donut_figure(
        [_clean(x["name"]) for x in nets],
        [round((int(x["bin"]) + int(x["bout"])) / 1024 / 1024, 2) for x in nets],
        _PIE_COLORS, "MB",
    ).to_plotly_json()
    rank = hbar_figure(
        [_clean(x["name"]) for x in apps], [round(int(x["fg"]) / 60) for x in apps], "#4080FF", " 分钟"
    ).to_plotly_json()

    events, _ = db.query_file_events(start_iso=start_iso, end_iso=end_iso, limit=200, offset=0)
    rows_html = "".join(
        f"<tr><td>{e['event_time']}</td><td>{event_type_label(e['event_type'])}</td>"
        f"<td>{_esc(e['name'])}</td><td>{_esc(e.get('process_name') or '—')}</td>"
        f"<td class='path'>{_esc(e['path'])}</td></tr>"
        for e in events
    )

    cards = [
        ("总使用时长", human_duration(summary["total"])),
        ("活跃时长", human_duration(summary["active"])),
        ("办公文档变动", str(summary["office"])),
        ("整机流量", human_size(summary["bytes_in"] + summary["bytes_out"])),
    ]
    cards_html = "".join(
        f"<div class='card'><div class='card-title'>{t}</div><div class='card-value'>{v}</div></div>"
        for t, v in cards
    )
    figures = {"trend": trend, "software": software, "office": office, "traffic": traffic, "rank": rank}
    fig_json = json.dumps(figures, ensure_ascii=False)

    html = _HTML_TEMPLATE.replace("__PLOTLY_JS__", plotly_js)
    html = html.replace("__TITLE__", f"电脑使用行为报告 · {start.isoformat()} ~ {end.isoformat()}")
    html = html.replace("__CARDS__", cards_html)
    html = html.replace("__ROWS__", rows_html or "<tr><td colspan='5'>暂无文件事件</td></tr>")
    html = html.replace("__FIGURES__", fig_json)
    html = html.replace("__GENERATED__", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    Path(path).write_text(html, encoding="utf-8")
    return len(events)


def _esc(text: str) -> str:
    return (
        ILLEGAL_CHARACTERS_RE.sub("", str(text))
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>__TITLE__</title>
<script>__PLOTLY_JS__</script>
<style>
  body{font-family:"Microsoft YaHei UI",sans-serif;background:#F5F7FB;color:#2A3342;margin:0;padding:32px;}
  h1{font-size:22px;margin:0 0 4px;}
  .sub{color:#6B7686;font-size:13px;margin-bottom:24px;}
  .cards{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px;}
  .card{background:#fff;border:1px solid #E8ECF4;border-radius:14px;padding:16px 20px;min-width:160px;flex:1;}
  .card-title{color:#6B7686;font-size:12px;}
  .card-value{font-size:22px;font-weight:700;margin-top:6px;}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
  .panel{background:#fff;border:1px solid #E8ECF4;border-radius:14px;padding:16px;}
  .panel h2{font-size:14px;margin:0 0 8px;color:#2A3342;}
  .chart{width:100%;height:300px;}
  .wide{grid-column:1 / -1;}
  table{width:100%;border-collapse:collapse;font-size:12px;}
  th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #F0F3F8;}
  th{color:#6B7686;background:#F7F9FC;}
  td.path{color:#9AA4B2;max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .foot{color:#9AA4B2;font-size:11px;margin-top:24px;}
</style></head>
<body>
<h1>__TITLE__</h1>
<div class="sub">数据完全保存在本机 · 报告生成于 __GENERATED__</div>
<div class="cards">__CARDS__</div>
<div class="grid">
  <div class="panel wide"><h2>整机使用时长趋势</h2><div id="trend" class="chart"></div></div>
  <div class="panel"><h2>软件有效使用时长</h2><div id="software" class="chart"></div></div>
  <div class="panel"><h2>办公文档类型分布</h2><div id="office" class="chart"></div></div>
  <div class="panel"><h2>软件流量占比</h2><div id="traffic" class="chart"></div></div>
  <div class="panel"><h2>软件使用排行</h2><div id="rank" class="chart"></div></div>
  <div class="panel wide"><h2>最近文件事件（最多 200 条）</h2>
    <table><thead><tr><th>时间</th><th>类型</th><th>文件名</th><th>操作软件</th><th>路径</th></tr></thead>
    <tbody>__ROWS__</tbody></table>
  </div>
</div>
<div class="foot">本报告由「电脑使用行为溯源监测系统」离线生成，不含任何联网内容。</div>
<script>
  var figs = __FIGURES__;
  var cfg = {responsive:true, displayModeBar:false};
  Object.keys(figs).forEach(function(k){
    var f = figs[k];
    Plotly.newPlot(k, f.data, f.layout, cfg);
  });
</script>
</body></html>"""