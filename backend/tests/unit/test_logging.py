import pytest

from app.core.logging import configure_logging, get_logger

pytestmark = pytest.mark.unit


def test_pii_redaction_processor_masks_known_keys_and_value_shapes(capsys):
    configure_logging("INFO")
    logger = get_logger("test")

    logger.info(
        "user_action",
        password="hunter2",
        aadhaar="1234 5678 9012",
        pan="ABCDE1234F",
        phone="9876543210",
        message="contact 9876543210 or PAN ABCDE1234F for aadhaar 123456789012",
    )

    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert "1234 5678 9012" not in out
    assert "9876543210" not in out
    assert "ABCDE1234F" not in out
    assert "123456789012" not in out
    assert "REDACTED" in out
