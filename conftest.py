import pytest

import gemini_models


@pytest.fixture(autouse=True)
def _fresh_model_chain():
    """gemini_models remembers models that ran out for the rest of the run;
    one test's "quota spent" must not leak into the next."""
    gemini_models.reset()
    yield
    gemini_models.reset()
