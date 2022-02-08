from homeassistant import config_entries
from .constants import DOMAIN

import logging

_LOGGER = logging.getLogger(__name__)

class ConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):

    async def async_step_user(self, user_input):
        # if get_config_entry(self.hass, None):
        #     return self.async_abort(reason="already_registered")
        return self.async_create_entry(
            title="Quick Automation",
            options={},
            data={},
        )
