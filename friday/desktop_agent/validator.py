"""Parameter Validator for the FRIDAY Desktop Agent.

This module validates the parameters of a Structured_Command against the
parameter schema of its referenced Registered_Command before the command may
be executed. It reuses the validation approach established in
``friday/modules/tool_calling/router.py::_validate_parameters`` (required
fields, string length bounds, and enum membership) and extends it with
numeric range checks (JSON Schema ``minimum``/``maximum``), including the
media-control volume level which is constrained to the inclusive range
``[0, 100]``.

When any parameter fails validation the validator reports a
``CommandStatus.VALIDATION_ERROR`` outcome so the enforcement gauntlet can
decline execution and record the decline in the Audit_Log.

**Validates: Requirements 3.6, 4.4**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from friday.desktop_agent.models import CommandStatus, RegisteredCommand

# Inclusive bounds for a media-control volume level (Req 4.4).
VOLUME_MIN = 0
VOLUME_MAX = 100


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a command's parameters against its schema.

    Attributes:
        valid: True when every parameter satisfies the schema.
        status: ``CommandStatus.VALIDATION_ERROR`` when invalid, else None.
        error: Human-readable description of the first validation failure,
            or None when valid.

    **Validates: Requirements 3.6**
    """

    valid: bool
    status: Optional[CommandStatus] = None
    error: Optional[str] = None


def _is_real_number(value: Any) -> bool:
    """Return True if ``value`` is an int or float but not a bool.

    ``bool`` is a subclass of ``int`` in Python, so it must be excluded to
    avoid treating ``True``/``False`` as numeric values.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_parameters(
    command: RegisteredCommand,
    parameters: dict[str, Any],
) -> Optional[str]:
    """Validate ``parameters`` against ``command``'s JSON Schema.

    Performs the following checks, mirroring the tool-calling router plus
    numeric range enforcement:

    - Required parameters must be present and, for strings, non-empty.
    - String parameters must satisfy ``minLength``/``maxLength`` bounds.
    - Enum parameters must match one of the declared values.
    - Numeric parameters (``type`` of ``"integer"`` or ``"number"``) must
      satisfy declared ``minimum``/``maximum`` bounds. This is where the
      media-control volume level is constrained to ``[0, 100]`` (Req 4.4).

    Args:
        command: The Registered_Command whose parameter schema to validate
            against.
        parameters: The supplied parameters from the Structured_Command.

    Returns:
        None if all validations pass, or an error message string describing
        the first validation failure.

    **Validates: Requirements 3.6, 4.4**
    """
    parameters_schema = command.parameters or {}
    properties = parameters_schema.get("properties", {})
    required_fields = parameters_schema.get("required", [])

    # Validate required parameters are present and non-empty (strings).
    for field_name in required_fields:
        if field_name not in parameters:
            return f"Missing required parameter: {field_name}"

        value = parameters[field_name]
        if isinstance(value, str) and len(value.strip()) == 0:
            return f"Required parameter '{field_name}' cannot be empty"

    # Validate each provided argument against its schema.
    for param_name, param_value in parameters.items():
        if param_name not in properties:
            # Allow unknown parameters (lenient validation), matching the
            # tool-calling router's behavior.
            continue

        param_schema = properties[param_name]
        param_type = param_schema.get("type")

        # String constraints: minLength, maxLength, enum.
        if param_type == "string" and isinstance(param_value, str):
            min_length = param_schema.get("minLength")
            if min_length is not None and len(param_value) < min_length:
                return (
                    f"Parameter '{param_name}' must be at least "
                    f"{min_length} character(s), got {len(param_value)}"
                )

            max_length = param_schema.get("maxLength")
            if max_length is not None and len(param_value) > max_length:
                return (
                    f"Parameter '{param_name}' must be at most "
                    f"{max_length} character(s), got {len(param_value)}"
                )

        # Enum membership applies regardless of declared type.
        enum_values = param_schema.get("enum")
        if enum_values is not None and param_value not in enum_values:
            return (
                f"Parameter '{param_name}' must be one of "
                f"{enum_values}, got {param_value!r}"
            )

        # Numeric range constraints: minimum, maximum (Req 4.4).
        if param_type in ("integer", "number"):
            if not _is_real_number(param_value):
                return (
                    f"Parameter '{param_name}' must be a "
                    f"{param_type}, got {type(param_value).__name__}"
                )

            if param_type == "integer" and isinstance(param_value, float):
                if not param_value.is_integer():
                    return (
                        f"Parameter '{param_name}' must be an integer, "
                        f"got {param_value}"
                    )

            minimum = param_schema.get("minimum")
            if minimum is not None and param_value < minimum:
                return (
                    f"Parameter '{param_name}' must be at least "
                    f"{minimum}, got {param_value}"
                )

            maximum = param_schema.get("maximum")
            if maximum is not None and param_value > maximum:
                return (
                    f"Parameter '{param_name}' must be at most "
                    f"{maximum}, got {param_value}"
                )

    return None


def validate(
    command: RegisteredCommand,
    parameters: dict[str, Any],
) -> ValidationResult:
    """Validate ``parameters`` and report a schema-validation outcome.

    Wraps :func:`validate_parameters`, returning a ``ValidationResult`` whose
    ``status`` is ``CommandStatus.VALIDATION_ERROR`` when any parameter fails
    validation (Req 3.6), and a valid result otherwise.

    Args:
        command: The Registered_Command to validate against.
        parameters: The supplied parameters from the Structured_Command.

    Returns:
        A ``ValidationResult`` describing whether validation passed and, on
        failure, the ``VALIDATION_ERROR`` status plus an error message.

    **Validates: Requirements 3.6, 4.4**
    """
    error = validate_parameters(command, parameters)
    if error is not None:
        return ValidationResult(
            valid=False,
            status=CommandStatus.VALIDATION_ERROR,
            error=error,
        )
    return ValidationResult(valid=True)


def clamp_volume(value: float) -> int:
    """Clamp a requested volume level to the inclusive range ``[0, 100]``.

    Ensures any applied media-control volume level lies within the allowed
    range regardless of the requested value (Req 4.4).

    Args:
        value: The requested volume level.

    Returns:
        The volume level clamped to ``[VOLUME_MIN, VOLUME_MAX]`` as an int.
    """
    return int(max(VOLUME_MIN, min(VOLUME_MAX, value)))
