"""Unknown enum values and `__typename` values decode instead of failing (CLAUDE.md rule 5)."""

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field, Tag, TypeAdapter, ValidationError

from whitemarket._runtime.enums import UnknownTolerantEnum
from whitemarket._runtime.typename import typename_discriminator


class Speed(UnknownTolerantEnum):
    SLOW = "SLOW"
    FAST = "FAST"


class Color(UnknownTolerantEnum):
    """Like CatalogColor and SteamApp: the schema itself declares an UNKNOWN member."""

    RED = "RED"
    UNKNOWN = "UNKNOWN"


class Car(BaseModel):
    speed: Speed


def test_declared_values_are_the_declared_members() -> None:
    assert Speed("SLOW") is Speed.SLOW
    assert not Speed.SLOW.is_unknown


def test_an_unknown_value_is_a_pseudo_member_with_the_raw_value() -> None:
    unknown = Speed("WARP")

    assert unknown.is_unknown
    assert unknown.value == "WARP"
    assert unknown == "WARP"
    assert unknown.name == "UNKNOWN"
    assert unknown not in list(Speed)
    assert unknown is not Speed.SLOW
    assert isinstance(unknown, Speed)


def test_unknown_members_with_the_same_raw_value_are_equal_and_hash_alike() -> None:
    assert Speed("WARP") == Speed("WARP")
    assert hash(Speed("WARP")) == hash(Speed("WARP"))
    assert Speed("WARP") != Speed("LUDICROUS")
    assert Speed("WARP") != Speed.FAST


def test_a_declared_unknown_member_is_not_reported_as_an_unknown_value() -> None:
    declared = Color("UNKNOWN")

    assert declared is Color.UNKNOWN
    assert not declared.is_unknown, "the server sent a value the snapshot knows"


def test_a_new_value_of_an_enum_that_declares_unknown_is_told_apart_from_it() -> None:
    new = Color("MAUVE")

    assert new.is_unknown
    assert new.value == "MAUVE"
    assert new is not Color.UNKNOWN
    assert new != Color.UNKNOWN
    assert new not in list(Color)


@pytest.mark.parametrize("bad", [5, None, 1.5, ["SLOW"]])
def test_a_non_string_value_is_still_an_error(bad: object) -> None:
    with pytest.raises(ValueError, match="is not a valid"):
        Speed(bad)


def test_pydantic_decodes_an_unknown_value_and_dumps_the_raw_value_back() -> None:
    car = Car.model_validate({"speed": "WARP"})

    assert car.speed.is_unknown
    assert car.model_dump(mode="json") == {"speed": "WARP"}


class Dog(BaseModel):
    typename__: str = Field(alias="__typename")
    bark: str


class Animal(BaseModel):
    typename__: str = Field(alias="__typename")


Pet = Annotated[
    Annotated[Dog, Tag("Dog")] | Annotated[Animal, Tag("__unknown__")],
    typename_discriminator("Dog"),
]


@pytest.mark.parametrize(
    ("value", "member"),
    [
        pytest.param({"__typename": "Dog", "bark": "woof"}, Dog, id="known"),
        pytest.param({"__typename": "Cat"}, Animal, id="unknown typename"),
    ],
)
def test_a_typename_selects_its_member_and_anything_else_the_fallback(
    value: dict[str, Any], member: type
) -> None:
    assert type(TypeAdapter(Pet).validate_python(value)) is member


@pytest.mark.parametrize("value", [{"__typename": 5}, {}], ids=["non-string", "missing"])
def test_a_typename_that_is_no_string_is_routed_to_the_fallback(value: dict[str, Any]) -> None:
    # The fallback member then rejects the value itself; the point is the route, not a crash.
    with pytest.raises(ValidationError) as caught:
        TypeAdapter(Pet).validate_python(value)

    assert {error["loc"][0] for error in caught.value.errors()} == {"__unknown__"}


def test_a_model_instance_is_routed_by_its_typename_attribute() -> None:
    dog = Dog.model_validate({"__typename": "Dog", "bark": "woof"})

    assert TypeAdapter(Pet).validate_python(dog) is dog


def test_unknown_values_decode_inside_optional_lists_of_optional_enums() -> None:
    class Garage(BaseModel):
        speeds: list[Speed | None] | None = None

    garage = Garage.model_validate({"speeds": ["SLOW", None, "WARP"]})

    assert garage.speeds is not None
    assert [s.value if s else None for s in garage.speeds] == ["SLOW", None, "WARP"]
    assert garage.speeds[2] is not None
    assert garage.speeds[2].is_unknown
    assert Garage.model_validate({"speeds": None}).speeds is None
    assert Garage.model_validate({"speeds": ["WARP"]}).model_dump(mode="json") == {
        "speeds": ["WARP"]
    }


def test_a_list_of_unions_keeps_its_known_members_and_decodes_an_unknown_one() -> None:
    adapter = TypeAdapter(list[Pet])

    pets = adapter.validate_python(
        [
            {"__typename": "Dog", "bark": "woof"},
            {"__typename": "Cat"},
            {"__typename": "Dog", "bark": "arf"},
        ]
    )

    assert [type(p) for p in pets] == [Dog, Animal, Dog]
    assert pets[1].typename__ == "Cat"
