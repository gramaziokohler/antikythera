import importlib
import os
import sys
import threading
import time
import warnings
from typing import Callable
from typing import Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

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


class _ReloadHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None], watched_files: Set[str]):
        self.callback = callback
        self.watched_files = watched_files
        self._last_reload = 0
        self._lock = threading.Lock()

    def on_any_event(self, event):
        if event.is_directory:
            return

        # Check if the event involves one of our watched files
        paths_to_check = [event.src_path]
        if hasattr(event, "dest_path"):
            paths_to_check.append(event.dest_path)

        for path in paths_to_check:
            # Use realpath to resolve symlinks/canonical paths
            real_path = os.path.realpath(path)
            if real_path in self.watched_files:
                self._trigger_reload(real_path)
                break

    def _trigger_reload(self, path):
        with self._lock:
            current_time = time.time()
            # Simple debounce: ignore events within 0.5 seconds of the last reload
            if current_time - self._last_reload > 0.5:
                LOG(f"Detected change in {path}, reloading...")
                self._last_reload = current_time
                self.callback()


class _PluginManager:
    __INSTANCE = None

    def __init__(self):
        if _PluginManager.__INSTANCE:
            raise RuntimeError("PluginManager is a singleton!")
        _PluginManager.__INSTANCE = self

        self._auto_discovery_done = False
        self._loaded_modules: Set[str] = set()
        self._module_files: Set[str] = set()
        self._observer = None

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
                obj = plugin.load()  # side-effect import

                # If the entry point points to a module, obj is the module
                if hasattr(obj, "__file__"):
                    module = obj
                    module_name = obj.__name__
                else:
                    # If the entry point points to a class/function, get its module
                    module_name = getattr(obj, "__module__", None)
                    module = sys.modules.get(module_name) if module_name else None

                if module_name:
                    self._loaded_modules.add(module_name)

                if module and hasattr(module, "__file__") and module.__file__:
                    file_path = os.path.realpath(module.__file__)
                    self._module_files.add(file_path)
            except Exception as e:
                warnings.warn(f"Failed to load plugin {plugin.name}: {e}", RuntimeWarning)

        self._auto_discovery_done = True

        LOG("Plugin discovery complete.")

    def reload_plugins(self) -> None:
        LOG("Reloading plugins...")
        for module_name in self._loaded_modules:
            module = sys.modules.get(module_name)
            if module:
                try:
                    importlib.reload(module)
                    LOG(f"Reloaded module: {module_name}")
                except Exception as e:
                    LOG(f"Failed to reload module {module_name}: {e}")

    def start_file_watcher(self, callback: Callable[[], None]) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()

        LOG(f"Starting file watcher on {len(self._module_files)} files")

        self._observer = Observer()
        handler = _ReloadHandler(callback, self._module_files)

        # Watch directories containing the files
        watched_dirs = set(os.path.dirname(f) for f in self._module_files)
        for directory in watched_dirs:
            if os.path.exists(directory):
                self._observer.schedule(handler, directory, recursive=False)

        self._observer.start()

    def stop_file_watcher(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None


PLUGIN_MANAGER = _PluginManager()
