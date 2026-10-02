import html
import json
from pathlib import Path

REPORT_CSS = """
body {
    font-family: Arial, sans-serif;
    margin: 30px;
    background: #f7f7f7;
}

.report {
    background: white;
    padding: 24px;
    border: 1px solid #ddd;
    max-width: 1200px;
}

h2 {
    margin-top: 0;
}

table {
    border-collapse: collapse;
    width: 100%;
}

th {
    background: #eeeeee;
    font-weight: bold;
}

th, td {
    border: 1px solid #cccccc;
    padding: 9px 12px;
    text-align: left;
    vertical-align: top;
}

tr:nth-child(even) {
    background: #fafafa;
}
"""

def write_report_css(path: str = "report.css") -> None:
    Path(path).write_text(REPORT_CSS, encoding="utf-8")


def render_html_report(
    title: str,
    headers: list[str],
    rows: list[list[object]],
    output_file: str,
) -> None:

    def render_cell(value: object) -> str:
        value = "" if value is None else str(value)

        # Automatically make URLs clickable.
        if value.startswith(("http://", "https://")):
            escaped = html.escape(value)
            return f'<a href="{escaped}">{escaped}</a>'

        return html.escape(value)

    header_html = "".join(
        f"<th>{html.escape(header)}</th>"
        for header in headers
    )

    rows_html = []

    for row in rows:
        cells = "".join(
            f"<td>{render_cell(value)}</td>"
            for value in row
        )

        rows_html.append(f"<tr>{cells}</tr>")

    if not rows_html:
        rows_html.append(
            f'<tr><td colspan="{len(headers)}">'
            'No records found'
            '</td></tr>'
        )

    document = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="report.css">
</head>

<body>
<div class="report">

<h2>{html.escape(title)}</h2>

<table>
<thead>
<tr>{header_html}</tr>
</thead>

<tbody>
{''.join(rows_html)}
</tbody>
</table>

</div>
</body>
</html>
"""

    write_report_css()

    Path(output_file).write_text(
        document,
        encoding="utf-8",
    )

    print(f"HTML_REPORT={output_file}")

def write_metadata_html(
    output_file: str,
    branch: str,
    build_number: str,
    git_commit: str,
    docker_image: str,
    vm_name: str,
    vm_ip: str,
    db_host: str,
    db_name: str,
    db_port: str,
    schema: str,
) -> None:

    rows = [
        ["Branch", branch],
        ["Build Number", build_number],
        ["Git Commit", git_commit],
        ["Docker Image", docker_image],
        ["VM Name", vm_name],
        ["VM IP", vm_ip],
        ["FastAPI Swagger", f"http://{vm_ip}:8080/docs"],
        ["Database Host", db_host],
        ["DB Name", db_name],
        ["DB Port", db_port],
        ["Schema", schema],
    ]

    render_html_report(
        title="NMDB Release Metadata",
        headers=["Field", "Value"],
        rows=rows,
        output_file=output_file,
    )