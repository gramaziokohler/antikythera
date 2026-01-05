import argparse
import datetime
import os
import tempfile
import zipfile

from compas.data import json_dump
from compas.data import json_load


def package_model_nesting(model_path: str, nesting_path: str, output_path: str) -> None:
    model_data = json_load(model_path)  # list of models
    nesting_data = json_load(nesting_path)  # matching list of nestring results

    if len(model_data) != len(nesting_data):
        raise ValueError(f"Model data length ({len(model_data)}) does not match nesting data length ({len(nesting_data)})")

    manifest = {"items": []}

    with tempfile.TemporaryDirectory() as tmp_dir:
        nesting_dir = os.path.join(tmp_dir, "nesting")
        model_dir = os.path.join(tmp_dir, "model")
        os.mkdir(model_dir)
        os.mkdir(nesting_dir)

        for i, (model, nesting) in enumerate(zip(model_data, nesting_data)):
            model_filename = f"model_{i}.json"
            nesting_filename = f"nesting_{i}.json"

            json_dump(model, os.path.join(model_dir, model_filename))
            json_dump(nesting, os.path.join(nesting_dir, nesting_filename))

            print(f"packaging model {os.path.join(model_dir, model_filename)}")

            manifest["items"].append({"model": f"model/{model_filename}", "nesting": f"nesting/{nesting_filename}"})

        json_dump(manifest, os.path.join(tmp_dir, "manifest.json"))

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(tmp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmp_dir)
                    zipf.write(file_path, arcname=arcname)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract matching model and nesting file pairs and package them as a .cog file")
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    parser.add_argument("--model", "-m", required=True, help="Path to the models file")
    parser.add_argument("--nesting", "-n", required=True, help="Path to the nesting results file")
    parser.add_argument("--output", "-o", default=f"model_{now}.cog", help="Output .cog file path")

    args = parser.parse_args()

    package_model_nesting(args.model, args.nesting, args.output)
