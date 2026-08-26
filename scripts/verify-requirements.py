# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

#!/usr/bin/env python3
"""
Planetary Explorer Installation Verification Script
Run this script to verify that all critical dependencies are correctly installed.
"""

import sys
import importlib
from importlib.metadata import PackageNotFoundError, version as package_version

from packaging import version


def check_module(module_name, min_version=None, exact_version=None, distribution_name=None):
    """Check if a module can be imported and meets version requirements."""
    try:
        importlib.import_module(module_name)
        module_version = package_version(distribution_name or module_name)
        
        if exact_version and module_version != exact_version:
            print(f"  {module_name}: {module_version} (expected exactly {exact_version})")
            return False
        elif min_version and version.parse(module_version) < version.parse(min_version):
            print(f" {module_name}: {module_version} (need >= {min_version})")
            return False
        else:
            print(f" {module_name}: {module_version}")
            return True
            
    except (ImportError, PackageNotFoundError) as e:
        print(f" {module_name}: Not installed ({e})")
        return False
    except Exception as e:
        print(f"  {module_name}: Error checking version ({e})")
        return False

def test_agent_framework_imports():
    """Verify the MAF OpenAI provider imports and constructs offline."""
    print("\n Testing Microsoft Agent Framework imports...")

    try:
        from agent_framework.openai import OpenAIChatCompletionClient

        client = OpenAIChatCompletionClient(
            model="verification-model",
            azure_endpoint="https://example.openai.azure.com",
            api_key="verification-key",
            api_version="2024-10-21",
        )
        print(f" Agent Framework client creation successful ({type(client).__name__})")
    except Exception as e:
        print(f" Agent Framework provider validation failed: {e}")
        return False

    return True

def main():
    print(" Planetary Explorer Installation Verification")
    print("=" * 50)
    
    # Framework packages are kept on the same release line.
    critical_exact = {
        'agent-framework-core': ('agent_framework', '1.10.0'),
        'agent-framework-openai': ('agent_framework.openai', '1.10.0'),
    }

    critical_minimum = {
        'openai': '2.54.0',
        'pydantic': '2.5.0',
    }
    
    # Core dependencies with minimum versions
    core_deps = {
        'azure.functions': '1.18.0',
        'aiohttp': '3.9.0',
        'requests': '2.31.0',
        'pystac_client': '0.7.0'
    }
    
    # Optional but recommended
    optional_deps = [
        'planetary_computer',
        'shapely',
        'numpy',
        'pandas'
    ]
    
    print("\n Checking critical dependencies (exact versions required):")
    critical_ok = True
    for distribution, (module, exact_ver) in critical_exact.items():
        if not check_module(
            module,
            exact_version=exact_ver,
            distribution_name=distribution,
        ):
            critical_ok = False
    for module, min_ver in critical_minimum.items():
        if not check_module(module, min_version=min_ver):
            critical_ok = False
    
    print("\n Checking core dependencies:")
    core_ok = True
    for module, min_ver in core_deps.items():
        if not check_module(module, min_version=min_ver):
            core_ok = False
    
    print("\n Checking optional dependencies:")
    for module in optional_deps:
        check_module(module)
    
    imports_ok = test_agent_framework_imports()
    
    print("\n" + "=" * 50)
    if critical_ok and core_ok and imports_ok:
        print(" SUCCESS: All critical components are working!")
        print("\nNext steps:")
        print("1. Run: ./setup-all-services.ps1 (or .sh)")
        print("2. Run: ./run-all-services.ps1 (or .sh)")
        print("3. Open: http://localhost:5173")
        return 0
    else:
        print(" FAILED: Some components need attention")
        print("\nTo fix issues:")
        print("1. pip install -r requirements.txt")
        print("2. For Agent Framework issues:")
        print("   pip install --force-reinstall agent-framework-core==1.10.0 agent-framework-openai==1.10.0 'openai>=2.54.0,<3.0.0'")
        print("3. Re-run this script to verify")
        return 1

if __name__ == '__main__':
    sys.exit(main())
