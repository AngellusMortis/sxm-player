import importlib
import inspect
from typing import Optional

import click
import yaml

from .players import BasePlayer

BASE_PLAYER = "sxm_player.players.BasePlayer "


class ConfigCommandClass(click.Command):
    def make_context(self, info_name, args, parent=None, **extra):
        config_file = self.get_config_file(args)
        if config_file is not None:
            config = self.load_config(config_file)
            extra["default_map"] = config

        return super().make_context(info_name, args, parent, **extra)

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


class PlayerClass(click.ParamType):
    name = "python_class"

    def convert(self, value, param, ctx):
        if "." not in value:
            module_path = "sxm_player.players"
            class_name = value
        else:
            try:
                module_path, class_name = value.rsplit(".", 1)
            except ValueError:
                self.fail(f"{value} is not a Python path")

        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            self.fail(f"{module_path} is not a Python module")

        try:
            klass = getattr(module, class_name)
        except AttributeError:
            self.fail(f"{class_name} does not inside in {module_path}")

        if not inspect.isclass(klass):
            self.fail(f"{class_name} is not a class")

        if not issubclass(klass, BasePlayer):
            self.fail(f"{class_name} does not inherit from {BASE_PLAYER}")

        return klass
