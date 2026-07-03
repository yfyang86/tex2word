"""Command-line interface: ``tex2word convert in.tex -o out.docx``."""

from __future__ import annotations

import argparse
import sys

from .pipeline import convert_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tex2word",
        description="Convert LaTeX to a native Microsoft Word (.docx) document.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    conv = sub.add_parser("convert", help="convert a .tex file to .docx")
    conv.add_argument("input", help="input .tex file")
    conv.add_argument("-o", "--output", help="output .docx path", default=None)
    conv.add_argument(
        "--report",
        help="write the conversion report (JSON, or HTML if the path ends in .html)",
        default=None,
    )
    conv.add_argument(
        "--no-manifest",
        action="store_true",
        help="do not embed the round-trip IR manifest in the .docx",
    )
    conv.add_argument(
        "--number-by-section",
        action="store_true",
        help="number figures/tables/equations as N.M per section (book/report style)",
    )
    conv.add_argument(
        "--citations",
        choices=("static", "zotero"),
        default="static",
        help="citation output: 'static' formatted text, or live 'zotero' CSL fields",
    )
    conv.add_argument(
        "--columns", type=int, default=1, metavar="N",
        help="lay out the body in N page columns; the default (1) auto-detects "
             "\\documentclass[twocolumn]/\\twocolumn/multicols, and N>1 overrides",
    )
    conv.add_argument(
        "--frontend", choices=("pure", "latexml"), default="pure",
        help="parser: 'pure' (pylatexenc) or 'latexml' (genuine TeX expansion)",
    )
    conv.add_argument(
        "--math-image-fallback", action="store_true",
        help="render math that can't become OMML as an image (needs TeX or matplotlib)",
    )
    conv.add_argument(
        "--csl", metavar="STYLE.csl", default=None,
        help="format citations/bibliography with a real CSL engine against this "
             ".csl style (needs the 'csl' extra: uv sync --extra csl)",
    )
    conv.add_argument(
        "--reference-doc", metavar="TEMPLATE.docx", default=None,
        help="adopt the styles, theme and page geometry of this Word .docx "
             "(journal/corporate template)",
    )
    conv.add_argument(
        "--lang", metavar="BCP47", default=None,
        help="document language for Word spell-check/accessibility (e.g. en-US, "
             "de-DE); overrides the babel/polyglossia language detected in the source",
    )
    conv.add_argument(
        "-q", "--quiet", action="store_true", help="suppress the stderr summary"
    )

    cov = sub.add_parser(
        "coverage", help="convert every .tex in a directory and emit a coverage dashboard"
    )
    cov.add_argument("directory", help="directory of .tex files (searched recursively)")
    cov.add_argument("-o", "--output", default="coverage.html", help="output HTML path")

    bench = sub.add_parser(
        "benchmark",
        help="convert every .tex in a directory and report quantitative metrics "
             "(math-OMML %%, validity, warnings, aborts)",
    )
    bench.add_argument("directory", help="directory of .tex files (searched recursively)")
    bench.add_argument("-o", "--output", default=None, help="write the metrics JSON here")
    bench.add_argument(
        "--fail-on-regression", action="store_true",
        help="exit non-zero if any document aborts or produces invalid OOXML",
    )

    rev = sub.add_parser(
        "to-latex", help="recover LaTeX from a tex2word-produced .docx (round-trip)"
    )
    rev.add_argument("input", help="input .docx (must carry the round-trip manifest)")
    rev.add_argument("-o", "--output", default=None, help="output .tex path (default: stdout)")
    rev.add_argument(
        "--no-reconcile",
        action="store_true",
        help="emit the embedded manifest verbatim, ignoring any Word edits to the body",
    )

    args = parser.parse_args(argv)

    if args.command == "convert":
        return _cmd_convert(args)
    if args.command == "coverage":
        return _cmd_coverage(args)
    if args.command == "benchmark":
        return _cmd_benchmark(args)
    if args.command == "to-latex":
        return _cmd_to_latex(args)
    return 1


def _cmd_to_latex(args: argparse.Namespace) -> int:
    from .roundtrip import to_latex

    try:
        with open(args.input, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2
    latex = to_latex(data, reconcile=not args.no_reconcile)
    if latex is None:
        print("error: no round-trip manifest in this .docx", file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(latex)
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(latex)
    return 0


def _cmd_benchmark(args: argparse.Namespace) -> int:
    import json

    from .benchmark import benchmark_dir, format_report

    result = benchmark_dir(args.directory)
    if not result["documents"]:
        print(f"no .tex files under {args.directory}", file=sys.stderr)
        return 2
    print(format_report(result))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        print(f"wrote {args.output}", file=sys.stderr)
    agg = result["aggregate"]
    if args.fail_on_regression and (agg["aborted"] or agg["valid"] < agg["documents"]):
        print("benchmark regression: aborts or invalid output", file=sys.stderr)
        return 1
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    import glob
    import os

    from .pipeline import convert_file
    from .report import aggregate_html

    paths = sorted(glob.glob(os.path.join(args.directory, "**", "*.tex"), recursive=True))
    if not paths:
        print(f"no .tex files under {args.directory}", file=sys.stderr)
        return 2
    results = []
    for path in paths:
        try:
            _, result = convert_file(path, os.devnull, embed_manifest=False)
            results.append((os.path.relpath(path, args.directory), result.report))
        except Exception as exc:  # never abort the whole run on one file
            print(f"warning: {path} failed: {exc}", file=sys.stderr)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(aggregate_html(results))
    print(f"wrote {args.output} ({len(results)} document(s))", file=sys.stderr)
    return 0


def _cmd_convert(args: argparse.Namespace) -> int:
    try:
        output_path, result = convert_file(
            args.input,
            args.output,
            embed_manifest=not args.no_manifest,
            number_by_section=args.number_by_section,
            citation_mode=args.citations,
            columns=args.columns,
            frontend=args.frontend,
            math_image_fallback=args.math_image_fallback,
            csl=args.csl,
            reference_doc=args.reference_doc,
            language=args.lang,
        )
    except FileNotFoundError:
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2

    if args.report:
        content = (
            result.report.to_html()
            if args.report.endswith(".html")
            else result.report.to_json()
        )
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(content)

    if not args.quiet:
        print(f"wrote {output_path}", file=sys.stderr)
        print(result.report.summary(), file=sys.stderr)
        for entry in result.report.errors:
            print(f"  error [{entry.construct}]: {entry.message}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
