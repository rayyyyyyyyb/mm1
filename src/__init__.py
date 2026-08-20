"""Top-level public API with lazy imports.

Readiness and asset-audit utilities must remain executable before the optional
training stack (for example ``timm``) has been installed.  Import model code
only when a caller actually requests one of the public training objects.
"""

from importlib import import_module

__all__ = [
    "QueryConditionedOVAvelDataset",
    "create_ov_avel_data_loaders",
    "OVOrthKDLoss",
    "OVOrthKDStudent",
]


_EXPORTS = {
    "QueryConditionedOVAvelDataset": ("src.data", "QueryConditionedOVAvelDataset"),
    "create_ov_avel_data_loaders": ("src.data", "create_ov_avel_data_loaders"),
    "OVOrthKDLoss": ("src.losses", "OVOrthKDLoss"),
    "OVOrthKDStudent": ("src.models", "OVOrthKDStudent"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
