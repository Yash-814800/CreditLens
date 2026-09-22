import pytest

from app.core.config import Settings, load_settings

pytestmark = pytest.mark.unit

_VALID_SECRET = "a" * 32
_VALID_PEPPER = "b" * 32


def _base_kwargs(**overrides):
    kwargs = dict(
        app_env="production",
        jwt_secret=_VALID_SECRET,
        hmac_pepper=_VALID_PEPPER,
        mock_llm=False,
        demo_underwriter_password="a-real-password",
        demo_auditor_password="a-real-password",
        demo_admin_password="a-real-password",
    )
    kwargs.update(overrides)
    return kwargs


def test_development_mode_has_no_guard_errors_even_with_placeholders():
    settings = Settings(app_env="development", jwt_secret="", hmac_pepper="", mock_llm=True)
    assert settings.production_guard_errors() == []


def test_production_mode_accepts_valid_config():
    settings = Settings(**_base_kwargs())
    assert settings.production_guard_errors() == []


def test_production_rejects_mock_llm():
    settings = Settings(**_base_kwargs(mock_llm=True))
    errors = settings.production_guard_errors()
    assert any("MOCK_LLM" in e for e in errors)


def test_production_rejects_short_jwt_secret():
    settings = Settings(**_base_kwargs(jwt_secret="short"))
    errors = settings.production_guard_errors()
    assert any("JWT_SECRET" in e for e in errors)


def test_production_rejects_placeholder_jwt_secret():
    settings = Settings(**_base_kwargs(jwt_secret="change-me-to-a-random-32-plus-character-secret"))
    errors = settings.production_guard_errors()
    assert any("JWT_SECRET" in e for e in errors)


def test_production_rejects_placeholder_hmac_pepper():
    settings = Settings(
        **_base_kwargs(hmac_pepper="change-me-to-a-random-32-plus-character-pepper")
    )
    errors = settings.production_guard_errors()
    assert any("HMAC_PEPPER" in e for e in errors)


def test_production_rejects_placeholder_demo_passwords():
    settings = Settings(**_base_kwargs(demo_admin_password="change-me-demo-only"))
    errors = settings.production_guard_errors()
    assert any("DEMO_ADMIN_PASSWORD" in e for e in errors)


def test_cors_origin_list_splits_and_strips():
    settings = Settings(cors_origins=" http://a.com , http://b.com ")
    assert settings.cors_origin_list == ["http://a.com", "http://b.com"]


def test_load_settings_refuses_unsafe_production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MOCK_LLM", "true")
    monkeypatch.setenv("JWT_SECRET", "short")
    monkeypatch.setenv("HMAC_PEPPER", "short")
    with pytest.raises(RuntimeError, match="Refusing to start in production mode"):
        load_settings()


def test_load_settings_succeeds_for_safe_production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MOCK_LLM", "false")
    monkeypatch.setenv("JWT_SECRET", _VALID_SECRET)
    monkeypatch.setenv("HMAC_PEPPER", _VALID_PEPPER)
    monkeypatch.setenv("DEMO_UNDERWRITER_PASSWORD", "a-real-password")
    monkeypatch.setenv("DEMO_AUDITOR_PASSWORD", "a-real-password")
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "a-real-password")
    load_settings()  # must not raise
