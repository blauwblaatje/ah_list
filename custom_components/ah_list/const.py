"""Constants for the Albert Heijn shopping list integration."""

from datetime import timedelta

DOMAIN = "ah_list"

CONF_TOKENS = "tokens"
CONF_REDIRECT_URL = "redirect_url"

UPDATE_INTERVAL = timedelta(minutes=10)
