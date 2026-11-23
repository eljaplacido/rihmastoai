"""A command line that writes where its operator asks: `params` is the operator's own namespace."""

import argparse


def export(params):
    with open(params.output, "w", encoding="utf-8") as fh:
        fh.write("done\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    export(args)
