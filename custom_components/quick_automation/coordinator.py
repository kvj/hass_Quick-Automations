from cgitb import enable
from multiprocessing import context
from .constants import DOMAIN
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers import entity_registry, device_registry
from homeassistant.components import device_automation, light
from homeassistant.const import (EVENT_HOMEASSISTANT_STARTED)
from homeassistant.helpers.trigger import async_initialize_triggers
from homeassistant.helpers.event import async_track_state_change
from homeassistant.util.yaml import parse_yaml

import secrets

from datetime import timedelta
import copy
import logging
_LOGGER = logging.getLogger(__name__)

_ON_OFF_ACTIONS = [
    (dict(domain="mqtt", type="action", subtype="on"), dict(domain="mqtt", type="action", subtype="off")),
    (dict(domain="mqtt", type="action", subtype="open"), dict(domain="mqtt", type="action", subtype="close")),
    (dict(domain="zha", type="remote_button_short_press", subtype="open"), dict(domain="zha", type="remote_button_short_press", subtype="close")),
    (dict(domain="zha", type="remote_button_short_press", subtype="turn_on"), dict(domain="zha", type="remote_button_short_press", subtype="turn_off")),
]
_BRIGHTNESS_ACTIONS = [
    (dict(domain="mqtt", type="action", subtype="brightness_move_up"), dict(domain="mqtt", type="action", subtype="brightness_move_down")),
    (dict(domain="zha", type="remote_button_long_press", subtype="dim_up"), dict(domain="zha", type="remote_button_long_press", subtype="dim_down")),
    (dict(domain="zha", type="remote_button_long_press", subtype="open"), dict(domain="zha", type="remote_button_long_press", subtype="close")),
]
_LEFT_RIGHT_ACTIONS = [
    (dict(domain="mqtt", type="action", subtype="arrow_left_click"), dict(domain="mqtt", type="action", subtype="arrow_right_click")),
    (dict(domain="zha", type="remote_button_short_press", subtype="left"), dict(domain="zha", type="remote_button_short_press", subtype="right")),
]
_TOGGLE_ACTIONS = [
    (dict(domain="mqtt", type="action", subtype="toggle"), dict(domain="mqtt", type="action")),
    (dict(domain="mqtt", type="action", subtype="single"), dict(domain="mqtt", type="action")),
    (dict(domain="zha", type="remote_button_short_press", subtype="remote_button_short_press"), dict(domain="zha", type="remote_button_short_press")),
    (dict(domain="zha", type="remote_button_short_press", subtype="turn_on"), dict(domain="zha", type="remote_button_short_press")),
]
_ON_OFF_TRIGGERS = [("turned_on", "turned_off")]

_BINARY_SENSOR_TRIGGERS = ["co", "cold", "connected", "gas", "hot", "light", "locked", "moist", "motion", "moving", "occupied", "plugged_in", "present", "problem", "running", "unsafe", "smoke", "sound", "tampered", "vibration", "opened"]
_ON_OFF_ENTITY_DOMAINS = ["binary_sensor", "fan", "light", "switch", "remote", "siren", "vacuum", "humidifier", "alert", "media_player"]
_TOGGLE_ENTITY_DOMAINS = ["script", "automation", "button", "scene"]
_ON_OFF_ENTITY_ACTION_DOMAINS = ["fan", "light", "switch", "remote", "siren", "vacuum", "humidifier", "cover", "lock", "alert", "media_player"]
_TOGGLE_ENTITY_ACTION_DOMAINS = ["script", "automation", "button", "scene"]

class Component(EntityComponent):

    def __init__(self, hass) -> None:
        super().__init__(
            _LOGGER, DOMAIN, hass
        )

    async def setup_config_entry(self, entry):
        self._config_entry = entry
        self.hass.data[DOMAIN]["entries"][entry.entry_id] = dict()
        entities = []
        _LOGGER.debug("setup_config_entry: %s", len(self.entry_list()))
        for item in self.entry_list():
            c = set_coordinator(self.hass, self, entry, item)
            await c.async_config_entry_first_refresh()
            entities.append(BaseEntity(c))
        await self.async_add_entities(entities)

    def _entry_list(self):
        return self._config_entry.as_dict().get("data", {}).get("entries", [])

    def entry_list(self):
        return list(self._entry_list())

    async def update_entry(self, data):
        def _find_trigger(triggers, trigger):
            for t in triggers["select"]:
                if t[triggers["key"]] == trigger:
                    return t
            return None
        entry_list = self.entry_list()
        entry = None
        if id := data.get("entry_id"):
            for idx, item in enumerate(entry_list):
                if item["id"] == id:
                    entry = dict(id=id)
                    entry_list[idx] = entry
                    break
        else:
            entry = dict(id=secrets.token_hex(8))
            entry_list.append(entry)
        if not entry:
            return False
        entry["config"] = await self.build_config(data)
        entry["name"] = data["title"]
        entry["source"] = data["source"]
        entry["destination"] = data["destination"]
        entry["enabled"] = data["enabled"]
        for link in data["links"]:
            if config_item := entry["config"].get(link["type"]):
                config_item["enabled"] = link["enabled"]
                config_item["reverse"] = link.get("reverse")
                config_item["extra"] = dict(parse_yaml(link.get("extra")))
                if selected := link.get("trigger"):
                    if trigger := _find_trigger(config_item["trigger"], selected):
                        config_item["trigger"]["triggers"] = [trigger]
        await self.reload(dict(entries=entry_list))
        return True

    def entity_id_by_id(self, id: str):
        for entity in list(self.entities):
            if entity.entry_id == id:
                return entity.entity_id
        return None

    async def delete_entry(self, entry_id: str):
        entity_reg = await entity_registry.async_get_registry(self.hass)
        entry_list = self.entry_list()
        for idx, item in enumerate(entry_list):
            if item["id"] == entry_id:
                del entry_list[idx]
                entity_reg.async_remove(self.entity_id_by_id(entry_id))
                await self.reload(dict(entries=entry_list))
                return True
        return False

    async def reload(self, data):
        self.hass.config_entries.async_update_entry(self._config_entry, data=data)
        for entity in list(self.entities):
            await entity.async_remove()
        await self.hass.config_entries.async_reload(self._config_entry.entry_id)

    def _device_triggers(self, triggers, domain=None, type=None, subtype=None):
        def l(t):
            if domain and t.get("domain") != domain:
                return False
            if type and t.get("type") != type:
                return False
            if subtype and t.get("subtype") != subtype:
                return False
            return True
        return list(filter(l, triggers))

    def _device_trigger(self, triggers, **kwargs):
        t_list = self._device_triggers(triggers, **kwargs)
        return t_list[0] if len(t_list) else None

    def _map_binary_sensor(self, triggers):
        t_list = self._device_triggers(triggers, domain="binary_sensor")
        type_map = {x["type"]: x for x in t_list}
        result = {}
        for key, value in type_map.items():
            if f"not_{key}" in type_map:
                result[key] = dict(triggers=[value, type_map[f"not_{key}"]])
            if f"no_{key}" in type_map:
                result[key] = dict(triggers=[value, type_map[f"no_{key}"]])
        return result


    async def load_actions(self, entry):
        entity_reg = await entity_registry.async_get_registry(self.hass)
        result = dict()
        if device_id := entry.get("device_id"):
            actions = await device_automation.async_get_device_automations(self.hass, "action", [device_id])
            a_list = actions.get(device_id)
            def _add_pair(name, kwargs1, kwargs2):
                t1 = self._device_trigger(a_list, **kwargs1)
                t2 = self._device_trigger(a_list, **kwargs2)
                if t1 and t2:
                    result[name] = dict(actions=[t1, t2])
            _LOGGER.debug("Actions: [%s] = %s", device_id, a_list)
            if toggle := self._device_trigger(a_list, type="toggle"):
                result["toggle"] = dict(actions=[toggle])
            elif press := self._device_trigger(a_list, type="press"):
                result["toggle"] = dict(actions=[press])
            _add_pair("on_off", {"type": "turn_on"}, {"type": "turn_off"})
            _add_pair("brightness", {"type": "brightness_increase"}, {"type": "brightness_decrease"})
        elif entity_id := entry.get("entity_id"):
            [domain, name] = entity_id.split(".")
            if domain in _ON_OFF_ENTITY_ACTION_DOMAINS:
                result["on_off"] = dict(actions=[{"entity_id": entity_id, "action": "turn_on"}, {"entity_id": entity_id, "action": "turn_off"}])
            if domain in _TOGGLE_ENTITY_ACTION_DOMAINS:
                action = "toggle"
                if domain == "script":
                    action = name
                elif domain == "automation":
                    action = "trigger"
                elif domain == "scene":
                    action = "apply"
                elif domain == "button":
                    action = "press"
                result["toggle"] = dict(actions=[{"entity_id": entity_id, "action": action}])
            if entity := entity_reg.async_get(entity_id):
                if domain == "light":
                    if entity.supported_features & light.SUPPORT_BRIGHTNESS:
                        result["brightness"] = dict(actions=[
                            {"entity_id": entity_id, "action": "turn_on", "extra": {"brightness_step_pct": 10}}, 
                            {"entity_id": entity_id, "action": "turn_on", "extra": {"brightness_step_pct": -10}}
                        ])
                    if entity.supported_features & light.SUPPORT_COLOR_TEMP:
                        result["left_right"] = dict(actions=[
                            {"entity_id": entity_id, "action": "turn_on", "extra": {"brightness_step_pct": 10}}, 
                            {"entity_id": entity_id, "action": "turn_on", "extra": {"brightness_step_pct": -10}}
                        ])
            # state = self.hass.states.get(entity_id)
            # _LOGGER.debug("Entity action: %s = %s, %s", entity_id, entity, domain)
        # _LOGGER.debug("Actions capabilities: %s = %s", entry, result)
        return result

    async def load_triggers(self, entry):
        entity_reg = await entity_registry.async_get_registry(self.hass)
        # device_reg = device_registry.async_get(self.hass)
        result = dict()
        if device_id := entry.get("device_id"):
            triggers = await device_automation.async_get_device_automations(self.hass, "trigger", [device_id])
            t_list = triggers.get(device_id, [])

            def _add_pair(name, kwargs1, kwargs2):
                t1 = self._device_trigger(t_list, **kwargs1)
                t2 = self._device_trigger(t_list, **kwargs2)
                if t1 and t2:
                    result[name] = dict(triggers=[t1, t2])

            _LOGGER.debug("Triggers: [%s] = %s", device_id, t_list)
            for pair in _ON_OFF_TRIGGERS:
                _add_pair("on_off", {"type": pair[0]}, {"type": pair[1]})
            for pair in _ON_OFF_ACTIONS:
                _add_pair("on_off", pair[0], pair[1])
            for pair in _BRIGHTNESS_ACTIONS:
                _add_pair("brightness", pair[0], pair[1])
            for pair in _LEFT_RIGHT_ACTIONS:
                _add_pair("left_right", pair[0], pair[1])
            binary_map = self._map_binary_sensor(t_list)
            if "on_off" not in result:
                for item in _BINARY_SENSOR_TRIGGERS:
                    if pair := binary_map.get(item):
                        result["on_off"] = pair
                        break
            for pair in _TOGGLE_ACTIONS:
                actions = self._device_triggers(t_list, **pair[1])
                if t := self._device_trigger(t_list, **pair[0]):
                    result["toggle"] = dict(triggers=[t], select=actions, key="subtype")
                if "toggle" not in result and len(actions):
                    result["toggle"] = dict(triggers=[actions[0]], select=actions, key="subtype")
        elif entity_id := entry.get("entity_id"):
            [domain, name] = entity_id.split(".")
            if domain in _ON_OFF_ENTITY_DOMAINS:
                result["on_off"] = dict(triggers=[{"entity_id": entity_id, "state": "on"}, {"entity_id": entity_id, "state": "off"}])
            if domain in _TOGGLE_ENTITY_DOMAINS:
                result["toggle"] = dict(trigers=[{"entity_id": entity_id, "domain": domain}])
            # state = self.hass.states.get(entity_id)
            _LOGGER.debug("Entity trigger: %s = %s", entity_id, result)
        # _LOGGER.debug("Trigger capabilities: %s = %s", entry, result)
        return result

    async def bind_trigger_actions(self, triggers, actions):
        result = {}
        for item in ("brightness", "left_right", "on_off"):
            if item in triggers and item in actions:
                result[item] = dict(trigger=triggers[item], action=actions[item], reverse=False, extra=dict(), enabled=True)
        has_on_off = "on_off" in result
        if "toggle" in triggers and "toggle" in actions:
            result["toggle"] = dict(trigger=triggers["toggle"], action=actions["toggle"], reverse=False, extra=dict(), enabled=not has_on_off)        
        if not has_on_off:
            if "toggle" in triggers and "on_off" in actions and "toggle" not in result:
                result["toggle"] = dict(trigger=triggers["toggle"], action=actions["on_off"], reverse=False, extra=dict(), enabled=True)
        return result

    async def _entity_name(self, data: dict):
        entity_reg = await entity_registry.async_get_registry(self.hass)
        device_reg = device_registry.async_get(self.hass)
        if device_id := data.get("device_id"):
            device = device_reg.async_get(device_id)
            return device.name_by_user or device.name if device else device_id
        if entity_id := data.get("entity_id"):
            entity = entity_reg.async_get(entity_id)
            return entity.name or entity.original_name if entity else entity_id
        return "undefined"

    async def build_name(self, data: dict):
        source_name = await self._entity_name(data.get("source", {}))
        destination_name = await self._entity_name(data.get("destination", {}))
        return "%s - %s" % (source_name, destination_name)

    async def build_config(self, data: dict):
        triggers = await self.load_triggers(data.get("source", {}))
        actions = await self.load_actions(data.get("destination", {}))
        binding = await self.bind_trigger_actions(triggers, actions)
        _LOGGER.debug("Binding - triggers: %s, %s", data, triggers)
        _LOGGER.debug("Binding - actions: %s, %s", data, actions)
        _LOGGER.debug("Binding - result: %s, %s", data, binding)
        return binding

    async def call_action(self, action, extra, type=None):
        if "device_id" in action:
            platform = await device_automation.async_get_device_automation_platform(
                self.hass, 
                action["domain"], 
                "action"
            )
            data = {
                **action,
                **extra,
                "type": type if type else action["type"],
            }
            _LOGGER.debug("call_action::device: %s, %s", data, action)
            await platform.async_call_action_from_config(self.hass, data, dict(), None)
        else:
            # Entity type - call service
            [domain, name] = action["entity_id"].split(".")
            service = type or action.get("action")
            data = {
                **action.get("extra", {}),
                **extra,
                "entity_id": action["entity_id"],
            }
            _LOGGER.debug("call_action::entity: %s.%s, %s", domain, service, data)
            await self.hass.services.async_call(domain, service, data, blocking=True)

    async def subscribe(self, config: dict, cb):
        states_map = dict()
        triggers_map = dict()
        async def on_state_change(entity_id, from_state, to_state):
            _LOGGER.debug("on_state_change: %s %s - %s", entity_id, from_state, to_state)
            domain = entity_id.split(".")[0]
            if payload := states_map.get((entity_id, to_state.state)):
                if from_state.state != to_state.state:
                    await cb(payload[0], payload[1])
            elif payload := states_map.get((entity_id, domain)):
                await cb(payload[0], payload[1])
            
        async def on_trigger(vars, context=None):
            if idx := vars.get("trigger", {}).get("idx"):
                if payload := triggers_map.get(int(idx)):
                    _LOGGER.debug("on_trigger: %s - %s, %s", vars, payload, idx)
                    await cb(payload[0], payload[1])
        states = set()
        triggers = []
        _remove_states = None
        _remove_triggers = None
        for key, item in config.items():
            for idx, trigger in enumerate(item["trigger"]["triggers"]):
                if "device_id" in trigger:
                    triggers_map[len(triggers)] = (key, idx)
                    triggers.append(trigger)
                    _LOGGER.debug("Subscribe to trigger: %s, %s", trigger.get("subtype"), trigger.get("type"))
                else:
                    entity_id = trigger.get("entity_id")
                    states.add(entity_id)
                    states_map[(entity_id, trigger.get("state"))] = (key, idx)
                    _LOGGER.debug("Subscribe to state: %s", entity_id)
        if len(states):
            _remove_states = async_track_state_change(self.hass, entity_ids=states, action=on_state_change)
        if len(triggers):
            _remove_triggers = await async_initialize_triggers(self.hass, triggers, on_trigger, DOMAIN, "name", _LOGGER.log)
        # _LOGGER.debug("subscribe: %s, %s", states, triggers)
        def _remove_listeners():
            _LOGGER.debug("Removing state listeners: %s", config)
            if _remove_states:
                _remove_states()
            if _remove_triggers:
                _remove_triggers()
        return _remove_listeners

class Coordinator(DataUpdateCoordinator):

    def __init__(self, hass, component: Component, entry, data: dict):
        super().__init__(
            hass,
            _LOGGER,
            name="Quick Automation",
            update_method=self.async_update,
            # update_interval=timedelta(seconds=30)
        )
        self._entry = entry
        self._data = data
        self._component = component
        _LOGGER.debug("New Coordinator: %s", data["id"])

    async def enable(self):
        _LOGGER.debug("Enable Coordinator: %s, %s", self._data["id"], self.hass.is_running)
        self._remove_state_listeners = None
        async def async_enable(_):
            config = self._data.get("config", {})
            _LOGGER.debug("HASS Started: %s", self._data["id"])
            async def on_trigger(key: str, idx: int):
                _LOGGER.debug("on_trigger:: %s, %s", key, idx)
                if not self._data["enabled"]:
                    return
                if entry := config.get(key):
                    if not entry["enabled"]:
                        return
                    action_type = None
                    action_idx = idx
                    if len(entry["action"]["actions"]) > 1:
                        if entry["reverse"]:
                            action_idx = 0 if idx == 1 else 1
                        if key == "toggle":
                            action_type = "toggle"
                    _LOGGER.debug("Calling call_action: %s, %s, %s", action_idx, action_type, entry)
                    await self._component.call_action(entry["action"]["actions"][action_idx], entry["extra"], action_type)
            self._remove_state_listeners = await self._component.subscribe(config, on_trigger)
        if self.hass.is_running:
            await async_enable(None)
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, async_enable)

    def disable(self):
        if self._remove_state_listeners:
            self._remove_state_listeners()

    async def async_update(self):
        return self._data

    @property
    def entity_name(self):
        return self._data.get("name", self.entity_id)

    @property
    def entity_id(self):
        return self._data.get("id")

    @property
    def unique_id(self):
        return "%s-%s" % (self._entry.entry_id, self.entity_id)

class BaseEntity(CoordinatorEntity):

    def __init__(self, coordinator: Coordinator):
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def state(self):
        return "on" if self._coordinator.data.get("enabled") else "off"

    @property
    def icon(self):
        return "mdi:link-variant"

    @property
    def name(self) -> str:
        return self._coordinator.entity_name

    @property
    def unique_id(self) -> str:
        return self._coordinator.unique_id

    @property
    def entry_id(self) -> str:
        return self._coordinator.entity_id

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        await self._coordinator.enable()
        self.async_on_remove(self._coordinator.disable)


def set_coordinator(hass, component, entry, data) -> Coordinator:
    instance = Coordinator(hass, component, entry, data)
    hass.data[DOMAIN]["entries"][entry.entry_id][data["id"]] = instance
    return instance

def get_coordinator(hass, entry, id):
    return hass.data[DOMAIN]["entries"][entry.entry_id].get(id)

def all_automations(hass, entry):
    return hass.data[DOMAIN]["data"]
