"""Denon HEOS Media Player."""
from collections import namedtuple
from functools import reduce, wraps
import logging
from operator import ior
from typing import Sequence

from pyheos import Heos, HeosError, const as heos_const

from homeassistant.components.media_player import MediaPlayerEntity, BrowseMedia
from homeassistant.components.media_player.const import (
    ATTR_MEDIA_ENQUEUE,
    DOMAIN,
    MEDIA_TYPE_MUSIC,
    MEDIA_TYPE_PLAYLIST,
    MEDIA_TYPE_URL,
    MEDIA_TYPE_ALBUM,  # bm
    MEDIA_TYPE_ARTIST,  # bm
    MEDIA_TYPE_COMPOSER,  # bm
    MEDIA_TYPE_CONTRIBUTING_ARTIST,  # bm
    MEDIA_TYPE_GENRE,  # bm
    MEDIA_TYPE_TRACK,  # bm
    SUPPORT_BROWSE_MEDIA,  # bm
    SUPPORT_CLEAR_PLAYLIST,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_SHUFFLE_SET,
    SUPPORT_STOP,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP,
    SUPPORT_TURN_OFF,
    MEDIA_CLASS_ALBUM,  # bm
    MEDIA_CLASS_ARTIST,  # bm
    MEDIA_CLASS_DIRECTORY,  # bm
    MEDIA_CLASS_EPISODE,  # bm
    MEDIA_CLASS_GENRE,  # bm
    MEDIA_CLASS_PLAYLIST,  # bm
    MEDIA_CLASS_PODCAST,  # bm
    MEDIA_CLASS_TRACK,  # bm
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_IDLE, STATE_PAUSED, STATE_PLAYING
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.util.dt import utcnow
from homeassistant.components.media_player.errors import BrowseError  # bm

from .const import (
    DATA_SOURCE_MANAGER,
    DATA_CONTROLLER_MANAGER,
    DOMAIN as HEOS_DOMAIN,
    SIGNAL_HEOS_UPDATED,
)

BASE_SUPPORTED_FEATURES = (
    SUPPORT_VOLUME_MUTE
    | SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_STEP
    | SUPPORT_CLEAR_PLAYLIST
    | SUPPORT_SHUFFLE_SET
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_PLAY_MEDIA
    | SUPPORT_TURN_OFF
    | SUPPORT_BROWSE_MEDIA
)

PLAY_STATE_TO_STATE = {
    heos_const.PLAY_STATE_PLAY: STATE_PLAYING,
    heos_const.PLAY_STATE_STOP: STATE_IDLE,
    heos_const.PLAY_STATE_PAUSE: STATE_PAUSED,
}

CONTROL_TO_SUPPORT = {
    heos_const.CONTROL_PLAY: SUPPORT_PLAY,
    heos_const.CONTROL_PAUSE: SUPPORT_PAUSE,
    heos_const.CONTROL_STOP: SUPPORT_STOP,
    heos_const.CONTROL_PLAY_PREVIOUS: SUPPORT_PREVIOUS_TRACK,
    heos_const.CONTROL_PLAY_NEXT: SUPPORT_NEXT_TRACK,
}

_LOGGER = logging.getLogger(__name__)


ATTR_HEOS_GROUP = "heos_group"  # group
ATTR_HEOS_GROUPNAME = "groupName"  # group
ATTR_HEOS_GROUPID = "groupid"  # group


async def async_setup_entry(
    hass: HomeAssistantType, entry: ConfigEntry, async_add_entities
):
    """Add media players for a config entry."""
    players = hass.data[HEOS_DOMAIN][DOMAIN]
    controller_manager = hass.data[HEOS_DOMAIN][DATA_CONTROLLER_MANAGER]  # group
    # devices = [HeosMediaPlayer(player) for player in players.values()]
    devices = [
        HeosMediaPlayer(player, controller_manager) for player in players.values()
    ]  # group
    async_add_entities(devices, True)


def log_command_error(command: str):
    """Return decorator that logs command failure."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                await func(*args, **kwargs)
            except (HeosError, ValueError) as ex:
                _LOGGER.error("Unable to %s: %s", command, ex)

        return wrapper

    return decorator


class UnknownMediaType(BrowseError):
    """Unknown media type."""


class HeosMediaPlayer(MediaPlayerEntity):
    """The HEOS player."""

    def __init__(self, player, controller_manager):
        """Initialize."""
        self._media_position_updated_at = None
        self._player = player
        self._signals = []
        self._supported_features = BASE_SUPPORTED_FEATURES
        self._source_manager = None
        self._group_list = []  # group
        self._group_name = None  # group
        self._controller_manager = controller_manager  # group
        self._groupid = None  # group

    async def _player_update(self, player_id, event):
        """Handle player attribute updated."""
        if self._player.player_id != player_id:
            return
        if event == heos_const.EVENT_PLAYER_NOW_PLAYING_PROGRESS:
            self._media_position_updated_at = utcnow()
        await self.get_groups()  # group
        await self.async_update_ha_state(True)

    async def _heos_updated(self):
        """Handle sources changed."""
        await self.get_groups()  # group
        await self.async_update_ha_state(True)

    async def async_added_to_hass(self):
        """Device added to hass."""
        # Update state when attributes of the player change
        self._signals.append(
            self._player.heos.dispatcher.connect(
                heos_const.SIGNAL_PLAYER_EVENT, self._player_update
            )
        )
        # Update state when heos changes
        self._signals.append(
            self.hass.helpers.dispatcher.async_dispatcher_connect(
                SIGNAL_HEOS_UPDATED, self._heos_updated
            )
        )

    @log_command_error("clear playlist")
    async def async_clear_playlist(self):
        """Clear players playlist."""
        await self._player.clear_queue()

    @log_command_error("pause")
    async def async_media_pause(self):
        """Send pause command."""
        await self._player.pause()

    @log_command_error("play")
    async def async_media_play(self):
        """Send play command."""
        await self._player.play()

    @log_command_error("move to previous track")
    async def async_media_previous_track(self):
        """Send previous track command."""
        await self._player.play_previous()

    @log_command_error("move to next track")
    async def async_media_next_track(self):
        """Send next track command."""
        await self._player.play_next()

    @log_command_error("stop")
    async def async_media_stop(self):
        """Send stop command."""
        await self._player.stop()

    @log_command_error("turn_off")
    async def async_turn_off(self):
        """Send turnoff-stop command."""
        await self._player.stop()

    @log_command_error("set mute")
    async def async_mute_volume(self, mute):
        """Mute the volume."""
        await self._player.set_mute(mute)

    @log_command_error("play media")
    async def async_play_media(self, media_type, media_id, **kwargs):
        _LOGGER.debug(f"async_play_media: {media_type} {media_id}")

        """Play a piece of media."""
        if media_type in (MEDIA_TYPE_URL, MEDIA_TYPE_MUSIC):
            await self._player.play_url(media_id)
            return

        if media_type == "quick_select":
            # media_id may be an int or a str
            selects = await self._player.get_quick_selects()
            try:
                index = int(media_id)
            except ValueError:
                # Try finding index by name
                index = next(
                    (index for index, select in selects.items() if select == media_id),
                    None,
                )
            if index is None:
                raise ValueError(f"Invalid quick select '{media_id}'")
            await self._player.play_quick_select(index)
            return

        if media_type == MEDIA_TYPE_PLAYLIST:
            playlists = await self._player.heos.get_playlists()
            playlist = next((p for p in playlists if p.name == media_id), None)
            if not playlist:
                raise ValueError(f"Invalid playlist '{media_id}'")
            add_queue_option = (
                heos_const.ADD_QUEUE_ADD_TO_END
                if kwargs.get(ATTR_MEDIA_ENQUEUE)
                else heos_const.ADD_QUEUE_REPLACE_AND_PLAY
            )
            await self._player.add_to_queue(playlist, add_queue_option)
            return

        if media_type == "favorite" or media_type == "favorites":
            # media_id may be an int or str
            try:
                index = int(media_id)
            except ValueError:
                # Try finding index by name
                index = next(
                    (
                        index
                        for index, favorite in self._source_manager.favorites.items()
                        if favorite.name == media_id
                    ),
                    None,
                )
            if index is None:
                raise ValueError(f"Invalid favorite '{media_id}'")
            await self._player.play_favorite(index)
            return

        raise ValueError(f"Unsupported media type '{media_type}'")

    @log_command_error("select source")
    async def async_select_source(self, source):
        """Select input source."""
        _LOGGER.debug(f"async_select_source: {source}")
        await self._source_manager.play_source(source, self._player)

    @log_command_error("set shuffle")
    async def async_set_shuffle(self, shuffle):
        """Enable/disable shuffle mode."""
        await self._player.set_play_mode(self._player.repeat, shuffle)

    @log_command_error("set volume level")
    async def async_set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        await self._player.set_volume(int(volume * 100))

    async def async_update(self):
        """Update supported features of the player."""
        controls = self._player.now_playing_media.supported_controls
        current_support = [CONTROL_TO_SUPPORT[control] for control in controls]
        self._supported_features = reduce(ior, current_support, BASE_SUPPORTED_FEATURES)
        await self.get_groups()  # group

        if self._source_manager is None:
            self._source_manager = self.hass.data[HEOS_DOMAIN][DATA_SOURCE_MANAGER]

    async def async_will_remove_from_hass(self):
        """Disconnect the device when removed."""
        for signal_remove in self._signals:
            signal_remove()
        self._signals.clear()

    @property
    def available(self) -> bool:
        """Return True if the device is available."""
        return self._player.available

    @property
    def device_info(self) -> dict:
        """Get attributes about the device."""
        return {
            "identifiers": {(HEOS_DOMAIN, self._player.player_id)},
            "name": self._player.name,
            "model": self._player.model,
            "manufacturer": "HEOS",
            "sw_version": self._player.version,
        }

    @property
    def device_state_attributes(self) -> dict:
        """Get additional attribute about the state."""
        return {
            "media_album_id": self._player.now_playing_media.album_id,
            "media_queue_id": self._player.now_playing_media.queue_id,
            "media_source_id": self._player.now_playing_media.source_id,
            "media_station": self._player.now_playing_media.station,
            "media_type": self._player.now_playing_media.type,
            ATTR_HEOS_GROUPID: self._groupid,  # group
            ATTR_HEOS_GROUP: self._group_list,  # group
            ATTR_HEOS_GROUPNAME: self._group_name,  # group
        }

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        return self._player.is_muted

    @property
    def media_album_name(self) -> str:
        """Album name of current playing media, music track only."""
        return self._player.now_playing_media.album

    @property
    def media_artist(self) -> str:
        """Artist of current playing media, music track only."""
        return self._player.now_playing_media.artist

    @property
    def media_content_id(self) -> str:
        """Content ID of current playing media."""
        return self._player.now_playing_media.media_id

    @property
    def media_content_type(self) -> str:
        """Content type of current playing media."""
        return MEDIA_TYPE_MUSIC

    @property
    def media_duration(self):
        """Duration of current playing media in seconds."""
        duration = self._player.now_playing_media.duration
        if isinstance(duration, int):
            return duration / 1000
        return None

    @property
    def media_position(self):
        """Position of current playing media in seconds."""
        # Some media doesn't have duration but reports position, return None
        if not self._player.now_playing_media.duration:
            return None
        return self._player.now_playing_media.current_position / 1000

    @property
    def media_position_updated_at(self):
        """When was the position of the current playing media valid."""
        # Some media doesn't have duration but reports position, return None
        if not self._player.now_playing_media.duration:
            return None
        return self._media_position_updated_at

    @property
    def media_image_remotely_accessible(self) -> bool:
        """If the image url is remotely accessible."""
        return True

    @property
    def media_image_url(self) -> str:
        """Image url of current playing media."""
        # May be an empty string, if so, return None
        image_url = self._player.now_playing_media.image_url
        return image_url if image_url else None

    @property
    def media_title(self) -> str:
        """Title of current playing media."""
        return self._player.now_playing_media.song

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self._player.name

    @property
    def should_poll(self) -> bool:
        """No polling needed for this device."""
        return False

    @property
    def shuffle(self) -> bool:
        """Boolean if shuffle is enabled."""
        return self._player.shuffle

    @property
    def source(self) -> str:
        """Name of the current input source."""
        return self._source_manager.get_current_source(self._player.now_playing_media)

    @property
    def source_list(self) -> Sequence[str]:
        """List of available input sources."""
        return self._source_manager.source_list

    @property
    def state(self) -> str:
        """State of the player."""
        return PLAY_STATE_TO_STATE[self._player.state]

    @property
    def supported_features(self) -> int:
        """Flag media player features that are supported."""
        return self._supported_features

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return str(self._player.player_id)

    @property
    def volume_level(self) -> float:
        """Volume level of the media player (0..1)."""
        return self._player.volume / 100

    @property
    def player_id(self) -> int:  # group
        """Return a player ID (int since PyHeos int)."""
        return self._player.player_id

    async def get_groups(self):  # group
        if (
            self._controller_manager.controller.connection_state
            != heos_const.STATE_CONNECTED
        ):
            _LOGGER.error("Unable to rebuild group because HEOS is not connected")
            return []
        # _LOGGER.debug(f"\n\nEntityID: {self.entity_id}\n\n")

        try:
            groupmgr = self._controller_manager.groupmanager
            await groupmgr.refresh_groups()
            self._groupid = groupmgr.get_groupid(self)
            self._group_list = groupmgr.get_grouplist(self._groupid)
            # _LOGGER.debug(f"HEOS Grouping - grouplist: {self._group_list}")
            self._group_name = groupmgr.get_groupname(self._groupid)
            return self._group_list
        except HeosError as err:
            _LOGGER.error("HEOS Unable to get group info: %s", err)
            self._group_name = ""
            self._group_list = []
            return []

    # async def get_groups(self):  # group
    #     """Rebuild the list of entities in speaker group"""
    #     grouplist = []
    #     # controller = self.hass.data[HEOS_DOMAIN][DATA_CONTROLLER_MANAGER].controller
    #     if self._controller.connection_state != heos_const.STATE_CONNECTED:
    #         _LOGGER.error("Unable to rebuild group because HEOS is not connected")
    #         return grouplist

    #     try:
    #         groups = await self._controller.get_groups(refresh=True)

    #         for group in groups.values():
    #             if (
    #                 any(member.player_id == self.player_id for member in group.members)
    #                 or group.leader.player_id == self.player_id
    #             ):
    #                 grouplist.append(
    #                     await self.entity_id_from_player_id(str(group.leader.player_id))
    #                 )
    #                 for member in group.members:
    #                     grouplist.append(
    #                         await self.entity_id_from_player_id(str(member.player_id))
    #                     )
    #                 self._group_name = group.name
    #                 # _LOGGER.debug(
    #                 #     "HEOS - player: "
    #                 #     + str(self.name)
    #                 #     + " is part of a group with name: "
    #                 #     + str(group.name)
    #                 #     + " where master: "
    #                 #     + str(group.leader.name)
    #                 #     + " and members are: "
    #                 #     + str(group.members)
    #                 # )

    #                 # _LOGGER.debug("HEOS - grouplist: " + str(grouplist))
    #                 return grouplist

    #         # _LOGGER.debug(
    #         #     "HEOS Rebuilding group info, no groups found for this device: %s",
    #         #     self.name,
    #         # )
    #         self._group_name = ""
    #         return grouplist

    # except HeosError as err:
    #     _LOGGER.error("HEOS Unable to get group info: %s", err)
    #     self._group_name = ""
    #     return grouplist

    async def async_browse_media(
        self, media_content_type=None, media_content_id=None
    ) -> BrowseMedia:
        """Implement the websocket media browsing helper."""

        _LOGGER.debug(
            f"Calling asyng_browse_media: {media_content_type} {media_content_id}"
        )

        media_library = self._source_manager
        if media_content_type in [None, "library", "None"]:
            return await self.hass.async_add_executor_job(
                library_payload, media_library
            )

        payload = {
            "media_content_type": media_content_type,
            "media_content_id": media_content_id,
        }

        _LOGGER.debug(f"media_content_id id: {media_content_id}")
        if media_content_id is not None and media_content_id != "None":
            try:
                mediasource = media_library.music_sources.get(
                    int(media_content_id), None
                )
            except ValueError:
                mediasource = None
                pass
            _LOGGER.debug(f"music_source: {mediasource}")
            media = await mediasource.browse()
            _LOGGER.debug(f"media: {media}")
            response = await self.hass.async_add_executor_job(
                build_item_response, media_library, payload, media
            )
            if response is None:
                raise BrowseError(
                    f"Media not found: {media_content_type} / {media_content_id}"
                )
            return response
        return None


def library_payload(media_library):
    """
    Create response payload to describe contents of a specific library.
    Used by async_browse_media.
    """
    # library_info = {
    #     "title": "Media Library",
    #     "media_class": MEDIA_CLASS_DIRECTORY,
    #     "media_content_id": "library",
    #     "media_content_type": "library",
    #     "can_play": False,
    #     "can_expand": True,
    #     "children": [],
    # }

    children = []
    # for item in media_library.browse():
    # for id, item in media_library.favorites.items():
    for id, item in media_library.music_sources.items():
        try:
            children.append(
                item_payload(item, {"media_content_type": item.name.lower()})
            )
        except UnknownMediaType:
            pass

    return BrowseMedia(
        title="Music Library",
        media_class=MEDIA_CLASS_DIRECTORY,
        media_content_id="library",
        media_content_type="library",
        can_play=False,
        can_expand=True,
        children=children,
    )


def item_payload(item, payload={}):
    """
    Create response payload for a single media item.
    Used by async_browse_media.
    """

    media_content_type = payload.get("media_content_type", "library")
    media_content_id = payload.get("media_content_id", None)

    # TYPE_MUSIC_SERVICE = "music_service"
    # TYPE_STATION = "station"
    # TYPE_SONG = "song"
    # TYPE_HEOS_SERVICE = "heos_service"
    # TYPE_PLAYLIST = "playlist"

    if item.type == heos_const.TYPE_MUSIC_SERVICE:
        item_media_class = MEDIA_CLASS_DIRECTORY
        media_type = MEDIA_TYPE_PLAYLIST
        media_can_expand = True
    elif item.type == heos_const.TYPE_STATION:
        item_media_class = MEDIA_CLASS_TRACK
        media_type = MEDIA_TYPE_MUSIC
        media_can_expand = False
    elif item.type == heos_const.TYPE_SONG:
        item_media_class = MEDIA_CLASS_TRACK
        media_type = MEDIA_TYPE_MUSIC
        media_can_expand = False
    elif item.type == heos_const.TYPE_HEOS_SERVICE:
        item_media_class = MEDIA_CLASS_DIRECTORY
        media_type = MEDIA_TYPE_PLAYLIST
        media_can_expand = True
    elif item.type == heos_const.TYPE_PLAYLIST:
        item_media_class = MEDIA_CLASS_PLAYLIST
        media_type = MEDIA_TYPE_PLAYLIST
        media_can_expand = False
    else:
        item_media_class = MEDIA_CLASS_DIRECTORY
        media_type = MEDIA_TYPE_PLAYLIST
        media_can_expand = True

    media_can_play = item.playable

    _LOGGER.debug(
        f"item payload: {item.name} ({item.source_id}) container: {item.container} playable: {media_can_play} type: {item.type} media_content_type: {media_content_type}"
    )

    if media_content_type is None:
        mid = str(item.source_id)
    elif media_content_type == "favorites" and media_content_id is not None:
        mid = item.name
    else:
        mid = str(item.source_id)

    # _LOGGER.debug(f"item payload: {item.name} ({item.source_id})")
    # try:
    #     # media_class = SONOS_TO_MEDIA_CLASSES[media_type]
    #     media_class = MEDIA_CLASS_DIRECTORY
    # except KeyError as err:
    #     _LOGGER.debug("Unknown media type received %s", media_type)
    #     raise UnknownMediaType from err
    return BrowseMedia(
        title=item.name,
        # thumbnail=item.image_url,
        media_class=item_media_class,
        media_content_id=mid,  # get_content_id(item),
        media_content_type=media_content_type,  # SONOS_TO_MEDIA_TYPES[media_type],
        can_play=media_can_play,  # can_play(item.item_class),
        can_expand=media_can_expand,  # can_expand(item),
    )


def build_item_response(media_library, payload, media):
    """Create response payload for the provided media query."""
    media_content_type = payload["media_content_type"]
    media_content_id = payload["media_content_id"]

    _LOGGER.debug(f"media: {media}")
    if media is not None:
        media_type = MEDIA_TYPE_ALBUM  # get_media_type(item)
        media_class = MEDIA_CLASS_DIRECTORY
        children = []
        for item in media:
            try:
                children.append(item_payload(item, payload))
            except UnknownMediaType:
                pass

        title = payload["media_content_type"]
        # id = payload["idstring"]
        thumbnail = None
        media_can_play = False
        media_can_expand = True

        return BrowseMedia(
            title=title,
            thumbnail=thumbnail,
            media_class=media_class,
            media_content_id=media_content_id,
            media_content_type=media_content_type,
            children=children,
            can_play=media_can_play,  # can_play=can_play(payload["search_type"]),
            can_expand=media_can_expand,  # can_expand=can_expand(payload["search_type"]),
        )
