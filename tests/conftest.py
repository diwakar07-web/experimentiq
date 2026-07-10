import pytest
import pandas as pd
from datetime import datetime
from config.settings import get_settings

@pytest.fixture(scope='module')
def mock_settings():
    """Returns a test configuration with small dataset size."""
    settings = get_settings()
    settings.data_generation.target_users = 100
    return settings

@pytest.fixture
def known_z_test_inputs():
    """Returns inputs where we know the statistical outcome."""
    return {
        "control_n": 1000,
        "variant_n": 1000,
        "control_conversions": 100,  # 10%
        "variant_conversions": 150   # 15%
        # Expected: Significant difference
    }

@pytest.fixture(scope='module')
def sample_users_df():
    data = {
        "user_id": [f"user_{i}" for i in range(10)],
        "signup_date": [datetime.utcnow()] * 10,
        "country_id": ["US"] * 10,
        "device_id": ["mobile"] * 10,
        "channel_id": ["organic"] * 10,
        "customer_type": ["new"] * 10
    }
    return pd.DataFrame(data)

@pytest.fixture(scope='module')
def sample_experiments_df():
    data = {
        "experiment_id": ["exp_1"] * 10,
        "experiment_name": ["Test A"] * 10,
        "user_id": [f"user_{i}" for i in range(10)],
        "variant": ["control", "variant"] * 5,
        "is_holdout": [False] * 10,
        "assignment_timestamp": [datetime.utcnow()] * 10
    }
    return pd.DataFrame(data)
