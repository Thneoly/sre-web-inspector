from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_INSPECTION_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SRE Inspection Report — {run_id}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 2rem; background: #f8fafc; color: #1e293b; }}
  h1 {{ margin-bottom: 0.25rem; }}
  h2.section {{ margin-top: 2rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.25rem; }}
  .meta {{ color: #64748b; margin-bottom: 2rem; }}
  .badge {{ display: inline-block; padding: 0.2em 0.6em; border-radius: 4px; font-size: 0.85em; font-weight: 600; color: #fff; }}
  .badge-ok {{ background: #22c55e; }}
  .badge-fail {{ background: #ef4444; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.25rem; margin-bottom: 1.25rem; }}
  .card h3 {{ margin: 0 0 0.5rem; }}
  .card .url {{ color: #64748b; font-size: 0.85em; word-break: break-all; }}
  .kv {{ display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1.5rem; margin: 0.75rem 0; }}
  .kv dt {{ color: #64748b; font-size: 0.85em; }}
  .kv dd {{ margin: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 0.75rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #e2e8f0; font-size: 0.85em; }}
  th {{ background: #f1f5f9; position: sticky; top: 0; }}
  a {{ color: #2563eb; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">
  Run: <strong>{run_id}</strong> &middot; {timestamp}
  &middot; Status: <span class="badge badge-{overall_ok}">{overall_status}</span>
</div>
{body}
</body>
</html>"""

_PAGE_CARD = """<div class="card">
<h3>{status_icon} {name}</h3>
<div class="url">{url}</div>
<table>
  <tr><th>Screenshot</th><th>HTML</th><th>Network</th><th>Replay Dir</th></tr>
  <tr>
    <td>{screenshot_link}</td>
    <td>{html_link}</td>
    <td>{network_link}</td>
    <td>{replay_dir}</td>
  </tr>
</table>
{replays_html}
{pre_replays_html}
{waits_html}
{error_html}
</div>"""


def _link(path: str | None, label: str = "") -> str:
    if not path:
        return "—"
    return f'<a href="{path}">{label or Path(path).name}</a>'


def _render_replay_table(replays: list[dict], title: str) -> str:
    if not replays:
        return ""
    rows = ""
    for r in replays:
        badge = "badge-ok" if r.get("ok") else "badge-fail"
        status = f'<span class="badge {badge}">{r.get("status", r.get("error", "?"))}</span>'
        rows += f"<tr><td>{r['name']}</td><td>{r['method']}</td><td style=\"font-size:0.8em\">{r['url']}</td><td>{status}</td></tr>"
    return f"<h4>{title}</h4><table><tr><th>Name</th><th>Method</th><th>URL</th><th>Result</th></tr>{rows}</table>"


def _render_inspection_report(summary: dict[str, Any]) -> str:
    """Render the WebInspectionRun format (backward-compatible)."""
    global_replays = summary.get("global_replays", []) or []
    global_html = _render_replay_table(global_replays, "Global Replays") if global_replays else "<p>None</p>"

    pages_html = ""
    for page in summary.get("pages", []) or []:
        evidence = page.get("evidence") or {}
        ok = page.get("ok", False)
        icon = "&check;" if ok else "&cross;"

        replays_html = _render_replay_table(page.get("replays", []) or [], "Replays")
        pre_html = _render_replay_table(page.get("pre_replays", []) or [], "Pre-Replays")
        waits_html = _render_replay_table(page.get("waits", []) or [], "Waited Requests/Responses")

        error_html = ""
        if not ok:
            error_html = f'<div style="color:#ef4444;margin-top:0.5rem"><strong>Error:</strong> {page.get("error", "unknown")}</div>'

        pages_html += _PAGE_CARD.format(
            status_icon=icon,
            name=page.get("name", "page"),
            url=page.get("url", ""),
            screenshot_link=_link(evidence.get("screenshot"), "Screenshot"),
            html_link=_link(evidence.get("html"), "HTML"),
            network_link=_link(evidence.get("network"), "Network"),
            replay_dir=evidence.get("replay_dir", "—"),
            replays_html=replays_html,
            pre_replays_html=pre_html,
            waits_html=waits_html,
            error_html=error_html,
        )

    body = f"<h2 class=\"section\">Global Replays</h2>\n{global_html}\n"
    body += f"<h2 class=\"section\">Pages</h2>\n{pages_html or '<p>No pages inspected.</p>'}"
    return body


def _render_generic_report(summary: dict[str, Any]) -> str:
    """Render any summary dict as a readable HTML report.

    Top-level scalars become a definition list.  The ``items`` list (if
    present) is rendered as a sortable table with one column per dict key.
    """
    parts: list[str] = []

    # --- key / value summary block ---
    kv_rows = ""
    for key in sorted(summary):
        if key in ("items", "pages", "global_replays"):
            continue
        val = summary[key]
        if isinstance(val, (list, dict)):
            val = f"<code>{_trunc(str(val), 120)}</code>"
        elif isinstance(val, bool):
            val = "&check;" if val else "&cross;"
        else:
            val = str(val)
        kv_rows += f"<dt>{key}</dt><dd>{val}</dd>\n"

    if kv_rows:
        parts.append(f"<h2 class=\"section\">Summary</h2>\n<dl class=\"kv\">\n{kv_rows}</dl>")

    # --- items table ---
    items = summary.get("items") or []
    if items and isinstance(items, list) and isinstance(items[0], dict):
        columns = list(items[0].keys())
        header = "".join(f"<th>{c}</th>" for c in columns)
        rows = ""
        for item in items:
            cells = "".join(f"<td>{_cell(val)}</td>" for val in item.values())
            rows += f"<tr>{cells}</tr>\n"
        parts.append(
            f"<h2 class=\"section\">Items ({len(items)})</h2>\n"
            f"<table><tr>{header}</tr>\n{rows}</table>"
        )

    return "\n".join(parts)


def _cell(val: Any) -> str:
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "&check;" if val else "&cross;"
    s = str(val)
    if s.startswith("http"):
        return f'<a href="{s}">{_trunc(s, 60)}</a>'
    return _trunc(s, 120)


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


def render_report(summary: dict[str, Any]) -> str:
    """Render a summary dict to an HTML report string.

    Routes to the inspection-specific renderer when ``kind`` is
    ``"WebInspectionRun"``, otherwise uses the generic renderer.
    """
    run_id = summary.get("run_id", "?")
    overall_ok = summary.get("ok", False)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kind = summary.get("kind", "")

    if kind == "WebInspectionRun":
        title = "SRE Inspection Report"
        body = _render_inspection_report(summary)
    else:
        title = f"{kind} Report" if kind else "Collection Report"
        body = _render_generic_report(summary)

    return _INSPECTION_TEMPLATE.format(
        title=title,
        run_id=run_id,
        timestamp=timestamp,
        overall_ok="ok" if overall_ok else "fail",
        overall_status="PASS" if overall_ok else "FAIL",
        body=body,
    )


def write_html_report(summary: dict[str, Any], output_dir: Path) -> Path:
    html = render_report(summary)
    path = output_dir / "run_result.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_json_report(summary: dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / "run_result.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
