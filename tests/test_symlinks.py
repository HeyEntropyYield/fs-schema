# pyright: reportPrivateUsage=false, reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportArgumentType=false
# Pins what soft links do today for every filesystem operation. It is a record, not a policy.
import shutil
from pathlib import Path
from typing import NamedTuple

import pytest

import fs_schema as fss
from fs_schema import Dir, File, MismatchErr, Schema, _ops


def _read_text(path: Path) -> str:
    return path.read_text()


class Inner(Schema):
    schema = {"inner": "inner.txt"}


class Tree(Schema):
    schema = {"note": File("note.txt", schema=_read_text), Dir("sub"): Inner}


class Loose(Schema):
    schema = {"note": File("note.txt", optional=True), Dir("sub", optional=True): Inner}


class Pics(Schema):
    schema = {"images": File(fmt="{stem}.png", min=0)}


class NeedPic(Schema):
    schema = {"images": File(fmt="{stem}.png", min=1)}


class Subs(Schema):
    schema = {Dir(alias="subs", fmt="{name}", min=0): Inner}


class World(NamedTuple):
    root: Path
    real: Path
    real_dir: Path
    gone: Path


@pytest.fixture
def world(tmp_path: Path) -> World:
    """`real` and `real_dir` exist, `gone` does not. All sit beside `root`, never inside it."""
    real = tmp_path / "real.txt"
    _ = real.write_text("body")
    real_dir = tmp_path / "real-dir"
    real_dir.mkdir()
    _ = (real_dir / "inner.txt").write_text("inside")
    root = tmp_path / "root"
    root.mkdir()
    return World(root, real, real_dir, tmp_path / "gone")


def _stray_temporaries(directory: Path) -> list[str]:
    return [path.name for path in directory.iterdir() if path.name.startswith(".")]


def _target(world: World, name: str) -> Path:
    return {"real": world.real, "real_dir": world.real_dir, "gone": world.gone}[name]


def _kinds(directory: Path) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for entry in sorted(directory.iterdir()):
        if entry.is_symlink():
            kinds[entry.name] = "symlink"
        else:
            kinds[entry.name] = "dir" if entry.is_dir() else "file"
    return kinds


# put / File.create


def test_put_replaces_a_live_symlink_and_leaves_its_target(world: World) -> None:
    link = world.root / "link.txt"
    link.symlink_to(world.real)
    fss.put(link, "new")
    assert link.is_file() and not link.is_symlink()
    assert link.read_text() == "new"
    assert world.real.read_text() == "body"


def test_put_replaces_a_dangling_symlink_and_never_creates_its_target(world: World) -> None:
    link = world.root / "link.txt"
    link.symlink_to(world.gone)
    fss.put(link, "new")
    assert link.is_file() and not link.is_symlink()
    assert not world.gone.exists()


def test_put_replaces_a_symlink_to_a_directory_with_a_file(world: World) -> None:
    link = world.root / "link"
    link.symlink_to(world.real_dir)
    fss.put(link, "new")
    assert link.is_file() and not link.is_symlink()
    assert (world.real_dir / "inner.txt").read_text() == "inside"


def test_put_does_not_replace_a_real_directory(world: World) -> None:
    with pytest.raises(IsADirectoryError):
        fss.put(world.real_dir, "new")
    assert _stray_temporaries(world.real_dir.parent) == []
    assert (world.real_dir / "inner.txt").read_text() == "inside"


def test_put_writes_through_a_symlinked_parent_directory(world: World) -> None:
    parent = world.root / "parent"
    parent.symlink_to(world.real_dir)
    fss.put(parent / "made.txt", "new")
    assert parent.is_symlink()
    assert (world.real_dir / "made.txt").read_text() == "new"
    assert _stray_temporaries(world.real_dir) == []


def test_put_copies_through_a_source_symlink(world: World) -> None:
    source = world.root / "source.txt"
    source.symlink_to(world.real)
    dest = world.root / "dest.txt"
    fss.put(dest, source)
    assert dest.is_file() and not dest.is_symlink()
    assert dest.read_text() == "body"


def test_put_from_a_dangling_source_symlink_raises_and_leaves_no_file(world: World) -> None:
    source = world.root / "source.txt"
    source.symlink_to(world.gone)
    dest = world.root / "dest.txt"
    with pytest.raises(FileNotFoundError):
        fss.put(dest, source)
    assert not dest.exists()
    assert _stray_temporaries(world.root) == []


def test_file_create_replaces_a_live_symlink(world: World) -> None:
    (world.root / "note.txt").symlink_to(world.real)
    _ = Tree.relative_to(world.root).note.create("new")
    assert _kinds(world.root) == {"note.txt": "file"}
    assert (world.root / "note.txt").read_text() == "new"
    assert world.real.read_text() == "body"


def test_file_create_replaces_a_dangling_symlink(world: World) -> None:
    (world.root / "note.txt").symlink_to(world.gone)
    _ = Tree.relative_to(world.root).note.create("new")
    assert _kinds(world.root) == {"note.txt": "file"}
    assert not world.gone.exists()


# Dir.create


def test_dir_create_writes_into_a_symlinked_directory(world: World) -> None:
    (world.root / "sub").symlink_to(world.real_dir)
    _ = Tree.relative_to(world.root).sub.create(inner="changed")
    assert (world.root / "sub").is_symlink()
    assert (world.real_dir / "inner.txt").read_text() == "changed"


def test_root_create_writes_into_a_symlinked_nested_directory(world: World) -> None:
    (world.root / "sub").symlink_to(world.real_dir)
    _ = Tree.relative_to(world.root).create(note="n", sub={"inner": "changed"})
    assert (world.root / "sub").is_symlink()
    assert (world.real_dir / "inner.txt").read_text() == "changed"


def test_root_create_writes_into_a_symlinked_root(world: World) -> None:
    link = world.root / "link"
    link.symlink_to(world.real_dir)
    _ = Inner.relative_to(link).create(inner="changed")
    assert link.is_symlink()
    assert (world.real_dir / "inner.txt").read_text() == "changed"


def test_create_keeps_a_symlink_where_a_required_directory_has_no_entry(world: World) -> None:
    (world.root / "sub").symlink_to(world.real_dir)
    _ = Tree.relative_to(world.root).create(note="n")
    assert (world.root / "sub").is_symlink()
    assert (world.real_dir / "inner.txt").read_text() == "inside"


def test_collection_create_writes_into_a_symlinked_member_directory(world: World) -> None:
    (world.root / "one").symlink_to(world.real_dir)
    _ = Subs.relative_to(world.root).create(subs={"one": {"inner": "changed"}})
    assert (world.root / "one").is_symlink()
    assert (world.real_dir / "inner.txt").read_text() == "changed"


@pytest.mark.parametrize("points_at", ["real", "gone"])
def test_dir_create_raises_over_a_file_or_dangling_symlink(world: World, points_at: str) -> None:
    (world.root / "sub").symlink_to(world.real if points_at == "real" else world.gone)
    with pytest.raises(FileExistsError):
        _ = Tree.relative_to(world.root).sub.create(inner="x")
    assert (world.root / "sub").is_symlink()
    assert not world.gone.exists()


# load


def test_load_reads_through_a_live_symlink(world: World) -> None:
    link = world.root / "link.txt"
    link.symlink_to(world.real)
    assert _ops.load(link, _read_text) == "body"
    (world.root / "note.txt").symlink_to(world.real)
    (world.root / "sub").symlink_to(world.real_dir)
    bound = fss.raise_mismatch(Tree.bind(world.root))
    assert bound.note.load() == "body"


def test_load_returns_the_error_for_a_dangling_symlink(world: World) -> None:
    link = world.root / "link.txt"
    link.symlink_to(world.gone)
    assert isinstance(_ops.load(link, _read_text), FileNotFoundError)


def test_load_returns_the_error_for_a_symlink_to_a_directory(world: World) -> None:
    link = world.root / "link"
    link.symlink_to(world.real_dir)
    assert isinstance(_ops.load(link, _read_text), IsADirectoryError)


# bind


def test_bind_accepts_a_file_symlink_and_a_directory_symlink(world: World) -> None:
    (world.root / "note.txt").symlink_to(world.real)
    (world.root / "sub").symlink_to(world.real_dir)
    bound = fss.raise_mismatch(Tree.bind(world.root))
    assert bound.note.path == world.root / "note.txt"
    assert bound.note.path.is_symlink()
    assert bound.sub.path == world.root / "sub"
    assert bound.sub.path.is_symlink()
    assert bound.sub.inner.path == world.root / "sub" / "inner.txt"
    assert bound.sub.inner.read_text() == "inside"


def test_bind_accepts_a_symlinked_root(world: World) -> None:
    link = world.root / "link"
    link.symlink_to(world.real_dir)
    bound = fss.raise_mismatch(Inner.bind(link))
    assert bound.path == link
    assert bound.inner.read_text() == "inside"


def test_bind_chains_through_a_link_to_a_link(world: World) -> None:
    middle = world.root / "middle.txt"
    middle.symlink_to(world.real)
    (world.root / "note.txt").symlink_to(middle)
    (world.root / "sub").mkdir()
    (world.root / "sub" / "inner.txt").write_text("i")
    assert fss.raise_mismatch(Tree.bind(world.root)).note.read_text() == "body"


@pytest.mark.parametrize(
    ("link", "target", "message"),
    [
        ("note.txt", "real_dir", "expected file: {root}/note.txt"),
        ("sub", "real", "expected directory: {root}/sub"),
        ("note.txt", "gone", "expected file: {root}/note.txt"),
        ("sub", "gone", "expected directory: {root}/sub"),
    ],
)
def test_bind_rejects_a_wrong_kind_or_dangling_fixed_symlink(
    world: World, link: str, target: str, message: str
) -> None:
    (world.root / "note.txt").symlink_to(world.real)
    (world.root / "sub").symlink_to(world.real_dir)
    (world.root / link).unlink()
    (world.root / link).symlink_to(_target(world, target))
    err = Tree.bind(world.root)
    assert isinstance(err, MismatchErr)
    assert str(err) == message.format(root=world.root)


def test_bind_treats_an_optional_dangling_symlink_as_absent(world: World) -> None:
    (world.root / "note.txt").symlink_to(world.gone)
    (world.root / "sub").symlink_to(world.gone)
    bound = fss.raise_mismatch(Loose.bind(world.root))
    assert bound.note is None
    assert bound.sub is None


@pytest.mark.parametrize(
    ("link", "target", "message"),
    [
        ("note.txt", "real_dir", "expected file: {root}/note.txt"),
        ("sub", "real", "expected directory: {root}/sub"),
    ],
)
def test_bind_rejects_an_optional_symlink_of_the_wrong_kind(world: World, link: str, target: str, message: str) -> None:
    (world.root / link).symlink_to(_target(world, target))
    err = Loose.bind(world.root)
    assert isinstance(err, MismatchErr)
    assert str(err) == message.format(root=world.root)


def test_bind_file_collection_keeps_live_file_symlinks_only(world: World) -> None:
    (world.root / "a.png").symlink_to(world.real)
    (world.root / "b.png").symlink_to(world.gone)
    (world.root / "c.png").symlink_to(world.real_dir)
    _ = (world.root / "d.png").write_bytes(b"png")
    bound = fss.raise_mismatch(Pics.bind(world.root))
    assert [image.path.name for image in bound.images] == ["a.png", "d.png"]
    assert bound.images[0].path.is_symlink()


def test_bind_directory_collection_keeps_live_directory_symlinks_only(world: World) -> None:
    (world.root / "one").symlink_to(world.real_dir)
    (world.root / "two").symlink_to(world.real)
    (world.root / "three").symlink_to(world.gone)
    (world.root / "four").mkdir()
    _ = (world.root / "four" / "inner.txt").write_text("four")
    bound = fss.raise_mismatch(Subs.bind(world.root))
    assert [sub.path.name for sub in bound.subs] == ["four", "one"]
    assert bound.subs[1].path.is_symlink()
    assert bound.subs[1].inner.read_text() == "inside"


def test_bind_directory_collection_member_with_a_dangling_child_mismatches(world: World) -> None:
    member = world.root / "one"
    member.mkdir()
    (member / "inner.txt").symlink_to(world.gone)
    err = Subs.bind(world.root)
    assert isinstance(err, MismatchErr)
    assert str(err) == f"expected file: {member / 'inner.txt'}"


def test_bind_names_dangling_symlinks_in_a_count_mismatch(world: World) -> None:
    (world.root / "b.png").symlink_to(world.gone)
    (world.root / "c.png").symlink_to(world.real_dir)
    err = NeedPic.bind(world.root)
    assert isinstance(err, MismatchErr)
    assert str(err) == f"expected 1..unbounded matches for defn 0, found 0 (dangling: b.png): {world.root}"


@pytest.mark.parametrize("points_at", ["real", "gone"])
def test_bind_rejects_a_root_symlink_that_is_not_a_live_directory(world: World, points_at: str) -> None:
    link = world.root / "link"
    link.symlink_to(world.real if points_at == "real" else world.gone)
    err = Inner.bind(link)
    assert isinstance(err, MismatchErr)
    assert str(err) == f"expected directory: {link}"


# exists_opt, exists, reading the bound path


def test_exists_opt_follows_a_symlink(world: World) -> None:
    live, dirlink, dangling = world.root / "live", world.root / "dirlink", world.root / "dangling"
    live.symlink_to(world.real)
    dirlink.symlink_to(world.real_dir)
    dangling.symlink_to(world.gone)
    assert fss.exists_opt(live) == live
    assert fss.exists_opt(dirlink) == dirlink
    assert fss.exists_opt(dangling) is None
    assert dangling.is_symlink()


def test_bound_path_reads_through_a_symlink_and_keeps_its_link_identity(world: World) -> None:
    (world.root / "note.txt").symlink_to(world.real)
    (world.root / "sub").symlink_to(world.real_dir)
    bound = fss.raise_mismatch(Tree.bind(world.root))
    assert bound.note.read_text() == "body"
    assert bound.note.read_bytes() == b"body"
    assert bound.note.path.is_symlink()
    assert bound.note.path.readlink() == world.real
    assert bound.note.exists() and bound.sub.exists()


def test_bound_node_exists_is_false_once_its_link_dangles(world: World) -> None:
    (world.root / "note.txt").symlink_to(world.real)
    (world.root / "sub").symlink_to(world.real_dir)
    bound = fss.raise_mismatch(Tree.bind(world.root))
    world.real.unlink()
    assert not bound.note.exists()
    assert bound.note.path.is_symlink()
    with pytest.raises(FileNotFoundError):
        bound.note.read_text()


# link_to (soft)


def test_link_to_replaces_an_existing_symlink_without_touching_either_target(world: World) -> None:
    link = world.root / "link.txt"
    link.symlink_to(world.real)
    other = world.root / "other.txt"
    _ = other.write_text("other")
    fss.link_to(link, other)
    assert link.readlink() == other
    assert world.real.read_text() == "body"
    assert other.read_text() == "other"
    assert _stray_temporaries(world.root) == []


def test_link_to_replaces_a_regular_file(world: World) -> None:
    dest = world.root / "dest.txt"
    _ = dest.write_text("old")
    fss.link_to(dest, world.real)
    assert dest.is_symlink()
    assert dest.read_text() == "body"


def test_link_to_replaces_a_symlink_to_a_directory_instead_of_entering_it(world: World) -> None:
    link = world.root / "link"
    link.symlink_to(world.real_dir)
    fss.link_to(link, world.real)
    assert link.readlink() == world.real
    assert (world.real_dir / "inner.txt").read_text() == "inside"
    assert _kinds(world.real_dir) == {"inner.txt": "file"}


def test_link_to_accepts_a_missing_target_and_makes_a_dangling_link(world: World) -> None:
    link = world.root / "link.txt"
    fss.link_to(link, world.gone)
    assert link.is_symlink()
    assert not link.exists()
    assert not world.gone.exists()


@pytest.mark.parametrize("kind", ["empty", "full"])
def test_link_to_does_not_replace_a_real_directory(world: World, kind: str) -> None:
    target = world.real_dir if kind == "full" else world.root / "empty"
    target.mkdir(exist_ok=True)
    with pytest.raises(IsADirectoryError):
        fss.link_to(target, world.real)
    assert not target.is_symlink()
    assert _stray_temporaries(target.parent) == []


def test_link_to_creates_the_link_inside_a_symlinked_parent(world: World) -> None:
    parent = world.root / "parent"
    parent.symlink_to(world.real_dir)
    fss.link_to(parent / "made.txt", world.real)
    assert parent.is_symlink()
    assert (world.real_dir / "made.txt").is_symlink()


def test_node_link_to_replaces_a_bound_symlink_and_the_node_reads_the_new_target(world: World) -> None:
    other = world.root.parent / "other.txt"
    _ = other.write_text("other")
    (world.root / "note.txt").symlink_to(world.real)
    (world.root / "sub").symlink_to(world.real_dir)
    bound = fss.raise_mismatch(Tree.bind(world.root))
    bound.note.link_to(other)
    assert (world.root / "note.txt").readlink() == other
    assert bound.note.read_text() == "other"
    assert world.real.read_text() == "body"


def test_link_to_a_bound_node_links_to_its_path_not_its_target(world: World) -> None:
    (world.root / "note.txt").symlink_to(world.real)
    (world.root / "sub").symlink_to(world.real_dir)
    bound = fss.raise_mismatch(Tree.bind(world.root))
    copy = world.root.parent / "copy.txt"
    fss.link_to(copy, bound.note.path)
    assert copy.readlink() == world.root / "note.txt"
    assert copy.read_text() == "body"


# copy_to


def test_copy_to_follow_true_writes_a_regular_file_from_a_symlink(world: World) -> None:
    source = world.root / "source.txt"
    source.symlink_to(world.real)
    dest = world.root.parent / "out" / "dest.txt"
    fss.copy_to(source, dest)
    assert dest.is_file() and not dest.is_symlink()
    assert dest.read_text() == "body"
    assert source.is_symlink()


def test_copy_to_follow_true_raises_for_a_dangling_source_and_leaves_no_dest(world: World) -> None:
    source = world.root / "source.txt"
    source.symlink_to(world.gone)
    dest = world.root.parent / "dest.txt"
    with pytest.raises(FileNotFoundError):
        fss.copy_to(source, dest)
    assert not dest.exists() and not dest.is_symlink()


def test_copy_to_follow_false_recreates_a_dangling_source_as_a_dangling_link(world: World) -> None:
    source = world.root / "source.txt"
    source.symlink_to(world.gone)
    dest = world.root.parent / "dest.txt"
    fss.copy_to(source, dest, follow_symlinks=False)
    assert dest.is_symlink()
    assert dest.readlink() == world.gone
    assert not dest.exists()


def test_copy_to_follow_false_copies_relative_link_text_without_rebasing_it(world: World) -> None:
    source = world.root / "source.txt"
    source.symlink_to("../real.txt")
    assert source.read_text() == "body"
    dest = world.root.parent / "a" / "b" / "dest.txt"
    fss.copy_to(source, dest, follow_symlinks=False)
    assert dest.readlink() == Path("../real.txt")
    assert not dest.exists()


def test_copy_to_replaces_a_symlink_dest_pointing_at_a_directory(world: World) -> None:
    source = world.root.parent / "src-tree"
    source.mkdir()
    _ = (source / "new.txt").write_text("new")
    dest = world.root / "dest"
    dest.symlink_to(world.real_dir)
    fss.copy_to(source, dest)
    assert dest.is_dir() and not dest.is_symlink()
    assert _kinds(dest) == {"new.txt": "file"}
    assert _kinds(world.real_dir) == {"inner.txt": "file"}


def test_copy_to_replaces_a_dangling_symlink_dest_without_creating_its_target(world: World) -> None:
    dest = world.root / "dest.txt"
    dest.symlink_to(world.gone)
    fss.copy_to(world.real, dest)
    assert dest.is_file() and not dest.is_symlink()
    assert not world.gone.exists()


def test_copy_to_replaces_a_symlink_dest_with_a_link_when_not_following(world: World) -> None:
    source = world.root / "source.txt"
    source.symlink_to(world.real)
    other = world.root / "other.txt"
    _ = other.write_text("other")
    dest = world.root / "dest.txt"
    dest.symlink_to(other)
    fss.copy_to(source, dest, follow_symlinks=False)
    assert dest.readlink() == world.real
    assert other.read_text() == "other"


def test_copy_to_writes_into_a_symlinked_dest_parent(world: World) -> None:
    parent = world.root / "parent"
    parent.symlink_to(world.real_dir)
    fss.copy_to(world.real, parent / "copied.txt")
    assert parent.is_symlink()
    assert (world.real_dir / "copied.txt").read_text() == "body"


def test_copy_to_refuses_a_dest_that_is_a_symlink_to_the_source(world: World) -> None:
    dest = world.root / "dest.txt"
    dest.symlink_to(world.real)
    with pytest.raises(ValueError, match="onto itself"):
        fss.copy_to(world.real, dest)
    assert dest.is_symlink()
    assert world.real.read_text() == "body"


def test_copy_to_refuses_a_dest_reached_through_a_symlink_into_the_source(world: World) -> None:
    inside = world.root / "inside"
    inside.symlink_to(world.real_dir)
    with pytest.raises(ValueError, match="onto itself"):
        fss.copy_to(world.real_dir, inside / "nested")
    assert _kinds(world.real_dir) == {"inner.txt": "file"}


def _tree_with_links(world: World) -> Path:
    source = world.root / "src"
    (source / "sub").mkdir(parents=True)
    _ = (source / "file.txt").write_text("file")
    (source / "file-link.txt").symlink_to(source / "file.txt")
    (source / "dir-link").symlink_to(world.real_dir)
    return source


def test_copy_to_directory_follow_true_turns_nested_links_into_real_copies(world: World) -> None:
    source = _tree_with_links(world)
    dest = world.root.parent / "out"
    fss.copy_to(source, dest)
    assert _kinds(dest) == {"dir-link": "dir", "file-link.txt": "file", "file.txt": "file", "sub": "dir"}
    assert (dest / "dir-link" / "inner.txt").read_text() == "inside"
    assert (dest / "file-link.txt").read_text() == "file"


def test_copy_to_directory_follow_false_recreates_nested_links(world: World) -> None:
    source = _tree_with_links(world)
    dest = world.root.parent / "out"
    fss.copy_to(source, dest, follow_symlinks=False)
    assert _kinds(dest) == {"dir-link": "symlink", "file-link.txt": "symlink", "file.txt": "file", "sub": "dir"}
    assert (dest / "dir-link").readlink() == world.real_dir
    assert (dest / "file-link.txt").readlink() == source / "file.txt"


def test_copy_to_directory_follow_true_with_a_dangling_child_raises_after_copying_the_rest(world: World) -> None:
    source = _tree_with_links(world)
    (source / "dangling.txt").symlink_to(world.gone)
    dest = world.root.parent / "out"
    with pytest.raises(shutil.Error, match=r"dangling\.txt"):
        fss.copy_to(source, dest)
    assert _kinds(dest) == {"dir-link": "dir", "file-link.txt": "file", "file.txt": "file", "sub": "dir"}


def test_copy_to_directory_follow_false_keeps_a_dangling_child_as_a_link(world: World) -> None:
    source = _tree_with_links(world)
    (source / "dangling.txt").symlink_to(world.gone)
    dest = world.root.parent / "out"
    fss.copy_to(source, dest, follow_symlinks=False)
    assert (dest / "dangling.txt").is_symlink()
    assert not (dest / "dangling.txt").exists()


def test_copy_to_clean_removes_only_the_symlink_when_dest_links_to_a_directory(world: World) -> None:
    dest = world.root / "dest"
    dest.symlink_to(world.real_dir)
    fss.copy_to(world.real, dest, clean=True)
    assert dest.is_file() and not dest.is_symlink()
    assert _kinds(world.real_dir) == {"inner.txt": "file"}


def test_copy_to_follows_a_symlink_to_a_directory_the_same_as_one_inside_a_tree(world: World) -> None:
    link = world.root / "link"
    link.symlink_to(world.real_dir)
    single = world.root.parent / "single"
    fss.copy_to(link, single)
    assert single.is_dir() and not single.is_symlink()
    assert (single / "inner.txt").read_text() == "inside"
    fss.copy_to(world.root, world.root.parent / "whole")
    assert _kinds(world.root.parent / "whole") == {"link": "dir"}


# symlink children of a schema directory, bind then copy_to


def _bound_tree(world: World) -> Tree:
    (world.root / "note.txt").symlink_to(world.real)
    (world.root / "sub").symlink_to(world.real_dir)
    return fss.raise_mismatch(Tree.bind(world.root))


def test_bound_schema_copy_to_follows_child_symlinks_by_default(world: World) -> None:
    bound = _bound_tree(world)
    out = world.root.parent / "out"
    bound.copy_to(out)
    assert _kinds(out) == {"note.txt": "file", "sub": "dir"}
    assert (out / "note.txt").read_text() == "body"
    assert (out / "sub" / "inner.txt").read_text() == "inside"
    assert _kinds(out / "sub") == {"inner.txt": "file"}


def test_bound_schema_copy_to_keeps_child_symlinks_when_not_following(world: World) -> None:
    bound = _bound_tree(world)
    out = world.root.parent / "out"
    bound.copy_to(out, follow_symlinks=False)
    assert _kinds(out) == {"note.txt": "symlink", "sub": "symlink"}
    assert (out / "note.txt").readlink() == world.real
    assert (out / "sub").readlink() == world.real_dir


def test_bound_child_file_copy_to_follows_or_keeps_its_symlink(world: World) -> None:
    bound = _bound_tree(world)
    followed = world.root.parent / "followed.txt"
    kept = world.root.parent / "kept.txt"
    bound.note.copy_to(followed)
    bound.note.copy_to(kept, follow_symlinks=False)
    assert followed.is_file() and not followed.is_symlink()
    assert kept.readlink() == world.real


def test_bound_child_directory_copy_to_keeps_its_symlink_when_not_following(world: World) -> None:
    bound = _bound_tree(world)
    kept = world.root.parent / "kept"
    bound.sub.copy_to(kept, follow_symlinks=False)
    assert kept.readlink() == world.real_dir


def test_bound_child_directory_copy_to_follows_a_symlinked_directory(world: World) -> None:
    bound = _bound_tree(world)
    followed = world.root.parent / "followed"
    bound.sub.copy_to(followed)
    assert followed.is_dir() and not followed.is_symlink()
    assert (followed / "inner.txt").read_text() == "inside"


def test_bound_schema_copy_to_publishes_a_tree_that_binds_without_links(world: World) -> None:
    bound = _bound_tree(world)
    out = world.root.parent / "out"
    bound.copy_to(out)
    published = fss.raise_mismatch(Tree.bind(out))
    assert not published.note.path.is_symlink()
    assert not published.sub.path.is_symlink()
    assert published.note.load() == "body"
