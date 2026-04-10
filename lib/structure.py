"""Shared structure loading for static_website_lhtml plugins."""

import yaml


def load_structure(site_directory):
    """Load the site structure YAML exported during generation."""
    structure_path = site_directory + '/structure/structure.yaml'
    with open(structure_path) as fid:
        return yaml.safe_load(fid)
