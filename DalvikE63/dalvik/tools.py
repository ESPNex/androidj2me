"""Find JDK tools already installed locally. Never fetch/clone dependencies."""
import os
import shutil
from pathlib import Path


def jdk_tool(name: str) -> str | None:
    locations = []
    if os.environ.get("JAVA_HOME"):
        locations.append(Path(os.environ["JAVA_HOME"]) / "bin" / name)
    locations.append(Path("/usr/lib/jvm/jdk-11/bin") / name)
    for candidate in locations:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)
