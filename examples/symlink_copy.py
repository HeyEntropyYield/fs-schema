# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportArgumentType=false
"""Image bytes stay in one directory. A working tree links them. A publish tree is regular files."""

import tempfile
from pathlib import Path

import fs_schema as fss


class Frame(fss.Schema):
    schema = {"frame": "frame.png"}


class Roll(fss.Schema):
    schema = {fss.Dir(alias="shots", fmt="{name}", min=0): Frame}


def link_frames(roll: fss.SchemaRoot[Roll], camera: Path) -> None:
    for src in sorted(camera.glob("*.png")):
        roll.shots.parse(src.stem).frame.link_to(src)


def publish(roll: Roll, dest: Path) -> Roll:
    # Upload and archive readers need bytes, not links back into the camera directory.
    roll.copy_to(dest, follow_symlinks=True, clean=True)
    return fss.raise_mismatch(Roll.bind(dest))


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        camera = root / "camera"
        camera.mkdir()
        for name in ("a.png", "b.png"):
            _ = (camera / name).write_bytes(name.encode())
        roll = Roll.relative_to(root / "roll")
        link_frames(roll, camera)
        bound = fss.raise_mismatch(roll.bind())
        published = publish(bound, root / "publish")
        frame = published.shots.parse("a").frame.path
        print(frame, frame.read_bytes())


if __name__ == "__main__":
    main()
