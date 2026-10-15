"""Importing the package must not import the CDK.

`aws_cdk` starts a Node process (through jsii) when it is imported. Code that runs
in a container without Node, such as a pipeline task that only needs
`DeploymentEnvironment`, must still be able to import this package.
"""

import subprocess
import sys

_SCRIPT = """
import sys

# Make any import of the CDK fail, as it would where Node is missing.
sys.modules["aws_cdk"] = None
sys.modules["constructs"] = None

from gds_idea_cdk_constructs import DeploymentEnvironment, IdeaTags

dev = DeploymentEnvironment.from_account_id("992382722318")
assert dev is DeploymentEnvironment.DEVELOPMENT
"""


def test_package_imports_without_the_cdk():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
