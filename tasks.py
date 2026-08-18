import os
from pathlib import Path


from compas_invocations2 import build
from compas_invocations2 import mkdocs
from compas_invocations2 import style
from compas_invocations2 import tests
from invoke.collection import Collection
from invoke.tasks import task

import compas_pb
from compas_pb.invocations import create_class_assets
from compas_pb.invocations import create_proto_bundle
from compas_pb.invocations import generate_proto_classes


@task
def pre_build(ctx):
    # Ensure proto classes are generated before building the package
    generate_proto_classes(ctx, target_language="python")


@task
def docker(ctx):
    """Build backend and frontend Docker images."""
    base = Path(ctx.config.get("base_folder", "."))
    frontend_repo = Path(ctx.config.get("frontend_repo", "../antikythera-frontend"))
    if not frontend_repo.is_absolute():
        frontend_repo = (base / frontend_repo).resolve()

    ctx.run(f'docker build -t antikythera:dev "{base}"')
    ctx.run(f'docker build -t antikythera-frontend:dev "{frontend_repo}"')


@task
def mcp(ctx, transport="stdio", host="0.0.0.0", port=8001, api_base=None):
    """Run the Antikythera MCP server.

    By default uses stdio transport (for Claude Desktop / VS Code agents).
    Pass --transport sse for a network-accessible SSE server.
    """
    cmd = "python -m antikythera_orchestrator.mcp_server"
    cmd += f" --transport {transport}"
    if transport == "sse":
        cmd += f" --host {host} --port {port}"
    if api_base:
        cmd += f" --api-base {api_base}"
    ctx.run(cmd, pty=True)


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
    create_class_assets,
    create_proto_bundle,
    pre_build,
    docker,
    mcp,
)
ns.configure(
    {
        "base_folder": os.path.dirname(__file__),
        # Antikythera owns these schemas, so it publishes their bindings itself.
        "package_name": "antikythera",
        "generated_folder": Path("./dist") / "generated",
        "frontend_repo": "../antikythera-frontend",
        "proto_folder": Path("./src") / "antikythera" / "proto",
        "proto_include_paths": [Path("./src") / "antikythera" / "proto", compas_pb.PROTOBUF_DEFS],
        "proto_out_folder": Path("./src") / "antikythera" / "proto",
    }
)
