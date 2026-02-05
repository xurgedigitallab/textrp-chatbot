"""
Weather Utilities for TextRP Bot
=================================
This module provides weather data fetching capabilities using
the OpenWeatherMap API. Supports queries by city name or ZIP code.

Dependencies:
    pip install requests aiohttp

Usage:
    from weather_utils import WeatherClient
    
    client = WeatherClient(api_key="your_api_key")
    weather = await client.get_weather_by_city("New York")
"""

import asyncio
import logging
import re
from typing import Optional, Dict, Any, Union
from datetime import datetime
from enum import Enum

import aiohttp

# Import retry utilities
try:
    from utils.retry import retry_async, WEATHER_RETRY_EXCEPTIONS
    RETRY_AVAILABLE = True
except ImportError:
    RETRY_AVAILABLE = False
    WEATHER_RETRY_EXCEPTIONS = (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS AND CONFIGURATION
# =============================================================================

# OpenWeatherMap API endpoints
OPENWEATHERMAP_BASE_URL = "https://api.openweathermap.org/data/2.5"
OPENWEATHERMAP_GEO_URL = "https://api.openweathermap.org/geo/1.0"

# Weather condition emoji mappings for chat display
WEATHER_EMOJIS = {
    # Thunderstorm group (2xx)
    "thunderstorm": "⛈️",
    
    # Drizzle group (3xx)
    "drizzle": "🌧️",
    
    # Rain group (5xx)
    "rain": "🌧️",
    "shower rain": "🌧️",
    
    # Snow group (6xx)
    "snow": "❄️",
    "sleet": "🌨️",
    
    # Atmosphere group (7xx)
    "mist": "🌫️",
    "fog": "🌫️",
    "haze": "🌫️",
    "dust": "💨",
    "sand": "💨",
    "tornado": "🌪️",
    
    # Clear (800)
    "clear": "☀️",
    
    # Clouds (80x)
    "clouds": "☁️",
    "few clouds": "🌤️",
    "scattered clouds": "⛅",
    "broken clouds": "🌥️",
    "overcast clouds": "☁️",
}

# Wind direction mappings
WIND_DIRECTIONS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
]


class TemperatureUnit(Enum):
    """Temperature unit options for API requests."""
    CELSIUS = "metric"      # Celsius, meters/sec
    FAHRENHEIT = "imperial" # Fahrenheit, miles/hour
    KELVIN = "standard"     # Kelvin, meters/sec


class WeatherClient:
    """
    Asynchronous weather client using OpenWeatherMap API.
    
    Provides methods to fetch current weather and forecasts
    by city name, ZIP code, or geographic coordinates.
    
    Attributes:
        api_key (str): OpenWeatherMap API key
        units (TemperatureUnit): Temperature unit preference
        lang (str): Language code for weather descriptions
        
    Example:
        >>> weather = WeatherClient(api_key="your_key")
        >>> data = await weather.get_weather_by_city("London")
        >>> print(f"Temperature: {data['temperature']}°C")
    """
    
    def __init__(
        self,
        api_key: str,
        units: TemperatureUnit = TemperatureUnit.FAHRENHEIT,
        lang: str = "en"
    ):
        """
        Initialize the weather client.
        
        Args:
            api_key: Your OpenWeatherMap API key
                    (Get one free at https://openweathermap.org/api)
            units: Temperature unit preference
            lang: Language code for descriptions (en, es, fr, etc.)
        """
        self.api_key = api_key
        self.units = units
        self.lang = lang
        
        # Validate API key is provided
        if not api_key or api_key == "your_openweathermap_api_key":
            logger.warning(
                "No valid API key provided. Get a free key at "
                "https://openweathermap.org/api"
            )
        
        logger.info(f"WeatherClient initialized with units={units.name}")
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    @staticmethod
    def degrees_to_direction(degrees: float) -> str:
        """
        Convert wind direction in degrees to compass direction.
        
        Args:
            degrees: Wind direction in degrees (0-360)
            
        Returns:
            str: Compass direction (N, NE, E, SE, S, SW, W, NW, etc.)
            
        Example:
            >>> WeatherClient.degrees_to_direction(45)
            'NE'
        """
        # Each direction covers 22.5 degrees (360/16)
        index = int((degrees + 11.25) / 22.5) % 16
        return WIND_DIRECTIONS[index]
    
    @staticmethod
    def get_weather_emoji(condition: str) -> str:
        """
        Get an emoji for a weather condition.
        
        Args:
            condition: Weather condition description
            
        Returns:
            str: Appropriate weather emoji
        """
        condition_lower = condition.lower()
        
        # Try exact match first
        if condition_lower in WEATHER_EMOJIS:
            return WEATHER_EMOJIS[condition_lower]
        
        # Try partial match
        for key, emoji in WEATHER_EMOJIS.items():
            if key in condition_lower or condition_lower in key:
                return emoji
        
        # Default emoji
        return "🌡️"
    
    @staticmethod
    def is_zip_code(query: str) -> bool:
        """
        Check if a query looks like a ZIP code.
        
        Supports US ZIP codes (5 digits or 5+4 format) and
        other common postal code formats.
        
        Args:
            query: The search query
            
        Returns:
            bool: True if query appears to be a ZIP/postal code
        """
        # US ZIP code patterns
        us_zip = re.match(r'^\d{5}(-\d{4})?$', query.strip())
        
        # UK postal code pattern
        uk_postal = re.match(
            r'^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$',
            query.strip().upper()
        )
        
        # Canadian postal code pattern
        ca_postal = re.match(
            r'^[A-Z]\d[A-Z]\s*\d[A-Z]\d$',
            query.strip().upper()
        )
        
        return bool(us_zip or uk_postal or ca_postal)
    
    def _get_unit_symbol(self) -> str:
        """Get the temperature unit symbol based on current settings."""
        if self.units == TemperatureUnit.CELSIUS:
            return "°C"
        elif self.units == TemperatureUnit.FAHRENHEIT:
            return "°F"
        else:
            return "K"
    
    def _get_speed_unit(self) -> str:
        """Get the wind speed unit based on current settings."""
        if self.units == TemperatureUnit.FAHRENHEIT:
            return "mph"
        else:
            return "m/s"
    
    # =========================================================================
    # API REQUEST METHODS
    # =========================================================================
    
    async def _make_request(
        self,
        endpoint: str,
        params: Dict[str, Any],
        max_retries: int = 3,
        base_delay: float = 0.5,
    ) -> Optional[Dict[str, Any]]:
        """
        Make an async HTTP request to the OpenWeatherMap API with retry logic.
        
        Args:
            endpoint: API endpoint URL
            params: Query parameters
            max_retries: Maximum retry attempts for transient failures
            base_delay: Initial delay between retries (seconds)
            
        Returns:
            Dict: JSON response data, None on failure
        """
        # Add common parameters
        params["appid"] = self.api_key
        params["units"] = self.units.value
        params["lang"] = self.lang
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(endpoint, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 401:
                            logger.error("Invalid API key. Please check your OpenWeatherMap API key.")
                            return None  # Don't retry auth errors
                        elif response.status == 404:
                            logger.warning("Location not found")
                            return None  # Don't retry not found
                        elif response.status >= 500:
                            # Server errors - retry
                            raise aiohttp.ClientError(f"Server error: {response.status}")
                        else:
                            error_data = await response.json()
                            logger.error(f"API error: {error_data.get('message', 'Unknown error')}")
                            return None
                            
            except WEATHER_RETRY_EXCEPTIONS as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        f"Weather API request failed (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Weather API request failed after {max_retries} attempts: {e}")
                    
            except aiohttp.ClientError as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"HTTP request failed (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"HTTP request failed after {max_retries} attempts: {e}")
                    
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return None
        
        return None
    
    def _parse_weather_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse raw API response into a clean weather data structure.
        
        Args:
            data: Raw API response
            
        Returns:
            Dict: Parsed weather data
        """
        # Extract main weather condition
        weather_info = data.get("weather", [{}])[0]
        main_data = data.get("main", {})
        wind_data = data.get("wind", {})
        clouds_data = data.get("clouds", {})
        sys_data = data.get("sys", {})
        
        # Get condition and emoji
        condition = weather_info.get("description", "Unknown").title()
        condition_main = weather_info.get("main", "Unknown")
        emoji = self.get_weather_emoji(condition_main)
        
        # Calculate wind direction
        wind_deg = wind_data.get("deg", 0)
        wind_direction = self.degrees_to_direction(wind_deg)
        
        # Parse sunrise/sunset times
        sunrise = sys_data.get("sunrise")
        sunset = sys_data.get("sunset")
        
        return {
            # Location info
            "city": data.get("name", "Unknown"),
            "country": sys_data.get("country", ""),
            "coordinates": {
                "lat": data.get("coord", {}).get("lat"),
                "lon": data.get("coord", {}).get("lon"),
            },
            
            # Current conditions
            "condition": condition,
            "condition_main": condition_main,
            "condition_id": weather_info.get("id"),
            "emoji": emoji,
            "icon": weather_info.get("icon"),
            
            # Temperature
            "temperature": main_data.get("temp"),
            "feels_like": main_data.get("feels_like"),
            "temp_min": main_data.get("temp_min"),
            "temp_max": main_data.get("temp_max"),
            "unit_symbol": self._get_unit_symbol(),
            
            # Atmosphere
            "humidity": main_data.get("humidity"),
            "pressure": main_data.get("pressure"),
            "visibility": data.get("visibility"),  # in meters
            "clouds": clouds_data.get("all"),  # percentage
            
            # Wind
            "wind_speed": wind_data.get("speed"),
            "wind_deg": wind_deg,
            "wind_direction": wind_direction,
            "wind_gust": wind_data.get("gust"),
            "speed_unit": self._get_speed_unit(),
            
            # Sun times
            "sunrise": datetime.fromtimestamp(sunrise) if sunrise else None,
            "sunset": datetime.fromtimestamp(sunset) if sunset else None,
            
            # Metadata
            "timezone_offset": data.get("timezone"),  # seconds from UTC
            "timestamp": datetime.fromtimestamp(data.get("dt", 0)),
        }
    
    # =========================================================================
    # WEATHER QUERY METHODS
    # =========================================================================
    
    async def get_weather_by_city(
        self,
        city: str,
        country_code: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get current weather for a city by name.
        
        Args:
            city: City name (e.g., "London", "New York")
            country_code: Optional ISO 3166 country code (e.g., "US", "GB")
            
        Returns:
            Dict: Weather data, None on failure
            
        Example:
            >>> weather = await client.get_weather_by_city("Paris", "FR")
            >>> print(f"{weather['emoji']} {weather['temperature']}°C")
        """
        logger.info(f"Fetching weather for city: {city}")
        
        # Build query string
        query = city
        if country_code:
            query = f"{city},{country_code}"
        
        data = await self._make_request(
            f"{OPENWEATHERMAP_BASE_URL}/weather",
            {"q": query}
        )
        
        if data is None:
            return None
        
        return self._parse_weather_response(data)
    
    async def get_weather_by_zip(
        self,
        zip_code: str,
        country_code: str = "US"
    ) -> Optional[Dict[str, Any]]:
        """
        Get current weather for a location by ZIP/postal code.
        
        Args:
            zip_code: ZIP or postal code
            country_code: ISO 3166 country code (default: "US")
            
        Returns:
            Dict: Weather data, None on failure
            
        Example:
            >>> weather = await client.get_weather_by_zip("10001", "US")
            >>> print(f"Weather in {weather['city']}: {weather['condition']}")
        """
        logger.info(f"Fetching weather for ZIP: {zip_code}, {country_code}")
        
        data = await self._make_request(
            f"{OPENWEATHERMAP_BASE_URL}/weather",
            {"zip": f"{zip_code},{country_code}"}
        )
        
        if data is None:
            return None
        
        return self._parse_weather_response(data)
    
    async def get_weather_by_coordinates(
        self,
        lat: float,
        lon: float
    ) -> Optional[Dict[str, Any]]:
        """
        Get current weather for a location by coordinates.
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            Dict: Weather data, None on failure
            
        Example:
            >>> weather = await client.get_weather_by_coordinates(40.7128, -74.0060)
        """
        logger.info(f"Fetching weather for coordinates: {lat}, {lon}")
        
        data = await self._make_request(
            f"{OPENWEATHERMAP_BASE_URL}/weather",
            {"lat": lat, "lon": lon}
        )
        
        if data is None:
            return None
        
        return self._parse_weather_response(data)
    
    async def get_weather(
        self,
        query: str,
        country_code: str = "US"
    ) -> Optional[Dict[str, Any]]:
        """
        Get weather using auto-detection of query type.
        
        Automatically determines if the query is a ZIP code or city name
        and calls the appropriate method.
        
        Args:
            query: City name or ZIP code
            country_code: Country code (used for ZIP code queries)
            
        Returns:
            Dict: Weather data, None on failure
            
        Example:
            >>> weather = await client.get_weather("New York")
            >>> weather = await client.get_weather("10001")
        """
        query = query.strip()
        
        if self.is_zip_code(query):
            return await self.get_weather_by_zip(query, country_code)
        else:
            return await self.get_weather_by_city(query)
    
    # =========================================================================
    # FORECAST METHODS
    # =========================================================================
    
    async def get_forecast(
        self,
        city: str,
        country_code: Optional[str] = None,
        days: int = 5
    ) -> Optional[Dict[str, Any]]:
        """
        Get weather forecast for a city.
        
        Returns forecast data in 3-hour intervals for up to 5 days.
        
        Args:
            city: City name
            country_code: Optional country code
            days: Number of days (1-5)
            
        Returns:
            Dict: Forecast data with list of forecast periods
        """
        logger.info(f"Fetching {days}-day forecast for: {city}")
        
        query = city
        if country_code:
            query = f"{city},{country_code}"
        
        # API returns 8 forecasts per day (3-hour intervals)
        cnt = min(days * 8, 40)
        
        data = await self._make_request(
            f"{OPENWEATHERMAP_BASE_URL}/forecast",
            {"q": query, "cnt": cnt}
        )
        
        if data is None:
            return None
        
        # Parse city info
        city_info = data.get("city", {})
        
        # Parse forecast list
        forecasts = []
        for item in data.get("list", []):
            forecasts.append({
                "timestamp": datetime.fromtimestamp(item.get("dt", 0)),
                "temperature": item.get("main", {}).get("temp"),
                "feels_like": item.get("main", {}).get("feels_like"),
                "humidity": item.get("main", {}).get("humidity"),
                "condition": item.get("weather", [{}])[0].get("description", "").title(),
                "condition_main": item.get("weather", [{}])[0].get("main", ""),
                "emoji": self.get_weather_emoji(
                    item.get("weather", [{}])[0].get("main", "")
                ),
                "wind_speed": item.get("wind", {}).get("speed"),
                "clouds": item.get("clouds", {}).get("all"),
                "precipitation_probability": item.get("pop", 0) * 100,
            })
        
        return {
            "city": city_info.get("name"),
            "country": city_info.get("country"),
            "timezone_offset": city_info.get("timezone"),
            "forecasts": forecasts,
            "unit_symbol": self._get_unit_symbol(),
            "speed_unit": self._get_speed_unit(),
        }
    
    # =========================================================================
    # GEOCODING METHODS
    # =========================================================================
    
    async def geocode_city(
        self,
        city: str,
        limit: int = 5
    ) -> Optional[list]:
        """
        Get geographic coordinates for a city name.
        
        Useful for finding exact locations when city names are ambiguous.
        
        Args:
            city: City name to search for
            limit: Maximum number of results
            
        Returns:
            List of location matches with coordinates
        """
        logger.info(f"Geocoding city: {city}")
        
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "q": city,
                    "limit": limit,
                    "appid": self.api_key,
                }
                async with session.get(
                    f"{OPENWEATHERMAP_GEO_URL}/direct",
                    params=params
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            logger.error(f"Geocoding error: {e}")
            return None
    
    async def reverse_geocode(
        self,
        lat: float,
        lon: float
    ) -> Optional[list]:
        """
        Get location name from coordinates.
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            List of location matches
        """
        logger.info(f"Reverse geocoding: {lat}, {lon}")
        
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "lat": lat,
                    "lon": lon,
                    "limit": 1,
                    "appid": self.api_key,
                }
                async with session.get(
                    f"{OPENWEATHERMAP_GEO_URL}/reverse",
                    params=params
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            logger.error(f"Reverse geocoding error: {e}")
            return None
    
    # =========================================================================
    # FORMATTED OUTPUT FOR BOT
    # =========================================================================
    
    def format_weather_message(
        self,
        weather: Dict[str, Any],
        include_details: bool = True
    ) -> str:
        """
        Format weather data as a nice message for chat display.
        
        This is a convenience method for generating bot responses.
        
        Args:
            weather: Weather data from get_weather methods
            include_details: Whether to include extended details
            
        Returns:
            str: Formatted weather message
        """
        if weather is None:
            return "❌ Unable to fetch weather data. Please try again."
        
        # Basic info
        city = weather.get("city", "Unknown")
        country = weather.get("country", "")
        location = f"{city}, {country}" if country else city
        
        emoji = weather.get("emoji", "🌡️")
        condition = weather.get("condition", "Unknown")
        temp = weather.get("temperature")
        feels_like = weather.get("feels_like")
        unit = weather.get("unit_symbol", "°F")
        
        # Build message
        message = f"""**{emoji} Weather for {location}**
━━━━━━━━━━━━━━━━━━━━━

**Condition:** {condition}
**Temperature:** {temp:.1f}{unit}
**Feels Like:** {feels_like:.1f}{unit}
"""
        
        if include_details:
            humidity = weather.get("humidity")
            wind_speed = weather.get("wind_speed")
            wind_dir = weather.get("wind_direction")
            speed_unit = weather.get("speed_unit", "mph")
            clouds = weather.get("clouds")
            visibility = weather.get("visibility")
            
            message += f"""
**Humidity:** {humidity}%
**Wind:** {wind_speed:.1f} {speed_unit} {wind_dir}
**Clouds:** {clouds}%
"""
            
            if visibility:
                vis_miles = visibility / 1609.34  # Convert meters to miles
                message += f"**Visibility:** {vis_miles:.1f} miles\n"
            
            # Sun times
            sunrise = weather.get("sunrise")
            sunset = weather.get("sunset")
            if sunrise and sunset:
                message += f"""
**Sunrise:** {sunrise.strftime('%I:%M %p')}
**Sunset:** {sunset.strftime('%I:%M %p')}
"""
        
        return message
    
    def format_forecast_message(
        self,
        forecast: Dict[str, Any],
        periods: int = 8
    ) -> str:
        """
        Format forecast data as a message for chat display.
        
        Args:
            forecast: Forecast data from get_forecast method
            periods: Number of forecast periods to show
            
        Returns:
            str: Formatted forecast message
        """
        if forecast is None:
            return "❌ Unable to fetch forecast data. Please try again."
        
        city = forecast.get("city", "Unknown")
        country = forecast.get("country", "")
        location = f"{city}, {country}" if country else city
        unit = forecast.get("unit_symbol", "°F")
        
        message = f"""**📅 Forecast for {location}**
━━━━━━━━━━━━━━━━━━━━━
"""
        
        forecasts = forecast.get("forecasts", [])[:periods]
        
        current_date = None
        for fc in forecasts:
            timestamp = fc.get("timestamp")
            if timestamp:
                date_str = timestamp.strftime("%a, %b %d")
                time_str = timestamp.strftime("%I:%M %p")
                
                # Add date header when date changes
                if date_str != current_date:
                    current_date = date_str
                    message += f"\n**{date_str}**\n"
                
                emoji = fc.get("emoji", "🌡️")
                temp = fc.get("temperature", 0)
                condition = fc.get("condition", "")
                pop = fc.get("precipitation_probability", 0)
                
                message += f"  {time_str}: {emoji} {temp:.0f}{unit}"
                if pop > 0:
                    message += f" 💧{pop:.0f}%"
                message += f" - {condition}\n"
        
        return message


# =============================================================================
# EXAMPLE USAGE AND TESTING
# =============================================================================

async def main():
    """
    Example usage of the WeatherClient.
    
    Demonstrates fetching weather by city and ZIP code.
    """
    import os
    
    # Get API key from environment
    api_key = os.getenv("WEATHER_API_KEY", "your_openweathermap_api_key")
    
    if api_key == "your_openweathermap_api_key":
        print("=" * 50)
        print("Weather Client Demo (No API Key)")
        print("=" * 50)
        print("\nTo test with real data, set WEATHER_API_KEY environment variable")
        print("Get a free API key at: https://openweathermap.org/api")
        print("\nDemonstrating query parsing:")
        print(f"  Is '10001' a ZIP code? {WeatherClient.is_zip_code('10001')}")
        print(f"  Is 'New York' a ZIP code? {WeatherClient.is_zip_code('New York')}")
        print(f"  Wind direction 45°: {WeatherClient.degrees_to_direction(45)}")
        print(f"  Weather emoji for 'rain': {WeatherClient.get_weather_emoji('rain')}")
        return
    
    # Initialize client
    client = WeatherClient(api_key=api_key, units=TemperatureUnit.FAHRENHEIT)
    
    print("=" * 50)
    print("Weather Client Demo")
    print("=" * 50)
    
    # Test weather by city
    print("\n1. Getting weather for New York...")
    weather = await client.get_weather_by_city("New York", "US")
    if weather:
        print(client.format_weather_message(weather))
    
    # Test weather by ZIP
    print("\n2. Getting weather for ZIP 90210...")
    weather = await client.get_weather_by_zip("90210", "US")
    if weather:
        print(client.format_weather_message(weather, include_details=False))
    
    # Test auto-detection
    print("\n3. Testing auto-detection with '10001'...")
    weather = await client.get_weather("10001")
    if weather:
        print(f"   Location: {weather['city']}, {weather['country']}")
        print(f"   Temperature: {weather['temperature']}°F")
    
    # Test forecast
    print("\n4. Getting forecast for London...")
    forecast = await client.get_forecast("London", "GB", days=2)
    if forecast:
        print(client.format_forecast_message(forecast, periods=4))
    
    print("\n" + "=" * 50)
    print("Demo complete!")


if __name__ == "__main__":
    asyncio.run(main())
