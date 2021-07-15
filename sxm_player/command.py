import importlib
import inspect
from typing import List, Optional, Type, Union

import typer
import yaml
from typer.core import TyperCommand

from sxm_player.players import BasePlayer

BASE_PLAYER = "sxm_player.players.BasePlayer "


class ConfigCommandClass(TyperCommand):
    def make_context(self, info_name, args, parent=None, **extra):
        config_file = self.get_config_file(args)
        if config_file is not None:
            config = self.load_config(config_file)
            extra["default_map"] = config

        response = super().make_context(info_name, args, parent, **extra)
        return response

    def parse_args(self, context, args):
        parser = self.make_parser(context)
        options, _, _ = parser.parse_args(args=args.copy())

        extra_args: List[str] = []
        if "player_class" in options:
            player_class = self.get_player_class(context, options)
            if player_class is not None:
                player_params = player_class.get_params()
                self.params = self.params + player_params
                extra_args = [p.name for p in player_params]

        super().parse_args(context, args)
        self.map_extra_args(context, extra_args)
        return

    def map_extra_args(self, context, extra_args: List[str]):
        for arg in extra_args:
            if arg in context.params:
                param = context.params.pop(arg)
                context.meta[arg] = param

    def get_player_class(self, context, options) -> Optional[Type[BasePlayer]]:
        player_param = None
        player_class = None

        for param in self.params:
            if param.human_readable_name == "PLAYER_CLASS":
                player_param = param
                break

        if player_param is not None:
            player_param.expose_value = False
            player_class, _ = player_param.handle_parse_result(context, options, [])
            player_param.expose_value = True
        return player_class

    def get_config_file(self, args: list) -> Optional[str]:
        config_file = None
        index = -1

        try:
            index = args.index("-c")
        except ValueError:
            try:
                index = args.index("--config-file")
            except ValueError:
                pass

        index += 1
        if index != 0 and len(args) > index:
            config_file = args[index]

        return config_file

    def load_config(self, config_file: str) -> dict:
        with open(config_file) as f:
            return yaml.safe_load(f)


def _get_module(class_name):
    module_path = "sxm_player.players"

    if "." in class_name:
        try:
            module_path, class_name = class_name.rsplit(".", 1)
        except ValueError:
            raise typer.BadParameter(f"{class_name} is not a Python path")

    return (module_path, class_name)


def validate_player(value: Union[str, Type[BasePlayer]]):
    if value is None or not isinstance(value, str) and issubclass(value, BasePlayer):
        return value

    module_path, class_name = _get_module(value)

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        raise typer.BadParameter(f"{module_path} is not a Python module")

    try:
        klass = getattr(module, class_name)
    except AttributeError:
        raise typer.BadParameter(f"{class_name} does not inside in {module_path}")

    if not inspect.isclass(klass):
        raise typer.BadParameter(f"{class_name} is not a class")

    if not issubclass(klass, BasePlayer):
        raise typer.BadParameter(f"{class_name} does not inherit from {BASE_PLAYER}")

    return klass
