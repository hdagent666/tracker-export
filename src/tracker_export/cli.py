"""Command-line interface for tracker-export."""

import argparse
import sys

from .export import collect_modules, export_batch, export_module, print_info


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="tracker-export",
        description="Bounce stems + samples from tracker modules "
                    "(MOD/XM/S3M/IT/...). Accepts multiple files and "
                    "directories (crawled for modules).")
    ap.add_argument("inputs", nargs="+",
                    help="module files and/or directories to crawl")
    ap.add_argument("-o", "--outdir", default=None,
                    help="parent folder for the <title>_export folders "
                         "(default: next to each module file)")
    ap.add_argument("--sr", type=int, default=44100,
                    help="render sample rate (default 44100)")
    ap.add_argument("--no-stems", action="store_true")
    ap.add_argument("--no-samples", action="store_true")
    ap.add_argument("--flat", action="store_true",
                    help="do not recurse into subdirectories")
    ap.add_argument("--lib", default=None, help="path to libxmp shared library")
    ap.add_argument("--info", action="store_true",
                    help="print module info for the first input and exit")
    ap.add_argument("--max-seconds", type=int, default=1200)
    args = ap.parse_args(argv)

    if args.info:
        return print_info(args.inputs[0], lib_path=args.lib)

    files = collect_modules(args.inputs, recursive=not args.flat)
    if not files:
        print("No tracker modules found in the given files/directories.")
        return 1
    if len(files) > 1:
        print(f"Found {len(files)} module(s).")

    if len(files) == 1:
        export_module(files[0], outdir=args.outdir,
                      sample_rate=args.sr,
                      do_stems=not args.no_stems,
                      do_samples=not args.no_samples,
                      lib_path=args.lib,
                      max_seconds=args.max_seconds, on_log=print)
        return 0

    exported, failures = export_batch(
        files, outdir=args.outdir, sample_rate=args.sr,
        do_stems=not args.no_stems, do_samples=not args.no_samples,
        lib_path=args.lib, max_seconds=args.max_seconds, on_log=print)
    return 0 if exported else 1


if __name__ == "__main__":
    sys.exit(main())
