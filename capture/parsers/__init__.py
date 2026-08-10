"""Pluggable message parsers for the Capture Engine.

Future parsers (email, OCR, bank statement, CSV) register via
``register_parser`` without changing the capture service or routes.
"""

from capture.parsers.base import MessageParser, ParsedCapture, ParserSource
from capture.parsers.sms_parser import SmsParser

_PARSERS: dict[str, MessageParser] = {}


def register_parser(parser: MessageParser) -> None:
    _PARSERS[parser.source.value] = parser


def get_parser(source: str | ParserSource | None = None) -> MessageParser:
    if source is None:
        return _PARSERS[ParserSource.SMS.value]

    key = source.value if isinstance(source, ParserSource) else str(source).strip().lower()
    parser = _PARSERS.get(key)
    if parser is None:
        raise ValueError(f"No capture parser registered for source '{key}'.")
    return parser


def list_parsers() -> list[str]:
    return sorted(_PARSERS.keys())


register_parser(SmsParser())

__all__ = [
    "MessageParser",
    "ParsedCapture",
    "ParserSource",
    "SmsParser",
    "get_parser",
    "list_parsers",
    "register_parser",
]
