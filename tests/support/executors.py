"""Fake executors: the seam between the generated client and the transport (no network)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from support.flavors import Flavor
from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._generated.sync_client import GeneratedClient


@dataclass(frozen=True)
class Call:
    document: str
    operation_name: str | None
    variables: Mapping[str, object]
    operation_type: str


class FakeExecutor:
    """Sync executor that records every call and answers with `data`."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.calls: list[Call] = []

    def execute(
        self,
        document: str,
        operation_name: str | None,
        variables: Mapping[str, object],
        operation_type: str,
    ) -> dict[str, Any]:
        self.calls.append(Call(document, operation_name, dict(variables), operation_type))
        return self.data


class FakeAsyncExecutor:
    """Async twin of `FakeExecutor`."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.calls: list[Call] = []

    async def execute(
        self,
        document: str,
        operation_name: str | None,
        variables: Mapping[str, object],
        operation_type: str,
    ) -> dict[str, Any]:
        self.calls.append(Call(document, operation_name, dict(variables), operation_type))
        return self.data


class Harness:
    """One generated client (async or sync) on a fake executor; `call` hides the difference."""

    def __init__(self, flavor: Flavor, data: dict[str, Any]) -> None:
        self.flavor = flavor
        if flavor.is_async:
            self.executor: FakeAsyncExecutor | FakeExecutor = FakeAsyncExecutor(data)
            self.client: Any = AsyncGeneratedClient(self.executor)
        else:
            self.executor = FakeExecutor(data)
            self.client = GeneratedClient(self.executor)

    def call(self, method: str, /, *args: object, **kwargs: object) -> Any:
        return self.flavor.run(getattr(self.client, method)(*args, **kwargs))

    @property
    def calls(self) -> list[Call]:
        return self.executor.calls
