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

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>NMDB Release Metadata</title>
<link rel="stylesheet" href="report.css">
</head>

<body>
<div class="report">

<h2>NMDB Release Metadata</h2>

<table>
<tr>
    <th>Field</th>
    <th>Value</th>
</tr>

<tr><td>Branch</td><td>{branch}</td></tr>
<tr><td>Build Number</td><td>{build_number}</td></tr>
<tr><td>Git Commit</td><td>{git_commit}</td></tr>
<tr><td>Docker Image</td><td>{docker_image}</td></tr>
<tr><td>VM Name</td><td>{vm_name}</td></tr>
<tr><td>VM IP</td><td>{vm_ip}</td></tr>
<tr>
    <td>FastAPI Swagger</td>
    <td>
        <a href="http://{vm_ip}:8080/docs">
            http://{vm_ip}:8080/docs
        </a>
    </td>
</tr>
<tr><td>Database Host</td><td>{db_host}</td></tr>
<tr><td>DB Name</td><td>{db_name}</td></tr>
<tr><td>DB Port</td><td>{db_port}</td></tr>
<tr><td>Schema</td><td>{schema}</td></tr>

</table>

</div>
</body>
</html>
"""

write_report_css()
Path(output_file).write_text(html, encoding="utf-8")



def write_prospector_html(
    input_file: str,
    output_file: str,
) -> None:
    import html
    import json

    data = json.loads(
        Path(input_file).read_text(encoding="utf-8")
    )

    messages = data.get("messages", [])

    rows = []

    for item in messages:
        location = item.get("location", {})

        path = (
            location.get("path")
            or item.get("path")
            or ""
        )

        line = (
            location.get("line")
            or item.get("line")
            or ""
        )

        code = item.get("code", "")
        message = item.get("message", "")

        rows.append(
            "<tr>"
            f"<td>{html.escape(str(path))}</td>"
            f"<td>{html.escape(str(line))}</td>"
            f"<td>{html.escape(str(code))}</td>"
            f"<td>{html.escape(str(message))}</td>"
            "</tr>"
        )

    if not rows:
        rows.append(
            '<tr><td colspan="4">'
            'No Prospector issues found'
            '</td></tr>'
        )

    document = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>NMDB Prospector Report</title>
<link rel="stylesheet" href="report.css">
</head>

<body>
<div class="report">

<h2>NMDB Prospector Report</h2>

<table>
<tr>
    <th>File</th>
    <th>Line</th>
    <th>Code</th>
    <th>Message</th>
</tr>

{''.join(rows)}

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

    print(f"PROSPECTOR_HTML={output_file}")

    phtml = sub.add_parser("prospector-html")
phtml.add_argument("--input", required=True)
phtml.add_argument("--output", required=True)


elif a.cmd == "prospector-html":
    write_prospector_html(
        input_file=a.input,
        output_file=a.output,
    )


stage('Prospector Report') {
    when {
        expression {
            return env.IS_STAGING == 'true'
        }
    }

    steps {
        sh '''#!/usr/bin/env bash
            set +e

            prospector \
                --output-format json \
                > prospector.json

            PROSPECTOR_RC=$?

            python3 "$RELEASE_PY" prospector-html \
                --input prospector.json \
                --output prospector.html

            exit 0
        '''

        archiveArtifacts(
            artifacts: 'prospector.json,prospector.html,report.css',
            fingerprint: true,
            allowEmptyArchive: false
        )
    }
}