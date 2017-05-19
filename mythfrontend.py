"""
Support for interface with a MythTV Frontend.

#For more details about this platform, please refer to the documentation at
#https://github.com/calmor15014/HA-Component-mythtv-frontend/
"""
import logging
import subprocess
import sys

import voluptuous as vol

# Adding all of the potential options for now, should trim down or implement
from homeassistant.components.media_player import (
    SUPPORT_NEXT_TRACK, SUPPORT_PAUSE, SUPPORT_PREVIOUS_TRACK,
    SUPPORT_TURN_OFF, SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_STEP,
    SUPPORT_PLAY, MediaPlayerDevice, PLATFORM_SCHEMA, SUPPORT_TURN_ON,
    SUPPORT_VOLUME_SET, SUPPORT_STOP)
from homeassistant.const import (
    CONF_HOST, CONF_NAME, STATE_OFF, STATE_ON, STATE_UNKNOWN, CONF_PORT,
    CONF_MAC, STATE_PLAYING, STATE_IDLE, STATE_PAUSED)
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util

# Prerequisite (to be converted to standard PyPI library when available)
# https://github.com/billmeek/MythTVServicesAPI

# WOL requirement for turn_on
REQUIREMENTS = ['wakeonlan==0.2.2']

# Set up logging object
_LOGGER = logging.getLogger(__name__)

# Set default configuration
DEFAULT_NAME = 'MythTV Frontend'
DEFAULT_PORT = 6547

# Set core supported media_player functions
# #TODO - Implement SUPPORT_TURN_OFF
SUPPORT_MYTHTV_FRONTEND = SUPPORT_PAUSE | SUPPORT_PREVIOUS_TRACK | \
                          SUPPORT_NEXT_TRACK | SUPPORT_PLAY | \
                          SUPPORT_STOP

# Set supported media_player functions when volume_control is enabled
SUPPORT_VOLUME_CONTROL = SUPPORT_VOLUME_STEP | SUPPORT_VOLUME_MUTE | \
                         SUPPORT_VOLUME_SET

# Set up YAML schema
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_MAC): cv.string
})


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the MythTV Frontend platform."""
    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    name = config.get(CONF_NAME)
    mac = config.get(CONF_MAC)
    _LOGGER.info('Connecting to MythTV Frontend')

    add_devices([MythTVFrontendDevice(host, port, name, mac)])
    _LOGGER.info("MythTV Frontend device %s:%d added as '%s'", host, port,
                 name)


class MythTVFrontendDevice(MediaPlayerDevice):
    """Representation of a MythTV Frontend."""

    def __init__(self, host, port, name, mac):
        """Initialize the MythTV API."""
        from mythtv_services_api import send as api
        from wakeonlan import wol
        # Save a reference to the api
        self._api = api
        self._host = host
        self._port = port
        self._name = name
        self._frontend = {}
        self._mac = mac
        self._wol = wol
        self._volume = {'control': False, 'level': 0, 'muted': False}
        self._state = STATE_UNKNOWN

    def update(self):
        """Retrieve the latest data."""
        return self.api_update()

    def api_update(self):
        """Use the API to get the latest status."""
        try:
            result = self._api.send(host=self._host, port=self._port,
                                    endpoint='Frontend/GetStatus',
                                    opts={'timeout': 1})
            # _LOGGER.debug(result)  # testing
            if list(result.keys())[0] in ['Abort', 'Warning']:
                # Remove volume controls while frontend is unavailable
                self._volume['control'] = False

                # If ping succeeds but API fails, MythFrontend state is unknown
                if self._ping_host():
                    self._state = STATE_UNKNOWN
                # If ping fails also, MythFrontend device is off/unreachable
                else:
                    self._state = STATE_OFF
                return False

            # Make frontend status values more user-friendly
            self._frontend = result['FrontendStatus']['State']

            # Determine state of frontend
            if self._frontend['state'] == 'idle':
                self._state = STATE_IDLE
            elif self._frontend['state'].startswith('Watching'):
                if self._frontend['playspeed'] == '0':
                    self._state = STATE_PAUSED
                else:
                    self._state = STATE_PLAYING
            else:
                self._state = STATE_ON

            # Set volume control flag and level if the volume tag is present
            if 'volume' in self._frontend:
                self._volume['control'] = True
                self._volume['level'] = int(self._frontend['volume'])
            # Set mute status if mute tag exists
            if 'mute' in self._frontend:
                self._volume['muted'] = (self._frontend['mute'] != '0')
        except:
            self._state = STATE_OFF
            _LOGGER.warning(
                "Communication error with MythTV Frontend Device '%s' at %s:%d",
                self._name, self._host, self._port)
            _LOGGER.warning(self._frontend)
            return False

        return True

    # Reference: device_tracker/ping.py
    def _ping_host(self):
        """Ping the host to see if API status has some errors."""
        if sys.platform == "win32":
            ping_cmd = ['ping', '-n 1', '-w 1000', self._host]
        else:
            ping_cmd = ['ping', '-nq', '-c1', '-W1', self._host]
        pinger = subprocess.Popen(ping_cmd,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
        try:
            pinger.communicate()
            return pinger.returncode == 0
        except subprocess.CalledProcessError:
            _LOGGER.warning("Mythfrontned ping error for '%s' at '%s'",
                            self._name, self._host)
            return False

    def api_send_action(self, action, value=None):
        """Send a command to the Frontend."""
        try:
            result = self._api.send(host=self._host, port=self._port,
                                    endpoint='Frontend/SendAction',
                                    postdata={'Action': action,
                                              'Value': value},
                                    opts={'debug': False, 'wrmi': True,
                                          'timeout': 1})
            # _LOGGER.debug(result)  # testing
            self.api_update()
        except OSError:
            self._state = STATE_OFF
            return False

        return result

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def volume_level(self):
        """Return volume level from 0 to 1."""
        return self._volume['level'] / 100

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._volume['muted']

    @property
    def supported_features(self):
        """Get supported features."""
        features = SUPPORT_MYTHTV_FRONTEND
        if self._mac:
            # Add WOL feature
            features |= SUPPORT_TURN_ON
        if self._volume['control']:
            features |= SUPPORT_VOLUME_CONTROL
        return features

    @property
    def media_title(self):
        """Return the title of current playing media."""
        title = self._frontend.get('title')
        try:
            if self._frontend.get('state').startswith('WatchingLiveTV'):
                title += " (Live TV)"
        except AttributeError:
            # ignore error if state is None
            pass
        return title

    @property
    def media_duration(self):
        """Duration of current playing media in seconds."""
        total_seconds = self._frontend.get('totalseconds')
        if total_seconds is not None:
            return int(total_seconds)
        return 0

    @property
    def media_position(self):
        """Position of current playing media in seconds."""
        seconds_played = self._frontend.get('secondsplayed')
        if seconds_played is not None:
            return int(seconds_played)
        return 0

    @property
    def media_position_updated_at(self):
        """Last valid time of media position."""
        if self._state == STATE_PLAYING or self._state == STATE_PAUSED:
            return dt_util.utcnow()

    # @property
    # def media_image_url(self):
    #     """Return the media image URL."""
    #     #TODO - implement media image from backend?

    def volume_up(self):
        """Volume up the media player."""
        self.api_send_action(action='VOLUMEUP')

    def volume_down(self):
        """Volume down media player."""
        self.api_send_action(action='VOLUMEDOWN')

    def set_volume_level(self, volume):
        """Set specific volume level."""
        self.api_send_action(action='SETVOLUME', value=int(volume * 100))

    def mute_volume(self, mute):
        """Send mute command."""
        self.api_send_action(action='MUTE')

    def media_play_pause(self):
        """Simulate play/pause media player."""
        if self._state == STATE_PLAYING:
            self.media_pause()
        elif self._state == STATE_PAUSED:
            self.media_play()

    def media_play(self):
        """Send play command."""
        self.api_send_action(action='PLAY')

    def media_pause(self):
        """Send pause command."""
        self.api_send_action(action='PAUSE')

    def media_next_track(self):
        """Send next track command."""
        self.api_send_action(action='JUMPFFWD')

    def media_previous_track(self):
        """Send previous track command."""
        self.api_send_action(action='JUMPRWND')

    def turn_on(self):
        """Turn the media player on."""
        if self._mac:
            self._wol.send_magic_packet(self._mac)
