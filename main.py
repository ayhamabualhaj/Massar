"""Run this file in PyCharm to generate the timetable."""
import json
from pathlib import Path

import pandas as pd

from masar.solver import solve
from masar.reporting import table_rows


def main():
    root = Path(__file__).resolve().parent
    data = json.loads((root / "data" / "masar_data_v2.json").read_text(encoding="utf-8"))
    result = solve(data, optimize=True, seconds=60)
    print(result["status"], result["diagnostics"])
    print(result["validation"])
    out = root / "masar_v2_output"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(table_rows(data, result)).to_csv(
        out / "timetable.csv", index=False, encoding="utf-8-sig"
    )


if __name__ == "__main__":
    main()
