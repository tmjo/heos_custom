"""Denon HEOS Media Player."""
import asyncio
from datetime import timedelta
import logging
from typing import Dict

from pyheos import Heos, HeosError, const as heos_const
from pyheos.player import HeosPlayer  # group
import voluptuous as vol

from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, HomeAssistantType
from homeassistant.util import Throttle

from . import services
from .config_flow import format_title
from .const import (
    COMMAND_RETRY_ATTEMPTS,
    COMMAND_RETRY_DELAY,
    DATA_CONTROLLER_MANAGER,
    DATA_SOURCE_MANAGER,
    DOMAIN,
    SIGNAL_HEOS_UPDATED,
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_HOST): cv.string})}, extra=vol.ALLOW_EXTRA
)

MIN_UPDATE_SOURCES = timedelta(seconds=1)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistantType, config: ConfigType):
    """Set up the HEOS component."""
    if DOMAIN not in config:
        return True
    host = config[DOMAIN][CONF_HOST]
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        # Create new entry based on config
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "import"}, data={CONF_HOST: host}
            )
        )
    else:
        # Check if host needs to be updated
        entry = entries[0]
        if entry.data[CONF_HOST] != host:
            hass.config_entries.async_update_entry(
                entry, title=format_title(host), data={**entry.data, CONF_HOST: host}
            )

    return True


async def async_setup_entry(hass: HomeAssistantType, entry: ConfigEntry):
    """Initialize config entry which represents the HEOS controller."""
    # Custom component warning January 2022
    _LOGGER.warning(
        "Grouping support for HEOS was added to the official integration in version 2021.12 and there is no longer any reason for using the custom integration you have installed. If you are using the mini-media-player card, remember to change card config platform from heos to media_player for grouping to work. This custom integration may exist for a while for testing other features such as media browsing and similar, feel free to continue using it."
    )

    # For backwards compat
    if entry.unique_id is None:
        hass.config_entries.async_update_entry(entry, unique_id=DOMAIN)

    host = entry.data[CONF_HOST]
    # Setting all_progress_events=False ensures that we only receive a
    # media position update upon start of playback or when media changes
    controller = Heos(host, all_progress_events=False)
    try:
        await controller.connect(auto_reconnect=True)
    # Auto reconnect only operates if initial connection was successful.
    except HeosError as error:
        await controller.disconnect()
        _LOGGER.debug("Unable to connect to controller %s: %s", host, error)
        raise ConfigEntryNotReady from error

    # Disconnect when shutting down
    async def disconnect_controller(event):
        await controller.disconnect()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, disconnect_controller)

    # Get players and sources
    try:
        players = await controller.get_players()
        favorites = {}
        if controller.is_signed_in:
            favorites = await controller.get_favorites()
        else:
            _LOGGER.warning(
                "%s is not logged in to a HEOS account and will be unable to retrieve "
                "HEOS favorites: Use the 'heos.sign_in' service to sign-in to a HEOS account",
                host,
            )
        inputs = await controller.get_input_sources()
        music_sources = await controller.get_music_sources()
    except HeosError as error:
        await controller.disconnect()
        _LOGGER.debug("Unable to retrieve players and sources: %s", error)
        raise ConfigEntryNotReady from error

    controller_manager = ControllerManager(hass, controller)
    await controller_manager.connect_listeners()

    await controller_manager.groupmanager.refresh_groups()  # group

    source_manager = SourceManager(favorites, inputs, music_sources)
    source_manager.connect_update(hass, controller)

    hass.data[DOMAIN] = {
        DATA_CONTROLLER_MANAGER: controller_manager,
        DATA_SOURCE_MANAGER: source_manager,
        MEDIA_PLAYER_DOMAIN: players,
    }

    services.register(hass, controller)

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, MEDIA_PLAYER_DOMAIN)
    )
    return True


async def async_unload_entry(hass: HomeAssistantType, entry: ConfigEntry):
    """Unload a config entry."""
    controller_manager = hass.data[DOMAIN][DATA_CONTROLLER_MANAGER]
    await controller_manager.disconnect()
    hass.data.pop(DOMAIN)

    services.remove(hass)

    return await hass.config_entries.async_forward_entry_unload(
        entry, MEDIA_PLAYER_DOMAIN
    )


class ControllerManager:
    """Class that manages events of the controller."""

    def __init__(self, hass, controller):
        """Init the controller manager."""
        self._hass = hass
        self._device_registry = None
        self._entity_registry = None
        self.controller = controller
        self._signals = []
        self.groupmanager = GroupManager(hass, controller)  # group

    async def connect_listeners(self):
        """Subscribe to events of interest."""
        self._device_registry, self._entity_registry = await asyncio.gather(
            self._hass.helpers.device_registry.async_get_registry(),
            self._hass.helpers.entity_registry.async_get_registry(),
        )
        # Handle controller events
        self._signals.append(
            self.controller.dispatcher.connect(
                heos_const.SIGNAL_CONTROLLER_EVENT, self._controller_event
            )
        )
        # Handle connection-related events
        self._signals.append(
            self.controller.dispatcher.connect(
                heos_const.SIGNAL_HEOS_EVENT, self._heos_event
            )
        )

    async def disconnect(self):
        """Disconnect subscriptions."""
        for signal_remove in self._signals:
            signal_remove()
        self._signals.clear()
        self.controller.dispatcher.disconnect_all()
        await self.controller.disconnect()

    async def _controller_event(self, event, data):
        """Handle controller event."""
        if event == heos_const.EVENT_PLAYERS_CHANGED:
            self.update_ids(data[heos_const.DATA_MAPPED_IDS])
        # Update players
        self._hass.helpers.dispatcher.async_dispatcher_send(SIGNAL_HEOS_UPDATED)

    async def _heos_event(self, event):
        """Handle connection event."""
        if event == heos_const.EVENT_CONNECTED:
            try:
                # Retrieve latest players and refresh status
                data = await self.controller.load_players()
                self.update_ids(data[heos_const.DATA_MAPPED_IDS])
            except HeosError as ex:
                _LOGGER.error("Unable to refresh players: %s", ex)
        # Update players
        self._hass.helpers.dispatcher.async_dispatcher_send(SIGNAL_HEOS_UPDATED)

    def update_ids(self, mapped_ids: Dict[int, int]):
        """Update the IDs in the device and entity registry."""
        # mapped_ids contains the mapped IDs (new:old)
        for new_id, old_id in mapped_ids.items():
            # update device registry
            entry = self._device_registry.async_get_device({(DOMAIN, old_id)})
            new_identifiers = {(DOMAIN, new_id)}
            if entry:
                self._device_registry.async_update_device(
                    entry.id, new_identifiers=new_identifiers
                )
                _LOGGER.debug(
                    "Updated device %s identifiers to %s", entry.id, new_identifiers
                )
            # update entity registry
            entity_id = self._entity_registry.async_get_entity_id(
                MEDIA_PLAYER_DOMAIN, DOMAIN, str(old_id)
            )
            if entity_id:
                self._entity_registry.async_update_entity(
                    entity_id, new_unique_id=str(new_id)
                )
                _LOGGER.debug("Updated entity %s unique id to %s", entity_id, new_id)


class SourceManager:
    """Class that manages sources for players."""

    def __init__(
        self,
        favorites,
        inputs,
        music_sources,
        *,
        retry_delay: int = COMMAND_RETRY_DELAY,
        max_retry_attempts: int = COMMAND_RETRY_ATTEMPTS,
    ):
        """Init input manager."""
        self.retry_delay = retry_delay
        self.max_retry_attempts = max_retry_attempts
        self.favorites = favorites
        self.inputs = inputs
        self.music_sources = music_sources
        self.source_list = self._build_source_list()

    def _build_source_list(self):
        """Build a single list of inputs from various types."""
        source_list = []
        source_list.extend([favorite.name for favorite in self.favorites.values()])
        source_list.extend([source.name for source in self.inputs])
        return source_list

    async def play_source(self, source: str, player):
        """Determine type of source and play it."""
        index = next(
            (
                index
                for index, favorite in self.favorites.items()
                if favorite.name == source
            ),
            None,
        )
        if index is not None:
            await player.play_favorite(index)
            return

        input_source = next(
            (
                input_source
                for input_source in self.inputs
                if input_source.name == source
            ),
            None,
        )
        if input_source is not None:
            await player.play_input_source(input_source)
            return

        _LOGGER.error("Unknown source: %s", source)

    def get_current_source(self, now_playing_media):
        """Determine current source from now playing media."""
        # Match input by input_name:media_id
        if now_playing_media.source_id == heos_const.MUSIC_SOURCE_AUX_INPUT:
            return next(
                (
                    input_source.name
                    for input_source in self.inputs
                    if input_source.input_name == now_playing_media.media_id
                ),
                None,
            )
        # Try matching favorite by name:station or media_id:album_id
        return next(
            (
                source.name
                for source in self.favorites.values()
                if source.name == now_playing_media.station
                or source.media_id == now_playing_media.album_id
            ),
            None,
        )

    def connect_update(self, hass, controller):
        """
        Connect listener for when sources change and signal player update.

        EVENT_SOURCES_CHANGED is often raised multiple times in response to a
        physical event therefore throttle it. Retrieving sources immediately
        after the event may fail so retry.
        """

        @Throttle(MIN_UPDATE_SOURCES)
        async def get_sources():
            retry_attempts = 0
            while True:
                try:
                    favorites = {}
                    if controller.is_signed_in:
                        favorites = await controller.get_favorites()
                    inputs = await controller.get_input_sources()
                    return favorites, inputs
                except HeosError as error:
                    if retry_attempts < self.max_retry_attempts:
                        retry_attempts += 1
                        _LOGGER.debug(
                            "Error retrieving sources and will retry: %s", error
                        )
                        await asyncio.sleep(self.retry_delay)
                    else:
                        _LOGGER.error("Unable to update sources: %s", error)
                        return

        async def update_sources(event, data=None):
            if event in (
                heos_const.EVENT_SOURCES_CHANGED,
                heos_const.EVENT_USER_CHANGED,
                heos_const.EVENT_CONNECTED,
            ):
                sources = await get_sources()
                # If throttled, it will return None
                if sources:
                    self.favorites, self.inputs = sources
                    self.source_list = self._build_source_list()
                    _LOGGER.debug("Sources updated due to changed event")
                    # Let players know to update
                    hass.helpers.dispatcher.async_dispatcher_send(SIGNAL_HEOS_UPDATED)

        controller.dispatcher.connect(
            heos_const.SIGNAL_CONTROLLER_EVENT, update_sources
        )
        controller.dispatcher.connect(heos_const.SIGNAL_HEOS_EVENT, update_sources)


class GroupManager:
    """Class that manages player groups."""

    def __init__(self, hass, controller):
        """Init the group manager."""
        self._hass = hass
        self.controller = controller
        self.groups = {}

    async def refresh_groups(self):
        self.groups = await self.controller.get_groups(refresh=True)

    def playerdict(self, players):
        playerdict = {}
        for player in players:
            playerdict[player.player_id] = player
        return playerdict

    def player_member(self, group, player):
        for member in group.members:
            if member.player_id == player.player_id:
                return True
        return False

    def players_member(self, group, players: Dict[int, HeosPlayer]):
        for player in players.values():
            if self.player_member(group, player):
                return True
        return False

    def player_master(self, group, player):
        if group.leader.player_id == player.player_id:
            return True
        return False

    def entity_id_from_player_id(self, playerid):  # group
        for device in self._hass.data[MEDIA_PLAYER_DOMAIN].entities:
            try:
                if playerid == device.player_id:
                    return device.entity_id
            except AttributeError as e:
                pass
        return None

    def get_groupid(self, player):
        # Groupid is also playerid of leader
        get_groupid = ""
        for groupid, group in self.groups.items():
            if self.player_master(group, player) or self.player_member(group, player):
                get_groupid = groupid
                return get_groupid
        return get_groupid

    def get_grouplist(self, groupid):
        grouplist = []
        group = self.groups.get(groupid, None)
        if group is not None:
            grouplist.append(self.entity_id_from_player_id(group.leader.player_id))
            # grouplist.append(group.leader)
            for member in group.members:
                grouplist.append(self.entity_id_from_player_id(member.player_id))
                # grouplist.append(member)
        return grouplist

    def get_groupname(self, groupid):
        groupname = ""
        group = self.groups.get(groupid, None)
        if group is not None:
            groupname = group.name
        return groupname

    async def groupinfo(self):
        """Display HEOS players and groups in log for debugging purposes."""
        try:
            await self.refresh_groups()
            players = await self.controller.get_players(refresh=True)

            playerstring = "\n\nHEOS PLAYERS:\n"
            if not players:
                playerstring += f"  None\n{players}\n"
            else:
                for playerid, player in players.items():
                    playerstring += f"     Player: {player.name}, ID: {player.player_id}, IP: {player.ip_address}, State: {player.state}\n"
            _LOGGER.info(f"{playerstring}\n\n")

            groupstring = "\n\nHEOS GROUPS:\n"
            if not self.groups:
                groupstring += f"  None\n{self.groups}\n"
            else:
                for groupid, group in self.groups.items():
                    groupstring += f"  Group: {group.name}, ID: {groupid}\n"
                    groupstring += f"     Leader: {group.leader.name}, ID: {group.leader.player_id}\n"
                    for member in group.members:
                        groupstring += (
                            f"     Member: {member.name}, ID: {member.player_id}\n"
                        )
            _LOGGER.info(f"{groupstring}\n\n")

            return playerstring + groupstring

        except HeosError as err:
            _LOGGER.error("Unable to get group info: %s", err)

    async def join(self, master: HeosPlayer, members: Dict[int, HeosPlayer]):
        try:
            await self.refresh_groups()
            newgroup = {}

            for groupid, group in self.groups.items():
                # Already master
                if master.player_id == group.leader.player_id:
                    newgroup[master.player_id] = master
                    newgroup.update(self.playerdict(group.members))
                    _LOGGER.debug(
                        f"HEOS grouping - Group existing with same master: {newgroup}"
                    )
                    break

            # No existing groups or master not member
            if not self.groups or len(newgroup) == 0:
                newgroup[master.player_id] = master
                _LOGGER.debug(f"HEOS grouping - New master: {master}")
            newgroup.update(members)
            _LOGGER.debug(f"HEOS grouping - New members: {members}")

            return await self.groupcmd_controller(newgroup)

        except HeosError as err:
            _LOGGER.error(f"HEOS grouping - unable to join: {err}")

    async def unjoin(self, members: Dict[int, HeosPlayer]):
        try:
            await self.refresh_groups()
            newgroup = {}

            for groupid, group in self.groups.items():
                newgroup = {}
                if group.leader.player_id in members:
                    newgroup[group.leader.player_id] = group.leader
                    _LOGGER.debug(
                        f"HEOS grouping - ungrouping master, removing group: {group.leader.name}"
                    )
                    break
                elif self.players_member(group, members):
                    newgroup[group.leader.player_id] = group.leader
                    _LOGGER.debug(
                        f"HEOS grouping - found member in group: {group.members} where master: {group.leader}"
                    )
                    for oldmember in group.members:
                        for removeplayer in members.values():
                            if oldmember.player_id == removeplayer.player_id:
                                _LOGGER.debug(
                                    f"HEOS grouping - ungrouping, removing: {oldmember.name}"
                                )
                            else:
                                newgroup[oldmember.player_id] = oldmember
                    break

            return await self.groupcmd_controller(newgroup)

        except HeosError as err:
            _LOGGER.error(f"HEOS grouping - unable to unjoin: {err}")

    async def groupcmd_controller(self, newgroup: Dict[int, HeosPlayer]):
        if len(newgroup) > 0:
            cmdstring = ""
            for memberid, member in newgroup.items():
                cmdstring += f"{member.player_id},"
            cmdstring.rstrip(",")
            _LOGGER.debug(f"HEOS grouping - sending to controller: {cmdstring}")
            # _LOGGER.debug(f"self.controller.create_group({cmdstring}, " ")")
            return await self.controller.create_group(cmdstring, "")
        else:
            _LOGGER.debug(f"HEOS grouping - nothing to do: {newgroup}")
            return None
