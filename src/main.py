# src/main.py
"""Influencer Outreach Pipeline - command line entry point.

  python -m src.main                  run every stage end-to-end
  python -m src.main --discover       1. search YouTube for candidate channels
  python -m src.main --collect        2. fetch public profile + recent video stats
  python -m src.main --filter         3. classify niche, apply rules, score
  python -m src.main --enrich         4. find published email / Instagram / website
  python -m src.main --personalize    5. generate email + Instagram DM
  python -m src.main --validate       6. re-check word limits
  python -m src.main --review         7. approve / reject messages
  python -m src.main --outreach       8. send (or simulate) emails, queue DMs, log
  python -m src.main --export         9. write dataset, sample messages, summary
  python -m src.main --mark-dm-sent ID [ID ...]   record DMs an operator sent by hand
"""
import argparse
import logging
import sys

from config.settings import load_campaign_config, settings
from src.ai.message_validator import validate_all_messages
from src.ai.personalization import generate_messages
from src.database.db import init_db
from src.discovery.discover import collect_profiles, discover_influencers
from src.enrichment.profile_enricher import enrich_profiles
from src.outreach.dm_manager import export_dm_queue, mark_dm_sent
from src.outreach.tracker import export_outreach_log, process_outreach, review_messages
from src.processing.filtering import filter_influencers
from src.reports.exporter import export_all

STAGES = ["discover", "collect", "filter", "enrich", "personalize", "validate", "review", "outreach", "export"]


def configure_logging() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def print_summary(summary: dict) -> None:
    print("\n" + "=" * 64)
    print(f"  {summary['campaign_name']}")
    print("=" * 64)
    for key in ("discovered_channels", "profiles_collected", "in_follower_range", "qualified",
                "needs_review", "not_qualified", "shortlist_with_valid_email", "shortlist_with_instagram",
                "messages_generated", "messages_valid"):
        print(f"  {key.replace('_', ' ').capitalize():<32}{summary[key]}")
    print("  Outreach:")
    for key, n in sorted(summary["outreach_by_channel_status"].items()):
        print(f"    {key:<40}{n}")
    print("=" * 64)
    print("  Outputs: data/raw, data/processed, data/exports")
    print("=" * 64 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Influencer outreach pipeline")
    for stage in STAGES:
        parser.add_argument(f"--{stage}", action="store_true", help=f"Run only the {stage} stage")
    parser.add_argument("--mark-dm-sent", nargs="+", metavar="INFLUENCER_ID",
                        help="Mark Instagram DMs as sent manually")
    args = parser.parse_args()

    configure_logging()
    logger = logging.getLogger("main")
    init_db()
    config = load_campaign_config()

    if args.mark_dm_sent:
        mark_dm_sent(args.mark_dm_sent, config["campaign_id"])
        export_dm_queue(config["campaign_id"])
        export_outreach_log(config["campaign_id"])
        return

    selected = [s for s in STAGES if getattr(args, s)]
    run = set(selected or STAGES)
    try:
        if "discover" in run:
            logger.info(">>> Stage 1: Discovery")
            discover_influencers(config=config)
        if "collect" in run:
            logger.info(">>> Stage 2: Data collection")
            collect_profiles(config=config)
        if "filter" in run:
            logger.info(">>> Stage 3: Filtering & classification")
            filter_influencers(config)
        if "enrich" in run:
            logger.info(">>> Stage 4: Profile enrichment")
            enrich_profiles()
        if "personalize" in run:
            logger.info(">>> Stage 5: Message personalization")
            generate_messages(config)
        if "validate" in run:
            logger.info(">>> Stage 6: Message validation")
            validate_all_messages()
        if "review" in run:
            logger.info(">>> Stage 7: Review")
            review_messages(config)
        if "outreach" in run:
            logger.info(">>> Stage 8: Sending & tracking")
            process_outreach(config)
        if "export" in run:
            logger.info(">>> Stage 9: Export")
            print_summary(export_all(config))
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
