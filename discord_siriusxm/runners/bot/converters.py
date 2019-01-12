from discord.ext.commands import Converter, BadArgument


class XMChannelConverter(Converter):
    async def convert(self, ctx, channel_id):
        channel = ctx.cog.state.get_channel(channel_id)

        if channel is None:
            raise BadArgument(
                f'`channel_id` is invalid. Use `{ctx.prefix}channels` for '
                f'a list of valid channels'
            )
