import os
from pathlib import Path

from compas_invocations2 import build
from compas_invocations2 import docs
from compas_invocations2 import style
from compas_invocations2 import tests
from invoke import Collection
from compas_pb.invocations import generate_proto_classes

ns = Collection(
    docs.help,
    style.check,
    style.lint,
    style.format,
    docs.docs,
    docs.linkcheck,
    tests.test,
    tests.testdocs,
    tests.testcodeblocks,
    build.prepare_changelog,
    build.clean,
    build.release,
    generate_proto_classes,
)
ns.configure(
    {
        "base_folder": os.path.dirname(__file__),
        "proto_folder": Path("./src") / "antikythera" / "proto",
        "proto_include_paths": [Path("./src") / "antikythera"/"proto"],
        "proto_out_folder": Path("./src") / "antikythera" / "proto",
    }
)
