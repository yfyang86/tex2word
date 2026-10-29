"""Run probes: write each into a private directory, convert, apply the oracles."""

from __future__ import annotations

import os
import signal
import tempfile
import time
import traceback
from collections.abc import Iterable, Iterator
from multiprocessing import get_context

from .assets import DEFAULT_FILES
from .model import Finding, Probe, Result
from .oracles import check, parse_docx

#: seconds before a single conversion counts as hung
TIMEOUT = 30


class _Timeout(Exception):
    pass


def _alarm(signum, frame):  # noqa: ARG001 - signal handler signature
    raise _Timeout()


def write_probe(probe: Probe, directory: str) -> str:
    """Materialise ``probe`` (main.tex + its files) in ``directory``."""
    files = {**DEFAULT_FILES, **probe.files}
    for rel, content in files.items():
        path = os.path.join(directory, rel)
        os.makedirs(os.path.dirname(path) or directory, exist_ok=True)
        if isinstance(content, bytes):
            with open(path, "wb") as fh:
                fh.write(content)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
    main = os.path.join(directory, "main.tex")
    with open(main, "w", encoding="utf-8") as fh:
        fh.write(probe.source)
    return main


def convert(probe: Probe, directory: str):
    """Convert a materialised probe; returns the ConversionResult."""
    from tex2word import convert_source

    return convert_source(probe.source, base_dir=directory)


def run_probe(probe: Probe) -> Result:
    start = time.perf_counter()
    res = Result(probe.id)
    with tempfile.TemporaryDirectory(prefix="t2w-synth-") as tmp:
        write_probe(probe, tmp)
        old = signal.signal(signal.SIGALRM, _alarm) if hasattr(signal, "SIGALRM") else None
        if old is not None:
            signal.alarm(TIMEOUT)
        try:
            result = convert(probe, tmp)
        except _Timeout:
            res.findings.append(Finding("timeout", f"no result after {TIMEOUT}s"))
            return _done(res, start)
        except Exception as exc:  # noqa: BLE001 - a crash is a finding, not a harness error
            tb = traceback.extract_tb(exc.__traceback__)
            where = f"{os.path.basename(tb[-1].filename)}:{tb[-1].name}" if tb else "?"
            res.findings.append(
                Finding(f"crash:{type(exc).__name__}@{where}", f"{exc}"[:300])
            )
            return _done(res, start)
        finally:
            if old is not None:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old)
    try:
        parsed = parse_docx(result.docx)
    except Exception as exc:  # noqa: BLE001
        res.findings.append(Finding("unreadable-docx", str(exc)[:200]))
        parsed = None
    res.findings.extend(check(probe, result, parsed))
    res.text = parsed.text if parsed else ""
    res.warnings = [f"{w.construct}: {w.message}" for w in result.report.warnings]
    return _done(res, start)


def _done(res: Result, start: float) -> Result:
    res.seconds = time.perf_counter() - start
    return res


def _init_worker(allow_tikz: bool) -> None:
    if not allow_tikz:
        # TikZ compiles are slow and depend on the machine's TeX install: off by
        # default, so results are deterministic (the "not rendered" path).
        from tex2word.backend import tikz

        tikz.available_engines = lambda: []  # type: ignore[assignment]


def _run_inline(probes: list[Probe], allow_tikz: bool) -> Iterator[Result]:
    """Run in this process, undoing the TikZ switch afterwards."""
    from tex2word.backend import tikz

    saved = tikz.available_engines
    _init_worker(allow_tikz)
    try:
        for p in probes:
            yield run_probe(p)
    finally:
        tikz.available_engines = saved  # type: ignore[assignment]


def run_all(
    probes: Iterable[Probe], *, jobs: int | None = None, allow_tikz: bool = False
) -> Iterator[Result]:
    """Run probes in parallel, yielding results as they finish."""
    probes = list(probes)
    jobs = jobs or min(os.cpu_count() or 1, 8)
    if jobs <= 1 or len(probes) < 8:
        yield from _run_inline(probes, allow_tikz)
        return
    ctx = get_context("fork")
    with ctx.Pool(jobs, initializer=_init_worker, initargs=(allow_tikz,)) as pool:
        yield from pool.imap_unordered(run_probe, probes, chunksize=8)
