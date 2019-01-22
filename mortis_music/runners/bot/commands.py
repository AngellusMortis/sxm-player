from discord.ext.commands import Command, Group


class MusicCommand(Command):
    @property
    def cog_name(self):
        return "Music"


class MusicPlayerGroup(Group):
    @property
    def cog_name(self):
        return "Music Player"


class PlexCommand(Command):
    @property
    def cog_name(self):
        return "Plex Player"


class SXMCommand(Command):
    @property
    def cog_name(self):
        return "SiriusXM Player"
