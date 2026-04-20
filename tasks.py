import os
from pathlib import Path


from compas_invocations2 import build
from compas_invocations2 import mkdocs
from compas_invocations2 import style
from compas_invocations2 import tests
from invoke.collection import Collection
from invoke.tasks import task

import compas_pb
from compas_pb.invocations import generate_proto_classes


@task
def pre_build(ctx):
    # Ensure proto classes are generated before building the package
    generate_proto_classes(ctx, target_language="python")


ns = Collection(
    style.check,
    style.lint,
    style.format,
    mkdocs.docs,
    tests.test,
    tests.testdocs,
    tests.testcodeblocks,
    build.prepare_changelog,
    build.clean,
    build.release,
    generate_proto_classes,
    pre_build,
)
ns.configure(
    {
        "base_folder": os.path.dirname(__file__),
        "proto_folder": Path("./src") / "antikythera" / "proto",
        "proto_include_paths": [Path("./src") / "antikythera" / "proto", compas_pb.PROTOBUF_DEFS],
        "proto_out_folder": Path("./src") / "antikythera" / "proto",
    }
)
