"""Entry point for `python -m scuf_envision`."""
import argparse
import logging


def main():
    parser = argparse.ArgumentParser(description="SCUF Envision Pro V2 Linux Driver")
    parser.add_argument("--profile", metavar="NAME",
                        help="Activate a named profile from config on startup")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from .bridge import run
    run(initial_profile=args.profile)


main()
