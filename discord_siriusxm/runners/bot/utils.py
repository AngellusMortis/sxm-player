from discord import TextChannel

__all__ = ['send_message']


async def send_message(ctx, message):
    if isinstance(ctx.message.channel, TextChannel):
        message = f'{ctx.message.author.mention}, {message}'

    await ctx.message.channel.send(message)
