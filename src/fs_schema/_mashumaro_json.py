"""Mashumaro JSON conversion used by filesystem operations."""

from dataclasses import is_dataclass
from pathlib import Path
from typing import TypeVar, cast

from typing_extensions import Protocol, runtime_checkable

import fs_schema._errmsg as em

from ._types import DataclassInstance

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_T_contra = TypeVar("_T_contra", contravariant=True)


@runtime_checkable
class _Encoder(Protocol[_T_contra]):
    def encode(self, obj: _T_contra) -> str | bytes: ...


@runtime_checkable
class _Decoder(Protocol[_T_co]):
    def decode(self, data: str | bytes | bytearray) -> _T_co: ...


def _json_codecs_exn(model: type[_T]) -> tuple[_Encoder[_T], _Decoder[_T]]:
    try:
        from mashumaro.codecs.json import JSONDecoder, JSONEncoder
    except ModuleNotFoundError as error:
        if error.name == "mashumaro":
            raise TypeError(em.Json.EXTRA) from error
        raise

    try:
        import orjson
    except ModuleNotFoundError as error:
        if error.name != "orjson":
            raise
        encoder, decoder = JSONEncoder(model), JSONDecoder(model)
    else:
        from mashumaro.codecs.orjson import ORJSONDecoder, ORJSONEncoder

        _ = orjson
        encoder, decoder = ORJSONEncoder(model), ORJSONDecoder(model)
    return cast(_Encoder[_T], encoder), cast(_Decoder[_T], decoder)


def _check_json_exn(path: Path) -> None:
    if path.suffix.casefold() != ".json":
        raise TypeError(em.Json.suffix(path.suffix or "<no suffix>"))


def _check_model_exn(model: type[object]) -> None:
    if not is_dataclass(model):
        raise TypeError(em.Json.model(model.__name__))


def decode_json(path: Path, model: type[_T]) -> _T:
    """Exception: api intentionally raises"""
    _check_json_exn(path)  # caller error
    _check_model_exn(model)  # caller error
    _, decoder = _json_codecs_exn(model)  # missing extra
    return decoder.decode(path.read_bytes())  # OSError


def encode_json(path: Path, value: DataclassInstance) -> str | bytes:
    """Exception: api intentionally raises"""
    _check_json_exn(path)  # caller error
    model = type(value)
    _check_model_exn(model)  # caller error
    encoder, _ = _json_codecs_exn(model)  # missing extra
    return encoder.encode(value)
