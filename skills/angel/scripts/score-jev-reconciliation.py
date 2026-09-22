#!/usr/bin/env python3
"""Create one complete ADR-22 Jev shadow artifact for an immutable run."""
import argparse
from pathlib import Path

from jev_reconciliation import score_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    args = parser.parse_args()
    artifact = score_run(Path(args.run_dir))
    print(f"{Path(args.run_dir).resolve() / 'jev-reconciliation.json'} "
          f"pairs={artifact['expected_pair_count']}")


if __name__ == "__main__":
    main()
