"""`SseParser` (ports the PHP SseLineParser cases)."""

import pytest

from whitemarket.errors.base import TransportError
from whitemarket.live._sse_parser import SseParser


def drain(parser: SseParser) -> list[str]:
    events: list[str] = []
    while (event := parser.next()) is not None:
        events.append(event)
    return events


def parse(chunks: list[bytes], cap: int = 1024) -> list[str]:
    parser = SseParser(cap)
    events: list[str] = []
    for chunk in chunks:
        parser.feed(chunk)
        events.extend(drain(parser))
    return events


STREAMS = [
    pytest.param(b'data: {"a":1}\n\n', ['{"a":1}'], id="centrifugo event"),
    pytest.param(b"data: one\n\ndata: two\n\n", ["one", "two"], id="two events"),
    pytest.param(b"data: one\r\n\r\ndata: two\r\n\r\n", ["one", "two"], id="CRLF"),
    pytest.param(b"data: one\r\rdata: two\r\r", ["one", "two"], id="CR only"),
    pytest.param(
        b"data: one\r\n\ndata: two\n\r\ndata: three\r\r",
        ["one", "two", "three"],
        id="mixed line endings",
    ),
    pytest.param(b"data: a\ndata: b\n\n", ["a\nb"], id="multi-line data joined with LF"),
    pytest.param(b"data: a\ndata:\ndata: b\n\n", ["a\n\nb"], id="empty data line inside"),
    pytest.param(b"data:  two\n\n", [" two"], id="one leading space stripped only"),
    pytest.param(b"data:x\n\n", ["x"], id="no space after the colon"),
    pytest.param(b"data\n\n", [""], id="bare data field"),
    pytest.param(b"data:\n\n", [""], id="empty data"),
    pytest.param(b": keepalive\n\ndata: x\n\n", ["x"], id="comment ignored"),
    pytest.param(b"data: a\n: c\ndata: b\n\n", ["a\nb"], id="comment inside an event"),
    pytest.param(
        b"event: m\nid: 7\nretry: 100\nfoo: bar\ndata: x\n\n", ["x"], id="other fields ignored"
    ),
    pytest.param(b"event: m\n\nid: 1\n\n", [], id="event without data is not dispatched"),
    pytest.param(b"\n\n\r\n\r\n", [], id="blank lines only"),
    pytest.param(b"data: a\n\ndata: b\n", ["a"], id="incomplete event dropped"),
    pytest.param(b"data: a\n\ndata: b", ["a"], id="incomplete line dropped"),
    pytest.param(b"data: {}\n\n", ["{}"], id="empty ping object"),
    pytest.param(b"data: a:b:c\n\n", ["a:b:c"], id="colon inside the value"),
    pytest.param(b"DATA: x\n\n", [], id="field name is case sensitive"),
    pytest.param(b"data2: x\ndatax: y\n\n", [], id="lookalike fields"),
    pytest.param("data: Пр\n\n".encode(), ["Пр"], id="multibyte UTF-8 passes through"),
    pytest.param(b"data: a\n\n\n\ndata: b\n\n", ["a", "b"], id="extra blank lines"),
    pytest.param(b"data: a\r\n", [], id="line end without the blank line"),
]


@pytest.mark.parametrize(("stream", "expected"), STREAMS)
def test_whole_stream_in_one_chunk(stream: bytes, expected: list[str]) -> None:
    assert parse([stream]) == expected


@pytest.mark.parametrize(("stream", "expected"), STREAMS)
def test_stream_byte_by_byte(stream: bytes, expected: list[str]) -> None:
    assert parse([stream[i : i + 1] for i in range(len(stream))]) == expected


@pytest.mark.parametrize(("stream", "expected"), STREAMS)
def test_stream_split_at_every_position(stream: bytes, expected: list[str]) -> None:
    for cut in range(len(stream) + 1):
        assert parse([stream[:cut], stream[cut:]]) == expected, f"cut at {cut}"


@pytest.mark.parametrize(("stream", "expected"), STREAMS)
def test_stream_split_at_every_pair_of_positions(stream: bytes, expected: list[str]) -> None:
    for first in range(len(stream) + 1):
        for second in range(first, len(stream) + 1):
            chunks = [stream[:first], stream[first:second], stream[second:]]
            assert parse(chunks) == expected, f"cuts at {first}, {second}"


def test_multibyte_character_split_across_chunks_survives() -> None:
    stream = "data: При\U0001f600\n\n".encode()

    assert parse([stream[i : i + 1] for i in range(len(stream))]) == ["При\U0001f600"]


def test_invalid_utf8_is_replaced_not_raised() -> None:
    assert parse([b"data: a\xffb\n\n"]) == ["a�b"]


def test_crlf_split_between_chunks_is_one_line_end() -> None:
    # If the LF after the CR were its own empty line, "a" would be dispatched before "b" is read.
    assert parse([b"data: a\r", b"\ndata: b\r\n\r", b"\n"]) == ["a\nb"]


def test_lone_cr_at_the_end_of_a_chunk_is_a_line_end_not_an_event_end() -> None:
    parser = SseParser(1024)
    parser.feed(b"data: a\r")
    assert parser.next() is None

    parser.feed(b"\r")

    assert parser.next() == "a"
    assert parser.next() is None


def test_cr_then_a_chunk_starting_with_text_ends_the_line() -> None:
    assert parse([b"data: a\r", b"\rdata: x"]) == ["a"]


def test_empty_chunks_change_nothing() -> None:
    assert parse([b"data: a\r", b"", b"\n", b"", b"\n"]) == ["a"]


def _patterned_stream() -> tuple[bytes, list[str]]:
    """200 events whose line endings, lengths, comments and prefixes cycle with co-prime periods."""
    endings = [b"\n", b"\r\n", b"\r"]
    stream = b""
    expected: list[str] = []
    for i in range(200):
        values: list[str] = []
        for j in range(1 + i % 3):
            value = chr(97 + (i * 7 + j) % 26) + "x" * ((i * 5 + j * 11) % 31)
            values.append(value)
            stream += (b"data: " if (i + j) % 2 else b"data:") + value.encode()
            stream += endings[(i + j) % 3]
            if (i + j) % 5 == 0:
                stream += b": comment" + endings[(i * 2 + j) % 3] + b"event: e" + endings[i % 3]
        # A bare LF right after a CR would fuse into one CRLF.
        stream += endings[1 + i % 2] if stream.endswith(b"\r") else endings[(i * 2) % 3]
        expected.append("\n".join(values))
    return stream, expected


def test_chunkings_of_a_long_stream_give_the_same_events() -> None:
    stream, expected = _patterned_stream()

    assert parse([stream], 4096) == expected

    for period in range(1, 41):
        sizes = [period, 1, (period * 3) % 17 + 1]
        chunks: list[bytes] = []
        pos = 0
        while pos < len(stream):
            size = sizes[len(chunks) % 3]
            chunks.append(stream[pos : pos + size])
            pos += size
        assert parse(chunks, 4096) == expected, f"period {period}"


@pytest.mark.parametrize("separator", [b" ", b""], ids=["with a space", "without a space"])
def test_event_of_exactly_the_cap_is_accepted(separator: bytes) -> None:
    payload = "a" * 1024

    assert parse([b"data:" + separator + payload.encode() + b"\n\n"]) == [payload]


@pytest.mark.parametrize("separator", [b" ", b""], ids=["with a space", "without a space"])
def test_event_of_the_cap_plus_one_is_refused(separator: bytes) -> None:
    with pytest.raises(TransportError):
        parse([b"data:" + separator + b"a" * 1025 + b"\n\n"])


def test_multi_line_data_of_exactly_the_cap_joined_length_is_accepted() -> None:
    joined = "a" * 511 + "\n" + "b" * 512  # 511 + 1 + 512 = 1024

    assert parse([b"data: " + b"a" * 511 + b"\ndata: " + b"b" * 512 + b"\n\n"]) == [joined]


def test_multi_line_data_over_the_cap_joined_length_is_refused() -> None:
    with pytest.raises(TransportError):
        parse([b"data: " + b"a" * 511 + b"\ndata: " + b"b" * 513 + b"\n\n"])


@pytest.mark.parametrize(
    ("line_length", "refused"),
    [
        pytest.param(1024 + 6, False, id="comment at the cap plus overhead"),
        pytest.param(1024 + 7, True, id="comment one byte over"),
    ],
)
def test_long_comment_line_is_bounded(line_length: int, refused: bool) -> None:
    chunks = [b": " + b"c" * (line_length - 2) + b"\n"]

    if refused:
        with pytest.raises(TransportError):
            parse(chunks)
    else:
        assert parse(chunks) == []


def test_long_unterminated_line_is_refused_without_waiting_for_its_end() -> None:
    parser = SseParser(1024)
    parser.feed(b"data: " + b"a" * 1000)

    with pytest.raises(TransportError):
        parser.feed(b"a" * 100)


def test_events_completed_before_the_error_can_still_be_taken() -> None:
    parser = SseParser(8)

    with pytest.raises(TransportError):
        parser.feed(b"data: ok\n\ndata: " + b"a" * 20 + b"\n\n")

    assert parser.next() == "ok"


@pytest.mark.parametrize(
    ("stream", "message"),
    [
        pytest.param(
            b"data: SECRET" + b"a" * 2000 + b"\n\n",
            "A live event line exceeds the size limit.",
            id="line",
        ),
        pytest.param(
            b"data: SECRET" + b"a" * 1000 + b"\ndata: " + b"a" * 100 + b"\n\n",
            "A live event exceeds the size limit.",
            id="event",
        ),
    ],
)
def test_cap_error_carries_no_stream_bytes(stream: bytes, message: str) -> None:
    with pytest.raises(TransportError) as caught:
        parse([stream])

    assert str(caught.value) == message
    assert "SECRET" not in repr(caught.value.args)


@pytest.mark.parametrize("cap", [0, -1])
def test_non_positive_cap_is_refused(cap: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        SseParser(cap)


def test_next_is_none_when_nothing_is_complete() -> None:
    parser = SseParser(1024)
    parser.feed(b"data: a\n")

    assert parser.next() is None
