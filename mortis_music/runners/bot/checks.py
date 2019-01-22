from discord import TextChannel

from .utils import send_message

__all__ = ["no_pm", "require_voice"]


async def no_pm(ctx):
    if not isinstance(ctx.message.channel, TextChannel):
        await send_message(
            ctx,
            (
                f"`{ctx.message.content}`: can only be used in a text chat "
                f"room in a Discord server"
            ),
        )
        return False
    return True


async def require_voice(ctx):
    if not await no_pm(ctx):
        return False

    if ctx.message.author.voice is None:
        await send_message(
            ctx,
            (
                f"`{ctx.message.content}`: can only be ran if you are in a "
                f"voice channel"
            ),
        )
        return False
    return True


async def require_player_voice(ctx):
    if ctx.cog.player.voice is None:
        await send_message(
            ctx,
            f"`{ctx.message.content}`: I do not seem to be in a voice channel",
        )
        return False
    return True


async def require_matching_voice(ctx):
    if not await require_voice(ctx):
        return False

    if not await require_player_voice(ctx):
        return False

    if ctx.message.author.voice is None or ctx.cog.player.voice is None:
        return False

    author_channel = ctx.message.author.voice.channel
    player_channel = ctx.cog.player.voice.channel

    if author_channel.id != player_channel.id:
        await send_message(
            ctx,
            (
                f"`{ctx.message.content}`: I am not in the same voice channel "
                f"as you"
            ),
        )
        return False
    return True


async def is_playing(ctx):
    if not ctx.cog.player.is_playing:
        await send_message(ctx, f"`{ctx.message.content}`: nothing is playing")
        return False
    return True
