from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Optional

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession


class BaseSessionStorage(ABC):
    """Abstract interface for session storage backends."""

    @abstractmethod
    def __init__(self, session_id: str): ...

    @staticmethod
    @abstractmethod
    def list_sessions(limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]: ...

    @abstractmethod
    def __enter__(self): ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb): ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def get(self, blueprint_id: str, key: str) -> Optional[Any]: ...

    @abstractmethod
    def set(self, blueprint_id: str, key: str, value: Any) -> None: ...

    @abstractmethod
    def set_all(self, blueprint_id: str, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def get_all(self, blueprint_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def save_session(self, session: BlueprintSession) -> None: ...

    @abstractmethod
    def load_session(self) -> Optional[BlueprintSession]: ...

    @abstractmethod
    def load_session_with_metadata(self) -> Optional[dict]: ...


class BaseBlueprintStorage(ABC):
    """Abstract interface for blueprint storage backends."""

    @abstractmethod
    def __init__(self): ...

    @abstractmethod
    def __enter__(self): ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb): ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def add_blueprint(self, blueprint: Blueprint) -> None: ...

    @abstractmethod
    def get_blueprint(self, blueprint_id: str) -> Blueprint: ...

    @abstractmethod
    def list_blueprints(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def remove_blueprint(self, blueprint_id: str) -> None: ...


class BaseModelStorage(ABC):
    """Abstract interface for model storage backends."""

    @abstractmethod
    def __init__(self): ...

    @abstractmethod
    def __enter__(self): ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb): ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def add_model(self, model_id: str, model: Any) -> None: ...

    @abstractmethod
    def add_nesting(self, model_id: str, nesting: Any) -> None: ...

    @abstractmethod
    def get_nesting(self, model_id: str) -> Optional[Any]: ...

    @abstractmethod
    def get_model(self, model_id: str) -> Any: ...

    @abstractmethod
    def list_models(self) -> list[str]: ...

    @abstractmethod
    def remove_model(self, model_id: str) -> None: ...
