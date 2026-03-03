"""Unit tests for WebAppContainerProperties dataclass."""

from gds_idea_cdk_constructs.web_app.props import WebAppContainerProperties


def test_default_values():
    """Test that default values are set correctly."""
    props = WebAppContainerProperties()

    assert props.cpu == 256
    assert props.memory_limit_mib == 512
    assert props.desired_count == 1
    assert props.container_port == 8080
    assert props.environment_variables == {}
    assert props.min_healthy_percent == 50
    assert props.health_check_grace_period == 60
    assert props.health_check_path is None


def test_custom_values():
    """Test initialization with custom values."""
    custom_env = {"KEY1": "value1", "KEY2": "value2"}
    props = WebAppContainerProperties(
        cpu=512,
        memory_limit_mib=1024,
        desired_count=3,
        container_port=8081,
        environment_variables=custom_env,
        min_healthy_percent=100,
        health_check_grace_period=120,
        health_check_path="/custom/health",
    )

    assert props.cpu == 512
    assert props.memory_limit_mib == 1024
    assert props.desired_count == 3
    assert props.container_port == 8081
    assert props.environment_variables == custom_env
    assert props.min_healthy_percent == 100
    assert props.health_check_grace_period == 120
    assert props.health_check_path == "/custom/health"


def test_partial_custom_values():
    """Test that we can override some values while keeping defaults."""
    props = WebAppContainerProperties(cpu=1024, desired_count=2)

    assert props.cpu == 1024
    assert props.desired_count == 2
    # Verify defaults for non-overridden values
    assert props.memory_limit_mib == 512
    assert props.container_port == 8080
    assert props.environment_variables == {}


def test_environment_variables_default_is_not_shared():
    """Test that default empty dict is not shared between instances."""
    props1 = WebAppContainerProperties()
    props2 = WebAppContainerProperties()

    props1.environment_variables["TEST"] = "value"

    assert "TEST" in props1.environment_variables
    assert "TEST" not in props2.environment_variables
    assert props1.environment_variables != props2.environment_variables
