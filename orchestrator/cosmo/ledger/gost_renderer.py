"""
COS-005: ГОСТ-Акт HTML renderer.

Генерирует HTML-отчёт по ГОСТ из структуры GOSTAct.
"""
from __future__ import annotations

try:
    from orchestrator.cosmo.ledger.gost_act import GOSTAct
except ImportError:
    from cosmo.ledger.gost_act import GOSTAct


def render_gost_act_html(act: GOSTAct) -> str:
    """Генерирует HTML-акт приёмочного тестирования."""
    header = act.header
    obj = act.object

    findings_html = ""
    if act.findings_table:
        for f in act.findings_table:
            sev_class = _severity_class(f.severity)
            findings_html += f"""<tr class="{sev_class}">
    <td>{f.severity}</td>
    <td>{f.title}</td>
    <td>{f.cwe or "—"}</td>
    <td>{f.description}</td>
    <td>{f.recommendation or "—"}</td>
</tr>"""
    else:
        findings_html = '<tr><td colspan="5" class="no-findings">Находок не обнаружено</td></tr>'

    signatures_html = ""
    for s in act.signatures:
        signatures_html += f"""<tr>
    <td>{s.role}</td>
    <td>{s.name}</td>
    <td>{s.date}</td>
    <td>{s.status}</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Акт приёмочного тестирования — {header.project_name}</title>
<style>
body {{ font-family: 'PT Serif', serif; margin: 40px; color: #1a1a1a; }}
h1 {{ font-size: 18pt; text-align: center; margin-bottom: 30px; }}
h2 {{ font-size: 14pt; margin-top: 30px; }}
table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
th, td {{ border: 1px solid #333; padding: 8px 12px; text-align: left; font-size: 11pt; }}
th {{ background: #f0f0f0; }}
.critical {{ background: #ffe0e0; }}
.high {{ background: #fff0e0; }}
.medium {{ background: #ffffe0; }}
.low, .info {{ background: #f8f8f8; }}
.no-findings {{ text-align: center; color: #666; font-style: italic; }}
.header-table td {{ width: 50%; }}
</style>
</head>
<body>
<h1>Акт приёмочного тестирования № {header.act_number or "—"}</h1>

<h2>1. Общие сведения</h2>
<table class="header-table">
<tr><td><strong>Проект:</strong></td><td>{header.project_name}</td></tr>
<tr><td><strong>Организация:</strong></td><td>{header.organization}</td></tr>
<tr><td><strong>Объект испытаний:</strong></td><td>{obj.name}</td></tr>
<tr><td><strong>URL:</strong></td><td>{obj.url or "—"}</td></tr>
<tr><td><strong>Домен:</strong></td><td>{obj.domain or "—"}</td></tr>
</table>

<h2>2. Результаты тестирования</h2>
<table>
<thead>
<tr>
    <th>Критичность</th>
    <th>Наименование</th>
    <th>CWE</th>
    <th>Описание</th>
    <th>Рекомендация</th>
</tr>
</thead>
<tbody>
{findings_html}
</tbody>
</table>

{"<h2>3. Подписи</h2><table><thead><tr><th>Должность</th><th>ФИО</th><th>Дата</th><th>Статус</th></tr></thead><tbody>" + signatures_html + "</tbody></table>" if act.signatures else ""}
</body>
</html>"""


def _severity_class(severity: str) -> str:
    return severity.lower()