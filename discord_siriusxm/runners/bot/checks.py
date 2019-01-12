from discord import TextChannel

from .utils import send_message

__all__ = ['no_pm', 'require_voice']


async def no_pm(ctx):
    print('test2')
    if not isinstance(ctx.message.channel, TextChannel):
        print('test3')
        await send_message(
            ctx,
            (f'`{ctx.message.content}`: can only be used in a text chat room '
             f'in a Discord server')
        )
        return False
    return True


async def require_voice(ctx):
    if not await no_pm(ctx):
        print('test1')
        return False

    if ctx.message.author.voice is None:
        await send_message(
            ctx,
            (f'`{ctx.message.content}`: can only be ran if you are in a voice '
             f'channel')
        )
        return False
    return True
