def write_prospector_html(
    input_file: str,
    output_file: str,
) -> None:

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

        rows.append([
            path,
            line,
            item.get("code", ""),
            item.get("message", ""),
        ])

    render_html_report(
        title="NMDB Prospector Report",
        headers=[
            "File",
            "Line",
            "Code",
            "Message",
        ],
        rows=rows,
        output_file=output_file,
    )