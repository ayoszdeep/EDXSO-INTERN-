from src.database.db import fetch_all
from src.discovery.discover import collect_profiles, discover_influencers
from src.processing.content_analysis import (
    classify_niche, detect_content_style, detect_language, evaluate_content_relevance,
)
from src.processing.filtering import filter_influencers
from src.processing.scoring import calculate_brand_fit_score


def _statuses(fake_client, config):
    discover_influencers(fake_client, config)
    collect_profiles(fake_client, config)
    filter_influencers(config)
    return {r["influencer_id"]: r for r in fetch_all("SELECT * FROM classifications")}


def test_each_rule_produces_an_explained_decision(fake_client, config):
    s = _statuses(fake_client, config)
    assert s["UC_PY"]["qualification_status"] == "Qualified"
    assert "Too many followers" in s["UC_BIG"]["qualification_reason"]
    assert s["UC_PHONE"]["qualification_status"] == "Not Qualified"
    assert "Consumer Tech" in s["UC_PHONE"]["qualification_reason"]
    assert "Low engagement" in s["UC_LOWENG"]["qualification_reason"]


def test_classified_csv_written(fake_client, config):
    from config.settings import settings
    _statuses(fake_client, config)
    assert (settings.DATA_ROOT / "processed" / "classified_influencers.csv").exists()


def test_niche_classification():
    assert classify_niche(["Build a RAG app with LangChain", "Ollama local LLM setup"])["sub_niche"] == \
        "AI & Machine Learning"
    assert classify_niche(["iPhone 18 review", "Best budget smartphone"])["sub_niche"] == "Consumer Tech"
    assert classify_niche(["Minecraft gameplay part 3"])["niche"] == "Gaming"
    assert classify_niche(["My grandmother's garden"])["niche"] == "Unclassified"


def test_word_boundaries_avoid_false_matches():
    # "ai" must not match inside "said" / "rain"
    assert classify_niche(["She said it would rain"])["niche"] == "Unclassified"


def test_content_relevance_levels():
    targets = ["Software Development", "AI & Machine Learning"]
    assert evaluate_content_relevance(["Python tips", "Docker basics", "LLM agents"], targets)[0] == "High"
    assert evaluate_content_relevance(["Python tips", "My trip", "Cooking"], targets)[0] == "Moderate"
    assert evaluate_content_relevance(["Pasta recipe"], targets)[0] == "Low"
    assert evaluate_content_relevance([], targets)[0] == "Unknown"


def test_style_and_language():
    assert detect_content_style(["FastAPI tutorial for beginners", "How to deploy Django"]) == "tutorial"
    assert detect_content_style(["Copilot vs Cursor", "Best AI tools review"]) == "review"
    assert detect_language(["Python सीखें हिंदी में पूरा कोर्स"]) == "Non-Latin script"
    assert detect_language(["Learn Python"]) == "English/Latin"


def test_score_rewards_measured_data_only(config):
    full, _ = calculate_brand_fit_score("AI & Machine Learning", "Technology", "High", 30000, 7.0, 3, config)
    missing, parts = calculate_brand_fit_score("AI & Machine Learning", "Technology", "High", 30000, None, None, config)
    assert full == 100
    assert parts["engagement"] == 0 and parts["activity"] == 0 and missing == 65
