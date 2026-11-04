"""Download public tennis/badminton/pickleball clips with ball labels for evaluation.

    uv run python ml/fetch_eval_data.py --list
    uv run python ml/fetch_eval_data.py tracknet-tennis kwyoke-badminton
    uv run python ml/fetch_eval_data.py --all
    uv run python ml/fetch_eval_data.py --suite ci        # the subset CI scores on every pull request

Writes ml/external/eval/<source>/ (git-ignored): clips/*.mp4, labels/*.json in the
ml/labels format, and source.json. Re-running resumes: finished downloads are kept.
These clips are evaluation-only; see ml/EVAL_DATA.md for licenses and what each one measures.
"""
import argparse
import sys

from eval_data import EVAL, SOURCES, SUITES, fetch_source, fetched_sources
import eval_sources  # noqa: F401  (registers the sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="*", help="source names (see --list)")
    parser.add_argument("--all", action="store_true", help="fetch every source")
    parser.add_argument("--suite", choices=sorted(SUITES), help="fetch the sources of a named subset")
    parser.add_argument("--list", action="store_true", help="list sources and what is already fetched")
    args = parser.parse_args()
    if args.list or not (args.sources or args.all or args.suite):
        fetched = fetched_sources()
        for name, spec in SOURCES.items():
            done = fetched.get(name)
            status = (f"fetched: {len(done['clips'])} clips, {sum(c['labeled'] for c in done['clips'])} labeled frames"
                      if done else f"not fetched ({spec.download_size})")
            print(f"{name:24s} {spec.sport:10s} {status}\n{'':35s}{spec.view}\n{'':35s}license: {spec.license}")
        return
    names = list(SOURCES) if args.all else [*SUITES.get(args.suite, ()), *args.sources]
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        parser.error(f"unknown source(s): {', '.join(unknown)}; see --list")
    failed = []
    for name in names:
        print(f"== {name}", file=sys.stderr)
        try:
            clips = fetch_source(name)
        except Exception as error:  # keep going: one broken host should not block the others
            failed.append(name)
            print(f"{name} failed: {error!r}", file=sys.stderr)
            continue
        print(f"{name}: {len(clips)} clips, {sum(c['labeled'] for c in clips)} labeled frames, "
              f"{sum(c['visible'] for c in clips)} with a visible ball -> {EVAL / name}")
    if failed:
        raise SystemExit(f"Failed: {', '.join(failed)} (re-run to resume)")


if __name__ == "__main__":
    main()
