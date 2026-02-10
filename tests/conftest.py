"""

Pytest Configuration and Fixtures

===================================

Shared fixtures and configuration for the test suite.

"""



import asyncio

import sys

import os

from unittest.mock import MagicMock, AsyncMock



import pytest



# Add project root to path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))





# =============================================================================

# ASYNC EVENT LOOP FIXTURE

# =============================================================================



@pytest.fixture(scope="session")

def event_loop():

    """Create an event loop for async tests."""

    loop = asyncio.new_event_loop()

    yield loop

    loop.close()





# =============================================================================

# MOCK FIXTURES

# =============================================================================



@pytest.fixture

def mock_xrpl_response_success():

    """Create a successful XRPL API response mock."""

    response = MagicMock()

    response.is_successful.return_value = True

    response.result = {

        "account_data": {

            "Account": "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",

            "Balance": "100000000",

            "Sequence": 1234,

            "OwnerCount": 5,

        }

    }

    return response





@pytest.fixture

def mock_xrpl_response_not_found():

    """Create an account-not-found XRPL API response mock."""

    response = MagicMock()

    response.is_successful.return_value = False

    response.result = {

        "error": "actNotFound",

        "error_message": "Account not found.",

    }

    return response





@pytest.fixture

def mock_weather_data():

    """Sample weather API response data."""

    return {

        "coord": {"lon": -74.006, "lat": 40.7143},

        "weather": [

            {"id": 800, "main": "Clear", "description": "clear sky", "icon": "01d"}

        ],

        "main": {

            "temp": 72.5,

            "feels_like": 70.2,

            "temp_min": 68.0,

            "temp_max": 76.0,

            "humidity": 45,

            "pressure": 1015,

        },

        "visibility": 16093,

        "wind": {"speed": 5.5, "deg": 180, "gust": 8.0},

        "clouds": {"all": 10},

        "dt": 1699900000,

        "sys": {

            "country": "US",

            "sunrise": 1699870000,

            "sunset": 1699908000,

        },

        "timezone": -18000,

        "name": "New York",

    }





@pytest.fixture

def mock_aiohttp_session():

    """Create a mock aiohttp ClientSession."""

    session = MagicMock()

    session.__aenter__ = AsyncMock(return_value=session)

    session.__aexit__ = AsyncMock(return_value=None)

    return session





@pytest.fixture

def mock_aiohttp_response(mock_weather_data):

    """Create a mock aiohttp response."""

    response = MagicMock()

    response.status = 200

    response.json = AsyncMock(return_value=mock_weather_data)

    return response





# =============================================================================

# SAMPLE DATA FIXTURES

# =============================================================================



@pytest.fixture

def valid_xrp_addresses():

    """List of valid XRP addresses for testing."""

    return [

        "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",

        "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",

        "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",

    ]





@pytest.fixture

def invalid_xrp_addresses():

    """List of invalid XRP addresses for testing."""

    return [

        "",

        "invalid",

        "r",

        "1N7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",

        "0x1234567890abcdef",

    ]





@pytest.fixture

def sample_nft_list():

    """Sample NFT data for testing."""

    return [

        {

            "NFTokenID": "000800007C4C336C0000000000000001",

            "Issuer": "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",

            "NFTokenTaxon": 0,

            "nft_serial": 1,

            "URI": "68747470733A2F2F6578616D706C652E636F6D2F6E66742F31",

        },

        {

            "NFTokenID": "000800007C4C336C0000000000000002",

            "Issuer": "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",

            "NFTokenTaxon": 1,

            "nft_serial": 2,

        },

    ]





@pytest.fixture

def sample_trust_lines():

    """Sample trust line data for testing."""

    return [

        {

            "account": "rIssuerAddress123456789012345",

            "currency": "USD",

            "balance": "100.50",

            "limit": "1000000",

        },

        {

            "account": "rAnotherIssuer123456789012",

            "currency": "EUR",

            "balance": "50.25",

            "limit": "500000",

        },

    ]





# =============================================================================

# UTILITY FIXTURES

# =============================================================================



@pytest.fixture

def temp_env_vars(monkeypatch):

    """Set temporary environment variables for testing."""

    def _set_env(**kwargs):

        for key, value in kwargs.items():

            monkeypatch.setenv(key, value)

    return _set_env

