from synthgen.fonts import font


def test_rupee_glyph_renders_in_house_font():
    f = font("house", 24)
    assert f.getmask("₹").getbbox() is not None


def test_rupee_glyph_renders_in_tamper_font():
    f = font("tamper", 24)
    assert f.getmask("₹").getbbox() is not None
