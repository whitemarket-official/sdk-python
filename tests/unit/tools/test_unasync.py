"""tools/unasync.py: the explicit rule table, the leftover scan, tree mode and check mode."""

from pathlib import Path

import pytest

unasync = pytest.importorskip("unasync", reason="tools/ is not part of this checkout")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("async def f():", "def f():", id="async def"),
        pytest.param("async with a as b:", "with a as b:", id="async with"),
        pytest.param("async for x in y:", "for x in y:", id="async for"),
        pytest.param("x = await g()", "x = g()", id="await"),
        pytest.param("return (await g()).y", "return (g()).y", id="await in parens"),
        pytest.param("def __aenter__(self):", "def __enter__(self):", id="__aenter__"),
        pytest.param("def __aexit__(self):", "def __exit__(self):", id="__aexit__"),
        pytest.param("def __aiter__(self):", "def __iter__(self):", id="__aiter__"),
        pytest.param("def __anext__(self):", "def __next__(self):", id="__anext__"),
        pytest.param("raise StopAsyncIteration", "raise StopIteration", id="StopAsyncIteration"),
        pytest.param("@asynccontextmanager", "@contextmanager", id="asynccontextmanager"),
        pytest.param("c.aclose()", "c.close()", id="aclose"),
        pytest.param("class AsyncGraphQLBase:", "class GraphQLBase:", id="AsyncX class"),
        pytest.param("httpx.AsyncClient()", "httpx.Client()", id="httpx.AsyncClient"),
        pytest.param("AsyncLock()", "Lock()", id="AsyncLock"),
        pytest.param("x: AsyncIterator[int]", "x: Iterator[int]", id="AsyncIterator"),
        pytest.param("await async_sleep(1)", "sleep(1)", id="async_sleep"),
        pytest.param(
            "from .async_base_client import X", "from .base_client import X", id="async_ module"
        ),
        pytest.param(
            "from whitemarket._async.x import Y", "from whitemarket._sync.x import Y", id="_async"
        ),
        pytest.param("import whitemarket._async", "import whitemarket._sync", id="_async bare"),
        pytest.param("data = await resp.aread()", "data = resp.read()", id="aread"),
        pytest.param(
            "async for c in r.aiter_bytes():", "for c in r.iter_bytes():", id="aiter_bytes"
        ),
        pytest.param("r.aiter_raw()", "r.iter_raw()", id="aiter_raw"),
        pytest.param("r.aiter_text()", "r.iter_text()", id="aiter_text"),
        pytest.param("r.aiter_lines()", "r.iter_lines()", id="aiter_lines"),
        pytest.param("x = await anext(it)", "x = next(it)", id="anext"),
        pytest.param("it = aiter(x)", "it = iter(x)", id="aiter"),
        pytest.param("class _AsyncHelper: ...", "class _Helper: ...", id="_AsyncX private"),
        pytest.param("_async_retry()", "_retry()", id="_async_x private"),
        pytest.param(
            "from whitemarket._generated.client import AsyncGeneratedClient",
            "from whitemarket._generated.sync_client import GeneratedClient",
            id="generated client module",
        ),
        pytest.param('__all__ = ["AsyncThing"]', '__all__ = ["Thing"]', id="name string"),
        pytest.param('x: "AsyncFoo[int]"', 'x: "Foo[int]"', id="forward reference"),
    ],
)
def test_each_rule_of_the_table(source: str, expected: str) -> None:
    assert unasync.rewrite(source) == expected


@pytest.mark.parametrize(
    "unchanged",
    [
        "asyncio_helper = 1",
        "def awaiting(): ...",
        "x = Asyncish",
        "AsynC = 1",
        "my_async = 1",
        "def aclosed(): ...",
        "_asynchronous = 1",
        "x = 'async_'",
        "# must not await here\n",
        'msg = "must not await here"',
        'doc = """Talks about AsyncThing and aread."""',
        "client = 1",
        "x.client",
    ],
)
def test_names_that_merely_look_similar_are_left_alone(unchanged: str) -> None:
    assert unasync.rewrite(unchanged) == unchanged


def test_comments_and_prose_keep_their_words_while_code_is_rewritten() -> None:
    source = "x = await f()  # we await it\n"

    assert unasync.rewrite(source) == "x = f()  # we await it\n"


def test_the_rule_table_has_one_rule_per_construct_and_unique_names() -> None:
    names = [rule.name for rule in unasync.RULES]

    assert len(names) == len(set(names))
    assert {"AsyncX", "async_x", "_async", "aclose", "__aenter__"} <= set(names)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("async def f(): ...\n", "def f(): ...\n", id="async def"),
        pytest.param("async with a as b: ...\n", "with a as b: ...\n", id="async with"),
        pytest.param("async for a in b: ...\n", "for a in b: ...\n", id="async for"),
        pytest.param("x = await f()\n", "x = f()\n", id="await"),
    ],
)
def test_the_keywords_async_and_await_are_removed(source: str, expected: str) -> None:
    assert unasync.rewrite(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "import asyncio\n",
        "x = asyncio.sleep(1)\n",
        "async_ = 1\n",
        "x = y.aiter_foo\n",
    ],
    ids=["import asyncio", "asyncio.sleep", "async_ alone", "aiter_ prefix"],
)
def test_something_with_no_rule_fails_instead_of_emitting_async_code(source: str) -> None:
    with pytest.raises(unasync.UnasyncError, match="no rule for"):
        unasync.convert(source, "src/x.py")


def test_a_forbidden_name_inside_a_string_or_comment_is_not_a_leftover() -> None:
    source = '"""Talks about asyncio and await."""\n# asyncio, async\nx = "asyncio"\n'

    assert unasync.leftovers(source) == []


def test_convert_adds_the_header_once_and_keeps_a_generated_files_own() -> None:
    plain = unasync.convert("x = 1\n", "src/whitemarket/_async/x.py")
    generated = unasync.convert("# DO NOT EDIT. Generated by x\nx = 1\n", "src/y.py")

    assert (
        plain
        == "# DO NOT EDIT: generated by tools/unasync.py from src/whitemarket/_async/x.py\nx = 1\n"
    )
    assert generated == "# DO NOT EDIT. Generated by x\nx = 1\n"
    assert unasync.convert("", "src/empty.py") == ""


def test_the_rewrite_is_deterministic_and_idempotent() -> None:
    source = "async def f(self):\n    async with self._lock:\n        return await self._g()\n"

    once = unasync.rewrite(source)

    assert once == unasync.rewrite(source)
    assert unasync.rewrite(once) == once


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_tree_mode_writes_every_file_removes_stale_ones_and_check_mode_agrees(
    tmp_path: Path,
) -> None:
    src, dst = tmp_path / "_async", tmp_path / "_sync"
    _write(src / "a.py", "async def f():\n    return await g()\n")
    _write(src / "sub" / "b.py", "x = AsyncThing()\n")
    _write(src / "__pycache__" / "skipped.py", "async def never(): ...\n")
    _write(dst / "stale.py", "old = 1\n")

    assert unasync.run([], [(src, dst)], check=True) != [], "nothing is written yet"
    assert unasync.run([], [(src, dst)], check=False) == []

    assert sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*.py")) == ["a.py", "sub/b.py"]
    assert "def f():\n    return g()\n" in (dst / "a.py").read_text(encoding="utf-8")
    assert "x = Thing()" in (dst / "sub" / "b.py").read_text(encoding="utf-8")
    assert unasync.run([], [(src, dst)], check=True) == []


def test_check_mode_reports_a_difference_a_missing_file_and_a_stale_file(tmp_path: Path) -> None:
    src, dst = tmp_path / "_async", tmp_path / "_sync"
    _write(src / "a.py", "x = 1\n")
    _write(src / "b.py", "y = 1\n")
    unasync.run([], [(src, dst)], check=False)
    (dst / "a.py").write_text("x = 2\n", encoding="utf-8")
    (dst / "b.py").unlink()
    _write(dst / "stale.py", "z = 1\n")

    problems = unasync.run([], [(src, dst)], check=True)

    assert sorted(p.split(": ")[0] for p in problems) == ["differs", "missing", "stale"]
    assert (dst / "a.py").read_text(encoding="utf-8") == "x = 2\n", "check mode writes nothing"
    assert not (dst / "b.py").exists()
    assert (dst / "stale.py").exists()


def test_file_mode_and_the_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = _write(tmp_path / "client.py", "# DO NOT EDIT. gen\nclass AsyncGeneratedClient: ...\n")
    dst = tmp_path / "sync_client.py"

    assert unasync.main(["--file", str(src), str(dst)]) == 0
    assert dst.read_text(encoding="utf-8") == "# DO NOT EDIT. gen\nclass GeneratedClient: ...\n"
    assert unasync.main(["--check", "--file", str(src), str(dst)]) == 0

    dst.write_text("changed\n", encoding="utf-8")
    assert unasync.main(["--check", "--file", str(src), str(dst)]) == 1
    assert "differs" in capsys.readouterr().err


def test_the_command_line_fails_on_an_unknown_construct(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _write(tmp_path / "a.py", "import asyncio\n")

    assert unasync.main(["--file", str(src), str(tmp_path / "b.py")]) == 2
    assert "no rule for asyncio" in capsys.readouterr().err
    assert not (tmp_path / "b.py").exists()
