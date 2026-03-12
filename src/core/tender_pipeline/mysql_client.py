from __future__ import annotations

import subprocess
from typing import List


def run_mysql_query(container: str, user: str, password: str, database: str, sql: str) -> str:
    cmd = [
        "docker",
        "exec",
        container,
        "mysql",
        f"-u{user}",
        f"-p{password}",
        "-D",
        database,
        "--batch",
        "--raw",
        "-e",
        sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=False, check=False)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"MySQL query failed: {stderr.strip()}")
    return stdout


def parse_mysql_tsv(output: str) -> List[dict]:
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    headers = [header.strip().lower() for header in lines[0].split("\t")]
    rows: List[dict] = []
    for line in lines[1:]:
        values = line.split("\t")
        row = dict(zip(headers, values))
        rows.append(row)
    return rows


def fetch_schema_metadata(
    container: str,
    user: str,
    password: str,
    database: str,
    tables: List[str],
) -> dict:
    if not tables:
        return {"tables": []}
    table_list = ",".join([f"'{t}'" for t in tables])
    sql = (
        "SELECT table_name, column_name, data_type "
        "FROM information_schema.columns "
        f"WHERE table_schema = '{database}' AND table_name IN ({table_list}) "
        "ORDER BY table_name, ordinal_position"
    )
    output = run_mysql_query(container, user, password, database, sql)
    rows = parse_mysql_tsv(output)
    tables_map: dict[str, list[dict]] = {}
    for row in rows:
        tables_map.setdefault(row["table_name"], []).append(
            {"name": row["column_name"], "type": row["data_type"]}
        )
    return {
        "tables": [
            {"name": name, "columns": columns} for name, columns in tables_map.items()
        ]
    }
