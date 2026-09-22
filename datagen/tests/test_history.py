import numpy as np

from synthgen.history import FEATURE_COLS, generate_history


def test_history_shape_and_default_rate():
    df = generate_history(n_rows=2000, target_default_rate=0.12)
    assert len(df) == 2000
    rate = df["defaulted"].mean()
    assert 0.08 <= rate <= 0.16, f"default rate {rate:.3f} outside target band"


def test_history_is_deterministic():
    df1 = generate_history(n_rows=500)
    df2 = generate_history(n_rows=500)
    assert df1.equals(df2)


def test_group_label_independent_of_features():
    """group_label is drawn independently of z/u/cohort -- no feature should
    correlate strongly with it (it must never leak into the scorecard)."""
    df = generate_history(n_rows=2000)
    group_numeric = (df["group_label"] == "A").astype(float)
    for col in FEATURE_COLS:
        valid = df[col].notna()
        r = np.corrcoef(df.loc[valid, col], group_numeric[valid])[0, 1]
        assert abs(r) < 0.12, f"{col} correlates with group_label at r={r:.3f}, expected near-zero"


def test_missingness_present_for_thin_files():
    df = generate_history(n_rows=2000)
    assert df["utility_tenure_months"].isna().mean() > 0
    assert df["gig_active_days_per_week"].isna().mean() > 0


def test_split_covers_all_three_buckets():
    df = generate_history(n_rows=2000)
    assert set(df["split"].unique()) == {"train", "val", "test"}
