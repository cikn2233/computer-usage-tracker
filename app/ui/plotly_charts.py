from __future__ import annotations

import json
import shutil
from pathlib import Path

import plotly.graph_objects as go
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView

from app.config import WEB_DIR
from app.ui.theme import current_palette

# 离线 bundled plotly.min.js：从 plotly 包复制到数据目录，供 file:// 加载，全程不联网。
def ensure_plotly_js() -> Path:
    target = Path(WEB_DIR) / "plotly.min.js"
    if target.exists() and target.stat().st_size > 100000:
        return target
    import plotly
    source = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return target


_BOOT_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="plotly.min.js"></script>
<style>
  html,body{margin:0;padding:0;background:transparent;overflow:hidden;}
  #chart{width:100vw;height:100vh;}
</style></head>
<body><div id="chart"></div>
<script>
  Plotly.newPlot('chart', [], {paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)'},
                 {responsive:true, displayModeBar:false});
  window.addEventListener('resize', function(){ Plotly.Plots.resize('chart'); });
  window.__apply = function(f){ Plotly.react('chart', f.data, f.layout, {responsive:true, displayModeBar:false}); };
</script></body></html>"""


class PlotView(QWebEngineView):
    """承载交互式 Plotly 图表的轻量 WebView，更新走 Plotly.react 避免重复解析 JS。"""

    def __init__(self, min_height: int = 240, parent=None):
        super().__init__(parent)
        self._ready = False
        self._pending: dict | None = None
        self.setMinimumHeight(min_height)
        self.setStyleSheet("background: transparent;")
        page = self.page()
        page.setBackgroundColor(QColor(0, 0, 0, 0))
        ensure_plotly_js()
        base = QUrl.fromLocalFile(str(Path(WEB_DIR)) + "/")
        self.setHtml(_BOOT_HTML, base)
        self.loadFinished.connect(self._on_loaded)

    def _on_loaded(self, ok: bool) -> None:
        self._ready = bool(ok)
        if self._ready and self._pending is not None:
            self._apply(self._pending)
            self._pending = None

    def render(self, fig: go.Figure) -> None:
        data = fig.to_plotly_json()
        if self._ready:
            self._apply(data)
        else:
            self._pending = data

    def _apply(self, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        self.page().runJavaScript(f"window.__apply({payload});")


def _layout(**extra) -> dict:
    pal = current_palette()
    layout = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Microsoft YaHei UI", color=pal["muted"], size=11),
        margin=dict(l=44, r=18, t=18, b=34),
        hoverlabel=dict(font=dict(family="Microsoft YaHei UI", size=12)),
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11)),
    )
    layout.update(extra)
    return layout


def _axis(pal: dict) -> dict:
    return dict(
        gridcolor=pal["table_grid"],
        zeroline=False,
        linecolor=pal["border"],
        tickfont=dict(size=10, color=pal["subtle"]),
    )


def _empty(fig: go.Figure, text: str) -> go.Figure:
    fig.add_annotation(
        text=text, showarrow=False,
        font=dict(size=13, color=current_palette()["subtle"]),
        xref="paper", yref="paper", x=0.5, y=0.5,
    )
    fig.update_layout(**_layout(showlegend=False))
    return fig


def usage_figure(labels, active, idle, lock=None, mode: str = "bar") -> go.Figure:
    pal = current_palette()
    fig = go.Figure()
    if not labels or not any(active) and not any(idle) and not (lock and any(lock)):
        return _empty(fig, "暂无使用数据")
    series = [("活跃", active, pal["active"]), ("闲置", idle, pal["idle"])]
    if lock is not None:
        series.append(("锁屏", lock, pal["lock"]))
    for name, values, color in series:
        if mode == "line":
            fig.add_trace(go.Scatter(
                x=labels, y=values, name=name, mode="lines+markers",
                line=dict(color=color, width=2.4, shape="spline"),
                marker=dict(size=5),
                hovertemplate="%{x}<br>" + name + " %{y:.2f} 小时<extra></extra>",
            ))
        else:
            fig.add_trace(go.Bar(
                x=labels, y=values, name=name, marker_color=color,
                marker_line_width=0,
                hovertemplate="%{x}<br>" + name + " %{y:.2f} 小时<extra></extra>",
            ))
    layout = _layout(barmode="stack", bargap=0.35)
    layout["xaxis"] = _axis(pal)
    layout["yaxis"] = _axis(pal)
    layout["yaxis"]["title"] = dict(text="小时", font=dict(size=10))
    fig.update_layout(**layout)
    return fig


def donut_figure(labels, values, colors, center_text: str = "", show_legend: bool = True) -> go.Figure:
    pal = current_palette()
    fig = go.Figure()
    if not values or not any(values):
        return _empty(fig, "暂无数据")
    fig.add_trace(go.Pie(
        labels=labels, values=values, hole=0.62,
        marker=dict(colors=colors, line=dict(color=pal["card"], width=2)),
        textinfo="percent", textposition="inside",
        insidetextfont=dict(size=11, color="#FFFFFF"),
        hovertemplate="%{label}<br>%{value} · %{percent}<extra></extra>",
        sort=False,
    ))
    layout = _layout(showlegend=show_legend, margin=dict(l=10, r=10, t=10, b=10))
    layout["uniformtext"] = dict(minsize=9, mode="hide")
    if show_legend:
        layout["legend"] = dict(orientation="v", y=0.5, x=1.02, font=dict(size=10))
    if center_text:
        layout["annotations"] = [dict(
            text=center_text, showarrow=False,
            font=dict(size=13, color=pal["text"], family="Microsoft YaHei UI"),
            x=0.5, y=0.5,
        )]
    fig.update_layout(**layout)
    return fig


def pie_figure(labels, values, colors) -> go.Figure:
    pal = current_palette()
    fig = go.Figure()
    if not values or not any(values):
        return _empty(fig, "暂无数据")
    fig.add_trace(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=colors, line=dict(color=pal["card"], width=2)),
        textinfo="label+percent", textposition="inside",
        insidetextfont=dict(size=11, color="#FFFFFF"),
        hovertemplate="%{label}<br>%{value} 次 · %{percent}<extra></extra>",
        sort=False,
    ))
    fig.update_layout(**_layout(
        showlegend=False, margin=dict(l=10, r=10, t=10, b=10),
        uniformtext=dict(minsize=9, mode="hide"),
    ))
    return fig


def hbar_figure(labels, values, color: str, suffix: str = "") -> go.Figure:
    pal = current_palette()
    fig = go.Figure()
    if not values or not any(values):
        return _empty(fig, "暂无数据")
    order = list(range(len(labels)))[::-1]
    fig.add_trace(go.Bar(
        x=[values[i] for i in order],
        y=[labels[i] for i in order],
        orientation="h", marker_color=color, marker_line_width=0,
        text=[f"{values[i]}{suffix}" for i in order],
        textposition="outside", textfont=dict(size=10, color=pal["muted"]),
        hovertemplate="%{y}<br>%{x}" + suffix + "<extra></extra>",
    ))
    layout = _layout(showlegend=False, margin=dict(l=10, r=40, t=10, b=24))
    layout["xaxis"] = _axis(pal)
    layout["yaxis"] = _axis(pal)
    layout["yaxis"]["automargin"] = True
    fig.update_layout(**layout)
    return fig


def traffic_figure(times, down, up) -> go.Figure:
    pal = current_palette()
    fig = go.Figure()
    if not times:
        return _empty(fig, "暂无流量采样")
    fig.add_trace(go.Scatter(
        x=times, y=down, name="下载", mode="lines",
        line=dict(color=pal["sky"], width=2),
        fill="tozeroy", fillcolor=_rgba(pal["sky"], 0.12),
        hovertemplate="%{x}<br>下载 %{y:.1f} KB/s<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=times, y=up, name="上传", mode="lines",
        line=dict(color=pal["mint"], width=2),
        hovertemplate="%{x}<br>上传 %{y:.1f} KB/s<extra></extra>",
    ))
    layout = _layout(margin=dict(l=44, r=14, t=10, b=30))
    layout["xaxis"] = _axis(pal)
    layout["xaxis"]["nticks"] = 6
    layout["xaxis"]["tickangle"] = 0
    layout["yaxis"] = _axis(pal)
    layout["yaxis"]["title"] = dict(text="KB/s", font=dict(size=10))
    fig.update_layout(**layout)
    return fig


def _rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"