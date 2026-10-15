"""User-facing error text. Import as em.

Groups are the topic, then the case: `em.Schema.Body.files`.
A sentence is one skeleton plus the slots. A method exists only where a value fills a slot.
"""

from collections.abc import Sequence
from typing import Final


def _must_be_a(subject: str, kind: str) -> str:
    return f"{subject} must be a {kind}"


def _must_be(subject: str, pred: str) -> str:
    return f"{subject} must be {pred}"


def _requires(subject: str, what: str) -> str:
    return f"{subject} requires {what}"


def _cannot(subject: str, act: str) -> str:
    return f"{subject} cannot {act}"


def _has_no(subject: str, thing: str) -> str:
    return f"{subject} has no {thing}"


def _does_not(subject: str, act: str) -> str:
    return f"{subject} does not {act}"


def _is_a(subject: str, kind: str) -> str:
    return f"{subject} is a {kind}"


def _only(name: str, scope: str) -> str:
    return f"{name} is only valid for {scope}"


def _at(sentence: str, where: object) -> str:
    return f"{sentence}: {where}"


def _quote(sentence: str, value: object) -> str:
    return f"{sentence}: {value!r}"


def _fix(problem: str, do: str) -> str:
    return f"{problem}; {do}"


class Node:
    """File or Dir constructor."""

    OPTIONAL: Final = _only("optional", "exact-name declarations")
    SORT: Final = _only("sort", "collection declarations")
    SORT_REV: Final = _only("sort_rev", "collection declarations")
    SKIP: Final = _only("skip_mismatch", "collection declarations")
    DOT_ALIAS: Final = _requires("Dir('.')", "alias")
    DOT_MATCH: Final = _cannot("Dir('.')", "take match")
    NEEDS: Final = _requires("declaration", "name, fmt, or match")
    NAME_FMT: Final = _cannot("name", "be combined with fmt")
    MIN: Final = _must_be("min", "at least zero")
    EXACT_MIN: Final = _must_be("exact-name min", "0 or 1")
    EXACT_MAX: Final = _must_be("exact-name max", "omitted or 1")
    MAX: Final = _must_be("max", "at least min")


class Layout:
    """Child keys inside one directory layout."""

    @staticmethod
    def duplicate(key: str) -> str:
        return _quote("duplicate child key", key)


class Schema:
    """The Schema class: bases, metaclass, and the schema dict."""

    class Body:
        """One schema dict."""

        MUST_DICT: Final = "must be a dict"
        NAME: Final = _must_be_a("name", "basename")
        ALIAS: Final = _must_be_a("alias", "public identifier")
        DIR_SCHEMA: Final = _must_be_a("Dir.schema", "Schema subclass")
        RHS: Final = _does_not("RHS", "satisfy Dir.schema")

        @staticmethod
        def decl(key: object, detail: str) -> str:
            return f"declaration {key!r} {detail}"

        @staticmethod
        def schema_or_dict(key: object, item: object) -> str:
            return _must_be_a(f"key {key!r} member {item!r}", "Schema or dict")

        @staticmethod
        def str_or_file(key: object, item: object) -> str:
            return _must_be_a(f"key {key!r} member {item!r}", "str or File")

        @staticmethod
        def files(key: object) -> str:
            return _must_be_a(f"key {key!r}", "list of file declarations")

        @staticmethod
        def invalid(key: object) -> str:
            return _quote("invalid entry", key)

        @staticmethod
        def shadow(name: str) -> str:
            return f"child {name!r} shadows a Schema member"

    @staticmethod
    def text(class_name: str, detail: str) -> str:
        return f"{class_name}.schema {detail}"

    @staticmethod
    def twice(name: str) -> str:
        return _cannot(name, "set schema twice")

    @staticmethod
    def one_base(class_name: str) -> str:
        return f"{class_name} must have exactly one direct Schema base and no mixins"

    @staticmethod
    def metaclass(class_name: str) -> str:
        return _must_be(f"{class_name} metaclass", "Schema")

    @staticmethod
    def override(class_name: str, name: str) -> str:
        return _cannot(f"{class_name} Schema declaration", f"override {name!r}")


class Bind:
    """Mismatch text."""

    @staticmethod
    def expected(kind: str, path: object) -> str:
        return _at(f"expected {kind}", path)

    @staticmethod
    def file(path: object) -> str:
        return Bind.expected("file", path)

    @staticmethod
    def directory(path: object) -> str:
        return Bind.expected("directory", path)

    @staticmethod
    def fixed(pattern: str | None, target: object) -> str:
        return _at(_does_not("fixed basename", f"match {pattern!r}"), target)

    @staticmethod
    def count(*, low: int, high: int | None, position: int, found: int, dangling: Sequence[str], path: object) -> str:
        upper = "unbounded" if high is None else str(high)
        suffix = f" (dangling: {', '.join(dangling)})" if dangling else ""
        return _at(f"expected {low}..{upper} matches for defn {position}, found {found}{suffix}", path)

    @staticmethod
    def failed(pattern: str, basename: str) -> str:
        return _at(f"failed match {pattern!r}", basename)


class Xor:
    @staticmethod
    def empty(path: object) -> str:
        return _at(_has_no("xor", "layouts"), path)

    @staticmethod
    def single(path: object) -> str:
        return _at(_has_no("xor", "single layout"), path)


class Fmt:
    """Basename format and match."""

    NONE: Final = _has_no("declaration", "formatter")
    TIME: Final = "time captures are unsupported"

    @staticmethod
    def capture(name: str) -> str:
        return f"capture {name!r} disagrees with the enclosing stamp"

    @staticmethod
    def basename(basename: str) -> str:
        return _quote(_must_be_a("formatted name", "basename"), basename)

    @staticmethod
    def pattern(pattern: str, basename: str) -> str:
        return _quote(_does_not("formatted basename", f"match {pattern!r}"), basename)


class Parse:
    @staticmethod
    def member(basename: str) -> str:
        return _does_not(f"member {basename!r}", "match")


class Create:
    FILENAMES: Final = "; keys are filenames, not captures"

    @staticmethod
    def unknown(key: str) -> str:
        return _quote("unknown create key", key)

    @staticmethod
    def duplicate(keys: object) -> str:
        return _quote("duplicate create keys", keys)

    @staticmethod
    def bound(name: str) -> str:
        return _fix(f"create on bound {name}", "use root()")

    @staticmethod
    def one_child(keys: Sequence[str]) -> str:
        return f"create keys {list(keys)} name one child"

    @staticmethod
    def pair(key: str) -> str:
        return _fix(f"{key!r} value is one (captures, payload) pair", "pass a list of pairs")

    @staticmethod
    def names(key: str) -> str:
        return _fix(_has_no(f"{key!r}", "formatter"), "pass a basename mapping")

    @staticmethod
    def collection(key: str) -> str:
        return _fix(_is_a(f"{key!r}", "collection"), "pass a basename mapping or (captures, payload) pairs")

    @staticmethod
    def file(key: str, missing: Sequence[str], stamped: Sequence[str]) -> str:
        parts = [f"missing captures {list(missing)}"]
        if stamped:
            parts.append(f"already stamped {list(stamped)}")
        detail = "; ".join(parts)
        return _fix(f"{_is_a(f'{key!r}', 'file collection')}; {detail}", "pass (captures, payload) pairs")

    @staticmethod
    def member(key: str, name: str, *, filenames: bool = False) -> str:
        hint = Create.FILENAMES if filenames else ""
        return f"{_does_not(f'{key!r} member {name!r}', 'match')}{hint}"


class Load:
    @staticmethod
    def subclass(path: object, declared: str, model: str) -> str:
        return f"{path}: {_must_be_a(f'declared loader {declared}', f'subclass of {model}')}"

    @staticmethod
    def loader(path: object, declared: object) -> str:
        return f"{path}: loader must be a class, not {declared!r}"

    @staticmethod
    def missing(path: object) -> str:
        return _at(_has_no("file", "declared loader"), path)


class Copy:
    @staticmethod
    def onto(target: object) -> str:
        return _at("refusing to copy onto itself", target)


class Json:
    EXTRA: Final = _requires("JSON dataclass conversion", "fs-schema[mashumaro]")

    @staticmethod
    def suffix(suffix: str) -> str:
        return f"suffix must be '.json', got {suffix!r}"

    @staticmethod
    def model(name: str) -> str:
        return _must_be_a(f"declared model {name}", "dataclass")
