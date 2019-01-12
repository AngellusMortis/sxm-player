from dataclasses import dataclass
from typing import List, Optional, Union

from discord.ext.commands import BadArgument, Converter

from ...models import XMChannel


class XMChannelConverter(Converter):
    async def convert(self, ctx, channel_id: str) -> XMChannel:
        channel = ctx.cog.state.get_channel(channel_id)

        if channel is None:
            raise BadArgument(
                f'`channel_id` is invalid. Use `{ctx.prefix}channels` for '
                f'a list of valid channels'
            )

        return channel


class XMChannelListConverter(XMChannelConverter):
    async def convert(self, ctx, channel_ids: str) -> List[XMChannel]:
        channel_ids = channel_ids.split(',')
        channels = []

        for channel_id in channel_ids:
            channels.append(await super().convert(ctx, channel_id))

        if len(channels) > 5:
            raise BadArgument('too many `channel_ids`. Cannot be more than 5')

        return channels


@dataclass
class IntRangeConverter(Converter):
    min: int = 1
    max: int = 10
    name: str = 'argument'

    @property
    def message(self):
        return '`{name}` must be a number between {min} and {max}'.format(
            name=self.name, min=self.min, max=self.max)

    async def convert(self, ctx, argument: str) -> int:
        try:
            argument = int(argument)
        except ValueError:
            raise BadArgument(self.message)

        if argument > self.max or argument < self.min:
            raise BadArgument(self.message)

        return argument


@dataclass
class VolumeConverter(IntRangeConverter):
    max: int = 100
    name: str = 'volume'

    async def convert(self, ctx,
                      argument: Optional[str]) -> Union[float, None]:
        if argument is not None:
            if argument[-1] == '%':
                argument = argument[:-1]
            argument = await super().convert(ctx, argument)
            argument = float(argument) / 100.0

        return argument
