"""Command-line interface: `tracker-export song.mod`."""

import argparse
import sys

from .export import ExportCancelled, export_module, print_info


def build_parser():
    ap = argparse.ArgumentParser(
        prog="tracker-export",
        description="Bounce stems and samples out of any tracker module.")
    ap.add_argument("input",
                    help="tracker module file (.mod/.xm/.s3m/.it/...)")
    ap.add_argument("-o", "--outdir", default=None,
                    help="where to create the export folder "
                         "(default: next to the input file)")
    ap.add_argument("--sr", type=int, default=44100,
                    help="render sample rate for mix/stems (default 44100)")
    ap.add_argument("--no-stems", action="store_true",
                    help="skip per-channel stems")
    ap.add_argument("--no-samples", action="store_true",
                    help="skip sample bouncing")
    ap.add_argument("--lib", default=None,
                    help="explicit path to libxmp shared library")
    ap.add_argument("--info", action="store_true",
                    help="print module info only, do not export")
    ap.add_argument("--max-seconds", type=int, default=1200,
                    help="cap per-render length in seconds (default 1200)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.info:
        print(print_info(args.input, args.lib))
        return 0
    try:
        export_module(args.input, outdir=args.outdir, sample_rate=args.sr,
                      do_stems=not args.no_stems,
                      do_samples=not args.no_samples,
                      lib_path=args.lib, max_seconds=args.max_seconds,
                      on_log=print)
    except ExportCancelled:
        print("Export cancelled.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
