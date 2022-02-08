from __future__ import annotations

from .constants import DOMAIN, PLATFORMS
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.components import websocket_api
from .frontend import locate_dir
from .coordinator import Component

import voluptuous as vol

import logging
import yaml
from copy import copy

_LOGGER = logging.getLogger(__name__)

def get_component(hass) -> Component:
    return hass.data[DOMAIN]["component"]

async def async_setup_entry(hass, entry):
    _LOGGER.debug("Setup platform from config entry: %s", entry)
    component = get_component(hass)
    await component.setup_config_entry(entry)
    return True

async def async_unload_entry(hass, entry):
    hass.data[DOMAIN]["entries"].pop(entry.entry_id)
    return True

async def async_setup(hass, config) -> bool:
    hass.data[DOMAIN] = dict(entries={}, component=Component(hass))
    _LOGGER.debug(f"__init__::async_setup: {config}, {locate_dir}")
    hass.http.register_static_path(
        "/quick_automation_ui", "%s/dist" % (locate_dir()), cache_headers=False)
    await async_register_panel(
        hass,
        "quick_automation",
        "quick-automation-panel",
        sidebar_title="Quick Automation",
        sidebar_icon="mdi:link-box-variant",
        module_url="/quick_automation_ui/index.js",
        embed_iframe=False,
        require_admin=True
    )
    hass.components.websocket_api.async_register_command(ws_load_trigger_action)
    hass.components.websocket_api.async_register_command(ws_update_entry)
    hass.components.websocket_api.async_register_command(ws_list_entries)
    hass.components.websocket_api.async_register_command(ws_remove_entry)
    return True

_ITEM_SCHEMA = vol.Schema({
    vol.Optional("device_id"): str,
    vol.Optional("entity_id"): str,
})

def _safe_yaml(value):
    if not value or len(value) == 0:
        return ''
    return yaml.dump(value)


def _serialize_config(config):
    result = [{
        "type": key, 
        "enabled": item["enabled"],
        "reverse": item["reverse"],
        "extra": _safe_yaml(item["extra"]),
        "triggers": sorted([x[item["trigger"]["key"]] for x in item["trigger"].get("select", [])]),
        "trigger": item["trigger"]["triggers"][0][item["trigger"]["key"]] if "key" in item["trigger"] else None,
    } for key, item in config.items()]
    return result

@websocket_api.websocket_command({
    vol.Required("type"): "quick_automation/load_trigger_action",
    vol.Required("source"): _ITEM_SCHEMA,
    vol.Required("destination"): _ITEM_SCHEMA,
})
@websocket_api.async_response
async def ws_load_trigger_action(hass, connection, msg: dict):
    _LOGGER.debug("ws_load_trigger_action: %s", msg)
    component = get_component(hass)
    config = await component.build_config(msg)
    connection.send_result(msg["id"], {
        "title": await component.build_name(msg),
        "links": _serialize_config(config)
    })

@websocket_api.websocket_command({
    vol.Required("type"): "quick_automation/update_entry",
    vol.Required("source"): _ITEM_SCHEMA,
    vol.Required("destination"): _ITEM_SCHEMA,
    vol.Optional("entry_id"): str,
    vol.Required("enabled"): bool,
    vol.Required("title"): str,
    vol.Required("links"): [vol.Schema({
        vol.Required("type"): str,
        vol.Required("enabled"): bool,
        vol.Optional("reverse"): bool,
        vol.Optional("extra"): str,
        vol.Required("triggers"): [str],
        vol.Optional("trigger"): vol.Any(str, None),
    })],
})
@websocket_api.async_response
async def ws_update_entry(hass, connection, msg: dict):
    _LOGGER.debug("ws_update_entry: %s", msg)
    component = get_component(hass)
    await component.update_entry(msg)
    connection.send_result(msg["id"], {})

@websocket_api.websocket_command({
    vol.Required("type"): "quick_automation/remove_entry",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_remove_entry(hass, connection, msg: dict):
    _LOGGER.debug("ws_remove_entry: %s", msg)
    component = get_component(hass)
    await component.delete_entry(msg["entry_id"])
    connection.send_result(msg["id"], {})

@websocket_api.websocket_command({
    vol.Required("type"): "quick_automation/list",
})
@websocket_api.async_response
async def ws_list_entries(hass, connection, msg: dict):
    component = get_component(hass)
    entries = component.entry_list()
    # _LOGGER.debug("ws_list_entries: %s - %s", msg, entries)
    result = [{
        "entry_id": item["id"],
        "title": item["name"],
        "enabled": item["enabled"],
        "source": item["source"],
        "destination": item["destination"],
        "links": _serialize_config(item["config"]),
    } for item in entries]
    connection.send_result(msg["id"], result)

