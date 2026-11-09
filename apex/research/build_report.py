#!/usr/bin/env python3
"""Fills a report template with generated tables.

  python3 build_report.py          report_template.md + results/tables.md -> apex/REPORT.md
  python3 build_report.py fusion   report_fusion_template.md + results/fusion_tables.md -> apex/REPORT_FUSION.md
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    fusion = len(sys.argv) > 1 and sys.argv[1] == "fusion"
    tables_file, tpl_file, out_file = (("fusion_tables.md", "report_fusion_template.md", "REPORT_FUSION.md") if fusion
                                       else ("tables.md", "report_template.md", "REPORT.md"))
    tables = open(os.path.join(HERE, "results", tables_file), encoding="utf-8").read()
    blocks = {}
    for m in re.finditer(r"^### ([TF]\d+b?) [^\n]*\n(.*?)(?=^### [TF]\d|\Z)", tables, flags=re.S | re.M):
        blocks[m.group(1)] = m.group(2).strip()
    tpl = open(os.path.join(HERE, tpl_file), encoding="utf-8").read()
    missing = [k for k in re.findall(r"\{\{([TF]\d+b?)\}\}", tpl) if k not in blocks]
    if missing:
        raise SystemExit(f"tables missing from results/{tables_file}: {missing}")
    out = re.sub(r"\{\{([TF]\d+b?)\}\}", lambda m: blocks[m.group(1)], tpl)
    path = os.path.join(HERE, "..", out_file)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    print("written:", os.path.normpath(path), f"({len(out.splitlines())} lines, tables: {sorted(blocks)})")


if __name__ == "__main__":
    main()
