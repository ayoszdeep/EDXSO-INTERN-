from src.ai.composer import best_title, choose_angle, clean_title, compose_messages, greeting_name
from src.ai.message_validator import count_words, validate_messages
from src.ai.personalization import load_prompt_template

BRAND = {"name": "DevFlow AI", "product": "an AI coding assistant that writes tests",
         "product_short": "an AI coding assistant"}
TARGETS = ["Software Development", "AI & Machine Learning"]


def profile(iid, name, title, themes, style, subs, eng):
    return {"influencer_id": iid, "name": name, "follower_count": subs, "engagement_rate": eng,
            "sub_niche": "AI & Machine Learning", "content_themes": themes, "content_style": style,
            "recent_content": [{"title": title}]}


PROFILES = [
    profile("A", "Jane Doe", "Build a RAG Chatbot with LangChain", ["AI agents & LLM apps"], "project build", 42000, 4.2),
    profile("B", "CodeWithSam", "FastAPI Tutorial for Beginners | Full Course 2026", ["Python development"], "tutorial", 9000, 3.1),
    profile("C", "Dev Reviews", "Cursor vs Copilot: Honest Review", ["AI coding tools"], "review", 60000, 2.0),
    profile("D", "Ana Lima", "Ollama Local LLM Setup", ["local and open-source LLMs"], "tutorial", 30000, 7.5),
]


def test_prompt_template_fills_brand():
    prompt = load_prompt_template(BRAND)
    assert "DevFlow AI" in prompt and "60 and 90 words" in prompt and "{brand_name}" not in prompt


def test_messages_respect_word_limits():
    for p in PROFILES:
        msg = compose_messages(p, BRAND, TARGETS)
        assert 60 <= count_words(msg["email_body"]) <= 90, msg["email_body"]
        assert 15 <= count_words(msg["instagram_dm"]) <= 30, msg["instagram_dm"]
        assert validate_messages(msg["email_body"], msg["instagram_dm"], greeting_name(p["name"]))["valid"]


def test_messages_are_personalized_not_one_template():
    msgs = [compose_messages(p, BRAND, TARGETS) for p in PROFILES]
    assert len({m["email_body"] for m in msgs}) == len(msgs)
    assert len({m["collaboration_type"] for m in msgs}) >= 3
    for p, m in zip(PROFILES, msgs):
        assert clean_title(p["recent_content"][0]["title"]) in m["email_body"]


def test_titles_are_never_cut_mid_phrase():
    assert clean_title("FastAPI Tutorial for Beginners | Full Course 2026") == "FastAPI Tutorial for Beginners"
    assert clean_title("🔥 BUILD AN AI AGENT 🔥 #python") == "Build An AI Agent"
    long = "This is a really long title that just keeps going and going without any separator at all"
    assert clean_title(long) is None
    assert best_title([{"title": long}], TARGETS) is None


def test_angle_follows_signals():
    assert choose_angle(9000, 3.0, "tutorial") == "affiliate"
    assert choose_angle(40000, 7.0, "tutorial") == "ambassador"
    assert choose_angle(40000, 3.0, "review") == "review"
    assert choose_angle(40000, 3.0, "tutorial") == "tutorial"


def test_greeting_uses_first_name_only_for_person_names():
    assert greeting_name("Jane Doe") == "Jane"
    assert greeting_name("Tech With Tim") == "Tech With Tim"
    assert greeting_name("CodeWithSam") == "CodeWithSam"


def test_validator_flags_problems():
    res = validate_messages("word " * 40, "Hi [Name] " + "word " * 20)
    assert not res["valid"]
    assert any("60-90" in e for e in res["errors"]) and any("placeholder" in e for e in res["errors"])


def test_channel_name_taglines_removed():
    assert greeting_name("Smitha Kolan - Machine Learning Engineer") == "Smitha"
    assert greeting_name("@Chander Mani Pandey") == "Chander"
    assert greeting_name("DevForge | AI Tutorials") == "DevForge"
