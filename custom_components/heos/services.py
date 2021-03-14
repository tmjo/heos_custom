"""Services for the HEOS integration."""
import functools
import logging

from pyheos import CommandFailedError, Heos, HeosError, const
import voluptuous as vol

from homeassistant.helpers import (
    config_validation as cv,
    entity_platform,
)  # entity_platform # group
from homeassistant.helpers.typing import HomeAssistantType

from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN

from .const import (
    ATTR_PASSWORD,
    ATTR_USERNAME,
    DATA_CONTROLLER_MANAGER, # group
    DOMAIN,
    ATTR_GROUPMEMBERS,  # group
    ATTR_MASTER,  # group
    ATTR_ENTITY_ID,  # group
    SERVICE_GROUPINFO,  # group
    SERVICE_JOIN,  # group
    SERVICE_UNJOIN,  # group
    SERVICE_SIGN_IN,
    SERVICE_SIGN_OUT,
)

_LOGGER = logging.getLogger(__name__)

HEOS_SIGN_IN_SCHEMA = vol.Schema(
    {vol.Required(ATTR_USERNAME): cv.string, vol.Required(ATTR_PASSWORD): cv.string}
)

HEOS_SIGN_OUT_SCHEMA = vol.Schema({})

HEOS_GROUPINFO_SCHEMA = vol.Schema({})  # group

HEOS_JOIN_SCHEMA = vol.Schema(  # group
    {
        vol.Required(ATTR_MASTER): cv.entity_id,
        vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids,
    }
)

HEOS_UNJOIN_SCHEMA = vol.Schema(  # group
    {vol.Optional(ATTR_ENTITY_ID, default=None): cv.comp_entity_ids}
)


def register(hass: HomeAssistantType, controller: Heos):
    """Register HEOS services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SIGN_IN,
        functools.partial(_sign_in_handler, controller),
        schema=HEOS_SIGN_IN_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SIGN_OUT,
        functools.partial(_sign_out_handler, controller),
        schema=HEOS_SIGN_OUT_SCHEMA,
    )
    hass.services.async_register(  # group
        DOMAIN,
        SERVICE_GROUPINFO,
        functools.partial(_groupinfo_handler, controller, hass),
        schema=HEOS_GROUPINFO_SCHEMA,
    )
    hass.services.async_register(  # group
        DOMAIN,
        SERVICE_JOIN,
        functools.partial(_join_handler, controller, hass),
        schema=HEOS_JOIN_SCHEMA,
    )
    hass.services.async_register(  # group
        DOMAIN,
        SERVICE_UNJOIN,
        functools.partial(_unjoin_handler, controller, hass),
        schema=HEOS_UNJOIN_SCHEMA,
    )


def remove(hass: HomeAssistantType):
    """Unregister HEOS services."""
    hass.services.async_remove(DOMAIN, SERVICE_SIGN_IN)
    hass.services.async_remove(DOMAIN, SERVICE_SIGN_OUT)
    hass.services.async_remove(DOMAIN, SERVICE_GROUPINFO)  # group
    hass.services.async_remove(DOMAIN, SERVICE_JOIN)  # group
    hass.services.async_remove(DOMAIN, SERVICE_UNJOIN)  # group


async def _sign_in_handler(controller, service):
    """Sign in to the HEOS account."""
    if controller.connection_state != const.STATE_CONNECTED:
        _LOGGER.error("Unable to sign in because HEOS is not connected")
        return
    username = service.data[ATTR_USERNAME]
    password = service.data[ATTR_PASSWORD]
    try:
        await controller.sign_in(username, password)
    except CommandFailedError as err:
        _LOGGER.error("Sign in failed: %s", err)
    except HeosError as err:
        _LOGGER.error("Unable to sign in: %s", err)


async def _sign_out_handler(controller, service):
    """Sign out of the HEOS account."""
    if controller.connection_state != const.STATE_CONNECTED:
        _LOGGER.error("Unable to sign out because HEOS is not connected")
        return
    try:
        await controller.sign_out()
    except HeosError as err:
        _LOGGER.error("Unable to sign out: %s", err)


async def _groupinfo_handler(controller, hass, service):  # group
    """Service to display HEOS players and groups in log for debugging purposes."""
    if controller.connection_state != const.STATE_CONNECTED:
        _LOGGER.error("Unable to get info because HEOS is not connected")
        return
    try:
        controller_manager = hass.data[DOMAIN][DATA_CONTROLLER_MANAGER]
        return await controller_manager.groupmanager.groupinfo()

    except HeosError as err:
        _LOGGER.error("Unable to get group info: %s", err)


async def _join_handler(controller, hass, service):  # group
    """Join HEOS players."""
    if controller.connection_state != const.STATE_CONNECTED:
        _LOGGER.error("Unable to join because HEOS is not connected")
        return
    master = service.data[ATTR_MASTER]
    entity_ids = service.data[ATTR_ENTITY_ID]

    _LOGGER.debug(f"HEOS grouping - Trying to group master {master} with {entity_ids}")

    # platform = entity_platform.current_platform.get()
    # platform.entities.get(service_call.data[ATTR_MASTER])
    controller_manager = hass.data[DOMAIN][DATA_CONTROLLER_MANAGER]
    # entities = await platform.async_extract_from_service(service_call)

    # Get devices
    master_device = None
    group_devices = {}
    for device in hass.data[MEDIA_PLAYER_DOMAIN].entities:
        # _LOGGER.debug(f"HEOS grouping - device {device.entity_id}")
        if device.entity_id == master:
            master_device = device
        elif device.entity_id in entity_ids:
            group_devices[device.player_id] = device

    try:
        return await controller_manager.groupmanager.join(master_device, group_devices)

    except HeosError as err:
        _LOGGER.error("HEOS grouping - Unable to join: %s", err)


async def _unjoin_handler(controller, hass, service):  # group
    """Unjoin HEOS players."""
    if controller.connection_state != const.STATE_CONNECTED:
        _LOGGER.error("Unable to unjoin because HEOS is not connected")
        return

    entity_ids = service.data.get(ATTR_ENTITY_ID, None)
    _LOGGER.debug(f"HEOS grouping - trying to ungroup: {entity_ids}")

    # Get devices
    group_devices = {}
    for device in hass.data[MEDIA_PLAYER_DOMAIN].entities:
        # _LOGGER.debug(f"HEOS grouping - device {device.entity_id}")
        if device.entity_id in entity_ids:
            group_devices[device.player_id] = device

    controller_manager = hass.data[DOMAIN][DATA_CONTROLLER_MANAGER]

    try:
        return await controller_manager.groupmanager.unjoin(group_devices)

    except HeosError as err:
        _LOGGER.error(f"HEOS group - unable to unjoin: {err}")
