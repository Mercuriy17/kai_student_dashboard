from collections.abc import Sequence
from core.exceptions import DomainValidationError


def validate_rso_weights(component_max_scores: Sequence[float], admission_min: float) -> None:
    if not component_max_scores:
        raise DomainValidationError("РСО дисципліни повинна містити хоча б один компонент оцінювання.")
    if any(score <= 0 for score in component_max_scores):
        raise DomainValidationError("Максимальний бал за кожен компонент РСО має бути більшим за 0.")

    total = round(sum(component_max_scores), 2)
    if total != 100.0:
        raise DomainValidationError(f"Сума балів РСО дорівнює {total}, але має становити рівно 100.0.")

    if not (0 <= admission_min < 100.0):
        raise DomainValidationError(f"Некоректний поріг допуску до сесії: {admission_min}.")