"""Builder syntax is general; catalog projection authority belongs to the host."""

import pytest
from test_brain_create_builder import _base_spec, _block, _fetch

from metis_model1.brain_create_builder import CreateBuilderError, render_create_endpoint


@pytest.mark.parametrize("profile", ("default", "detail_alpha", "summary_beta", "expanded"))
def test_builder_renders_declared_profile_identifier_without_a_code_owned_roster(profile):
    spec = _base_spec()
    block = _block("main")
    fetch = _fetch(catalog="assets")
    fetch["output"] = {"projection": profile, "steps": [], "fallbacks": []}
    block["fetches"] = [fetch]
    spec["endpoint"]["blocks"] = [block]
    source = render_create_endpoint(spec).metis_text
    expected = "return response" + ("" if profile == "default" else "." + profile)
    assert expected in source
    assert block["output"] is None


@pytest.mark.parametrize("profile", ("", "detail -> shuffle", "a.b", "a\nreturn response", 7))
def test_projection_extension_does_not_open_a_source_escape_hatch(profile):
    spec = _base_spec()
    spec["endpoint"]["output"] = {"projection": profile, "steps": [], "fallbacks": []}
    with pytest.raises(CreateBuilderError):
        render_create_endpoint(spec)
