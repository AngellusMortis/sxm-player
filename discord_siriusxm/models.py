import time
from dataclasses import dataclass
from typing import List

import discord
from sxm.models import XMChannel, XMLiveChannel


class DictState:
    """Class that uses a shared memory dictionary to populate attributes"""
    _state_dict = None

    def __init__(self, state_dict):
        self._state_dict = state_dict

    def __getattr__(self, attr):
        if self._state_dict is not None and attr in self._state_dict:
            return self._state_dict[attr]
        else:
            raise AttributeError("--%r object has no attribute %r" % (
                type(self).__name__, attr))

    def __setattr__(self, attr, value):
        if self._state_dict is not None and attr in self._state_dict:
            self._state_dict[attr] = value
        super().__setattr__(attr, value)


class XMState(DictState):
    """Class to store state SiriusXM Radio player for Discord Bot"""
    _channels = None

    @staticmethod
    def init_state(state):
        state['active_channel_id'] = None
        state['channels'] = []
        state['start_time'] = None
        state['live'] = None
        state['processing_file'] = False

    @property
    def channels(self) -> List[XMChannel]:
        if self._channels is None:
            self._channels = []
            for channel in self._state_dict['channels']:
                self._channels.append(XMChannel(channel))
        return self._channels

    @channels.setter
    def channels(self, value):
        self._channels = None
        self._state_dict['channels'] = value

    @property
    def live(self) -> XMLiveChannel:
        if self._live is None:
            if self._state_dict['live'] is not None:
                self._live = XMLiveChannel(self._state_dict['live'])
        return self._live

    @live.setter
    def live(self, value):
        self._live = None
        self._state_dict['live'] = value

    def get_channel(self, name):
        name = name.lower()
        for channel in self.channels:
            if channel.name.lower() == name or \
                    channel.id.lower() == name or \
                    channel.channel_number == name:
                return channel
        return None

    def set_channel(self, channel_id, start_time=None):
        self.active_channel_id = channel_id
        self.start_time = start_time or int(time.time() * 1000)
        self.live = None

    def reset_channel(self):
        self.active_channel_id = None
        self.start_time = None
        self.live = None


@dataclass
class BotState:
    """Class to store the state for Discord bot"""
    xm_state: XMState = None
    voice: discord.VoiceClient = None
    source: discord.AudioSource = None

    def __init__(self, state_dict):
        self.xm_state = XMState(state_dict)

    @property
    def is_playing(self) -> bool:
        return not(self.voice is None or self.source is None)
