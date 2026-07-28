"""Create the greenfield quant_vnext tables.

This script is intentionally separate from the legacy startup migration. Run it
only after validating the new engine and reviewing the SQL in persistence.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import engine
from quant_vnext.persistence import FACTOR_VALUES_DDL, RESEARCH_DDL, RESONANCE_DDL, OUTCOME_DDL


def main() -> None:
    statements = (FACTOR_VALUES_DDL, RESEARCH_DDL, RESONANCE_DDL, OUTCOME_DDL)
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
    print("quant_vnext tables created")


if __name__ == "__main__":
    main()
