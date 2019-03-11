from discord import DMChannel, Embed, TextChannel
from discord.ext.commands import errors

__all__ = ["send_message"]


async def send_message(
    ctx, message: str = None, embed: Embed = None, sep: str = ", "
):
    if message is None and embed is None:
        raise errors.CommandError("A message or a embed must be provided")

    if isinstance(ctx, TextChannel):
        channel = ctx
    elif isinstance(ctx.message.channel, (DMChannel, TextChannel)):
        channel = ctx.message.channel
        if message is not None:
            message = f"{ctx.message.author.mention}{sep}{message}"
        else:
            message = ctx.message.author.mention

    await channel.send(message, embed=embed)
