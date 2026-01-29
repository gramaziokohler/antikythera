import glob
import os

import pytest

from antikythera.io import BlueprintJsonSerializer

ROOT_DIR = os.path.join(os.path.dirname(__file__), "../../")
EXAMPLES_DIR = os.path.join(ROOT_DIR, "examples")
EXAMPLE_BLUEPRINTS = glob.glob(os.path.join(EXAMPLES_DIR, "*.json"))


@pytest.mark.parametrize("filepath", EXAMPLE_BLUEPRINTS)
def test_example_blueprints_validation(filepath):
    """Test that all json files in examples/ are valid against the schema."""
    assert os.path.exists(filepath), f"File not found: {filepath}"
    BlueprintJsonSerializer.validate_file(filepath)


def test_invalid_blueprint_validation():
    """Test that validation fails for invalid blueprint."""
    invalid_data = {
        "id": "test",
        "name": "Invalid",
        # Missing version
        "tasks": [],
    }
    with pytest.raises(Exception):  # Expecting jsonschema.ValidationError
        BlueprintJsonSerializer.validate(invalid_data)
