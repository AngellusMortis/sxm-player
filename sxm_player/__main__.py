import typer

from sxm_player.cli import main
from sxm_player.command import ConfigCommandClass


def start():
    app = typer.Typer()
    app.command(
        cls=ConfigCommandClass,
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )(main)
    app()


if __name__ == "__main__":
    start()
