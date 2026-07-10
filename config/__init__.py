"""
ExperimentIQ — Configuration Package

Exposes the application settings singleton and logging configurator.
All modules import from this package to access configuration.
"""

from config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
