# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportUnknownArgumentType=false, reportIndexIssue=false, reportAny=false
import builtins
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from mashumaro.mixins.orjson import DataClassORJSONMixin
from typing_extensions import assert_type

import fs_schema as fss
from fs_schema import _mashumaro_json, _schema


@dataclass
class Child:
    count: int


@dataclass
class Manifest:
    name: str
    children: list[Child] = field(default_factory=list)


@dataclass
class MixinModel(DataClassORJSONMixin):
    value: int


def test_plain_and_mixin_dataclasses_round_trip(tmp_path: Path) -> None:
    fixed = fss.File("manifest.json", schema=Manifest)
    matched = fss.File(fmt="manifest-{part:d}.JSON", schema=Manifest)
    mixin = fss.File("mixin.json", schema=MixinModel)

    class Layout(fss.Schema):
        schema = {"fixed": fixed, "matched": matched, "mixin": mixin}

    root = Layout.relative_to(tmp_path)
    root.fixed.put(Manifest("fixed", [Child(2)]))
    root.matched.format(part=1).put(Manifest("matched", [Child(3)]))
    root.mixin.put(MixinModel(4))

    bound = fss.raise_mismatch(root.bind())
    assert fss.raise_exn(bound.fixed.load()) == Manifest("fixed", [Child(2)])
    assert fss.raise_exn(bound.matched[0].load()) == Manifest("matched", [Child(3)])
    assert fss.raise_exn(bound.mixin.load()) == MixinModel(4)


def test_orjson_backend_and_stdlib_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    encoder, decoder = _mashumaro_json._json_codecs(Manifest)
    assert type(encoder).__module__ == type(decoder).__module__ == "mashumaro.codecs.orjson"

    real_import = builtins.__import__

    def without_orjson(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "orjson":
            raise ModuleNotFoundError("blocked orjson", name="orjson")
        return real_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as import_patch:
        import_patch.setattr(builtins, "__import__", without_orjson)
        fallback_encoder, fallback_decoder = _mashumaro_json._json_codecs(Manifest)
    assert type(fallback_encoder).__module__ == type(fallback_decoder).__module__ == "mashumaro.codecs.json"


def test_missing_mashumaro_error_names_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def without_mashumaro(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "mashumaro.codecs.json":
            raise ModuleNotFoundError("blocked mashumaro", name="mashumaro")
        return real_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as import_patch:
        import_patch.setattr(builtins, "__import__", without_mashumaro)
        with pytest.raises(TypeError, match=r"fs-schema\[mashumaro\]"):
            _mashumaro_json._json_codecs(Manifest)


def test_raw_path_and_save_writes_take_precedence(tmp_path: Path) -> None:
    saved_to: list[Path] = []

    @dataclass
    class Saved:
        value: int

        def save(self, path: Path) -> None:
            saved_to.append(path)
            path.write_text(f"saved {self.value}")

    file = _schema._FixedFile(tmp_path / "nested" / "value.json", fss.File("value.json", schema=Manifest))
    file.put(b"bytes")
    assert file.read_bytes() == b"bytes"
    file.put("text")
    assert file.read_text() == "text"
    source = tmp_path / "source"
    source.write_bytes(b"copied")
    file.put(source)
    assert file.read_bytes() == b"copied"
    file.put(Saved(3))
    assert saved_to == [file.path]
    assert file.read_text() == "saved 3"


def test_json_validation_errors_leave_created_parent(tmp_path: Path) -> None:
    @dataclass
    class NotJson:
        value: int

    target = tmp_path / "nested" / "value.txt"
    with pytest.raises(TypeError, match=r"requires a [.]json file"):
        fss.put(target, NotJson(1))
    assert target.parent.is_dir()
    assert not target.exists()

    wrong_model = _schema._FixedFile(tmp_path / "model.json", fss.File("model.json", schema=int))
    wrong_model.put(Manifest("value"))
    error = wrong_model.load()
    assert isinstance(error, TypeError)
    assert "declared model int is not a dataclass" in str(error)


def test_declared_model_keeps_generic_load_type() -> None:
    declaration = fss.File("manifest.json", schema=Manifest)
    fixed = _schema._FixedFile(Path("manifest.json"), declaration)
    assert_type(declaration, fss.File[Manifest])
    assert_type(fixed.load(), Manifest | Exception)
