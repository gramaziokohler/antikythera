import sys
import warnings

if sys.version_info < (3, 10):
    # in Python < 3.10, entry_points has a different API than in later versions
    # the one from importlib_metadata behaves like the one in stdlib from 3.10+
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points

_DEBUG = False
_PLUGINS_GROUP = "antikythera.agents"


def _create_logger(debug):
    # I want to include sufficient debug printing because plugin discovery can be tricky.
    # I don't want to use logging module with NullHandler becuase this is a library and it shouldn't configure logging.
    # I don't want to use print directly because I don't want to clutter the code with if DEBUG checks.
    # I really don't want to shadow built-in print, because I'm not god

    def noop(*args, **kwargs):
        pass

    if debug:
        return print
    else:
        return noop


def set_debug(enabled: bool) -> None:
    """Enable or disable debug logging for the plugin system.

    Parameters
    ----------
    enabled : bool
        If True, enable debug logging. If False, disable it.
    """
    global _DEBUG, LOG
    _DEBUG = enabled

    LOG = _create_logger(_DEBUG)


LOG = _create_logger(_DEBUG)


class _PluginManager:
    __INSTANCE = None

    def __init__(self):
        if _PluginManager.__INSTANCE:
            raise RuntimeError("PluginManager is a singleton!")
        _PluginManager.__INSTANCE = self

        self._auto_discovery_done = False

        LOG("PluginManager initialized")

    def discover_plugins(self) -> None:
        if self._auto_discovery_done:
            LOG("Plugin discovery already done, skipping")
            return

        discovered_plugins = entry_points(group=_PLUGINS_GROUP)

        LOG(f"Found {len(discovered_plugins)} plugins in group '{_PLUGINS_GROUP}'")

        for plugin in discovered_plugins:
            LOG(f"Loading plugin: {plugin.name}")

            try:
                plugin.load()  # side-effect import
            except Exception as e:
                warnings.warn(f"Failed to load plugin {plugin.name}: {e}", RuntimeWarning)

        self._auto_discovery_done = True

        LOG("Plugin discovery complete.")


PLUGIN_MANAGER = _PluginManager()
