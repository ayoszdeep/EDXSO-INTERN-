# src/ai/personalization.py
"""Stage 5: personalized outreach generation for shortlisted creators.

With OPENAI_API_KEY set, an LLM writes each email + DM from the creator's real
profile (prompts/outreach_prompt.txt). Output that breaks the word limits gets
one corrective retry; if it still fails (or no key is set) the rule-based
composer in src/ai/composer.py is used. The method used is recorded per message.
"""
import csv
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import load_campaign_config, settings
from src.ai.composer import choose_angle, compose_messages, greeting_name, ANGLES
from src.ai.message_validator import validate_messages
from src.database.db import fetch_all, save_message

LOGGER = logging.getLogger(__name__)
REQUIRED_KEYS = ("email_subject", "email_body", "instagram_dm")


def load_prompt_template(brand: Optional[Dict[str, Any]] = None) -> str:
    brand = brand or load_campaign_config()["brand"]
    template = settings.PROMPT_PATH.read_text(encoding="utf-8").strip()
    return template.replace("{brand_name}", brand["name"]).replace("{brand_product}", brand["product"])


def build_profile(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "influencer_id": row["influencer_id"],
        "name": row["name"],
        "greeting_name": greeting_name(row["name"]),
        "platform": row.get("platform", "YouTube"),
        "follower_count": row.get("follower_count") or 0,
        "engagement_rate": row.get("engagement_rate"),
        "sub_niche": row.get("sub_niche"),
        "content_themes": [t for t in (row.get("content_themes") or "").split("; ") if t],
        "content_style": row.get("content_style"),
        "recent_content": [{"title": v.get("title"), "url": v.get("url"), "views": v.get("view_count")}
                           for v in json.loads(row.get("recent_content") or "[]")],
    }


def generate_with_openai(system_prompt: str, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call the LLM; one corrective retry if word limits are missed."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30)
    except Exception as e:
        LOGGER.warning("OpenAI client unavailable: %s", e)
        return None

    angle_key = choose_angle(profile["follower_count"], profile["engagement_rate"], profile["content_style"] or "")
    payload = {**profile, "suggested_collaboration": ANGLES[angle_key][0]}
    payload.pop("influencer_id", None)
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": "Creator profile:\n" + json.dumps(payload, ensure_ascii=False)}]

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL, response_format={"type": "json_object"},
                messages=messages, temperature=0.8, max_tokens=600)
            result = json.loads(response.choices[0].message.content)
        except Exception as e:
            LOGGER.warning("OpenAI call failed for %s: %s", profile["name"], e)
            return None
        if not all(isinstance(result.get(k), str) and result[k].strip() for k in REQUIRED_KEYS):
            LOGGER.warning("LLM response missing keys for %s", profile["name"])
            return None
        check = validate_messages(result["email_body"], result["instagram_dm"], profile["greeting_name"])
        if check["valid"]:
            return result
        messages += [{"role": "assistant", "content": json.dumps(result)},
                     {"role": "user", "content": "Fix these problems and return the full JSON again: "
                                                 + "; ".join(check["errors"])}]
    LOGGER.info("LLM output for %s failed validation twice; using composer", profile["name"])
    return None


def generate_messages(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    config = config or load_campaign_config()
    rows = fetch_all("""
        SELECT i.*, c.sub_niche, c.content_themes, c.content_style, c.brand_fit_score
        FROM influencers i JOIN classifications c USING (influencer_id)
        WHERE c.qualification_status = 'Qualified'
        ORDER BY c.brand_fit_score DESC
    """)
    if not rows:
        LOGGER.warning("No qualified influencers to message. Run --filter first.")
        return []

    # Keep messages that were already sent untouched; regenerate the rest.
    sent_ids = {r["influencer_id"] for r in fetch_all(
        "SELECT influencer_id FROM outreach WHERE campaign_id = ? AND channel = 'email' "
        "AND status IN ('Simulated', 'Sent')", (config["campaign_id"],))}

    use_llm = bool(settings.OPENAI_API_KEY)
    system_prompt = load_prompt_template(config["brand"]) if use_llm else ""
    LOGGER.info("Generating messages for %d qualified creators (%s)", len(rows),
                f"LLM: {settings.OPENAI_MODEL}" if use_llm else "rule-based composer; no OPENAI_API_KEY set")

    generated = []
    for row in rows:
        if row["influencer_id"] in sent_ids:
            continue
        profile = build_profile(row)
        result, method = None, "rule-based composer"
        if use_llm:
            result = generate_with_openai(system_prompt, profile)
            method = f"llm:{settings.OPENAI_MODEL}" if result else "rule-based composer (LLM fallback)"
        if not result:
            result = compose_messages({**profile, "sub_niche": row.get("sub_niche")},
                                      config["brand"], config["target_sub_niches"])

        check = validate_messages(result["email_body"], result["instagram_dm"], profile["greeting_name"])
        record = {
            "influencer_id": row["influencer_id"],
            "campaign_id": config["campaign_id"],
            "name": row["name"],
            "email_subject": result["email_subject"].strip(),
            "email_body": result["email_body"].strip(),
            "email_word_count": check["email_word_count"],
            "instagram_dm": result["instagram_dm"].strip(),
            "dm_word_count": check["dm_word_count"],
            "personalization_signals": str(result.get("personalization_signals", "")),
            "collaboration_type": str(result.get("collaboration_type", "")),
            "generation_method": method,
            "validation_status": "Valid" if check["valid"] else "Invalid",
            "validation_errors": "; ".join(check["errors"]),
            "review_status": "Pending Review",
            "reviewed_at": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        save_message(record)
        generated.append(record)

    export_messages_csv(config["campaign_id"])
    LOGGER.info("Generated %d message sets (%d valid)", len(generated),
                sum(1 for g in generated if g["validation_status"] == "Valid"))
    return generated


def export_messages_csv(campaign_id: str) -> None:
    rows = fetch_all("""
        SELECT m.*, e.contact_email, e.instagram_handle
        FROM messages m LEFT JOIN enrichments e USING (influencer_id)
        WHERE m.campaign_id = ? ORDER BY m.name
    """, (campaign_id,))
    path = settings.DATA_ROOT / "exports" / "personalized_messages.csv"
    headers = ["influencer_id", "name", "contact_email", "instagram_handle", "email_subject", "email_body",
               "email_word_count", "instagram_dm", "dm_word_count", "collaboration_type",
               "personalization_signals", "generation_method", "validation_status", "validation_errors",
               "review_status", "generated_at"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    LOGGER.info("Saved %d message sets to %s", len(rows), path)
