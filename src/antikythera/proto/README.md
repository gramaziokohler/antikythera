# Protocol Buffer Definitions

This directory contains the Protocol Buffer definitions for Antikythera's Agent Communication Protocol.

## Files

- `antikythera.proto`: Main message definitions for task assignment and completion

## Usage

### Generating Python bindings

```bash
invoke generate-proto-classes
```

**Important**: Generated files (`*_pb2.py`) are not committed to version control. Each developer needs to generate them locally after cloning the repository or updating proto definitions.

For releases, the protobuf files are automatically generated during the CI/CD process before publishing.

## Integration with compas_pb

These message definitions use `google.protobuf.Any` to support type-safe serialization of COMPAS objects via the `compas_pb` library. This allows for:

- Full type safety for COMPAS geometry objects
- Efficient binary serialization
- Schema evolution and backwards compatibility
- Language-agnostic agent implementations
