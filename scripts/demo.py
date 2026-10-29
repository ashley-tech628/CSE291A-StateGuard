import argparse
import json

from stateguard.demo import run_clean_demo


parser = argparse.ArgumentParser()
parser.add_argument("--db", default="results/demo.sqlite3")
parser.add_argument("--trace", default="results/demo.json")
args = parser.parse_args()
print(json.dumps(run_clean_demo(args.db, args.trace), indent=2))
