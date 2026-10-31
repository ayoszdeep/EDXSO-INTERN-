from src.enrichment.contact_extractor import (
    extract_emails, extract_instagram, extract_website, pick_business_email,
)
from src.enrichment.email_finder import find_email, validate_email_syntax


def test_email_syntax_validation():
    assert validate_email_syntax("collabs@creator.com")
    assert validate_email_syntax("user.name+tag@domain.co.uk")
    assert not validate_email_syntax("invalid-email")
    assert not validate_email_syntax("@nodomain.com")
    assert not validate_email_syntax("spaces in@email.com")
    assert not validate_email_syntax("")


def test_extract_emails_handles_obfuscation_and_junk():
    text = "Business: jane [at] python [dot] org | img logo@2x.png | test@example.com | noreply@x.io"
    assert extract_emails(text) == ["jane@python.org"]


def test_business_email_preferred():
    assert pick_business_email(["jane@site.com", "business@site.com"]) == "business@site.com"
    assert pick_business_email([]) is None


def test_missing_email_is_not_found_never_guessed():
    res = find_email("No contact info here", "https://youtube.com/@x/about",
                     [{"description": "Thanks for watching", "url": "u"}], None)
    assert res == {"email": "Not Found", "email_source": "Not Found",
                   "email_source_url": "Not Found", "email_validation_status": "unavailable"}


def test_email_found_records_source():
    res = find_email("", "about-url", [{"description": "Sponsorships: team@python.org", "url": "video-url"}], None)
    assert res["email"] == "team@python.org"
    assert res["email_source"] == "YouTube video description"
    assert res["email_source_url"] == "video-url"


def test_instagram_and_website_extraction():
    texts = ["Follow instagram.com/jane.codes", "IG: https://www.instagram.com/jane.codes/ and instagram.com/p/abc"]
    assert extract_instagram(texts) == "jane.codes"
    assert extract_instagram(["nothing"]) is None
    desc = "Courses: https://bit.ly/x Site: https://janecodes.dev/ Twitter https://x.com/jane"
    assert extract_website(desc) == "https://janecodes.dev/"
    assert extract_website("only https://youtube.com/@jane") is None
