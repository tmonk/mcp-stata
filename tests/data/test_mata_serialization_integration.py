import pytest

pytestmark = pytest.mark.requires_stata


def test_client_get_mata_state_serializes_values(client):
    client.run_command_structured("mata: mata clear", echo=False, strip_smcl=True)
    client.run_command_structured("mata: real scalar a", echo=False, strip_smcl=True)
    client.run_command_structured("mata: a=5", echo=False, strip_smcl=True)
    client.run_command_structured('mata: string scalar s', echo=False, strip_smcl=True)
    client.run_command_structured('mata: s="hello"', echo=False, strip_smcl=True)
    client.run_command_structured("mata: real matrix M", echo=False, strip_smcl=True)
    client.run_command_structured("mata: M=J(2,2,0)", echo=False, strip_smcl=True)
    client.run_command_structured("mata: M[1,1]=1", echo=False, strip_smcl=True)
    client.run_command_structured("mata: M[1,2]=2", echo=False, strip_smcl=True)
    client.run_command_structured("mata: M[2,1]=3", echo=False, strip_smcl=True)
    client.run_command_structured("mata: M[2,2]=4", echo=False, strip_smcl=True)
    client.run_command_structured(
        "mata:\nreal scalar g(real scalar x) {\n return(x^2)\n}\nend",
        echo=False,
        strip_smcl=True,
    )

    state = client.get_mata_state(include_values=True, matrix_max_rows=10, matrix_max_cols=10)
    assert state["success"] is True
    objects = {o["name"]: o for o in state["objects"]}
    funcs = {f["name"]: f for f in state["functions"]}

    assert "a" in objects
    assert objects["a"]["value"] == 5
    assert objects["a"]["type_family"] == "real"
    assert "s" in objects
    assert objects["s"]["value"] == "hello"
    assert objects["s"]["type_family"] == "string"
    assert "M" in objects
    assert objects["M"]["value"]["rows"] == 2
    assert objects["M"]["value"]["cols"] == 2
    assert objects["M"]["value"]["values"][0][0] == 1
    assert "g" in funcs

    client.run_command_structured("mata: mata clear", echo=False, strip_smcl=True)
