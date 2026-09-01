"""Server-rendered charts: independent of Streamlit's optional Plotly JS chunk."""
import io
import os
import tempfile
import threading
from pathlib import Path

_cache_dir = Path(tempfile.gettempdir()) / 'quant-terminal-matplotlib'
_cache_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(_cache_dir))
import matplotlib
matplotlib.use("Agg")
from matplotlib import dates as mdates
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

_PLOT_LOCK = threading.Lock()


def chart_png(plotly_figure):
    """Render the app's line/candle/level traces without a browser dependency."""
    with _PLOT_LOCK:
        figure = Figure(figsize=(12, 4.8), dpi=130, facecolor="#101318")
        axis = figure.subplots()
        axis.set_facecolor("#101318")
        axis.tick_params(colors="#d1d4dc", labelsize=8)
        for spine in axis.spines.values():
            spine.set_color("#444b56")
        for trace in plotly_figure.data:
            if trace.type not in {"scatter", "candlestick"}:
                continue
            x = pd.to_datetime(trace.x)
            if trace.type == "candlestick":
                positions = mdates.date2num(x.to_pydatetime())
                for pos, opening, high, low, close in zip(positions, trace.open, trace.high, trace.low, trace.close):
                    if not all(np.isfinite(float(v)) for v in (opening, high, low, close)):
                        continue
                    color = "#42b983" if close >= opening else "#ef7171"
                    axis.vlines(pos, low, high, colors=color, linewidth=.65)
                    body = max(abs(close - opening), (high - low) * .02, .001)
                    axis.add_patch(Rectangle((pos - .33, min(opening, close)), .66, body,
                                             facecolor=color, edgecolor=color, linewidth=.5))
                axis.xaxis_date()
            else:
                color = trace.line.color if trace.line and trace.line.color else "#72a9f8"
                axis.plot(x, trace.y, label=trace.name or "Value", color=color, linewidth=1.1)
        for shape in plotly_figure.layout.shapes or ():
            if shape.y0 is not None and shape.y1 == shape.y0:
                axis.axhline(float(shape.y0), linestyle="--", linewidth=.8,
                             color=shape.line.color or "#adb5bd", alpha=.8)
            elif shape.y0 is not None and shape.y1 is not None:
                axis.axhspan(float(shape.y0), float(shape.y1), color="#72a9f8", alpha=.08)
        axis.set_ylabel("Price / NAV (₹)", color="#d1d4dc")
        axis.set_xlabel("Date", color="#d1d4dc")
        axis.grid(alpha=.15)
        locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        if plotly_figure.layout.title.text:
            axis.set_title(plotly_figure.layout.title.text, color="#d1d4dc", fontsize=11)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(facecolor="#20252d", labelcolor="#d1d4dc", fontsize=8)
        axis.autoscale_view()
        figure.tight_layout()
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", facecolor=figure.get_facecolor())
        return buffer.getvalue()


def render_chart(figure, st, key):
    # This path needs no JS chart module, CDN request, Kaleido or browser runtime.
    try:
        st.image(chart_png(figure), width="stretch")
    except (ValueError, TypeError, AttributeError) as exc:
        st.warning(f"Chart could not be rendered ({type(exc).__name__}); the underlying figures remain available.")
    st.caption("Reliable chart image. For interactive zoom, download and open the self-contained HTML chart; it requires no external chart service.")
    st.download_button("Download interactive chart", figure.to_html(include_plotlyjs=True, full_html=True),
                       file_name=f"{key}.html", mime="text/html", key=f"chart_download_{key}")
