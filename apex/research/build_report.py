#!/usr/bin/env python3
"""Fills report_template.md with the tables of results/tables.md -> apex/REPORT.md."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    tables = open(os.path.join(HERE, "results", "tables.md"), encoding="utf-8").read()
    blocks = {}
    for m in re.finditer(r"^### (T\d+b?) [^\n]*\n(.*?)(?=^### T|\Z)", tables, flags=re.S | re.M):
        blocks[m.group(1)] = m.group(2).strip()
    tpl = open(os.path.join(HERE, "report_template.md"), encoding="utf-8").read()
    missing = [k for k in re.findall(r"\{\{(T\d+b?)\}\}", tpl) if k not in blocks]
    if missing:
        raise SystemExit(f"tables missing from results/tables.md: {missing}")
    out = re.sub(r"\{\{(T\d+b?)\}\}", lambda m: blocks[m.group(1)], tpl)
    path = os.path.join(HERE, "..", "REPORT.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    print("written:", os.path.normpath(path), f"({len(out.splitlines())} lines, tables: {sorted(blocks)})")


if __name__ == "__main__":
    main()
