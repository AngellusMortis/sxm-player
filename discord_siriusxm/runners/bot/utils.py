from discord import TextChannel, Embed
from discord.ext.commands import errors

__all__ = ['send_message']


async def send_message(ctx, message: str = None,
                       embed: Embed = None, sep: str = ', '):
    if message is None and embed is None:
        raise errors.CommandError('A message or a embed must be provided')

    if isinstance(ctx.message.channel, TextChannel):
        if message is not None:
            message = f'{ctx.message.author.mention}{sep}{message}'
        else:
            message = ctx.message.author.mention

    await ctx.message.channel.send(message, embed=embed)
