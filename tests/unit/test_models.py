from sourcebrief_shared.models import Workspace


def test_workspace_model_instantiates() -> None:
    workspace = Workspace(name="Demo", slug="demo")
    assert workspace.name == "Demo"
    assert workspace.slug == "demo"
