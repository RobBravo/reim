"""Connector registry.

Connectors are discovered through the catalog, not through imports scattered in
core code: each entry names a dotted module path that must expose a
``BaseConnector`` subclass. Adding a country or a source is therefore a catalog
change plus a new module — no edit to the registry itself.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass

from reim.core.exceptions import ConnectorLoadError, ConnectorNotFoundError
from reim.domain.sources.catalog import SourceCatalog, SourceEntry, get_catalog
from reim.ingestion.base import BaseConnector


@dataclass(frozen=True, slots=True)
class RegisteredPipeline:
    """A catalog entry paired with the connector class implementing it."""

    key: str
    entry: SourceEntry
    connector_class: type[BaseConnector]

    @property
    def enabled(self) -> bool:
        """Whether this pipeline should be executed by ``run-all``."""
        return self.entry.enabled

    def build(self) -> BaseConnector:
        """Instantiate the connector for this entry."""
        return self.connector_class(self.entry)


def load_connector_class(dotted_path: str) -> type[BaseConnector]:
    """Import ``dotted_path`` and return the single ``BaseConnector`` subclass in it.

    Args:
        dotted_path: Module path, e.g.
            ``reim.ingestion.connectors.nicaragua.worldbank_cpi_inflation``.

    Raises:
        ConnectorLoadError: The module is missing, fails to import, or does not
            define exactly one concrete connector class.
    """
    try:
        module = importlib.import_module(dotted_path)
    except ImportError as exc:
        msg = f"Could not import connector module {dotted_path!r}: {exc}"
        raise ConnectorLoadError(msg, module=dotted_path) from exc

    candidates = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseConnector)
        and obj is not BaseConnector
        and not inspect.isabstract(obj)
        and obj.__module__ == dotted_path
    ]
    if not candidates:
        msg = f"Module {dotted_path!r} defines no concrete BaseConnector subclass"
        raise ConnectorLoadError(msg, module=dotted_path)
    if len(candidates) > 1:
        names = ", ".join(sorted(cls.__name__ for cls in candidates))
        msg = f"Module {dotted_path!r} defines multiple connector classes: {names}"
        raise ConnectorLoadError(msg, module=dotted_path, candidates=names)
    return candidates[0]


class ConnectorRegistry:
    """Lazily resolves catalog entries to connector classes."""

    def __init__(self, catalog: SourceCatalog | None = None) -> None:
        self._catalog = catalog or get_catalog()
        self._cache: dict[str, RegisteredPipeline] = {}

    @property
    def catalog(self) -> SourceCatalog:
        """The catalog backing this registry."""
        return self._catalog

    def keys(self, *, enabled_only: bool = False) -> list[str]:
        """Return every known pipeline key, optionally only the enabled ones."""
        entries = self._catalog.enabled_sources if enabled_only else self._catalog.sources
        return [entry.key for entry in entries]

    def get(self, key: str) -> RegisteredPipeline:
        """Resolve one pipeline key to its registered pipeline.

        Raises:
            ConnectorNotFoundError: No catalog entry uses that key.
            ConnectorLoadError: The connector module could not be loaded.
        """
        if key in self._cache:
            return self._cache[key]

        entry = next((source for source in self._catalog.sources if source.key == key), None)
        if entry is None:
            msg = f"No pipeline registered under key {key!r}"
            raise ConnectorNotFoundError(msg, key=key, available=self.keys())

        registered = RegisteredPipeline(
            key=key,
            entry=entry,
            connector_class=load_connector_class(entry.connector),
        )
        self._cache[key] = registered
        return registered

    def all(self, *, enabled_only: bool = True) -> list[RegisteredPipeline]:
        """Resolve every pipeline, optionally restricted to enabled entries."""
        return [self.get(key) for key in self.keys(enabled_only=enabled_only)]

    def validate_all(self) -> list[str]:
        """Import every connector referenced by the catalog.

        Returns:
            Human-readable error strings; empty when every connector loads.
        """
        problems: list[str] = []
        for entry in self._catalog.sources:
            try:
                load_connector_class(entry.connector)
            except ConnectorLoadError as exc:
                problems.append(f"{entry.key}: {exc.message}")
        return problems
